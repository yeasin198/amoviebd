import os
import asyncio
import requests
from flask import Flask, request, render_template_string, redirect, session, url_for
from threading import Thread
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient

# ==========================================
# 🛑 শুধুমাত্র এই লিঙ্কটি পরিবর্তন করবেন 🛑
# ==========================================
MONGO_URI = "mongodb+srv://Demo270:Demo270@cluster0.ls1igsg.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
# ==========================================

# ডাটাবেস কানেকশন
try:
    sync_client = MongoClient(MONGO_URI)
    sync_db = sync_client["MasterBotDB"]
    sync_settings = sync_db["settings"]
    
    async_client = AsyncIOMotorClient(MONGO_URI)
    async_db = async_client["MasterBotDB"]
    async_settings = async_db["settings"]
except Exception as e:
    print(f"❌ ডাটাবেস কানেকশন এরর: {e}")

app = Flask(__name__)
app.secret_key = os.urandom(24) # সিকিউর সেশন কি

# গ্লোবাল ভেরিয়েবল বট কন্ট্রোল করার জন্য
bot_running = False

# --- এডমিন প্যানেল ডিজাইন ---
LOGIN_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Admin Login</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body { font-family: sans-serif; background: #f0f2f5; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }
        .login-card { background: white; padding: 30px; border-radius: 10px; box-shadow: 0 4px 10px rgba(0,0,0,0.1); width: 100%; max-width: 350px; }
        h2 { text-align: center; color: #1a73e8; }
        input { width: 100%; padding: 12px; margin: 10px 0; border: 1px solid #ddd; border-radius: 5px; box-sizing: border-box; }
        .btn { width: 100%; padding: 12px; background: #1a73e8; color: white; border: none; border-radius: 5px; cursor: pointer; font-size: 16px; }
        .error { color: red; text-align: center; margin-bottom: 10px; }
    </style>
</head>
<body>
    <div class="login-card">
        <h2>Admin Login</h2>
        {% if error %}<div class="error">{{ error }}</div>{% endif %}
        <form method="post">
            <input type="text" name="username" placeholder="Username" required>
            <input type="password" name="password" placeholder="Password" required>
            <button type="submit" class="btn">Login</button>
        </form>
    </div>
</body>
</html>
"""

ADMIN_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Bot Admin Panel</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body { font-family: sans-serif; background: #f4f7f6; margin: 0; padding: 20px; }
        .card { max-width: 700px; margin: auto; background: white; padding: 25px; border-radius: 12px; box-shadow: 0 5px 15px rgba(0,0,0,0.1); }
        h2 { text-align: center; color: #333; }
        .status { text-align: center; padding: 10px; margin-bottom: 20px; border-radius: 5px; font-weight: bold; }
        .status-on { background: #d4edda; color: #155724; }
        .status-off { background: #f8d7da; color: #721c24; }
        .group { margin-bottom: 15px; }
        label { display: block; font-weight: bold; margin-bottom: 5px; color: #555; }
        input { width: 100%; padding: 10px; border: 1px solid #ccc; border-radius: 5px; box-sizing: border-box; }
        .btn-save { width: 100%; padding: 12px; background: #28a745; color: white; border: none; border-radius: 5px; cursor: pointer; font-size: 16px; margin-top: 10px; }
        .logout { display: block; text-align: center; margin-top: 20px; color: red; text-decoration: none; font-weight: bold; }
        .section-title { background: #e9ecef; padding: 10px; border-radius: 5px; margin: 20px 0 10px; font-weight: bold; color: #333; }
    </style>
</head>
<body>
    <div class="card">
        <h2>⚙️ Master Admin Panel</h2>
        <div class="status {{ 'status-on' if bot_status else 'status-off' }}">
            Bot Status: {{ 'RUNNING' if bot_status else 'STOPPED / WAITING FOR CONFIG' }}
        </div>
        <form method="post">
            <div class="section-title">🔑 লগইন সেটিংস</div>
            <div class="group"><label>Admin Username:</label><input type="text" name="p_user" value="{{ c.get('p_user','admin') }}"></div>
            <div class="group"><label>Admin Password:</label><input type="text" name="p_pass" value="{{ c.get('p_pass','admin') }}"></div>

            <div class="section-title">🤖 বটের মূল সেটিংস (প্রয়োজনীয়)</div>
            <div class="group"><label>Bot Token:</label><input type="text" name="bot_token" value="{{ c.get('bot_token','') }}"></div>
            <div class="group"><label>API ID:</label><input type="text" name="api_id" value="{{ c.get('api_id','') }}"></div>
            <div class="group"><label>API HASH:</label><input type="text" name="api_hash" value="{{ c.get('api_hash','') }}"></div>
            <div class="group"><label>Owner ID:</label><input type="text" name="owner_id" value="{{ c.get('owner_id','') }}"></div>

            <div class="section-title">🔗 অন্যান্য সেটিংস</div>
            <div class="group"><label>Telegram Username (@ ছাড়া):</label><input type="text" name="admin_username" value="{{ c.get('admin_username','') }}"></div>
            <div class="group"><label>Website Link:</label><input type="text" name="website_link" value="{{ c.get('website_link','') }}"></div>
            
            <button type="submit" class="btn-save">Save & Restart Bot</button>
        </form>
        <a href="/logout" class="logout">Logout</a>
    </div>
</body>
</html>
"""

# --- ওয়েবসাইট রুটস ---

@app.route('/')
def index():
    return "<h1>Server is Live! Go to <a href='/admin'>/admin</a> to configure.</h1>"

@app.route('/login', methods=['GET', 'POST'])
def login():
    config = sync_settings.find_one({"id": "config"}) or {"p_user": "admin", "p_pass": "admin"}
    error = None
    if request.method == 'POST':
        user = request.form.get('username')
        pw = request.form.get('password')
        if user == config.get('p_user', 'admin') and pw == config.get('p_pass', 'admin'):
            session['logged_in'] = True
            return redirect(url_for('admin_panel'))
        else:
            error = "ভুল ইউজারনেম বা পাসওয়ার্ড!"
    return render_template_string(LOGIN_HTML, error=error)

@app.route('/admin', methods=['GET', 'POST'])
def admin_panel():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        data = {k: v for k, v in request.form.items()}
        sync_settings.update_one({"id": "config"}, {"$set": data}, upsert=True)
        # এখানে রিফ্রেশ করলে বট অটোমেটিক নতুন ডাটা পাবে লুপের কারণে
        return redirect(url_for('admin_panel'))

    config = sync_settings.find_one({"id": "config"}) or {}
    return render_template_string(ADMIN_HTML, c=config, bot_status=bot_running)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# --- টেলিগ্রাম বট লজিক ---

async def bot_task():
    global bot_running
    while True:
        config = await async_settings.find_one({"id": "config"})
        
        # চেক করা হচ্ছে সব প্রয়োজনীয় তথ্য আছে কি না
        if not config or not config.get("bot_token") or not config.get("api_id") or not config.get("api_hash"):
            print("⚠️ সেটিংস অসম্পূর্ণ! Admin Panel থেকে API ID, Hash এবং Token দিন।")
            bot_running = False
            await asyncio.sleep(10) # ১০ সেকেন্ড পর আবার চেক করবে
            continue

        try:
            print("🔄 বট চালু করার চেষ্টা করা হচ্ছে...")
            bot = Client(
                "my_bot",
                api_id=int(config["api_id"]),
                api_hash=config["api_hash"],
                bot_token=config["bot_token"],
                in_memory=True
            )

            @bot.on_message(filters.command("start") & filters.private)
            async def start_handler(client, message):
                user = message.from_user
                
                # ইউজারের প্রোফাইল ফটো
                photo_id = None
                try:
                    async for photo in client.get_chat_photos(user.id, limit=1):
                        photo_id = photo.file_id
                except: pass

                caption = (
                    f"👋 **হ্যালো, {user.first_name}!**\n\n"
                    f"👤 **নাম:** `{user.first_name} {user.last_name or ''}`\n"
                    f"🆔 **আইডি:** `{user.id}`\n\n"
                    "নিচের বাটনগুলো ব্যবহার করুন:"
                )

                buttons = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("🌐 ওয়েবসাইট", url=config.get("website_link", "https://google.com")),
                        InlineKeyboardButton("👨‍💻 এডমিন", url=f"https://t.me/{config.get('admin_username', 'admin')}")
                    ]
                ])

                if photo_id:
                    await message.reply_photo(photo=photo_id, caption=caption, reply_markup=buttons)
                else:
                    await message.reply_text(text=caption, reply_markup=buttons)

            await bot.start()
            bot_running = True
            print("🚀 বট সফলভাবে অনলাইন হয়েছে!")
            
            # বট চালু থাকার জন্য ইনফিনিট লুপ (যতক্ষণ না সেটিংস পরিবর্তন হয়)
            while True:
                new_config = await async_settings.find_one({"id": "config"})
                # যদি টোকেন পরিবর্তন করা হয়, তবে লুপ ভেঙে নতুন করে স্টার্ট নিবে
                if new_config.get("bot_token") != config.get("bot_token"):
                    break
                await asyncio.sleep(20)
            
            await bot.stop()
            bot_running = False

        except Exception as e:
            bot_running = False
            print(f"❌ বট এরর: {e}")
            await asyncio.sleep(10)

# রান করার সিস্টেম
def start_flask():
    # Render বা পোর্টে রান করার জন্য ৫০০০ বা ৮০৮০
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    # ব্যাকগ্রাউন্ডে ওয়েবসাইট চালু করা
    t = Thread(target=start_flask)
    t.daemon = True
    t.start()
    
    # মেইন থ্রেডে বট লুপ চালু করা
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(bot_task())
    except KeyboardInterrupt:
        pass
