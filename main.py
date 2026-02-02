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
# 🛑 শুধুমাত্র আপনার MongoDB লিঙ্কটি এখানে দিন 🛑
# ==========================================
MONGO_URI = "mongodb+srv://Demo270:Demo270@cluster0.ls1igsg.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
# ==========================================

# ডাটাবেস কানেকশন
sync_client = MongoClient(MONGO_URI)
sync_db = sync_client["MasterBotDB"]
sync_settings = sync_db["settings"]

async_client = AsyncIOMotorClient(MONGO_URI)
async_db = async_client["MasterBotDB"]
async_settings = async_db["settings"]

app = Flask(__name__)
app.secret_key = "bot_admin_secret_key"

# --- এডমিন প্যানেল UI (HTML/CSS) ---
ADMIN_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Admin Dashboard</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body { font-family: 'Segoe UI', sans-serif; background: #f0f2f5; margin: 0; padding: 20px; }
        .container { max-width: 600px; margin: auto; background: white; padding: 25px; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.1); }
        h2 { text-align: center; color: #1a73e8; }
        .section { background: #e8f0fe; padding: 10px; margin: 20px 0 10px; border-radius: 5px; font-weight: bold; }
        .group { margin-bottom: 12px; }
        label { display: block; font-size: 14px; margin-bottom: 5px; color: #555; }
        input { width: 100%; padding: 10px; border: 1px solid #ddd; border-radius: 6px; box-sizing: border-box; }
        .btn { width: 100%; padding: 12px; background: #1a73e8; color: white; border: none; border-radius: 6px; cursor: pointer; font-size: 16px; margin-top: 15px; }
        .logout { display: block; text-align: center; margin-top: 20px; color: red; text-decoration: none; }
    </style>
</head>
<body>
    <div class="container">
        <h2>⚙️ Admin Dashboard</h2>
        <form method="post">
            <div class="section">🔐 Login Credentials</div>
            <div class="group"><label>Username:</label><input type="text" name="p_user" value="{{ c.get('p_user','admin') }}"></div>
            <div class="group"><label>Password:</label><input type="text" name="p_pass" value="{{ c.get('p_pass','admin') }}"></div>
            
            <div class="section">🤖 Telegram Bot API (Auto Start)</div>
            <div class="group"><label>Bot Token:</label><input type="text" name="bot_token" value="{{ c.get('bot_token','') }}" placeholder="Enter Token"></div>
            <div class="group"><label>API ID:</label><input type="text" name="api_id" value="{{ c.get('api_id','') }}" placeholder="Enter API ID"></div>
            <div class="group"><label>API HASH:</label><input type="text" name="api_hash" value="{{ c.get('api_hash','') }}" placeholder="Enter API Hash"></div>
            <div class="group"><label>Webhook/Site URL:</label><input type="text" name="webhook_url" value="{{ c.get('webhook_url','') }}" placeholder="https://app.onrender.com"></div>

            <div class="section">🔗 Other Variable Settings</div>
            <div class="group"><label>Admin ID (Owner):</label><input type="text" name="owner_id" value="{{ c.get('owner_id','') }}"></div>
            <div class="group"><label>Admin Username (@ ছাড়া):</label><input type="text" name="admin_username" value="{{ c.get('admin_username','') }}"></div>
            <div class="group"><label>Website Link:</label><input type="text" name="website_link" value="{{ c.get('website_link','') }}"></div>
            <div class="group"><label>TMDB API Key:</label><input type="text" name="tmdb_api" value="{{ c.get('tmdb_api','') }}"></div>
            <div class="group"><label>Sortlink API:</label><input type="text" name="sortlink_api" value="{{ c.get('sortlink_api','') }}"></div>
            <div class="group"><label>Sortlink Link:</label><input type="text" name="sortlink_url" value="{{ c.get('sortlink_url','') }}"></div>
            <div class="group"><label>File Channel ID:</label><input type="text" name="file_channel" value="{{ c.get('file_channel','') }}"></div>

            <button type="submit" class="btn">Save & Update Everything</button>
        </form>
        <a href="/logout" class="logout">Logout</a>
    </div>
</body>
</html>
"""

# --- Flask Web Routes ---

@app.route('/')
def home():
    return "<h1>Bot Server is Live!</h1><p>Visit /admin to configure.</p>"

@app.route('/login', methods=['GET', 'POST'])
def login():
    config = sync_settings.find_one({"id": "config"}) or {"p_user": "admin", "p_pass": "admin"}
    if request.method == 'POST':
        if request.form.get('u') == config['p_user'] and request.form.get('p') == config['p_pass']:
            session['logged_in'] = True
            return redirect(url_for('admin_panel'))
    return render_template_string("""
        <body style="display:flex;justify-content:center;align-items:center;height:100vh;background:#f0f2f5;font-family:sans-serif;">
        <form method="post" style="background:white;padding:30px;border-radius:10px;box-shadow:0 5px 15px rgba(0,0,0,0.1);">
            <h3>Admin Login</h3>
            <input type="text" name="u" placeholder="User" required style="display:block;width:200px;margin-bottom:10px;padding:8px;"><br>
            <input type="password" name="p" placeholder="Pass" required style="display:block;width:200px;margin-bottom:10px;padding:8px;"><br>
            <button type="submit" style="width:100%;padding:10px;background:#1a73e8;color:white;border:none;border-radius:5px;">Login</button>
        </form></body>""", config=config)

@app.route('/admin', methods=['GET', 'POST'])
def admin_panel():
    if not session.get('logged_in'): return redirect(url_for('login'))
    if request.method == 'POST':
        data = {k: v for k, v in request.form.items()}
        sync_settings.update_one({"id": "config"}, {"$set": data}, upsert=True)
        # Webhook Update
        try:
            requests.get(f"https://api.telegram.org/bot{data['bot_token']}/setWebhook?url={data['webhook_url']}/webhook")
        except: pass
        return redirect(url_for('admin_panel'))
    config = sync_settings.find_one({"id": "config"}) or {}
    return render_template_string(ADMIN_TEMPLATE, c=config)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# --- Telegram Bot Logic (Auto-Setup) ---

async def bot_task():
    while True:
        config = await async_settings.find_one({"id": "config"})
        
        if config and config.get("bot_token") and config.get("api_id"):
            try:
                # API ID কে ইন্টিজারে কনভার্ট করা
                api_id = int(config["api_id"])
                api_hash = config["api_hash"]
                bot_token = config["bot_token"]

                bot = Client("my_bot", api_id=api_id, api_hash=api_hash, bot_token=bot_token)

                @bot.on_message(filters.command("start") & filters.private)
                async def start_handler(client, message):
                    user = message.from_user
                    full_name = f"{user.first_name} {user.last_name or ''}"
                    
                    # প্রোফাইল ফটো গেট করা
                    photo_id = None
                    async for photo in client.get_chat_photos(user.id, limit=1):
                        photo_id = photo.file_id

                    caption = (
                        f"👋 **হ্যালো, {user.first_name}!**\n\n"
                        f"👤 **আপনার নাম:** `{full_name}`\n"
                        f"🆔 **আপনার আইডি:** `{user.id}`\n\n"
                        "নিচের বাটনগুলো ব্যবহার করুন:"
                    )

                    buttons = InlineKeyboardMarkup([
                        [
                            InlineKeyboardButton("🌐 ওয়েবসাইট", url=config.get("website_link", "https://t.me/")),
                            InlineKeyboardButton("👨‍💻 এডমিন", url=f"https://t.me/{config.get('admin_username', 'admin')}")
                        ]
                    ])

                    if photo_id:
                        await message.reply_photo(photo=photo_id, caption=caption, reply_markup=buttons)
                    else:
                        await message.reply_text(text=caption, reply_markup=buttons)

                print("🚀 বট অটোমেটিক চালু হয়েছে!")
                await bot.start()
                # বট সচল রাখা
                await asyncio.Event().wait()
                
            except Exception as e:
                print(f"❌ এরর: {e}. ১০ সেকেন্ড পর আবার চেষ্টা করা হচ্ছে...")
                await asyncio.sleep(10)
        else:
            print("⚠️ ডাটাবেসে বটের তথ্য নেই। এডমিন প্যানেল থেকে তথ্য দিন।")
            await asyncio.sleep(15)

# --- Main Runner ---

def start_flask():
    app.run(host="0.0.0.0", port=8080)

if __name__ == "__main__":
    # ওয়েবসাইট আলাদা থ্রেডে চালু হবে
    Thread(target=start_flask, daemon=True).start()
    
    # বট মেইন লুপে চলবে
    try:
        asyncio.run(bot_task())
    except (KeyboardInterrupt, SystemExit):
        pass
