import os
import asyncio
import requests
from flask import Flask, request, render_template_string, redirect, session, url_for
from threading import Thread
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message
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
    db_movies = async_db["movies"]
    db_drafts = async_db["drafts"]
    print("✅ MongoDB Connected Successfully!")
except Exception as e:
    print(f"❌ MongoDB Connection Error: {e}")

app = Flask(__name__)
app.secret_key = os.urandom(24)

# গ্লোবাল স্ট্যাটাস
bot_running = False

# --- অ্যাডমিন প্যানেল ডিজাইন (HTML) ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Master Bot Admin</title>
    <style>
        body { font-family: 'Segoe UI', sans-serif; background: #f0f2f5; margin: 0; padding: 20px; }
        .container { max-width: 800px; margin: auto; background: white; padding: 30px; border-radius: 15px; box-shadow: 0 5px 20px rgba(0,0,0,0.1); }
        h2 { text-align: center; color: #1a73e8; }
        .status { text-align: center; padding: 10px; margin-bottom: 20px; border-radius: 8px; font-weight: bold; }
        .online { background: #d4edda; color: #155724; }
        .offline { background: #f8d7da; color: #721c24; }
        .section { background: #f8f9fa; padding: 15px; border-radius: 8px; margin-bottom: 20px; border-left: 5px solid #1a73e8; }
        .group { margin-bottom: 15px; }
        label { display: block; margin-bottom: 5px; font-weight: bold; color: #555; }
        input { width: 100%; padding: 10px; border: 1px solid #ddd; border-radius: 5px; box-sizing: border-box; }
        .btn { width: 100%; padding: 12px; background: #28a745; color: white; border: none; border-radius: 5px; cursor: pointer; font-size: 16px; font-weight: bold; }
        .btn:hover { background: #218838; }
        .logout { display: block; text-align: center; margin-top: 20px; color: #d93025; text-decoration: none; }
    </style>
</head>
<body>
    <div class="container">
        <h2>⚙️ Admin Control Panel</h2>
        <div class="status {{ 'online' if bot_status else 'offline' }}">
            {{ '🟢 BOT IS ONLINE' if bot_status else '🔴 BOT IS OFFLINE / WAITING FOR CONFIG' }}
        </div>
        <form method="post">
            <div class="section">
                <label>Admin Username:</label>
                <input type="text" name="p_user" value="{{ c.get('p_user','admin') }}">
                <label>Admin Password:</label>
                <input type="password" name="p_pass" value="{{ c.get('p_pass','admin') }}">
            </div>
            <div class="section">
                <label>Bot Token:</label>
                <input type="text" name="bot_token" value="{{ c.get('bot_token','') }}" placeholder="Enter Telegram Bot Token">
                <label>API ID:</label>
                <input type="text" name="api_id" value="{{ c.get('api_id','') }}" placeholder="Enter API ID">
                <label>API HASH:</label>
                <input type="text" name="api_hash" value="{{ c.get('api_hash','') }}" placeholder="Enter API Hash">
            </div>
            <div class="section">
                <label>TMDB API Key:</label>
                <input type="text" name="tmdb_api" value="{{ c.get('tmdb_api','') }}" placeholder="Enter TMDB API Key">
                <label>File Channel ID:</label>
                <input type="text" name="file_channel" value="{{ c.get('file_channel','') }}" placeholder="Example: -100123456789">
            </div>
            <div class="section">
                <label>Website Link:</label>
                <input type="text" name="website_link" value="{{ c.get('website_link','') }}">
                <label>Admin Telegram Username (no @):</label>
                <input type="text" name="admin_username" value="{{ c.get('admin_username','') }}">
            </div>
            <button type="submit" class="btn">Save All & Restart Bot</button>
        </form>
        <a href="/logout" class="logout">Logout</a>
    </div>
</body>
</html>
"""

# --- Flask Routes ---

@app.route('/')
def index():
    return "<h1>Server is Running! Go to /admin</h1>"

@app.route('/login', methods=['GET', 'POST'])
def login():
    config = sync_settings.find_one({"id": "config"}) or {"p_user": "admin", "p_pass": "admin"}
    if request.method == 'POST':
        if request.form.get('username') == config.get('p_user') and request.form.get('password') == config.get('p_pass'):
            session['logged_in'] = True
            return redirect(url_for('admin_panel'))
    return render_template_string("""
    <div style="max-width:300px; margin:100px auto; font-family:sans-serif;">
        <h2>Login</h2>
        <form method="post">
            <input type="text" name="username" placeholder="Username" style="width:100%; padding:10px; margin-bottom:10px;"><br>
            <input type="password" name="password" placeholder="Password" style="width:100%; padding:10px; margin-bottom:10px;"><br>
            <button type="submit" style="width:100%; padding:10px; background:#1a73e8; color:white; border:none; cursor:pointer;">Login</button>
        </form>
    </div>
    """)

@app.route('/admin', methods=['GET', 'POST'])
def admin_panel():
    if not session.get('logged_in'): return redirect(url_for('login'))
    if request.method == 'POST':
        data = {k: v.strip() for k, v in request.form.items()}
        sync_settings.update_one({"id": "config"}, {"$set": data}, upsert=True)
        return redirect(url_for('admin_panel'))
    config = sync_settings.find_one({"id": "config"}) or {}
    return render_template_string(HTML_TEMPLATE, c=config, bot_status=bot_running)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# --- Telegram Bot Task ---

async def bot_task():
    global bot_running
    while True:
        config = await async_settings.find_one({"id": "config"})
        if not config or not config.get("bot_token") or not config.get("api_id"):
            bot_running = False
            await asyncio.sleep(10); continue

        try:
            bot = Client(
                "master_bot_session",
                api_id=int(config["api_id"]),
                api_hash=config["api_hash"],
                bot_token=config["bot_token"],
                in_memory=True
            )

            # TMDB সার্চ ফাংশন
            async def search_tmdb(query):
                api_key = config.get("tmdb_api")
                if not api_key: return []
                url = f"https://api.themoviedb.org/3/search/movie?api_key={api_key}&query={query}"
                try:
                    res = requests.get(url).json()
                    return res.get("results", [])[:5]
                except: return []

            @bot.on_message(filters.command("start") & filters.private)
            async def start_handler(client, message):
                await message.reply_text(f"👋 হ্যালো {message.from_user.first_name}!\nমুভি পোস্ট করতে লিখুন: `/post মুভির নাম`")

            # ১. মুভি পোস্ট কমান্ড
            @bot.on_message(filters.command("post") & filters.private)
            async def post_handler(client, message: Message):
                query = message.text.split(" ", 1)
                if len(query) < 2: return await message.reply_text("❌ ব্যবহার: `/post Leo`")
                
                msg = await message.reply_text("🔍 মুভি খুঁজছি...")
                results = await search_tmdb(query[1])
                if not results: return await msg.edit("❌ কোনো মুভি পাওয়া যায়নি!")
                
                btns = []
                for m in results:
                    year = m.get("release_date", "N/A")[:4]
                    btns.append([InlineKeyboardButton(f"{m['title']} ({year})", callback_data=f"msel_{m['id']}")])
                
                await msg.edit("✅ নিচের তালিকা থেকে মুভি সিলেক্ট করুন:", reply_markup=InlineKeyboardMarkup(btns))

            # ২. মুভি সিলেকশন
            @bot.on_callback_query(filters.regex(r"^msel_"))
            async def msel_handler(client, callback):
                tmdb_id = callback.data.split("_")[1]
                api_key = config.get("tmdb_api")
                m = requests.get(f"https://api.themoviedb.org/3/movie/{tmdb_id}?api_key={api_key}").json()
                
                # ড্রাফট শুরু
                await db_drafts.update_one(
                    {"user_id": callback.from_user.id},
                    {"$set": {
                        "title": m['title'],
                        "poster": f"https://image.tmdb.org/t/p/w500{m['poster_path']}",
                        "desc": m['overview'],
                        "files": [],
                        "step": "lang"
                    }}, upsert=True
                )
                
                btns = [
                    [InlineKeyboardButton("Bangla", callback_data="lang_Bangla"), InlineKeyboardButton("Hindi", callback_data="lang_Hindi")],
                    [InlineKeyboardButton("English", callback_data="lang_English"), InlineKeyboardButton("Dual Audio", callback_data="lang_Dual")]
                ]
                await callback.message.edit_text(f"🎬 মুভি: **{m['title']}**\n\nএখন ভাষা সিলেক্ট করুন:", reply_markup=InlineKeyboardMarkup(btns))

            # ৩. ভাষা সিলেকশন
            @bot.on_callback_query(filters.regex(r"^lang_"))
            async def lang_handler(client, callback):
                lang = callback.data.split("_")[1]
                await db_drafts.update_one({"user_id": callback.from_user.id}, {"$set": {"lang": lang, "step": "qual"}})
                
                btns = [
                    [InlineKeyboardButton("480p", callback_data="qual_480p"), InlineKeyboardButton("720p", callback_data="qual_720p")],
                    [InlineKeyboardButton("1080p", callback_data="qual_1080p"), InlineKeyboardButton("4K UHD", callback_data="qual_4K")]
                ]
                await callback.message.edit_text("🎯 মুভির কোয়ালিটি সিলেক্ট করুন:", reply_markup=InlineKeyboardMarkup(btns))

            # ৪. কোয়ালিটি সিলেকশন (লুপের অংশ)
            @bot.on_callback_query(filters.regex(r"^qual_"))
            async def qual_handler(client, callback):
                qual = callback.data.split("_")[1]
                await db_drafts.update_one({"user_id": callback.from_user.id}, {"$set": {"current_qual": qual, "step": "upload"}})
                await callback.message.edit_text(f"📥 এখন মুভির **{qual}** ফাইলটি পাঠান।\nআপনি চাইলে সরাসরি ফাইলটি এখানে ফরোয়ার্ড করতে পারেন।")

            # ৫. ফাইল হ্যান্ডলার (আনলিমিটেড ফাইল লুপ)
            @bot.on_message(filters.private & (filters.document | filters.video))
            async def file_handler(client, message):
                draft = await db_drafts.find_one({"user_id": message.from_user.id})
                if not draft or draft.get("step") != "upload": return

                wait_msg = await message.reply_text("📤 ফাইলটি চ্যানেলে আপলোড হচ্ছে, দয়া করে অপেক্ষা করুন...")
                
                try:
                    # ফাইল চ্যানেলে ফরোয়ার্ড
                    channel_id = int(config.get("file_channel"))
                    fwd_msg = await message.forward(channel_id)
                    
                    # ডাটাবেসে ফাইল আইডি সেভ করা
                    file_info = {"qual": draft["current_qual"], "file_id": fwd_msg.id}
                    await db_drafts.update_one(
                        {"user_id": message.from_user.id},
                        {"$push": {"files": file_info}, "$set": {"step": "next_choice"}}
                    )

                    btns = [
                        [InlineKeyboardButton("➕ আরও কোয়ালিটি এড করুন", callback_data="add_more_qual")],
                        [InlineKeyboardButton("✅ পোস্টিং শেষ করুন", callback_data="finish_post")]
                    ]
                    await wait_msg.edit(f"✅ **{draft['current_qual']}** ফাইলটি সফলভাবে এড হয়েছে।\nএখন কি করবেন?", reply_markup=InlineKeyboardMarkup(btns))
                except Exception as e:
                    await wait_msg.edit(f"❌ এরর: {e}\nনিশ্চিত করুন বটটি আপনার চ্যানেলে এডমিন আছে।")

            # ৬. আরও কোয়ালিটি এড করার হ্যান্ডলার
            @bot.on_callback_query(filters.regex("add_more_qual"))
            async def add_more_handler(client, callback):
                await db_drafts.update_one({"user_id": callback.from_user.id}, {"$set": {"step": "qual"}})
                btns = [
                    [InlineKeyboardButton("480p", callback_data="qual_480p"), InlineKeyboardButton("720p", callback_data="qual_720p")],
                    [InlineKeyboardButton("1080p", callback_data="qual_1080p"), InlineKeyboardButton("4K UHD", callback_data="qual_4K")]
                ]
                await callback.message.edit_text("🎯 পরবর্তী কোয়ালিটি সিলেক্ট করুন:", reply_markup=InlineKeyboardMarkup(btns))

            # ৭. পোস্টিং ফিনিশ করা
            @bot.on_callback_query(filters.regex("finish_post"))
            async def finish_handler(client, callback):
                draft = await db_drafts.find_one({"user_id": callback.from_user.id})
                if not draft: return
                
                # মেইন মুভি কালেকশনে ডাটা ট্রান্সফার
                movie_data = {
                    "title": draft["title"],
                    "lang": draft["lang"],
                    "poster": draft["poster"],
                    "desc": draft["desc"],
                    "files": draft["files"] # এখানে সব কোয়ালিটির ফাইল লিস্ট আছে
                }
                await db_movies.insert_one(movie_data)
                await db_drafts.delete_one({"user_id": callback.from_user.id})
                
                await callback.message.edit_text(f"🏁 সফলভাবে **{draft['title']}** সাইটে এড করা হয়েছে!\nমোট কোয়ালিটি ফাইল এড হয়েছে: {len(draft['files'])} টি।")

            await bot.start()
            bot_running = True
            print("🚀 Bot is Online with Movie Post System!")
            
            # বট চালু রাখতে লুপ
            while True:
                new_conf = await async_settings.find_one({"id": "config"})
                if new_conf.get("bot_token") != config.get("bot_token"): break
                await asyncio.sleep(20)
            
            await bot.stop()
            bot_running = False

        except Exception as e:
            print(f"❌ Bot Error: {e}")
            bot_running = False
            await asyncio.sleep(10)

# --- রান করার সিস্টেম ---

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    # ওয়েবসাইট ব্যাকগ্রাউন্ডে
    Thread(target=run_flask, daemon=True).start()
    
    # মেইন লুপে বট
    try:
        asyncio.run(bot_task())
    except (KeyboardInterrupt, SystemExit):
        pass
