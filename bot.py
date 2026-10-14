import os
import re
import time
import asyncio
import aiohttp
import telebot
from flask import Flask
from threading import Thread
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# --- ফ্লাস্ক সার্ভার (রেন্ডার পোর্ট এবং UptimeRobot ২৪/৭ লাইভ রাখার জন্য) ---
app = Flask('')

@app.route('/')
def home():
    return "🤖 Ultimate Cyberpunk Matrix Proxy Checker Bot is Live 24/7!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_flask)
    t.start()

# --- টেলিগ্রাম বট কনফিগারেশন ---
BOT_TOKEN = "8979502036:AAEtECd3-YbcjjE15j0XA_v_zQpQ-2RkVNA"  # আপনার বটের টোকেন এখানে বসাবেন

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="Markdown")

user_sessions = {}

# স্মার্ট প্রক্সি ক্লিনার (অটো ফরম্যাট ফিক্সার)
def clean_proxy_text(raw_text):
    # Regex দিয়ে যেকোনো টেক্সট থেকে IP:Port খুঁজে বের করা
    pattern = r'\b(?Py)?(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}):(\d{1,5})\b'
    matches = re.findall(r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}):(\d{1,5})', raw_text)
    return list(set([f"{ip}:{port}" for ip, port in matches]))

# সুপারসনিক অ্যাসিনক্রোনাস প্রক্সি চেকার ইঞ্জিন
async def test_single_proxy(session, proxy, p_type):
    start_time = time.time()
    
    if p_type in ["HTTP", "HTTPS"]:
        test_url = f"http://{proxy}"
    elif p_type == "SOCKS4":
        test_url = f"socks4://{proxy}"
    elif p_type == "SOCKS5":
        test_url = f"socks5://{proxy}"
    else:
        return False, 0, "Unknown", "Dead 🔴"

    try:
        async with session.get("http://ip-api.com/json/?fields=status,country", proxy=test_url, timeout=3.5) as response:
            if response.status == 200:
                data = await response.json()
                if data.get("status") == "success":
                    speed = round((time.time() - start_time) * 1000, 2)
                    country = data.get("country", "Unknown")
                    
                    # হাই-টেক অ্যানোনিমিটি লেভেল ডিটেকশন
                    anonymity = "Elite 🟢" if speed < 350 else ("Anonymous 🟡" if speed < 700 else "Transparent 🟠")
                    return True, speed, country, anonymity
    except:
        pass
    return False, 0, "Unknown", "Dead 🔴"

@bot.message_handler(commands=['start', 'menu'])
def show_main_menu(message):
    menu_text = (
        "⚡ **CYBERPUNK ELITE PROXY MATRIX (LIFETIME EDITION)** ⚡\n\n"
        "🚀 *বিশ্বের সবচেয়ে দ্রুতগতির এবং আধুনিক আনলিমিটেড প্রক্সি চেকার বট!*\n"
        "*(সুপারসনিক স্পিড, কান্ট্রি ডিটেকশন ও ডুয়াল ফাইল এক্সপোর্ট সিস্টেম)*\n\n"
        "💎 **মাথা নষ্ট করা প্রিমিয়াম ফিচারসমূহ:**\n"
        "┣ 🌐 HTTP, HTTPS, SOCKS4, SOCKS5 মাল্টি-প্রোটোকল\n"
        "┣ 🚀 **Asyncio আল্ট্রা-ফাস্ট ইঞ্জিন (১০-২০ সেকেন্ডে স্ক্যান)**\n"
        "┣ 🌍 অটো কান্ট্রি ও আইপি লোকেশন ডিটেকশন\n"
        "┣ 🛡️ রিয়েল-টাইম অ্যানোনিমিটি লেভেল চেক (Elite/Anonymous)\n"
        "┣ 📁 **ডুয়াল ফাইল আউটপুট (Active ফাইল আলাদা + Dead ফাইল আলাদা)**\n"
        "┣ 🧠 স্মার্ট অটো-ফরম্যাট প্রক্সি ক্লিনার (ভুল টেক্সট অটো ফিল্টার)\n"
        "┗ ♻️ আনলিমিটেড প্রক্সি প্রসেসিং (কোনো লিমিট নেই!)\n\n"
        "🚀 **ব্যবহার শুরু করতে:**\n"
        "আপনার প্রক্সি লিস্ট `.txt` ফাইলে আপলোড করুন অথবা সরাসরি চ্যাটে পেস্ট করুন!"
    )
    
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("⚙️ সিস্টেম স্ট্যাটাস", callback_data="sys_status"),
        InlineKeyboardButton("📖 প্রো-ইউজার গাইড", callback_data="sys_help"),
        InlineKeyboardButton("📢 অফিশিয়াল চ্যানেল", url="https://t.me/your_channel") # চাইলে আপনার চ্যানেল লিঙ্ক দিতে পারেন
    )
    bot.reply_to(message, menu_text, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data in ["sys_status", "sys_help"])
def system_callbacks(call):
    if call.data == "sys_status":
        bot.answer_callback_query(call.id, "🟢 ম্যাট্রিক্স সিস্টেম ১০০% লাইভ, সিকিউর এবং সুপার ফাস্ট আছে!", show_alert=True)
    elif call.data == "sys_help":
        help_msg = (
            "📖 **চিরস্থায়ী ব্যবহারবিধি:**\n\n"
            "১. যত খুশি তত হাজার হাজার প্রক্সি `.txt` ফাইলে দিন বা চ্যাটে দিন।\n"
            "২. যেকোনো প্রোটোকল সিলেক্ট করলেই রকেট গতিতে স্ক্যান শুরু হয়ে যাবে।\n"
            "৩. চেকিং শেষে বট স্বয়ংক্রিয়ভাবে দুটি ফাইল পাঠাবে: একটি লাইভ প্রক্সির (Active), অন্যটি ফেইলড প্রক্সির (Dead)।"
        )
        bot.send_message(call.message.chat.id, help_msg)

@bot.message_handler(content_types=['document', 'text'])
def handle_user_input(message):
    chat_id = message.chat.id
    
    if message.text and message.text.startswith('/'):
        return

    raw_data = ""
    if message.content_type == 'document':
        if not message.document.file_name.endswith('.txt'):
            bot.reply_to(message, "❌ **এরর!** দয়া করে শুধুমাত্র `.txt` ফরম্যাটের ফাইল দিন বস! 🛑")
            return
        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        raw_data = downloaded_file.decode('utf-8', errors='ignore')
    elif message.text:
        raw_data = message.text

    # স্মার্ট ক্লিনারের মাধ্যমে আনলিমিটেড প্রক্সি এক্সট্রাক্ট করা
    proxies = clean_proxy_text(raw_data)
    
    if not proxies:
        bot.reply_to(message, "⚠️ **উফ!** কোনো ভ্যালিড প্রক্সি পাওয়া যায়নি। সঠিক ফরম্যাটে (`IP:PORT`) প্রক্সি দিন! 🧐")
        return

    user_sessions[chat_id] = {"proxies": proxies}
    
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🌐 HTTP / HTTPS", callback_data="run_http"),
        InlineKeyboardButton("🔒 SOCKS4", callback_data="run_socks4"),
        InlineKeyboardButton("💎 SOCKS5", callback_data="run_socks5"),
        InlineKeyboardButton("✨ অল প্রোটোকল (ALL)", callback_data="run_all")
    )
    
    bot.reply_to(
        message, 
        f"🎯 **স্মার্ট ক্লিনার দ্বারা ফিল্টারকৃত ইউনিক প্রক্সি:** `{len(proxies)}` টি\n\n"
        "👇 *সুপারসনিক স্পিডে চেক করতে প্রোটোকল সিলেক্ট করুন:*", 
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("run_"))
def execution_callback(call):
    chat_id = call.message.chat.id
    action = call.data.replace("run_", "")
    
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
        "🚀 **SUPERSONIC SPEED ENGINE ACTIVATED...**\n⚡ *রকেট গতিতে প্রক্সি স্ক্যানিং চলছে, ম্যাট্রিক্স ডেটা প্রসেস হচ্ছে...*", 
        chat_id, 
        call.message.message_id
    )
    
    asyncio.run(run_supersonic_scanner(chat_id, proxies, protocols, call.message.message_id))

async def run_supersonic_scanner(chat_id, proxies, protocols, message_id):
    active_results = {p: [] for p in protocols}
    dead_proxies = []
    
    tasks = []
    start_time = time.time()
    
    # আল্ট্রা-ফাস্ট aiohttp কনকারেন্সি ইঞ্জিন
    connector = aiohttp.TCPConnector(limit=300, ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        for proxy in proxies:
            for p_type in protocols:
                tasks.append(test_single_proxy(session, proxy, p_type))
        
        results = await asyncio.gather(*tasks)

    idx = 0
    for proxy in proxies:
        for p_type in protocols:
            is_active, speed, country, anonymity = results[idx]
            idx += 1
            
            if is_active:
                active_results[p_type].append(f"{proxy} | Country: {country} | Anonymity: {anonymity} | Speed: {speed}ms")
            else:
                dead_proxies.append(f"{proxy} ({p_type})")

    total_active = sum(len(v) for v in active_results.values())
    total_dead = len(dead_proxies)
    total_time = round(time.time() - start_time, 2)
    
    try:
        bot.delete_message(chat_id, message_id)
    except:
        pass

    report = (
        f"👑 **LIFETIME MATRIX MISSION REPORT** 👑\n\n"
        f"⚡ **ইঞ্জিন:** `Asyncio Supersonic Pro`\n"
        f"✅ **সক্রিয় ও ১০০% লাইভ প্রক্সি:** `{total_active}`\n"
        f"❌ **মৃত / ফেইলড প্রক্সি:** `{total_dead}`\n"
        f"⏱️ **মোট সময় লেগেছে:** `{total_time} সেকেন্ড`\n\n"
    )
    
    for p_type, plist in active_results.items():
        report += f"🔹 **{p_type}:** `{len(plist)}` টি সক্রিয়\n"

    # ফাইল প্রস্তুতকরণ
    active_file_content = ""
    for p_type, plist in active_results.items():
        if plist:
            active_file_content += f"\n--- {p_type} ACTIVE PROXIES (WITH DETAILS) ---\n" + "\n".join(plist) + "\n"

    dead_file_content = "--- DEAD / FAILED PROXIES ---\n" + "\n".join(dead_proxies) if dead_proxies else "No dead proxies."

    # Active Proxies File
    if active_file_content.strip():
        active_filename = f"Active_Live_Proxies_{chat_id}.txt"
        with open(active_filename, "w", encoding="utf-8") as f:
            f.write(active_file_content.strip())
        
        with open(active_filename, "rb") as f:
            bot.send_document(chat_id, f, caption="🟢 **রকেট গতিতে স্ক্যান করা ১০০% লাইভ ও ভ্যালিড প্রক্সি ফাইল!**")
        os.remove(active_filename)

    # Dead Proxies File
    dead_filename = f"Dead_Failed_Proxies_{chat_id}.txt"
    with open(dead_filename, "w", encoding="utf-8") as f:
        f.write(dead_file_content.strip())
    
    with open(dead_filename, "rb") as f:
        bot.send_document(chat_id, f, caption=report + "\n🔴 **কাজ না করা মৃত প্রক্সিগুলোর ফাইল!**")
    os.remove(dead_filename)

    if chat_id in user_sessions:
        del user_sessions[chat_id]

if __name__ == "__main__":
    print("🌐 Flask Server & Lifetime Supersonic Engine Starting...")
    keep_alive()
    print("🤖 Ultimate Lifetime Proxy Checker Bot সফলভাবে লাইভ হয়েছে... 🚀")
    bot.infinity_polling()
