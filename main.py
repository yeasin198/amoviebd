import telebot
import requests
import os
import time
import threading
from telebot import types
from pymongo import MongoClient
from flask import Flask, render_template_string, redirect, url_for, request, session

# ================== ডাটাবেস সেটআপ ==================
# আপনার MongoDB URI এখানে দিন অথবা Environment Variable হিসেবে সেট করুন।
MONGO_URI = os.environ.get('MONGO_URI', "your_mongodb_uri_here") 

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
app.secret_key = "secret_movie_key_123"

# অ্যাডমিন প্যানেল ডিফল্ট লগইন
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "password123"

admin_states = {}

# --- [সহায়ক ফাংশনসমূহ] ---
def get_config():
    conf = config_col.find_one({'type': 'core_settings'}) or {}
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

def auto_delete_task(bot, chat_id, msg_id, delay):
    """নির্দিষ্ট সময় পর মেসেজ ডিলিট করার থ্রেড ফাংশন"""
    if delay > 0:
        time.sleep(delay)
        try:
            bot.delete_message(chat_id, msg_id)
        except: pass

# --- [টেলিগ্রাম বট লজিক] ---
def register_handlers(bot):
    if not bot: return

    @bot.message_handler(commands=['start'])
    def start(message):
        config = get_config()
        # Deep Linking চেক (যখন ওয়েবসাইট থেকে 'Download' এ ক্লিক করবে)
        if len(message.text.split()) > 1:
            movie_id = message.text.split()[1]
            movie = movies_col.find_one({'tmdb_id': str(movie_id)})
            if movie:
                is_protect = True if config.get('PROTECT_CONTENT') == 'on' else False
                
                # মুভি ফাইল পাঠানো
                sent_msg = bot.copy_message(
                    chat_id=message.chat.id,
                    from_chat_id=int(config['STORAGE_CHANNEL_ID']),
                    message_id=int(movie['file_id']),
                    protect_content=is_protect
                )
                
                # অটো ডিলিট অপশন
                delay = int(config.get('AUTO_DELETE_TIME', 0))
                if delay > 0:
                    bot.send_message(message.chat.id, f"⚠️ ফাইলটি {delay} সেকেন্ড পর ডিলিট হবে।")
                    threading.Thread(target=auto_delete_task, args=(bot, message.chat.id, sent_msg.message_id, delay)).start()
                return
            else:
                bot.send_message(message.chat.id, "❌ ফাইলটি ডাটাবেসে পাওয়া যায়নি।")
                return
        bot.reply_to(message, "🎬 স্বাগতম! মুভি পোস্ট করতে অ্যাডমিন `/post মুভির নাম` লিখুন।", parse_mode="Markdown")

    @bot.message_handler(commands=['post'])
    def post_search(message):
        config = get_config()
        if str(message.from_user.id) != str(config.get('ADMIN_ID')): return
        query = message.text.replace('/post', '').strip()
        if not query:
            bot.reply_to(message, "⚠️ মুভির নাম লিখুন। যেমন: `/post Avatar`")
            return
        
        tmdb_api = config.get('TMDB_API_KEY')
        url = f"https://api.themoviedb.org/3/search/movie?api_key={tmdb_api}&query={query}"
        try:
            res = requests.get(url).json().get('results', [])
        except: res = []

        if not res:
            bot.reply_to(message, "❌ মুভিটি খুঁজে পাওয়া যায়নি।")
            return

        markup = types.InlineKeyboardMarkup()
        for m in res[:5]:
            markup.add(types.InlineKeyboardButton(text=f"{m['title']} ({m.get('release_date', '')[:4]})", callback_data=f"sel_{m['id']}"))
        bot.send_message(message.chat.id, "🔍 মুভিটি সিলেক্ট করুন:", reply_markup=markup)

    @bot.callback_query_handler(func=lambda call: call.data.startswith('sel_'))
    def lang_sel(call):
        movie_id = call.data.split('_')[1]
        markup = types.InlineKeyboardMarkup()
        for l in ["Bangla", "Hindi", "English", "Multi"]:
            markup.add(types.InlineKeyboardButton(text=l, callback_data=f"lang_{movie_id}_{l}"))
        bot.edit_message_text("🌐 ল্যাঙ্গুয়েজ সিলেক্ট করুন:", call.message.chat.id, call.message.message_id, reply_markup=markup)

    @bot.callback_query_handler(func=lambda call: call.data.startswith('lang_'))
    def qual_sel(call):
        _, mid, lang = call.data.split('_')
        markup = types.InlineKeyboardMarkup()
        for q in ["480p", "720p", "1080p", "4K", "Bluray"]:
            markup.add(types.InlineKeyboardButton(text=q, callback_data=f"save_{mid}_{lang}_{q}"))
        bot.edit_message_text("💎 কোয়ালিটি সিলেক্ট করুন:", call.message.chat.id, call.message.message_id, reply_markup=markup)

    @bot.callback_query_handler(func=lambda call: call.data.startswith('save_'))
    def ask_file(call):
        _, mid, lang, qual = call.data.split('_')
        admin_states[call.from_user.id] = {'tmdb_id': mid, 'lang': lang, 'qual': qual}
        bot.edit_message_text(f"📥 মুভি: {mid}\nভাষা: {lang}\nকোয়ালিটি: {qual}\n\nএখন মুভি ফাইলটি (ভিডিও/ডকুমেন্ট) এখানে পাঠান।", call.message.chat.id, call.message.message_id)

    @bot.message_handler(content_types=['video', 'document'])
    def handle_incoming_file(message):
        uid = message.from_user.id
        config = get_config()
        if uid in admin_states:
            state = admin_states[uid]
            # স্টোরেজ চ্যানেলে মুভিটি রাখা
            sent_msg = bot.copy_message(int(config['STORAGE_CHANNEL_ID']), message.chat.id, message.message_id)
            
            # TMDB থেকে ডিটেইলস সংগ্রহ (Cast, Crew, Trailer সহ)
            tmdb_api = config['TMDB_API_KEY']
            m_url = f"https://api.themoviedb.org/3/movie/{state['tmdb_id']}?api_key={tmdb_api}&append_to_response=credits,videos"
            m = requests.get(m_url).json()
            
            cast = ", ".join([a['name'] for a in m.get('credits', {}).get('cast', [])[:10]])
            director = next((p['name'] for p in m.get('credits', {}).get('crew', []) if p['job'] == 'Director'), 'N/A')
            trailer_key = next((v['key'] for v in m.get('videos', {}).get('results', []) if v['type'] == 'Trailer'), "")

            movie_data = {
                'tmdb_id': str(state['tmdb_id']), 
                'title': m['title'],
                'lang': state['lang'], 
                'quality': state['qual'],
                'file_id': sent_msg.message_id,
                'poster': f"https://image.tmdb.org/t/p/w500{m.get('poster_path')}",
                'rating': m.get('vote_average', 'N/A'),
                'story': m.get('overview', 'N/A'),
                'cast': cast,
                'director': director,
                'trailer': f"https://www.youtube.com/embed/{trailer_key}" if trailer_key else ""
            }
            movies_col.update_one({'tmdb_id': movie_data['tmdb_id']}, {'$set': movie_data}, upsert=True)
            bot.send_message(message.chat.id, f"✅ মুভি সফলভাবে সেভ হয়েছে!\nটাইটেল: {m['title']}")
            del admin_states[uid]

# --- [FLASK WEB ROUTES] ---

@app.route('/')
def home():
    movies = list(movies_col.find().sort('_id', -1))
    return render_template_string(HOME_HTML, movies=movies)

@app.route('/movie/<tmdb_id>')
def movie_details(tmdb_id):
    movie = movies_col.find_one({'tmdb_id': tmdb_id})
    if not movie: return "Movie Not Found", 404
    
    config = get_config()
    sh_set = get_shortener()
    
    # বটের ইউজারনেম পাওয়া
    bot_username = ""
    if config.get('BOT_TOKEN'):
        try:
            bot_username = telebot.TeleBot(config['BOT_TOKEN']).get_me().username
        except: pass

    long_url = f"https://t.me/{bot_username}?start={tmdb_id}"
    final_url = long_url
    
    # লিঙ্ক শর্টনার লজিক
    if sh_set.get('status') == 'on' and sh_set.get('api_url'):
        try:
            res = requests.get(sh_set['api_url'], params={'api': sh_set['api_key'], 'url': long_url}).json()
            final_url = res.get('shortenedUrl') or res.get('short_url') or long_url
        except: pass

    return render_template_string(DETAILS_HTML, m=movie, download_url=final_url)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form.get('u') == ADMIN_USERNAME and request.form.get('p') == ADMIN_PASSWORD:
            session['logged_in'] = True
            return redirect(url_for('admin'))
    return render_template_string(LOGIN_HTML)

@app.route('/admin')
def admin():
    if not session.get('logged_in'): return redirect(url_for('login'))
    return render_template_string(ADMIN_HTML, config=get_config(), shortener=get_shortener(), movies=list(movies_col.find()))

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

@app.route('/save_shortener', methods=['POST'])
def save_shortener():
    if not session.get('logged_in'): return redirect(url_for('login'))
    data = {
        'type': 'shortener', 'api_url': request.form.get('api_url'), 
        'api_key': request.form.get('api_key'), 'status': request.form.get('status')
    }
    settings_col.update_one({'type': 'shortener'}, {'$set': data}, upsert=True)
    return redirect(url_for('admin'))

@app.route('/delete/<tmdb_id>')
def delete_movie(tmdb_id):
    if not session.get('logged_in'): return redirect(url_for('login'))
    movies_col.delete_one({'tmdb_id': tmdb_id})
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

# ================== ডিজাইন ও টেমপ্লেট ==================

HOME_HTML = """
<!DOCTYPE html><html><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Movie Portal</title><link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css">
<style>
body{background:#0b0c10;color:#c5c6c7; font-family: 'Segoe UI', sans-serif;}
.card{background:#1f2833;border:none; transition:0.3s;}
.card:hover{transform:translateY(-10px); border:1px solid #66fcf1;}
.card-title{font-size: 0.9rem; color:#fff;}
a{text-decoration:none;}
.navbar{background:#1f2833; border-bottom: 2px solid #66fcf1;}
</style></head><body>
<nav class="navbar navbar-dark mb-5"><div class="container"><a class="navbar-brand text-info fw-bold" href="/">🎬 MOVIE PORTAL</a></div></nav>
<div class="container"><div class="row row-cols-2 row-cols-md-5 g-4">
{% for m in movies %}
<div class="col"><a href="/movie/{{m.tmdb_id}}"><div class="card h-100">
<img src="{{m.poster}}" class="card-img-top"><div class="card-body text-center">
<h6 class="card-title">{{m.title}}</h6><small class="text-info">{{m.lang}} | {{m.quality}}</small>
</div></div></a></div>
{% endfor %}
</div></div></body></html>
"""

DETAILS_HTML = """
<!DOCTYPE html><html><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{{m.title}}</title><link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css">
<style>
body{background:#0b0c10;color:#c5c6c7;}
.poster{width:100%; border-radius:15px; box-shadow: 0 0 15px #66fcf1;}
.btn-download{background:#66fcf1; color:#0b0c10; font-weight:bold; font-size:1.3rem;}
.btn-download:hover{background:#45a29e;}
.badge-custom{background:#1f2833; color:#66fcf1; border:1px solid #66fcf1;}
</style></head><body>
<div class="container py-5">
    <div class="row">
        <div class="col-md-4 mb-4"><img src="{{m.poster}}" class="poster"></div>
        <div class="col-md-8">
            <h1 class="text-white">{{m.title}}</h1>
            <div class="mb-3">
                <span class="badge badge-custom">⭐ {{m.rating}}</span>
                <span class="badge badge-custom">🌐 {{m.lang}}</span>
                <span class="badge badge-custom">💎 {{m.quality}}</span>
            </div>
            <p><b>Director:</b> {{m.director}}</p>
            <p><b>Cast:</b> {{m.cast}}</p>
            <p><b>Storyline:</b><br>{{m.story}}</p>
            <a href="{{download_url}}" class="btn btn-download w-100 py-3 mt-3">🚀 Download Now</a>
        </div>
    </div>
    {% if m.trailer %}
    <div class="mt-5"><h3>Official Trailer</h3>
    <div class="ratio ratio-16x9"><iframe src="{{m.trailer}}" allowfullscreen></iframe></div></div>
    {% endif %}
    <div class="text-center mt-5"><a href="/" class="btn btn-outline-info">← Home</a></div>
</div></body></html>
"""

ADMIN_HTML = """
<!DOCTYPE html><html><head><title>Admin Panel</title><link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css"></head>
<body class="bg-light container py-5">
<div class="d-flex justify-content-between mb-4"><h2>⚙️ Admin Control</h2><a href="/" class="btn btn-secondary">Site Home</a></div>
<div class="row">
    <div class="col-md-6 mb-4">
        <div class="card p-3 shadow-sm"><h5>Core Settings</h5>
        <form action="/save_config" method="POST">
            <label>Site URL</label><input name="site_url" class="form-control mb-2" value="{{config.SITE_URL}}">
            <label>Bot Token</label><input name="token" class="form-control mb-2" value="{{config.BOT_TOKEN}}">
            <label>TMDB API Key</label><input name="tmdb" class="form-control mb-2" value="{{config.TMDB_API_KEY}}">
            <label>Admin Chat ID</label><input name="admin_id" class="form-control mb-2" value="{{config.ADMIN_ID}}">
            <label>Storage Channel ID</label><input name="channel_id" class="form-control mb-2" value="{{config.STORAGE_CHANNEL_ID}}">
            <label>Auto Delete (Sec)</label><input name="delete_time" type="number" class="form-control mb-2" value="{{config.AUTO_DELETE_TIME}}">
            <label>Protect Content</label><select name="protect" class="form-control mb-3">
                <option value="on" {% if config.PROTECT_CONTENT == 'on' %}selected{% endif %}>ON</option>
                <option value="off" {% if config.PROTECT_CONTENT == 'off' %}selected{% endif %}>OFF</option>
            </select>
            <button class="btn btn-primary w-100">Save Config</button></form></div>
    </div>
    <div class="col-md-6">
        <div class="card p-3 shadow-sm mb-4"><h5>Link Shortener</h5>
        <form action="/save_shortener" method="POST">
            <label>API URL</label><input name="api_url" class="form-control mb-2" value="{{shortener.api_url}}">
            <label>API Key</label><input name="api_key" class="form-control mb-2" value="{{shortener.api_key}}">
            <label>Status</label><select name="status" class="form-control mb-2">
                <option value="on" {% if shortener.status == 'on' %}selected{% endif %}>ON</option>
                <option value="off" {% if shortener.status == 'off' %}selected{% endif %}>OFF</option>
            </select><button class="btn btn-success w-100">Update Shortener</button></form></div>
    </div>
</div>
<div class="card p-3"><h5>Database Movies</h5><table class="table">
{% for m in movies %}<tr><td>{{m.title}} ({{m.quality}})</td><td><a href="/delete/{{m.tmdb_id}}" class="text-danger">Delete</a></td></tr>{% endfor %}
</table></div></body></html>
"""

LOGIN_HTML = """
<!DOCTYPE html><html><head><title>Login</title><link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css"></head>
<body class="d-flex align-items-center justify-content-center bg-dark" style="height:100vh;">
<div class="card p-4" style="width:300px;"><h4>Admin Login</h4>
<form method="POST"><input name="u" class="form-control mb-2" placeholder="User"><input name="p" type="password" class="form-control mb-3" placeholder="Pass">
<button class="btn btn-primary w-100">Login</button></form></div></body></html>
"""

# ================== রান অ্যাপ্লিকেশন ==================

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
