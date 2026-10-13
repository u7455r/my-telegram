import os
import time
import requests
import telebot
from flask import Flask
from threading import Thread
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- ফ্লাস্ক সার্ভার (রেন্ডারের পোর্ট এবং UptimeRobot-এর জন্য) ---
app = Flask('')

@app.route('/')
def home():
    return "🤖 Ultimate Proxy Checker Bot is Alive and Running 24/7!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_flask)
    t.start()

# --- টেলিগ্রাম বট কনফিগারেশন ---
BOT_TOKEN = "8979502036:AAEHLGeqG4zZza1EEWxbef85cS-cCOyee34"  # আপনার বটের টোকেন এখানে বসাবেন

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="Markdown")

user_sessions = {}

# প্রক্সি টেস্ট করার ফাংশন
def test_proxy_connection(proxy, proxy_type):
    start_time = time.time()
    proxies_map = {
        "HTTP": {"http": f"http://{proxy}", "https": f"http://{proxy}"},
        "HTTPS": {"http": f"http://{proxy}", "https": f"http://{proxy}"},
        "SOCKS4": {"http": f"socks4://{proxy}", "https": f"socks4://{proxy}"},
        "SOCKS5": {"http": f"socks5://{proxy}", "https": f"socks5://{proxy}"}
    }
    
    try:
        res = requests.get("http://httpbin.org/ip", proxies=proxies_map.get(proxy_type), timeout=5)
        if res.status_code == 200:
            speed = round((time.time() - start_time) * 1000, 2)
            return True, speed
    except:
        pass
    return False, 0

@bot.message_handler(commands=['start', 'menu'])
def show_main_menu(message):
    menu_text = (
        "🔥 **ULTIMATE CYBERPUNK PROXY MATRIX v3.5** 🔥\n\n"
        "⚡ *আনলিমিটেড বাল্ক প্রক্সি চেকার বট (ফাইল সাপোর্ট সহ)!*\n\n"
        "💎 **ম্যাট্রিক্স ফিচারস:**\n"
        "┣ 🌐 HTTP, HTTPS, SOCKS4, SOCKS5 সাপোর্ট\n"
        "┣ 🚀 **আনলিমিটেড প্রক্সি প্রসেসিং (নো লিমিট!)**\n"
        "┣ ♻️ অটো ডুপ্লিকেট রিমুভ ও ক্লিন ফিল্টারিং\n"
        "┣ 📊 রিয়েল-টাইম ডায়নামিক প্রোগ্রেস এবং স্ট্যাটাস\n"
        "┗ 📥 লাইভ প্রক্সি ফাইল জেনারেটর ও ডাউনলোডার\n\n"
        "🚀 **ব্যবহার শুরু করতে:**\n"
        "আপনার প্রক্সিগুলো `.txt` ফাইলে আপলোড করুন অথবা সরাসরি চ্যাটে পেস্ট করুন!"
    )
    
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("⚙️ সিস্টেম স্ট্যাটাস", callback_data="sys_status"),
        InlineKeyboardButton("📖 হেল্প গাইড", callback_data="sys_help")
    )
    bot.reply_to(message, menu_text, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data in ["sys_status", "sys_help"])
def system_callbacks(call):
    if call.data == "sys_status":
        bot.answer_callback_query(call.id, "🟢 সিস্টেম রেন্ডার ক্লাউডে ১০০% লাইভ ও আনলিমিটেড মোডে সক্রিয় আছে!", show_alert=True)
    elif call.data == "sys_help":
        help_msg = (
            "📖 **উইথআউট লিমিট গাইড:**\n\n"
            "১. যত খুশি তত প্রক্সি `.txt` ফাইলে দিন (১ হাজার হোক বা ১০ হাজার)।\n"
            "২. বট নিজে থেকেই ডুপ্লিকেট বাদ দিয়ে নিখুঁতভাবে চেক করবে।\n"
            "৩. প্রসেস চলাকালীন চাইলে 'প্রসেস বাতিল' করতে পারবেন।"
        )
        bot.send_message(call.message.chat.id, help_msg)

@bot.message_handler(content_types=['document', 'text'])
def handle_user_input(message):
    chat_id = message.chat.id
    
    if message.text and message.text.startswith('/'):
        return

    proxies = []
    if message.content_type == 'document':
        if not message.document.file_name.endswith('.txt'):
            bot.reply_to(message, "❌ **এরর!** দয়া করে শুধুমাত্র `.txt` ফরম্যাটের ফাইল দিন বস! 🛑")
            return
        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        proxies = downloaded_file.decode('utf-8', errors='ignore').splitlines()
    elif message.text:
        proxies = message.text.splitlines()

    # আনলিমিটেড প্রক্সির জন্য শুধু ডুপ্লিকেট এবং ফাঁকা লাইন রিমুভ করা হবে (কোনো সাইজ লিমিট নেই)
    proxies = list(set([p.strip() for p in proxies if ":" in p and not p.startswith('#')]))
    
    if not proxies:
        bot.reply_to(message, "⚠️ **উফ!** কোনো ভ্যালিড প্রক্সি পাওয়া যায়নি। সঠিক ফরম্যাটে (`IP:PORT`) প্রক্সি দিন! 🧐")
        return

    user_sessions[chat_id] = {"proxies": proxies, "active": True}
    
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🌐 HTTP / HTTPS", callback_data="run_http"),
        InlineKeyboardButton("🔒 SOCKS4", callback_data="run_socks4"),
        InlineKeyboardButton("💎 SOCKS5", callback_data="run_socks5"),
        InlineKeyboardButton("✨ অল প্রোটোকল (ALL)", callback_data="run_all"),
        InlineKeyboardButton("❌ প্রসেস বাতিল", callback_data="run_cancel")
    )
    
    bot.reply_to(
        message, 
        f"🎯 **আনলিমিটেড প্রক্সি লোড হয়েছে:** `{len(proxies)}` টি\n\n"
        "👇 *কোন প্রোটোকলে চেক করতে চান তা সিলেক্ট করুন:*", 
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("run_"))
def execution_callback(call):
    chat_id = call.message.chat.id
    action = call.data.replace("run_", "")
    
    if action == "cancel":
        if chat_id in user_sessions:
            user_sessions[chat_id]["active"] = False
        bot.answer_callback_query(call.id, "প্রসেস বাতিল করা হয়েছে!", show_alert=True)
        bot.edit_message_text("🛑 **প্রসেস ইউজারের দ্বারা বাতিল করা হয়েছে।** ❌", chat_id, call.message.message_id)
        return

    if chat_id not in user_sessions:
        bot.answer_callback_query(call.id, "সেশন এক্সপায়ার্ড! আবার প্রক্সি পাঠান।", show_alert=True)
        return

    proxies = user_sessions[chat_id]["proxies"]
    
    if action == "http":
        protocols = ["HTTP", "HTTPS"]
    elif action == "socks4":
        protocols = ["SOCKS4"]
    elif action == "socks5":
        protocols = ["SOCKS5"]
    else:
        protocols = ["HTTP", "HTTPS", "SOCKS4", "SOCKS5"]

    bot.edit_message_text(
        "🚀 **UNLIMITED MATRIX SCANNING STARTED...**\n⏳ *প্রক্সি ম্যাট্রিক্স লোড হচ্ছে, বিশাল লিস্ট প্রসেস হতে একটু সময় লাগতে পারে...*", 
        chat_id, 
        call.message.message_id
    )
    
    execute_matrix_scanning(chat_id, proxies, protocols, call.message.message_id)

def execute_matrix_scanning(chat_id, proxies, protocols, message_id):
    active_results = {p: [] for p in protocols}
    total_tasks = len(proxies) * len(protocols)
    tested = 0
    start_time = time.time()
    
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🛑 প্রসেস বাতিল (ABORT)", callback_data="run_cancel"))

    def worker_thread(proxy, p_type):
        if not user_sessions.get(chat_id, {}).get("active", True):
            return None
        is_active, speed = test_proxy_connection(proxy, p_type)
        return (proxy, p_type, is_active, speed)

    # বিশাল লিস্ট দ্রুত চেক করার জন্য থ্রেড পুল অপ্টিমাইজ করা হয়েছে
    with ThreadPoolExecutor(max_workers=30) as executor:
        futures = [executor.submit(worker_thread, proxy, p_type) for proxy in proxies for p_type in protocols]

        for future in as_completed(futures):
            if not user_sessions.get(chat_id, {}).get("active", True):
                break
            
            res = future.result()
            if not res:
                continue
                
            proxy, p_type, is_active, speed = res
            tested += 1
            
            if is_active:
                active_results[p_type].append(f"{proxy} | Speed: {speed}ms")

            # ডায়নামিক প্রোগ্রেস আপডেট (বড় লিস্টের জন্য ফ্রিকোয়েন্সি সেট করা হয়েছে)
            if tested % 25 == 0 or tested == total_tasks:
                elapsed = time.time() - start_time
                progress_pct = int((tested / total_tasks) * 100)
                bar_filled = "█" * (progress_pct // 10)
                bar_empty = "░" * (10 - (progress_pct // 10))
                total_active = sum(len(v) for v in active_results.values())
                
                loading_text = (
                    f"⚡ **UNLIMITED PROXY MATRIX RUNNING** ⚡\n\n"
                    f"🎯 **প্রোগ্রেস:** `[{bar_filled}{bar_empty}] {progress_pct}%`\n"
                    f"🔄 **পরীক্ষিত:** `{tested}/{total_tasks}`\n"
                    f"🔥 **সক্রিয় প্রক্সি:** `{total_active}`\n"
                    f"⏱️ **সময় ব্যয়:** `{round(elapsed, 1)} সেকেন্ড`\n\n"
                    f"💬 *'বিশাল ডেটা প্রসেসিং চলছে, চিল বস...'*"
                )
                try:
                    bot.edit_message_text(loading_text, chat_id, message_id, reply_markup=markup)
                except:
                    pass

    total_active = sum(len(v) for v in active_results.values())
    total_time = round(time.time() - start_time, 2)
    
    try:
        bot.delete_message(chat_id, message_id)
    except:
        pass

    report = (
        f"👑 **UNLIMITED MATRIX MISSION REPORT** 👑\n\n"
        f"📊 **মোট টেস্ট করা হয়েছে:** `{total_tasks}`\n"
        f"✅ **সক্রিয় প্রক্সি পাওয়া গেছে:** `{total_active}`\n"
        f"⏱️ **মোট সময় লেগেছে:** `{total_time} সেকেন্ড`\n\n"
    )
    
    for p_type, plist in active_results.items():
        report += f"🔹 **{p_type}:** `{len(plist)}` টি সক্রিয়\n"

    file_content = ""
    for p_type, plist in active_results.items():
        if plist:
            file_content += f"\n--- {p_type} PROXIES ---\n" + "\n".join(plist) + "\n"

    if file_content.strip():
        filename = f"unlimited_proxies_{chat_id}.txt"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(file_content.strip())
        
        with open(filename, "rb") as f:
            bot.send_document(chat_id, f, caption=report + "\n📂 *সব সক্রিয় প্রক্সিগুলোর ফাইল নিচে দেওয়া হলো!*")
        os.remove(filename)
    else:
        bot.send_message(chat_id, report + "\n\n❌ **দুঃখিত! এই বিশাল লিস্টে কোনো প্রক্সি সক্রিয় পাওয়া যায়নি।** 💀")

    if chat_id in user_sessions:
        del user_sessions[chat_id]

if __name__ == "__main__":
    print("🌐 Flask Server & Unlimited Bot Starting...")
    keep_alive()
    print("🤖 Ultimate Unlimited Proxy Checker Bot সফলভাবে রান হচ্ছে... 🚀")
    bot.infinity_polling()
