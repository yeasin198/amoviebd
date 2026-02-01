import telebot
import requests
import os
import time
import threading
from telebot import types
from pymongo import MongoClient
from flask import Flask, render_template_string, redirect, url_for, request, session

# ================== ডাটাবেস সেটআপ ==================
MONGO_URI = os.environ.get('MONGO_URI') 

try:
    client = MongoClient(MONGO_URI)
    db = client['movie_portal_db']
    config_col = db['bot_config']
    movies_col = db['movies_data']
    settings_col = db['settings']
    print("✅ MongoDB Connected Successfully!")
except Exception as e:
    print(f"❌ MongoDB Connection Error: {e}")

app = Flask(__name__)
app.secret_key = "super_secret_key_movie_portal"

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "password123"

admin_states = {}

# --- [সহায়ক ফাংশনসমূহ] ---
def get_config():
    conf = config_col.find_one({'type': 'core_settings'}) or {}
    # ডিফল্ট ভ্যালু যদি না থাকে
    defaults = {
        'SITE_URL': '', 'BOT_TOKEN': '', 'TMDB_API_KEY': '', 
        'ADMIN_ID': '', 'STORAGE_CHANNEL_ID': '',
        'AUTO_DELETE_TIME': 0, 'PROTECT_CONTENT': 'off'
    }
    for key, val in defaults.items():
        if key not in conf: conf[key] = val
    return conf

def get_shortener():
    return settings_col.find_one({'type': 'shortener'}) or {'status': 'off', 'api_url': '', 'api_key': ''}

def create_bot():
    config = get_config()
    token = config.get('BOT_TOKEN')
    if token:
        return telebot.TeleBot(token, threaded=False)
    return None

def auto_delete_msg(bot, chat_id, msg_id, delay):
    """নির্দিষ্ট সময় পর মেসেজ ডিলিট করার ফাংশন"""
    if delay > 0:
        time.sleep(delay)
        try:
            bot.delete_message(chat_id, msg_id)
        except:
            pass

# --- [টেলিগ্রাম বট লজিক] ---
def register_handlers(bot):
    if not bot: return

    @bot.message_handler(commands=['start'])
    def start(message):
        config = get_config()
        if len(message.text.split()) > 1:
            tmdb_id = message.text.split()[1]
            movie = movies_col.find_one({'tmdb_id': str(tmdb_id)})
            if movie:
                # ফরওয়ার্ড প্রোটেকশন চেক
                protect = True if config.get('PROTECT_CONTENT') == 'on' else False
                
                # ফাইল পাঠানো
                sent_msg = bot.copy_message(
                    message.chat.id, 
                    int(config['STORAGE_CHANNEL_ID']), 
                    movie['file_id'],
                    protect_content=protect
                )
                
                # অটো ডিলিট লজিক
                delay = int(config.get('AUTO_DELETE_TIME', 0))
                if delay > 0:
                    bot.send_message(message.chat.id, f"⚠️ এই ফাইলটি {delay} সেকেন্ড পর অটোমেটিক ডিলিট হয়ে যাবে। দ্রুত সেভ বা অন্য কোথাও ফরওয়ার্ড (যদি অনুমতি থাকে) করে রাখুন।")
                    threading.Thread(target=auto_delete_msg, args=(bot, message.chat.id, sent_msg.message_id, delay)).start()
                return
            else:
                bot.send_message(message.chat.id, "❌ মুভিটি পাওয়া যায়নি।")
                return
        bot.reply_to(message, "🎬 মুভি সার্চ করতে লিখুন: `/post Movie Name`", parse_mode="Markdown")

    @bot.message_handler(commands=['post'])
    def post_search(message):
        config = get_config()
        if str(message.from_user.id) != str(config.get('ADMIN_ID')): return
        query = message.text.replace('/post', '').strip()
        if not query:
            bot.reply_to(message, "⚠️ মুভির নাম লিখুন।")
            return
        
        tmdb_api = config.get('TMDB_API_KEY')
        url = f"https://api.themoviedb.org/3/search/movie?api_key={tmdb_api}&query={query}"
        res = requests.get(url).json().get('results', [])

        if not res:
            bot.reply_to(message, "❌ খুঁজে পাওয়া যায়নি।")
            return

        markup = types.InlineKeyboardMarkup()
        for m in res[:5]:
            markup.add(types.InlineKeyboardButton(text=f"{m['title']} ({m.get('release_date', '')[:4]})", callback_data=f"sel_{m['id']}"))
        bot.send_message(message.chat.id, "🔍 মুভি সিলেক্ট করুন:", reply_markup=markup)

    @bot.callback_query_handler(func=lambda call: call.data.startswith('sel_'))
    def lang_sel(call):
        movie_id = call.data.split('_')[1]
        markup = types.InlineKeyboardMarkup()
        for l in ["Bangla", "Hindi", "English", "Multi"]:
            markup.add(types.InlineKeyboardButton(text=l, callback_data=f"lang_{movie_id}_{l}"))
        bot.edit_message_text("🌐 ল্যাঙ্গুয়েজ সিলেক্ট করুন:", call.message.chat.id, call.message.message_id, reply_markup=markup)

    @bot.callback_query_handler(func=lambda call: call.data.startswith('lang_'))
    def ask_file(call):
        _, mid, lang = call.data.split('_')
        admin_states[call.from_user.id] = {'tmdb_id': mid, 'lang': lang}
        bot.edit_message_text("📥 এবার মুভি ফাইলটি (Video/Doc) এখানে পাঠান।", call.message.chat.id, call.message.message_id)

    @bot.message_handler(content_types=['video', 'document'])
    def save_file(message):
        uid = message.from_user.id
        config = get_config()
        if uid in admin_states:
            state = admin_states[uid]
            sent_msg = bot.copy_message(int(config['STORAGE_CHANNEL_ID']), message.chat.id, message.message_id)
            
            # TMDB থেকে ডিটেইলস সংগ্রহ (Credits ও Videos সহ)
            tmdb_api = config['TMDB_API_KEY']
            m_url = f"https://api.themoviedb.org/3/movie/{state['tmdb_id']}?api_key={tmdb_api}&append_to_response=credits,videos"
            m = requests.get(m_url).json()
            
            # ডাটা প্রসেসিং
            cast = ", ".join([actor['name'] for actor in m.get('credits', {}).get('cast', [])[:5]])
            director = next((person['name'] for person in m.get('credits', {}).get('crew', []) if person['job'] == 'Director'), 'Unknown')
            trailer_key = next((v['key'] for v in m.get('videos', {}).get('results', []) if v['type'] == 'Trailer'), '')

            movie_data = {
                'tmdb_id': str(state['tmdb_id']), 
                'title': m['title'],
                'lang': state['lang'], 
                'file_id': sent_msg.message_id,
                'poster': f"https://image.tmdb.org/t/p/w500{m.get('poster_path')}",
                'rating': m.get('vote_average', 'N/A'),
                'story': m.get('overview', 'No story available.'),
                'cast': cast,
                'director': director,
                'trailer': f"https://www.youtube.com/embed/{trailer_key}" if trailer_key else ""
            }
            movies_col.update_one({'tmdb_id': movie_data['tmdb_id']}, {'$set': movie_data}, upsert=True)
            bot.send_message(message.chat.id, f"✅ **{m['title']}** সফলভাবে অ্যাড হয়েছে!")
            del admin_states[uid]

# --- [WEB UI ROUTES] ---

@app.route('/')
def home():
    movies = list(movies_col.find().sort('_id', -1))
    return render_template_string(HOME_HTML, movies=movies)

@app.route('/movie/<tmdb_id>')
def movie_details(tmdb_id):
    movie = movies_col.find_one({'tmdb_id': tmdb_id})
    if not movie: return "Movie Not Found", 404
    
    config = get_config()
    bot_username = ""
    try:
        temp_bot = telebot.TeleBot(config['BOT_TOKEN'])
        bot_username = temp_bot.get_me().username
    except: pass

    # শর্টনার চেক
    long_url = f"https://t.me/{bot_username}?start={tmdb_id}"
    sh_set = get_shortener()
    final_url = long_url
    if sh_set.get('status') == 'on' and sh_set.get('api_url'):
        try:
            res_short = requests.get(sh_set['api_url'], params={'api': sh_set['api_key'], 'url': long_url}).json()
            final_url = res_short.get('shortenedUrl') or res_short.get('short_url') or long_url
        except: pass

    return render_template_string(DETAILS_HTML, m=movie, download_url=final_url)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form.get('username') == ADMIN_USERNAME and request.form.get('password') == ADMIN_PASSWORD:
            session['logged_in'] = True
            return redirect(url_for('admin'))
    return render_template_string(LOGIN_HTML)

@app.route('/admin')
def admin():
    if not session.get('logged_in'): return redirect(url_for('login'))
    config = get_config()
    shortener = get_shortener()
    movies = list(movies_col.find().sort('_id', -1))
    return render_template_string(ADMIN_HTML, config=config, shortener=shortener, movies=movies)

@app.route('/save_config', methods=['POST'])
def save_config():
    if not session.get('logged_in'): return redirect(url_for('login'))
    data = {
        'SITE_URL': request.form.get('site_url').rstrip('/'),
        'BOT_TOKEN': request.form.get('token'),
        'TMDB_API_KEY': request.form.get('tmdb'),
        'ADMIN_ID': request.form.get('admin_id'),
        'STORAGE_CHANNEL_ID': request.form.get('channel_id'),
        'AUTO_DELETE_TIME': int(request.form.get('delete_time', 0)),
        'PROTECT_CONTENT': request.form.get('protect')
    }
    config_col.update_one({'type': 'core_settings'}, {'$set': data}, upsert=True)
    try:
        bot = telebot.TeleBot(data['BOT_TOKEN'])
        bot.remove_webhook()
        time.sleep(1)
        bot.set_webhook(url=f"{data['SITE_URL']}/webhook")
    except: pass
    return redirect(url_for('admin'))

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

@app.route('/delete/<tmdb_id>')
def delete_movie(tmdb_id):
    if not session.get('logged_in'): return redirect(url_for('login'))
    movies_col.delete_one({'tmdb_id': tmdb_id})
    return redirect(url_for('admin'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ================== HTML টেমপ্লেটস ==================

HOME_HTML = """
<!DOCTYPE html><html><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Movie Search Site</title><link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css">
<style>body{background:#0b0c10;color:white;}.card{background:#1f2833;border:none;transition: 0.3s; cursor: pointer;}.card:hover{transform: scale(1.05); border: 1px solid #66fcf1;}</style>
</head><body class="container py-5">
<h2 class="text-center mb-5" style="color:#66fcf1;">🎬 Latest Movie Portal</h2>
<div class="row row-cols-2 row-cols-md-5 g-4">
{% for m in movies %}
<div class="col"><a href="/movie/{{m.tmdb_id}}" style="text-decoration:none; color:inherit;">
<div class="card h-100"><img src="{{m.poster}}" class="card-img-top">
<div class="card-body p-2 text-center"><h6 class="card-title">{{m.title}}</h6>
<p class="small text-muted">{{m.lang}} | ⭐ {{m.rating}}</p></div></div></a></div>
{% endfor %}
</div></body></html>
"""

DETAILS_HTML = """
<!DOCTYPE html><html><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{{m.title}} - Details</title><link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css">
<style>body{background:#0b0c10;color:white;}.poster-img{width:100%; border-radius:10px; box-shadow: 0 0 20px #66fcf1;} .btn-dl{background:#66fcf1; color:#0b0c10; font-weight:bold; font-size: 1.2rem;}</style>
</head><body class="container py-5">
<div class="row">
    <div class="col-md-4 mb-4"><img src="{{m.poster}}" class="poster-img"></div>
    <div class="col-md-8">
        <h1 style="color:#66fcf1;">{{m.title}}</h1>
        <p>⭐ <b>Rating:</b> {{m.rating}} | 🌐 <b>Language:</b> {{m.lang}}</p>
        <hr>
        <p><b>Director:</b> {{m.director}}</p>
        <p><b>Cast:</b> {{m.cast}}</p>
        <p><b>Storyline:</b><br>{{m.story}}</p>
        <a href="{{download_url}}" class="btn btn-dl w-100 py-3 mt-3">🚀 Download via Bot</a>
    </div>
</div>
{% if m.trailer %}
<div class="mt-5"><h3>Official Trailer</h3>
<div class="ratio ratio-16x9"><iframe src="{{m.trailer}}" allowfullscreen></iframe></div></div>
{% endif %}
<div class="text-center mt-5"><a href="/" class="text-muted">← Back to Home</a></div>
</body></html>
"""

LOGIN_HTML = """
<!DOCTYPE html><html><head><title>Login</title><link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css"></head>
<body class="d-flex align-items-center justify-content-center" style="height:100vh; background:#1f2833;">
<div class="card p-4 shadow" style="width:350px;"><h4>Admin Login</h4>
<form method="POST"><input name="username" class="form-control mb-2" placeholder="Username">
<input type="password" name="password" class="form-control mb-3" placeholder="Password">
<button class="btn btn-primary w-100">Login</button></form></div></body></html>
"""

ADMIN_HTML = """
<!DOCTYPE html><html><head><title>Admin Panel</title><link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css"></head>
<body class="container py-5">
<div class="d-flex justify-content-between mb-4"><h3>⚙️ Control Panel</h3><a href="/logout" class="btn btn-danger btn-sm">Logout</a></div>
<form action="/save_config" method="POST">
<div class="row">
    <div class="col-md-6 mb-4"><div class="card p-3 shadow-sm"><h5>Core Settings</h5>
        <label>Site URL</label><input name="site_url" class="form-control mb-2" value="{{config.SITE_URL}}">
        <label>Bot Token</label><input name="token" class="form-control mb-2" value="{{config.BOT_TOKEN}}">
        <label>TMDB API Key</label><input name="tmdb" class="form-control mb-2" value="{{config.TMDB_API_KEY}}">
        <label>Admin ID</label><input name="admin_id" class="form-control mb-2" value="{{config.ADMIN_ID}}">
        <label>Storage Channel ID</label><input name="channel_id" class="form-control mb-2" value="{{config.STORAGE_CHANNEL_ID}}">
    </div></div>
    <div class="col-md-6"><div class="card p-3 shadow-sm"><h5>Bot Features</h5>
        <label>Auto Delete (Seconds - 0 to disable)</label><input name="delete_time" type="number" class="form-control mb-2" value="{{config.AUTO_DELETE_TIME}}">
        <label>Forward Protection (Protect Content)</label>
        <select name="protect" class="form-control mb-3">
            <option value="on" {% if config.PROTECT_CONTENT == 'on' %}selected{% endif %}>ON (Cannot Forward/Save)</option>
            <option value="off" {% if config.PROTECT_CONTENT == 'off' %}selected{% endif %}>OFF</option>
        </select>
        <button class="btn btn-primary w-100">Save All Settings</button>
    </div></div>
</div>
</form>
<div class="card p-3 mt-4"><h5>Movies ({{movies|length}})</h5>
<table class="table">{% for m in movies %}<tr><td>{{m.title}}</td><td><a href="/delete/{{m.tmdb_id}}" class="text-danger">Delete</a></td></tr>{% endfor %}</table>
</div></body></html>
"""

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
