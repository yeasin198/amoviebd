import telebot
import requests
import os
import time
from telebot import types
from pymongo import MongoClient
from flask import Flask, render_template_string, redirect, url_for, request, session
from threading import Thread

# ================== ডাটাবেস সেটআপ ==================
# Render বা Koyeb এর Environment Variable এ 'MONGO_URI' অবশ্যই সেট করবেন।
MONGO_URI = os.environ.get('MONGO_URI') 

try:
    client = MongoClient(MONGO_URI)
    db = client['movie_portal_db']
    config_col = db['bot_config']     # বট ও সাইট সেটিংস
    movies_col = db['movies_data']     # মুভি লিস্ট ও ফাইল আইডি
    settings_col = db['settings']      # শর্টনার সেটিংস
    print("✅ MongoDB Connected Successfully!")
except Exception as e:
    print(f"❌ MongoDB Connection Error: {e}")

app = Flask(__name__)
app.secret_key = "any_random_secret_string_for_session" # সেশনের জন্য সিক্রেট কী

# অ্যাডমিন প্যানেল লগইন ক্রেডেনশিয়াল (আপনি চাইলে এখানে পরিবর্তন করতে পারেন)
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "password123"

# অ্যাডমিন যখন মুভি আপলোড করছে তখন মুভি আইডি মনে রাখার জন্য গ্লোবাল ডিকশনারি
admin_states = {}

# --- [সহায়ক ফাংশনসমূহ] ---
def get_config():
    """ডাটাবেস থেকে মূল সেটিংস আনে"""
    return config_col.find_one({'type': 'core_settings'}) or {}

def get_shortener():
    """ডাটাবেস থেকে লিঙ্ক শর্টনার সেটিংস আনে"""
    return settings_col.find_one({'type': 'shortener'}) or {'status': 'off', 'api_url': '', 'api_key': ''}

def create_bot():
    """বট অবজেক্ট তৈরি করার ফাংশন"""
    config = get_config()
    token = config.get('BOT_TOKEN')
    if token:
        return telebot.TeleBot(token, threaded=False)
    return None

# --- [টেলিগ্রাম বট লজিক ও হ্যান্ডলার] ---
def register_handlers(bot):
    if not bot: return

    # ১. স্টার্ট কমান্ড (ডাউনলোড হ্যান্ডলার সহ)
    @bot.message_handler(commands=['start'])
    def start(message):
        # ওয়েবসাইট থেকে বা বাটন থেকে আসলে লিঙ্ক চেক করবে (Deep Linking)
        if len(message.text.split()) > 1:
            tmdb_id = message.text.split()[1]
            movie = movies_col.find_one({'tmdb_id': str(tmdb_id)})
            if movie:
                config = get_config()
                bot.copy_message(message.chat.id, int(config['STORAGE_CHANNEL_ID']), movie['file_id'])
                return
            else:
                bot.send_message(message.chat.id, "❌ দুঃখিত, মুভি ফাইলটি আমাদের ডাটাবেসে পাওয়া যায়নি।")
                return
        bot.reply_to(message, "🎬 মুভি সার্চ করতে লিখুন: `/post Movie Name`", parse_mode="Markdown")

    # ২. অ্যাডমিন কমান্ড (প্যানেল লিঙ্ক পাওয়ার জন্য)
    @bot.message_handler(commands=['admin'])
    def admin_cmd(message):
        config = get_config()
        if str(message.from_user.id) == str(config.get('ADMIN_ID')):
            site_url = config.get('SITE_URL', request.host_url).rstrip('/')
            bot.reply_to(message, f"🔐 **অ্যাডমিন প্যানেল লগইন লিঙ্ক:**\n{site_url}/login", parse_mode="Markdown")
        else:
            bot.reply_to(message, "🚫 আপনি এই বটের অ্যাডমিন নন।")

    # ৩. মুভি সার্চ ও তালিকা প্রদান (/post)
    @bot.message_handler(commands=['post'])
    def post_search(message):
        config = get_config()
        if str(message.from_user.id) != str(config.get('ADMIN_ID')): return
        query = message.text.replace('/post', '').strip()
        if not query:
            bot.reply_to(message, "⚠️ মুভির নাম লিখুন। যেমন: `/post Avatar`")
            return
        
        # TMDB API কল
        tmdb_api = config.get('TMDB_API_KEY')
        url = f"https://api.themoviedb.org/3/search/movie?api_key={tmdb_api}&query={query}"
        try:
            res = requests.get(url).json().get('results', [])
        except:
            res = []

        if not res:
            bot.reply_to(message, "❌ এই নামে কোনো মুভি খুঁজে পাওয়া যায়নি।")
            return

        markup = types.InlineKeyboardMarkup()
        for m in res[:5]:
            btn_text = f"{m['title']} ({m.get('release_date', 'N/A')[:4]})"
            markup.add(types.InlineKeyboardButton(text=btn_text, callback_data=f"sel_{m['id']}"))
        bot.send_message(message.chat.id, "🔍 নিচের তালিকা থেকে সঠিক মুভিটি সিলেক্ট করুন:", reply_markup=markup)

    # ৪. মুভি সিলেক্ট করার পর ভাষা নির্বাচন
    @bot.callback_query_handler(func=lambda call: call.data.startswith('sel_'))
    def lang_sel(call):
        movie_id = call.data.split('_')[1]
        markup = types.InlineKeyboardMarkup()
        for l in ["Bangla", "Hindi", "English", "Multi"]:
            markup.add(types.InlineKeyboardButton(text=l, callback_data=f"lang_{movie_id}_{l}"))
        bot.edit_message_text("🌐 মুভির অডিও ল্যাঙ্গুয়েজ সিলেক্ট করুন:", call.message.chat.id, call.message.message_id, reply_markup=markup)

    # ৫. ভাষা নির্বাচনের পর ফাইল আপলোড চাওয়া
    @bot.callback_query_handler(func=lambda call: call.data.startswith('lang_'))
    def ask_file(call):
        _, mid, lang = call.data.split('_')
        admin_states[call.from_user.id] = {'tmdb_id': mid, 'lang': lang}
        bot.edit_message_text("📥 এবার মুভি ফাইলটি (Video/Doc) এখানে পাঠান। এটি অটোমেটিক লিঙ্ক হয়ে যাবে।", call.message.chat.id, call.message.message_id)

    # ৬. ফাইল পাঠানো হলে সেটি সেভ করা
    @bot.message_handler(content_types=['video', 'document'])
    def save_file(message):
        uid = message.from_user.id
        config = get_config()
        if uid in admin_states:
            state = admin_states[uid]
            # ফাইলটি স্টোরেজ চ্যানেলে কপি করা
            sent_msg = bot.copy_message(int(config['STORAGE_CHANNEL_ID']), message.chat.id, message.message_id)
            
            # TMDB থেকে বিস্তারিত তথ্য ও পোস্টার সংগ্রহ
            m_url = f"https://api.themoviedb.org/3/movie/{state['tmdb_id']}?api_key={config['TMDB_API_KEY']}"
            m_info = requests.get(m_url).json()
            
            movie_data = {
                'tmdb_id': str(state['tmdb_id']), 
                'title': m_info['title'],
                'lang': state['lang'], 
                'file_id': sent_msg.message_id,
                'poster': f"https://image.tmdb.org/t/p/w500{m_info.get('poster_path')}",
                'rating': m_info.get('vote_average', 'N/A')
            }
            # ডাটাবেসে মুভিটি সেভ বা আপডেট করা
            movies_col.update_one({'tmdb_id': movie_data['tmdb_id']}, {'$set': movie_data}, upsert=True)
            
            # বটের ইউজারনেম বের করা লিঙ্কের জন্য
            bot_name = bot.get_me().username
            long_url = f"https://t.me/{bot_name}?start={state['tmdb_id']}"
            
            # লিঙ্ক শর্টনার চেক
            sh_set = get_shortener()
            final_url = long_url
            if sh_set.get('status') == 'on' and sh_set.get('api_url'):
                try:
                    res_short = requests.get(sh_set['api_url'], params={'api': sh_set['api_key'], 'url': long_url}).json()
                    final_url = res_short.get('shortenedUrl') or res_short.get('short_url') or long_url
                except: pass

            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🚀 Download Now", url=final_url))
            
            caption = f"🎬 **{m_info['title']}**\n🌐 ভাষা: {state['lang']}\n⭐ রেটিং: {movie_info.get('vote_average')}\n💎 কোয়ালিটি: HD 720p/1080p (Auto)"
            bot.send_photo(message.chat.id, movie_data['poster'], caption=caption, reply_markup=markup, parse_mode="Markdown")
            
            # সেশন মুছে ফেলা
            del admin_states[uid]

# --- [WEBHOOK ROUTE] ---
@app.route('/webhook', methods=['POST'])
def webhook():
    bot = create_bot()
    if bot and request.headers.get('content-type') == 'application/json':
        register_handlers(bot)
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return '', 200
    return 'Forbidden', 403

# --- [WEBSITE UI ROUTES] ---

# ইউজার প্যানেল (হোম পেজ)
@app.route('/')
def home():
    movies = list(movies_col.find().sort('_id', -1))
    config = get_config()
    bot_username = ""
    if config.get('BOT_TOKEN'):
        try: 
            temp_bot = telebot.TeleBot(config['BOT_TOKEN'])
            bot_username = temp_bot.get_me().username
        except: pass
    
    html = """
    <!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Movie Search Site</title><link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css">
    <style>body{background:#0b0c10;color:white;}.card{background:#1f2833;border:none;margin-bottom:20px;transition: 0.3s;}.card:hover{transform: scale(1.05); border: 1px solid #45a29e;} .btn-dl{background:#66fcf1; color:#0b0c10; font-weight:bold; border:none;}</style></head>
    <body class="container py-5"><h2 class="text-center mb-5" style="color:#66fcf1;">🎬 Latest Movie Releases</h2><div class="row row-cols-2 row-cols-md-5 g-3">
    {% for m in movies %}<div class="col"><div class="card h-100"><img src="{{m.poster}}" class="card-img-top"><div class="card-body p-2 text-center">
    <h6 class="card-title">{{m.title}}</h6><p class="small text-muted">{{m.lang}} | ⭐ {{m.rating}}</p>
    <a href="https://t.me/{{bot_username}}?start={{m.tmdb_id}}" class="btn btn-dl btn-sm w-100">Download</a></div></div></div>{% endfor %}
    </div></body></html>
    """
    return render_template_string(html, movies=movies, bot_username=bot_username)

# লগইন পেজ
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form.get('username') == ADMIN_USERNAME and request.form.get('password') == ADMIN_PASSWORD:
            session['logged_in'] = True
            return redirect(url_for('admin'))
        else:
            return "❌ ভুল ইউজারনেম বা পাসওয়ার্ড! <a href='/login'>আবার চেষ্টা করুন</a>"
    
    return """
    <!DOCTYPE html><html><head><title>Login</title><link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css"></head>
    <body class="d-flex align-items-center justify-content-center" style="height:100vh; background:#1f2833;">
    <div class="card p-4 shadow" style="width:350px;"><h4 class="text-center mb-3">Admin Login</h4>
    <form method="POST"><input name="username" class="form-control mb-2" placeholder="Username" required>
    <input type="password" name="password" class="form-control mb-3" placeholder="Password" required>
    <button class="btn btn-primary w-100">Login</button></form></div></body></html>
    """

# অ্যাডমিন প্যানেল
@app.route('/admin')
def admin():
    if not session.get('logged_in'): return redirect(url_for('login'))
    config = get_config()
    shortener = get_shortener()
    movies = list(movies_col.find().sort('_id', -1))
    
    html = """
    <!DOCTYPE html><html><head><title>Admin Panel</title><link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css"></head>
    <body class="container py-5">
    <div class="d-flex justify-content-between mb-4"><h3>⚙️ Control Panel</h3><a href="/logout" class="btn btn-outline-danger btn-sm">Logout</a></div>
    <div class="row"><div class="col-md-6 mb-4"><div class="card p-3 shadow-sm"><h5>Core Settings</h5>
    <form action="/save_config" method="POST">
    <label>Site URL (ex: https://myapp.onrender.com)</label><input name="site_url" class="form-control mb-2" value="{{config.SITE_URL}}" placeholder="https://app.onrender.com">
    <label>Bot Token</label><input name="token" class="form-control mb-2" value="{{config.BOT_TOKEN}}">
    <label>TMDB API Key</label><input name="tmdb" class="form-control mb-2" value="{{config.TMDB_API_KEY}}">
    <label>Admin Telegram ID</label><input name="admin_id" class="form-control mb-2" value="{{config.ADMIN_ID}}">
    <label>Storage Channel ID</label><input name="channel_id" class="form-control mb-2" value="{{config.STORAGE_CHANNEL_ID}}">
    <button class="btn btn-primary w-100 mt-2">Save & Set Webhook</button></form></div></div>
    <div class="col-md-6"><div class="card p-3 shadow-sm"><h5>Link Shortener</h5><form action="/save_shortener" method="POST">
    <label>API URL</label><input name="api_url" class="form-control mb-2" value="{{shortener.api_url}}" placeholder="https://gplinks.in/api">
    <label>API Key</label><input name="api_key" class="form-control mb-2" value="{{shortener.api_key}}">
    <label>Status</label><select name="status" class="form-control mb-2"><option value="on" {% if shortener.status == 'on' %}selected{% endif %}>ON</option><option value="off" {% if shortener.status == 'off' %}selected{% endif %}>OFF</option></select>
    <button class="btn btn-success w-100 mt-2">Update Shortener</button></form></div></div></div>
    <div class="card p-3 mt-4"><h5>Movies in Database</h5><table class="table table-sm"><thead><tr><th>Title</th><th>Action</th></tr></thead>
    <tbody>{% for m in movies %}<tr><td>{{m.title}}</td><td><a href="/delete/{{m.tmdb_id}}" class="btn btn-link text-danger">Delete</a></td></tr>{% endfor %}</tbody></table></div>
    </body></html>
    """
    return render_template_string(html, config=config, shortener=shortener, movies=movies)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/save_config', methods=['POST'])
def save_config():
    if not session.get('logged_in'): return redirect(url_for('login'))
    site_url = request.form.get('site_url').rstrip('/')
    token = request.form.get('token')
    data = {'type': 'core_settings', 'SITE_URL': site_url, 'BOT_TOKEN': token, 'TMDB_API_KEY': request.form.get('tmdb'), 'ADMIN_ID': request.form.get('admin_id'), 'STORAGE_CHANNEL_ID': request.form.get('channel_id')}
    config_col.update_one({'type': 'core_settings'}, {'$set': data}, upsert=True)
    
    # Webhook সেটআপ
    try:
        temp_bot = telebot.TeleBot(token)
        temp_bot.remove_webhook()
        time.sleep(1)
        temp_bot.set_webhook(url=f"{site_url}/webhook")
    except: pass
    return redirect(url_for('admin'))

@app.route('/save_shortener', methods=['POST'])
def save_shortener():
    if not session.get('logged_in'): return redirect(url_for('login'))
    data = {'type': 'shortener', 'api_url': request.form.get('api_url'), 'api_key': request.form.get('api_key'), 'status': request.form.get('status')}
    settings_col.update_one({'type': 'shortener'}, {'$set': data}, upsert=True)
    return redirect(url_for('admin'))

@app.route('/delete/<tmdb_id>')
def delete_movie(tmdb_id):
    if not session.get('logged_in'): return redirect(url_for('login'))
    movies_col.delete_one({'tmdb_id': tmdb_id})
    return redirect(url_for('admin'))

# --- [মেইন অ্যাপ্লিকেশন রান] ---
if __name__ == '__main__':
    # পোর্ট বাইন্ডিং
    port = int(os.environ.get('PORT', 5000))
    # Flask সার্ভার চালু করা (Gunicorn প্রোডাকশনে এটি নিয়ন্ত্রণ করবে)
    app.run(host='0.0.0.0', port=port)
