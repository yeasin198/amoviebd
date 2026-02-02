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

# --- Shortlink ফাংশন (এটি শর্টলিংক তৈরি করবে) ---
def get_shortlink(url, api_key, domain):
    if not api_key or not domain:
        return url
    try:
        res = requests.get(f"https://{domain}/api?api={api_key}&url={url}")
        data = res.json()
        if data.get("status") == "success":
            return data.get("shortenedUrl")
    except:
        pass
    return url

# --- এডমিন প্যানেল ডিজাইন ---
LOGIN_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Admin Login</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body { font-family: sans-serif; background: #1a1a1a; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; color: white; }
        .card { background: #2d2d2d; padding: 30px; border-radius: 12px; width: 90%; max-width: 350px; text-align: center; }
        input { width: 100%; padding: 12px; margin: 10px 0; border: none; border-radius: 6px; box-sizing: border-box; }
        .btn { width: 100%; padding: 12px; background: #007bff; color: white; border: none; border-radius: 6px; cursor: pointer; }
    </style>
</head>
<body>
    <div class="card">
        <h2>Admin Panel</h2>
        <form method="post">
            <input type="text" name="username" placeholder="Username" required>
            <input type="password" name="password" placeholder="Password" required>
            <button type="submit" class="btn">Login</button>
        </form>
    </div>
</body>
</html>
"""

# অ্যাডমিন ড্যাশবোর্ড কোড (আগের চেয়ে আরও গোছানো)
ADMIN_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Settings</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body { font-family: sans-serif; background: #f4f7f6; padding: 20px; }
        .container { max-width: 600px; margin: auto; background: white; padding: 20px; border-radius: 10px; box-shadow: 0 5px 15px rgba(0,0,0,0.1); }
        .group { margin-bottom: 15px; }
        label { display: block; font-weight: bold; margin-bottom: 5px; }
        input { width: 100%; padding: 10px; border: 1px solid #ddd; border-radius: 5px; box-sizing: border-box; }
        .btn { width: 100%; padding: 12px; background: #28a745; color: white; border: none; border-radius: 5px; cursor: pointer; }
        .section { background: #eee; padding: 10px; margin-top: 20px; font-weight: bold; }
    </style>
</head>
<body>
    <div class="container">
        <h2>⚙️ Admin Settings</h2>
        <form method="post">
            <div class="section">🔐 Login Settings</div>
            <div class="group"><label>Username:</label><input type="text" name="p_user" value="{{ c.get('p_user','admin') }}"></div>
            <div class="group"><label>Password:</label><input type="text" name="p_pass" value="{{ c.get('p_pass','admin') }}"></div>
            
            <div class="section">🤖 Bot Core</div>
            <div class="group"><label>Bot Token:</label><input type="text" name="bot_token" value="{{ c.get('bot_token','') }}"></div>
            <div class="group"><label>API ID:</label><input type="text" name="api_id" value="{{ c.get('api_id','') }}"></div>
            <div class="group"><label>API HASH:</label><input type="text" name="api_hash" value="{{ c.get('api_hash','') }}"></div>
            <div class="group"><label>Owner ID:</label><input type="text" name="owner_id" value="{{ c.get('owner_id','') }}"></div>

            <div class="section">🔗 APIs & Links</div>
            <div class="group"><label>Website URL:</label><input type="text" name="website_link" value="{{ c.get('website_link','') }}"></div>
            <div class="group"><label>Admin Telegram Username (@ ছাড়া):</label><input type="text" name="admin_username" value="{{ c.get('admin_username','') }}"></div>
            <div class="group"><label>TMDB API Key:</label><input type="text" name="tmdb_api" value="{{ c.get('tmdb_api','') }}"></div>
            <div class="group"><label>Sortlink API Key:</label><input type="text" name="sortlink_api" value="{{ c.get('sortlink_api','') }}"></div>
            <div class="group"><label>Sortlink Domain (e.g., shareus.io):</label><input type="text" name="sortlink_url" value="{{ c.get('sortlink_url','') }}"></div>
            
            <button type="submit" class="btn">Save Settings</button>
        </form>
        <br><center><a href="/logout">Logout</a></center>
    </div>
</body>
</html>
"""

# --- ওয়েবসাইট রুটস ---

@app.route('/')
def home():
    return "<h1>Server is Running!</h1>"

@app.route('/login', methods=['GET', 'POST'])
def login():
    config = sync_settings.find_one({"id": "config"}) or {"p_user": "admin", "p_pass": "admin"}
    if request.method == 'POST':
        if request.form.get('username') == config['p_user'] and request.form.get('password') == config['p_pass']:
            session['logged_in'] = True
            return redirect(url_for('admin_panel'))
    return render_template_string(LOGIN_HTML)

@app.route('/admin', methods=['GET', 'POST'])
def admin_panel():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    if request.method == 'POST':
        data = {k: v for k, v in request.form.items()}
        sync_settings.update_one({"id": "config"}, {"$set": data}, upsert=True)
        return redirect(url_for('admin_panel'))
    config = sync_settings.find_one({"id": "config"}) or {}
    return render_template_string(ADMIN_HTML, c=config)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# --- টেলিগ্রাম বট লজিক ---

async def bot_task():
    # ডাটাবেস থেকে কনফিগ লোড
    conf = await async_settings.find_one({"id": "config"})
    if not conf or not conf.get("bot_token"):
        print("⚠️ Waiting for config...")
        return

    try:
        bot = Client(
            "my_bot",
            api_id=int(conf["api_id"]),
            api_hash=conf["api_hash"],
            bot_token=conf["bot_token"]
        )

        @bot.on_message(filters.command("start") & filters.private)
        async def start_handler(client, message):
            user = message.from_user
            full_name = f"{user.first_name} {user.last_name or ''}"
            
            # ইউজার প্রোফাইল ফটো
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
                    InlineKeyboardButton("🌐 ওয়েবসাইট", url=conf.get("website_link", "https://t.me/")),
                    InlineKeyboardButton("👨‍💻 এডমিন", url=f"https://t.me/{conf.get('admin_username', 'admin')}")
                ]
            ])

            if photo_id:
                await message.reply_photo(photo=photo_id, caption=caption, reply_markup=buttons)
            else:
                await message.reply_text(text=caption, reply_markup=buttons)

        # --- মুভি সার্চ ডেমো (TMDB ব্যবহার করে) ---
        @bot.on_message(filters.text & filters.private)
        async def movie_search(client, message):
            tmdb_key = conf.get("tmdb_api")
            if not tmdb_key:
                return await message.reply("⚠️ TMDB API সেট করা নেই।")
            
            search_query = message.text
            res = requests.get(f"https://api.themoviedb.org/3/search/movie?api_key={tmdb_key}&query={search_query}")
            data = res.json()
            
            if data.get("results"):
                movie = data["results"][0]
                title = movie["title"]
                rating = movie["vote_average"]
                overview = movie["overview"]
                await message.reply(f"🎬 **Movie:** {title}\n⭐ **Rating:** {rating}\n\n📝 {overview}")
            else:
                await message.reply("❌ কোনো মুভি পাওয়া যায়নি।")

        await bot.start()
        print("🚀 বট সফলভাবে অনলাইন হয়েছে!")
        await asyncio.Event().wait()
    except Exception as e:
        print(f"❌ বট ক্র্যাশ করেছে: {e}")

# রান ফাংশন
def run_web():
    app.run(host="0.0.0.0", port=8080)

if __name__ == "__main__":
    Thread(target=run_web, daemon=True).start()
    
    loop = asyncio.get_event_loop()
    loop.run_until_complete(bot_task())
