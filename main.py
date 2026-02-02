import os
import asyncio
import requests
from flask import Flask, request, render_template_string, redirect
from threading import Thread
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient

# ==========================================
# 🛑 শুধুমাত্র এই লিঙ্কটি পরিবর্তন করবেন 🛑
# ==========================================
MONGO_URI = "আপনার_মোঙ্গোডিবি_লিঙ্ক_এখানে_দিন"
# ==========================================

# ডাটাবেস সেটআপ
sync_client = MongoClient(MONGO_URI)
sync_db = sync_client["MasterBotDB"]
sync_settings = sync_db["settings"]

async_client = AsyncIOMotorClient(MONGO_URI)
async_db = async_client["MasterBotDB"]
async_settings = async_db["settings"]

app = Flask(__name__)

# --- অ্যাডমিন প্যানেল ডিজাইন (HTML/CSS) ---
ADMIN_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Bot Admin Panel</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body { font-family: 'Segoe UI', sans-serif; background-color: #f0f2f5; margin: 0; padding: 20px; }
        .card { max-width: 700px; margin: auto; background: white; padding: 30px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.1); }
        h2 { text-align: center; color: #1a73e8; margin-bottom: 25px; }
        .group { margin-bottom: 15px; }
        label { display: block; font-weight: 600; margin-bottom: 5px; color: #444; }
        input { width: 100%; padding: 10px; border: 1px solid #ccc; border-radius: 6px; box-sizing: border-box; font-size: 14px; }
        .btn { width: 100%; padding: 12px; background: #1a73e8; color: white; border: none; border-radius: 6px; cursor: pointer; font-size: 16px; font-weight: bold; margin-top: 20px; }
        .btn:hover { background: #1557b0; }
        .alert { background: #d4edda; color: #155724; padding: 10px; border-radius: 6px; text-align: center; margin-bottom: 20px; }
        hr { margin: 30px 0; border: 0; border-top: 1px solid #eee; }
    </style>
</head>
<body>
    <div class="card">
        <h2>⚙️ Bot Admin Panel</h2>
        {% if success %}<div class="alert">✅ সেটিংস সফলভাবে সেভ হয়েছে! বট রিস্টার্ট করুন।</div>{% endif %}
        <form method="post">
            <div class="group"><label>Webhook URL (https://your-app.onrender.com):</label><input type="text" name="webhook_url" value="{{ c.get('webhook_url','') }}" required></div>
            <div class="group"><label>Bot Token:</label><input type="text" name="bot_token" value="{{ c.get('bot_token','') }}" required></div>
            <div class="group"><label>API ID:</label><input type="text" name="api_id" value="{{ c.get('api_id','') }}" required></div>
            <div class="group"><label>API HASH:</label><input type="text" name="api_hash" value="{{ c.get('api_hash','') }}" required></div>
            <div class="group"><label>Admin ID (Owner):</label><input type="text" name="owner_id" value="{{ c.get('owner_id','') }}" required></div>
            <div class="group"><label>Admin Username (@ ছাড়া):</label><input type="text" name="admin_username" value="{{ c.get('admin_username','') }}"></div>
            <hr>
            <div class="group"><label>TMDB API Key:</label><input type="text" name="tmdb_api" value="{{ c.get('tmdb_api','') }}"></div>
            <div class="group"><label>Sortlink API Key:</label><input type="text" name="sortlink_api" value="{{ c.get('sortlink_api','') }}"></div>
            <div class="group"><label>Sortlink Web Link (e.g., shareus.io):</label><input type="text" name="sortlink_url" value="{{ c.get('sortlink_url','') }}"></div>
            <div class="group"><label>File Channel ID (e.g., -100...):</label><input type="text" name="file_channel" value="{{ c.get('file_channel','') }}"></div>
            <div class="group"><label>Website Link:</label><input type="text" name="website_link" value="{{ c.get('website_link','') }}"></div>
            
            <button type="submit" class="btn">Save & Update Webhook</button>
        </form>
    </div>
</body>
</html>
"""

@app.route('/')
def home():
    return "<h1>Server is Active!</h1>"

@app.route('/admin', methods=['GET', 'POST'])
def admin_panel():
    success = False
    if request.method == 'POST':
        data = {k: v for k, v in request.form.items()}
        sync_settings.update_one({"id": "config"}, {"$set": data}, upsert=True)
        
        # অটোমেটিক Webhook সেট করার এপিআই কল
        try:
            requests.get(f"https://api.telegram.org/bot{data['bot_token']}/setWebhook?url={data['webhook_url']}/webhook")
        except: pass
        success = True

    config = sync_settings.find_one({"id": "config"}) or {}
    return render_template_string(ADMIN_HTML, c=config, success=success)

# --- টেলিগ্রাম বট লজিক ---

async def start_bot():
    config = await async_settings.find_one({"id": "config"})
    if not config or not config.get("bot_token"):
        print("⚠️ ওয়েবসাইটের /admin পেজ থেকে কনফিগার করুন।")
        return

    try:
        bot = Client(
            "my_bot",
            api_id=int(config["api_id"]),
            api_hash=config["api_hash"],
            bot_token=config["bot_token"]
        )

        @bot.on_message(filters.command("start") & filters.private)
        async def start_handler(client, message):
            user = message.from_user
            full_name = f"{user.first_name} {user.last_name or ''}"
            
            # ইউজারের ছবি আনা
            photo_id = None
            async for photo in client.get_chat_photos(user.id, limit=1):
                photo_id = photo.file_id

            caption = (
                f"👋 **হ্যালো, {user.first_name}!**\n\n"
                f"👤 **নাম:** `{full_name}`\n"
                f"🆔 **আইডি:** `{user.id}`\n\n"
                "বাটনগুলো চেক করুন:"
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

        print("🚀 বট অনলাইন হয়ে গেছে!")
        await bot.start()
        await asyncio.Event().wait()
    except Exception as e:
        print(f"❌ এরর: {e}")

# ওয়েবসাইট চালানোর জন্য ফাংশন
def run_web():
    # Render ডিফল্ট পোর্ট 8080 ব্যবহার করে
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

if __name__ == "__main__":
    # ওয়েবসাইটকে আলাদা ব্যাকগ্রাউন্ড থ্রেডে চালানো
    Thread(target=run_web, daemon=True).start()
    
    # বটকে মেইন ইভেন্ট লুপে চালানো
    try:
        asyncio.run(start_bot())
    except (KeyboardInterrupt, SystemExit):
        pass
