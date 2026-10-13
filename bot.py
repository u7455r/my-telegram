import os
import time
import requests
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from concurrent.futures import ThreadPoolExecutor, as_completed

# 🔥 আপনার টেলিগ্রাম বটের টোকেন এখানে একবারই বসিয়ে দিন (এরপর আর গিটহাবে হাত দেওয়া লাগবে না)
BOT_TOKEN = "8979502036:AAEsR-ZK2vjZjxsPMe_HHXTDrDwrZ_Gotio"

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="Markdown")

# ইউজার সেশন ম্যানেজমেন্ট
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
        "🔥 **ULTIMATE CYBERPUNK PROXY MATRIX v3.0** 🔥\n\n"
        "⚡ *অটো-ম্যানেজড অল-ইন-ওয়ান প্রক্সি চেকার বট!*\n"
        "*(এই বটে কোড বারবার এডিট করার কোনো ঝামেলা নেই, সবকিছু অটোমেটিক!)*\n\n"
        "💎 **ম্যাট্রিক্স ফিচারস:**\n"
        "┣ 🌐 HTTP, HTTPS, SOCKS4, SOCKS5 সাপোর্ট\n"
        "┣ ⚡ সুপার ফাস্ট মাল্টি-থ্রেডেড ব্যাচ স্ক্যানার\n"
        "┣ ♻️ অটো ডুপ্লিকেট রিমুভ ও ক্লিন ফিল্টারিং\n"
        "┣ 📊 রিয়েল-টাইম ডায়নামিক প্রোগ্রেস এবং স্ট্যাটাস\n"
        "┗ 📥 লাইভ প্রক্সি ফাইল জেনারেটর ও ডাউনলোডার\n\n"
        "🚀 **ব্যবহার শুরু করতে:**\n"
        "আপনার প্রক্সিগুলো (`IP:PORT`) সরাসরি চ্যাটে পেস্ট করুন অথবা `.txt` ফাইল আপলোড করুন!"
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
        bot.answer_callback_query(call.id, "🟢 সিস্টেম রেন্ডার ক্লাউডে ১০০% সক্রিয় ও সুপার ফাস্ট আছে!", show_alert=True)
    elif call.data == "sys_help":
        help_msg = (
            "📖 **কুইক গাইড:**\n\n"
            "১. একসাথে অনেক প্রক্সি চেক করতে চাইলে `.txt` ফাইল দিন।\n"
            "২. ছোট লিস্ট হলে সরাসরি চ্যাটে কপি-পেস্ট করুন।\n"
            "৩. প্রসেস চলাকালীন সময়ে যেকোনো সময় 'বাতিল করুন' বাটন টিপে থামাতে পারবেন।"
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

    # অটো ডুপ্লিকেট এবং ফাঁকা লাইন রিমুভ
    proxies = list(set([p.strip() for p in proxies if ":" in p and not p.startswith('#')]))
    
    if not proxies:
        bot.reply_to(message, "⚠️ **উফ!** কোনো ভ্যালিড প্রক্সি পাওয়া যায়নি। সঠিক ফরম্যাটে (`IP:PORT`) প্রক্সি দিন! 🧐")
        return

    if len(proxies) > 400:
        bot.reply_to(message, "⚠️ **লিমিট অ্যালার্ট:** একবারে সর্বোচ্চ ৪০০টি প্রক্সি চেক করা নিরাপদ! 🚀")
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
        f"🎯 **মোট ইউনিক প্রক্সি লোড হয়েছে:** `{len(proxies)}` টি\n\n"
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
        "🚀 **MATRIX PROTOCOL ACTIVATED...**\n⏳ *প্রক্সি স্ক্যানিং শুরু হচ্ছে, একটু অপেক্ষা করুন বস...*", 
        chat_id, 
        call.message.message_id
    )
    
    # ব্যাকগ্রাউন্ডে মাল্টিথ্রেডে স্ক্যানিং চালানো
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

    with ThreadPoolExecutor(max_workers=20) as executor:
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

            # লাইভ প্রোগ্রেস ডায়নামিক আপডেট
            if tested % 10 == 0 or tested == total_tasks:
                elapsed = time.time() - start_time
                progress_pct = int((tested / total_tasks) * 100)
                bar_filled = "█" * (progress_pct // 10)
                bar_empty = "░" * (10 - (progress_pct // 10))
                total_active = sum(len(v) for v in active_results.values())
                
                loading_text = (
                    f"⚡ **ELITE PROXY CHECKER RUNNING** ⚡\n\n"
                    f"🎯 **প্রোগ্রেস:** `[{bar_filled}{bar_empty}] {progress_pct}%`\n"
                    f"🔄 **পরীক্ষিত:** `{tested}/{total_tasks}`\n"
                    f"🔥 **সক্রিয় প্রক্সি:** `{total_active}`\n"
                    f"⏱️ **সময় ব্যয়:** `{round(elapsed, 1)} সেকেন্ড`\n\n"
                    f"💬 *'ম্যাট্রিক্স স্ক্যান চলছে, রিলাক্স বস...'*"
                )
                try:
                    bot.edit_message_text(loading_text, chat_id, message_id, reply_markup=markup)
                except:
                    pass

    # ফাইনাল রিপোর্ট ও ফাইল জেনারেট
    total_active = sum(len(v) for v in active_results.values())
    total_time = round(time.time() - start_time, 2)
    
    try:
        bot.delete_message(chat_id, message_id)
    except:
        pass

    report = (
        f"👑 **MATRIX MISSION REPORT** 👑\n\n"
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
        filename = f"elite_proxies_{chat_id}.txt"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(file_content.strip())
        
        with open(filename, "rb") as f:
            bot.send_document(chat_id, f, caption=report + "\n📂 *সক্রিয় প্রক্সিগুলোর ফাইল নিচে দেওয়া হলো!*")
        os.remove(filename)
    else:
        bot.send_message(chat_id, report + "\n\n❌ **দুঃখিত! এই টেস্টে কোনো প্রক্সি সক্রিয় পাওয়া যায়নি।** 💀")

    if chat_id in user_sessions:
        del user_sessions[chat_id]

if __name__ == "__main__":
    print("🤖 Ultimate Auto-Managed Proxy Checker Bot সফলভাবে রান হচ্ছে... 🚀")
    bot.infinity_polling()
