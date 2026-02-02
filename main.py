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

# ডাটাবেস কানেকশন সেটআপ
try:
    sync_client = MongoClient(MONGO_URI)
    sync_db = sync_client["MasterBotDB"]
    sync_settings = sync_db["settings"]
    
    async_client = AsyncIOMotorClient(MONGO_URI)
    async_db = async_client["MasterBotDB"]
    async_settings = async_db["settings"]
    print("✅ MongoDB Connected Successfully!")
except Exception as e:
    print(f"❌ MongoDB Connection Error: {e}")

app = Flask(__name__)
app.secret_key = os.urandom(24)

# গ্লোবাল ভেরিয়েবল
bot_running = False

# --- অ্যাডমিন প্যানেল ডিজাইন (HTML) ---
LOGIN_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Admin Login</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #f0f2f5; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }
        .login-card { background: white; padding: 30px; border-radius: 12px; box-shadow: 0 8px 20px rgba(0,0,0,0.1); width: 100%; max-width: 350px; }
        h2 { text-align: center; color: #1a73e8; margin-bottom: 20px; }
        input { width: 100%; padding: 12px; margin: 10px 0; border: 1px solid #ddd; border-radius: 6px; box-sizing: border-box; font-size: 14px; }
        .btn { width: 100%; padding: 12px; background: #1a73e8; color: white; border: none; border-radius: 6px; cursor: pointer; font-size: 16px; font-weight: bold; }
        .btn:hover { background: #1557b0; }
        .error { color: #d93025; text-align: center; margin-bottom: 10px; font-size: 14px; }
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
    <title>Master Bot Admin</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body { font-family: 'Segoe UI', sans-serif; background: #f4f7f6; margin: 0; padding: 20px; }
        .card { max-width: 800px; margin: auto; background: white; padding: 30px; border-radius: 15px; box-shadow: 0 4px 15px rgba(0,0,0,0.05); }
        h2 { text-align: center; color: #333; margin-top: 0; }
        .status-box { text-align: center; padding: 12px; border-radius: 8px; margin-bottom: 25px; font-weight: bold; font-size: 15px; }
        .online { background: #e6ffed; color: #22863a; border: 1px solid #22863a; }
        .offline { background: #ffeef0; color: #cb2431; border: 1px solid #cb2431; }
        .section { background: #f8f9fa; padding: 15px; border-radius: 8px; margin-bottom: 20px; border-left: 5px solid #1a73e8; }
        .section-title { font-weight: bold; margin-bottom: 15px; color: #1a73e8; font-size: 16px; display: block; }
        .group { margin-bottom: 12px; }
        label { display: block; font-size: 14px; color: #555; margin-bottom: 5px; }
        input { width: 100%; padding: 10px; border: 1px solid #ccc; border-radius: 5px; box-sizing: border-box; font-size: 14px; }
        .btn-save { width: 100%; padding: 15px; background: #28a745; color: white; border: none; border-radius: 8px; cursor: pointer; font-size: 16px; font-weight: bold; transition: 0.3s; }
        .btn-save:hover { background: #218838; }
        .logout { display: block; text-align: center; margin-top: 20px; color: #666; text-decoration: none; font-size: 14px; }
    </style>
</head>
<body>
    <div class="card">
        <h2>⚙️ Admin Control Panel</h2>
        
        <div class="status-box {{ 'online' if bot_status else 'offline' }}">
            Status: {{ '🟢 BOT IS ONLINE' if bot_status else '🔴 BOT IS OFFLINE / WAITING FOR CONFIG' }}
        </div>

        <form method="post">
            <div class="section">
                <span class="section-title">🔑 Panel Credentials</span>
                <div class="group"><label>Admin Username:</label><input type="text" name="p_user" value="{{ c.get('p_user','admin') }}"></div>
                <div class="group"><label>Admin Password:</label><input type="text" name="p_pass" value="{{ c.get('p_pass','admin') }}"></div>
            </div>

            <div class="section">
                <span class="section-title">🤖 Bot Configuration (Must Fill)</span>
                <div class="group"><label>Bot Token:</label><input type="text" name="bot_token" value="{{ c.get('bot_token','') }}" placeholder="123456:ABC-DEF..."></div>
                <div class="group"><label>API ID:</label><input type="text" name="api_id" value="{{ c.get('api_id','') }}" placeholder="1234567"></div>
                <div class="group"><label>API HASH:</label><input type="text" name="api_hash" value="{{ c.get('api_hash','') }}" placeholder="a1b2c3d4..."></div>
                <div class="group"><label>Owner ID:</label><input type="text" name="owner_id" value="{{ c.get('owner_id','') }}"></div>
            </div>

            <div class="section">
                <span class="section-title">🔗 Extra Settings</span>
                <div class="group"><label>Admin Telegram User (no @):</label><input type="text" name="admin_username" value="{{ c.get('admin_username','') }}"></div>
                <div class="group"><label>Website Link:</label><input type="text" name="website_link" value="{{ c.get('website_link','') }}"></div>
            </div>

            <button type="submit" class="btn-save">Save & Restart Bot</button>
        </form>
        <a href="/logout" class="logout">Logout from Panel</a>
    </div>
</body>
</html>
"""

# --- Flask Routes ---

@app.route('/')
def index():
    return "<h1>Server is Running!</h1><p>Go to /admin to configure the bot.</p>"

@app.route('/login', methods=['GET', 'POST'])
def login():
    config = sync_settings.find_one({"id": "config"}) or {"p_user": "admin", "p_pass": "admin"}
    error = None
    if request.method == 'POST':
        if request.form.get('username') == config.get('p_user') and request.form.get('password') == config.get('p_pass'):
            session['logged_in'] = True
            return redirect(url_for('admin_panel'))
        else:
            error = "Invalid Credentials!"
    return render_template_string(LOGIN_HTML, error=error)

@app.route('/admin', methods=['GET', 'POST'])
def admin_panel():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        # সব ডেটা ট্রিম (Space remove) করে সেভ করা হচ্ছে
        data = {k: v.strip() for k, v in request.form.items()}
        sync_settings.update_one({"id": "config"}, {"$set": data}, upsert=True)
        return redirect(url_for('admin_panel'))

    config = sync_settings.find_one({"id": "config"}) or {}
    return render_template_string(ADMIN_HTML, c=config, bot_status=bot_running)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# --- Pyrogram Bot Task ---

async def bot_task():
    global bot_running
    while True:
        # ডেটাবেস থেকে কনফিগ লোড
        config = await async_settings.find_one({"id": "config"})
        
        # প্রয়োজনীয় কি চেক করা
        if not config or not config.get("bot_token") or not config.get("api_id") or not config.get("api_hash"):
            print("🕒 Waiting for configuration from Admin Panel...")
            bot_running = False
            await asyncio.sleep(10)
            continue

        try:
            print("📡 Attempting to start the Bot...")
            
            # API ID কে Integer এ কনভার্ট করা বাধ্যতামূলক
            app_bot = Client(
                "master_bot_session",
                api_id=int(config["api_id"]),
                api_hash=config["api_hash"],
                bot_token=config["bot_token"],
                in_memory=True
            )

            @app_bot.on_message(filters.command("start") & filters.private)
            async def start_cmd(client, message):
                user = message.from_user
                
                # ফটো হ্যান্ডলিং
                photo = None
                try:
                    async for p in client.get_chat_photos(user.id, limit=1):
                        photo = p.file_id
                except: pass

                text = (
                    f"👋 **Hello, {user.first_name}!**\n\n"
                    f"🆔 Your ID: `{user.id}`\n"
                    f"✨ Status: Bot is working perfectly."
                )
                
                buttons = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("🌐 Website", url=config.get("website_link", "https://t.me/")),
                        InlineKeyboardButton("👨‍💻 Admin", url=f"https://t.me/{config.get('admin_username', 'admin')}")
                    ]
                ])

                if photo:
                    await message.reply_photo(photo, caption=text, reply_markup=buttons)
                else:
                    await message.reply_text(text, reply_markup=buttons)

            await app_bot.start()
            bot_running = True
            print("🚀 Bot is Online!")

            # লুপ যাতে বট চলতে থাকে এবং সেটিংস চেঞ্জ হলে রিস্টার্ট নেয়
            while True:
                new_conf = await async_settings.find_one({"id": "config"})
                # টোকেন বা আইডি পরিবর্তন হলে অটো রিস্টার্ট হবে
                if (new_conf.get("bot_token") != config.get("bot_token") or 
                    new_conf.get("api_id") != config.get("api_id")):
                    print("⚙️ Settings changed, restarting bot...")
                    break
                await asyncio.sleep(20)

            await app_bot.stop()
            bot_running = False

        except Exception as e:
            bot_running = False
            print(f"❌ Bot Error: {e}")
            await asyncio.sleep(15) # এরর হলে ১৫ সেকেন্ড পর আবার চেষ্টা করবে

# --- Execution ---

def run_flask():
    # Render বা অন্যান্য হোস্টিং এর জন্য পোর্ট ৮০৮০ ডিফল্ট
    app.run(host="0.0.0.0", port=8080, debug=False, use_reloader=False)

if __name__ == "__main__":
    # ১. ফ্লাস্ক অ্যাপ ব্যাকগ্রাউন্ড থ্রেডে চালানো
    flask_thread = Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()

    # ২. বট রান করা (Main Loop)
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(bot_task())
    except KeyboardInterrupt:
        print("🛑 Stopped by User")
