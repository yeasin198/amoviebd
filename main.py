import os
import asyncio
from flask import Flask, render_template, request
from threading import Thread
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from motor.motor_asyncio import AsyncIOMotorClient

# [নির্দেশনা]: শুধুমাত্র নিচের এই লিঙ্কটি কোডে রাখতে হবে যাতে বট ডাটাবেসের সাথে কানেক্ট হতে পারে।
# বাকি সব (API ID, Token, TMDB Key) আপনি ওয়েবসাইট থেকে সেট করবেন।
MONGO_URI = "আপনার_মোঙ্গোডিবি_লিঙ্ক_এখানে_দিন"

# ডাটাবেস সেটআপ
db_client = AsyncIOMotorClient(MONGO_URI)
db = db_client["BotConfigDB"]
settings_col = db["settings"]

app = Flask(__name__)

# --- ওয়েবসাইট এডমিন প্যানেল (Frontend) ---

@app.route('/')
def index():
    return "<h1 style='text-align:center;'>বট এবং ওয়েবসাইট সার্ভার সচল আছে।<br>এডমিন প্যানেলের জন্য /admin এ যান।</h1>"

@app.route('/admin', methods=['GET', 'POST'])
async def admin_panel():
    if request.method == 'POST':
        # ওয়েবসাইট থেকে ডাটা নিয়ে ডাটাবেসে সেভ করা
        config_data = {
            "api_id": request.form.get("api_id"),
            "api_hash": request.form.get("api_hash"),
            "bot_token": request.form.get("bot_token"),
            "owner_id": request.form.get("owner_id"),
            "admin_username": request.form.get("admin_username"),
            "file_channel": request.form.get("file_channel"),
            "shortlink_api": request.form.get("shortlink_api"),
            "shortlink_url": request.form.get("shortlink_url"),
            "website_link": request.form.get("website_link"),
            "tmdb_api": request.form.get("tmdb_api")  # TMDB API যোগ করা হয়েছে
        }
        await settings_col.update_one({"id": "bot_config"}, {"$set": config_data}, upsert=True)
        return "<h2>✅ সফলভাবে আপডেট হয়েছে! বটটি রিস্টার্ট করুন।</h2><a href='/admin'>ফিরে যান</a>"

    # ডাটাবেস থেকে বর্তমান ডাটা নিয়ে ফর্মে দেখানো
    current_config = await settings_col.find_one({"id": "bot_config"}) or {}
    
    html_form = f"""
    <html>
    <head><title>Admin Panel</title></head>
    <body style="font-family: Arial; padding: 30px; background-color: #f4f4f4;">
        <div style="max-width: 600px; margin: auto; background: white; padding: 20px; border-radius: 10px; box-shadow: 0px 0px 10px #ccc;">
            <h2 style="text-align: center; color: #333;">Bot Admin Panel</h2>
            <form method="post">
                <label>API ID:</label><br><input type="text" name="api_id" value="{current_config.get('api_id', '')}" style="width:100%; padding:8px; margin: 10px 0;"><br>
                <label>API HASH:</label><br><input type="text" name="api_hash" value="{current_config.get('api_hash', '')}" style="width:100%; padding:8px; margin: 10px 0;"><br>
                <label>BOT TOKEN:</label><br><input type="text" name="bot_token" value="{current_config.get('bot_token', '')}" style="width:100%; padding:8px; margin: 10px 0;"><br>
                <label>OWNER ID:</label><br><input type="text" name="owner_id" value="{current_config.get('owner_id', '')}" style="width:100%; padding:8px; margin: 10px 0;"><br>
                <label>ADMIN USERNAME (টেলিগ্রাম):</label><br><input type="text" name="admin_username" value="{current_config.get('admin_username', '')}" style="width:100%; padding:8px; margin: 10px 0;"><br>
                <hr>
                <label>TMDB API KEY:</label><br><input type="text" name="tmdb_api" value="{current_config.get('tmdb_api', '')}" placeholder="Enter TMDB API Key" style="width:100%; padding:8px; margin: 10px 0; border: 2px solid #007bff;"><br>
                <hr>
                <label>FILE CHANNEL ID:</label><br><input type="text" name="file_channel" value="{current_config.get('file_channel', '')}" style="width:100%; padding:8px; margin: 10px 0;"><br>
                <label>SHORTLINK URL:</label><br><input type="text" name="shortlink_url" value="{current_config.get('shortlink_url', '')}" style="width:100%; padding:8px; margin: 10px 0;"><br>
                <label>SHORTLINK API KEY:</label><br><input type="text" name="shortlink_api" value="{current_config.get('shortlink_api', '')}" style="width:100%; padding:8px; margin: 10px 0;"><br>
                <label>WEBSITE LINK:</label><br><input type="text" name="website_link" value="{current_config.get('website_link', '')}" style="width:100%; padding:8px; margin: 10px 0;"><br>
                
                <input type="submit" value="Save All Settings" style="width: 100%; padding: 10px; background: #28a745; color: white; border: none; cursor: pointer; border-radius: 5px; font-size: 16px;">
            </form>
        </div>
    </body>
    </html>
    """
    return html_form

# --- টেলিগ্রাম বট লজিক ---

async def start_telegram_bot():
    # ডাটাবেস থেকে সেটিংস লোড করা
    config = await settings_col.find_one({"id": "bot_config"})
    
    if not config or not config.get("bot_token"):
        print("⚠️ ডাটাবেসে বটের কনফিগারেশন নেই। ওয়েবসাইট এডমিন প্যানেল থেকে তথ্য দিন।")
        return

    try:
        bot = Client(
            "my_bot",
            api_id=int(config["api_id"]),
            api_hash=config["api_hash"],
            bot_token=config["bot_token"]
        )

        @bot.on_message(filters.command("start") & filters.private)
        async def start_cmd(client, message):
            user = message.from_user
            full_name = f"{user.first_name} {user.last_name or ''}"
            
            # ইউজারের প্রোফাইল ফটো গেট করা
            photo_id = None
            async for photo in client.get_chat_photos(user.id, limit=1):
                photo_id = photo.file_id

            caption = (
                f"👋 **স্বাগতম {user.first_name}!**\n\n"
                f"👤 **আপনার নাম:** `{full_name}`\n"
                f"🆔 **আপনার আইডি:** `{user.id}`\n\n"
                "আমাদের সার্ভিস পেতে নিচের বাটন ব্যবহার করুন।"
            )

            buttons = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🌐 আমাদের ওয়েবসাইট", url=config["website_link"]),
                    InlineKeyboardButton("👨‍💻 এডমিন", url=f"https://t.me/{config['admin_username']}")
                ]
            ])

            if photo_id:
                await message.reply_photo(photo=photo_id, caption=caption, reply_markup=buttons)
            else:
                await message.reply_text(text=caption, reply_markup=buttons)

        print("🚀 বট সফলভাবে চালু হয়েছে!")
        await bot.start()
        
    except Exception as e:
        print(f"❌ এরর: {e}")

# ওয়েবসাইট এবং বট একসাথে চালানোর জন্য থ্রেডিং
def run_website():
    app.run(host="0.0.0.0", port=8080)

if __name__ == "__main__":
    # ওয়েবসাইট থ্রেড চালু করা
    t = Thread(target=run_website)
    t.daemon = True
    t.start()

    # বট চালু করা
    loop = asyncio.get_event_loop()
    loop.run_until_complete(start_telegram_bot())
    loop.run_forever()
