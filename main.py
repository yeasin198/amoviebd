import telebot
import requests
import os
import time
import threading
import urllib.parse
from telebot import types
from pymongo import MongoClient
from bson import ObjectId
from flask import Flask, render_template_string, redirect, url_for, request, session

# ================== ডাটাবেস সেটআপ ==================
MONGO_URI = os.environ.get('MONGO_URI', "YOUR_MONGODB_URI_HERE") 

try:
    client = MongoClient(MONGO_URI)
    db = client['movie_portal_db']
    config_col = db['bot_config']      
    movies_col = db['movies_data']      
    episodes_col = db['episodes_data']  
    print("✅ MongoDB Connected Successfully!")
except Exception as e:
    print(f"❌ MongoDB Connection Error: {e}")

app = Flask(__name__)
app.secret_key = "ultimate_portal_final_secret_key_full_version"

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "password123"

admin_states = {}

# --- [সহায়ক ফাংশনসমূহ] ---
def get_config():
    try:
        conf = config_col.find_one({'type': 'core_settings'}) or {}
    except:
        conf = {}
    defaults = {
        'SITE_URL': '', 'BOT_TOKEN': '', 'TMDB_API_KEY': '', 
        'ADMIN_ID': '', 'STORAGE_CHANNEL_ID': '',
        'AUTO_DELETE_TIME': 0, 'PROTECT_CONTENT': 'off',
        'SHORTENER_URL': '', 'SHORTENER_API': '' 
    }
    for key, val in defaults.items():
        if key not in conf: conf[key] = val
    return conf

def get_short_link(long_url):
    config = get_config()
    s_url = config.get('SHORTENER_URL')
    s_api = config.get('SHORTENER_API')
    if not s_url or not s_api: return long_url
    try:
        api_endpoint = f"https://{s_url}?api={s_api}&url={urllib.parse.quote(long_url)}"
        res = requests.get(api_endpoint).json()
        return res.get('shortenedUrl') or res.get('shortlink') or long_url
    except:
        return long_url

def create_bot():
    config = get_config()
    token = config.get('BOT_TOKEN')
    if token and len(token) > 20:
        try:
            return telebot.TeleBot(token, threaded=False)
        except:
            return None
    return None

def auto_delete_task(bot, chat_id, msg_id, delay):
    if delay > 0:
        time.sleep(delay)
        try:
            bot.delete_message(chat_id, msg_id)
        except: pass

# --- [টেলিগ্রাম বট হ্যান্ডলার] ---
def register_handlers(bot):
    if not bot: return

    @bot.message_handler(commands=['start'])
    def start(message):
        config = get_config()
        if len(message.text.split()) > 1:
            cmd_data = message.text.split()[1]
            file_to_send = None
            if cmd_data.startswith('dl_'):
                file_to_send = cmd_data.replace('dl_', '')
            
            if file_to_send:
                protect = True if config.get('PROTECT_CONTENT') == 'on' else False
                try:
                    sent_msg = bot.copy_message(message.chat.id, int(config['STORAGE_CHANNEL_ID']), int(file_to_send), protect_content=protect)
                    delay = int(config.get('AUTO_DELETE_TIME', 0))
                    if delay > 0:
                        bot.send_message(message.chat.id, f"⚠️ ফাইলটি {delay} সেকেন্ড পর ডিলিট হবে।")
                        threading.Thread(target=auto_delete_task, args=(bot, message.chat.id, sent_msg.message_id, delay)).start()
                except:
                    bot.send_message(message.chat.id, "❌ ফাইল পাওয়া যায়নি।")
                return
        bot.reply_to(message, "🎬 মুভি বা টিভি শো খুঁজতে আমাদের ওয়েবসাইট ভিজিট করুন।")

    @bot.message_handler(commands=['post'])
    def post_search(message):
        config = get_config()
        if str(message.from_user.id) != str(config.get('ADMIN_ID')): return
        query = message.text.replace('/post', '').strip()
        if not query:
            bot.reply_to(message, "⚠️ মুভির নাম লিখুন।")
            return
        
        tmdb_api = config.get('TMDB_API_KEY')
        url = f"https://api.themoviedb.org/3/search/multi?api_key={tmdb_api}&query={query}"
        try: res = requests.get(url).json().get('results', [])
        except: res = []

        if not res:
            bot.reply_to(message, "❌ কিছুই খুঁজে পাওয়া যায়নি।")
            return

        markup = types.InlineKeyboardMarkup()
        for m in res[:8]:
            if m['media_type'] not in ['movie', 'tv']: continue
            name = m.get('title') or m.get('name')
            year = (m.get('release_date') or m.get('first_air_date') or 'N/A')[:4]
            markup.add(types.InlineKeyboardButton(text=f"[{m['media_type'].upper()}] {name} ({year})", callback_data=f"sel_{m['media_type']}_{m['id']}"))
        bot.send_message(message.chat.id, "🔍 কি আপলোড করতে চান সিলেক্ট করুন:", reply_markup=markup)

    @bot.callback_query_handler(func=lambda call: call.data.startswith('sel_'))
    def handle_selection(call):
        _, m_type, m_id = call.data.split('_')
        if m_type == 'movie':
            markup = types.InlineKeyboardMarkup()
            for l in ["Bangla", "Hindi", "English", "Multi"]:
                markup.add(types.InlineKeyboardButton(text=l, callback_data=f"lang_m_{m_id}_{l}"))
            bot.edit_message_text("🌐 ল্যাঙ্গুয়েজ সিলেক্ট করুন:", call.message.chat.id, call.message.message_id, reply_markup=markup)
        else:
            admin_states[call.from_user.id] = {'type': 'tv', 'tmdb_id': m_id}
            msg = bot.send_message(call.message.chat.id, "📺 সিজন নম্বর লিখুন:")
            bot.register_next_step_handler(msg, get_season)

    def get_season(message):
        uid = message.from_user.id
        if uid in admin_states:
            admin_states[uid]['season'] = message.text
            bot.send_message(message.chat.id, "🔢 এপিসোড নম্বর লিখুন:")
            bot.register_next_step_handler(message, get_episode)

    def get_episode(message):
        uid = message.from_user.id
        if uid in admin_states:
            admin_states[uid]['episode'] = message.text
            bot.send_message(message.chat.id, "📥 কোয়ালিটি লিখুন:")
            bot.register_next_step_handler(message, get_tv_quality)

    def get_tv_quality(message):
        uid = message.from_user.id
        if uid in admin_states:
            admin_states[uid]['qual'] = message.text
            bot.send_message(message.chat.id, "📥 ভিডিও ফাইলটি পাঠান:")

    @bot.callback_query_handler(func=lambda call: call.data.startswith('lang_m_'))
    def movie_qual(call):
        _, _, mid, lang = call.data.split('_')
        markup = types.InlineKeyboardMarkup()
        for q in ["480p", "720p", "1080p", "4K", "Custom"]:
            markup.add(types.InlineKeyboardButton(text=q, callback_data=f"qual_m_{mid}_{lang}_{q}"))
        bot.edit_message_text("💎 কোয়ালিটি সিলেক্ট করুন:", call.message.chat.id, call.message.message_id, reply_markup=markup)

    @bot.callback_query_handler(func=lambda call: call.data.startswith('qual_m_'))
    def movie_file_ask(call):
        _, _, mid, lang, qual = call.data.split('_')
        if qual == "Custom":
            admin_states[call.from_user.id] = {'type': 'movie', 'tmdb_id': mid, 'lang': lang}
            msg = bot.send_message(call.message.chat.id, "🖊️ কাস্টম কোয়ালিটি লিখুন:")
            bot.register_next_step_handler(msg, get_custom_qual)
        else:
            admin_states[call.from_user.id] = {'type': 'movie', 'tmdb_id': mid, 'lang': lang, 'qual': qual}
            bot.send_message(call.message.chat.id, f"📥 মুভি ফাইলটি এখানে পাঠান:")

    def get_custom_qual(message):
        uid = message.from_user.id
        if uid in admin_states:
            admin_states[uid]['qual'] = message.text
            bot.send_message(message.chat.id, "📥 মুভি ফাইলটি এখানে পাঠান:")

    @bot.message_handler(content_types=['video', 'document'])
    def save_media(message):
        uid = message.from_user.id
        config = get_config()
        if uid not in admin_states: return
        state = admin_states[uid]
        try:
            sent_msg = bot.copy_message(int(config['STORAGE_CHANNEL_ID']), message.chat.id, message.message_id)
            tmdb_api = config['TMDB_API_KEY']
            tmdb_url = f"https://api.themoviedb.org/3/{state['type']}/{state['tmdb_id']}?api_key={tmdb_api}&append_to_response=credits,videos"
            m = requests.get(tmdb_url).json()
            
            title = m.get('title') or m.get('name', 'Unknown')
            year = (m.get('release_date') or m.get('first_air_date') or 'N/A')[:4]
            cast = ", ".join([a['name'] for a in m.get('credits', {}).get('cast', [])[:8]])
            director = next((p['name'] for p in m.get('credits', {}).get('crew', []) if p['job'] in ['Director', 'Executive Producer']), 'N/A')
            trailer_key = next((v['key'] for v in m.get('videos', {}).get('results', []) if v['type'] == 'Trailer'), "")

            movie_info = {
                'tmdb_id': str(state['tmdb_id']), 'type': state['type'], 'title': title, 'year': year,
                'poster': f"https://image.tmdb.org/t/p/w500{m.get('poster_path')}",
                'rating': str(round(m.get('vote_average', 0), 1)), 'story': m.get('overview', 'N/A'),
                'cast': cast, 'director': director, 'trailer': f"https://www.youtube.com/embed/{trailer_key}" if trailer_key else "",
                'lang': state.get('lang', 'N/A'), 'quality': state.get('qual', 'HD')
            }
            movies_col.update_one({'tmdb_id': movie_info['tmdb_id']}, {'$set': movie_info}, upsert=True)

            file_label = f"{state.get('lang', '')} {state['qual']}".strip()
            file_data = {'quality': file_label, 'file_id': sent_msg.message_id}

            if state['type'] == 'movie':
                movies_col.update_one({'tmdb_id': state['tmdb_id']}, {'$push': {'files': file_data}})
            else:
                episodes_col.update_one(
                    {'tmdb_id': state['tmdb_id'], 'season': int(state['season']), 'episode': int(state['episode'])},
                    {'$set': {'tmdb_id': state['tmdb_id'], 'season': int(state['season']), 'episode': int(state['episode'])},
                     '$push': {'files': file_data}}, upsert=True
                )
            bot.send_message(message.chat.id, f"✅ সফলভাবে অ্যাড হয়েছে: {title}")
            del admin_states[uid]
        except Exception as e:
            bot.send_message(message.chat.id, f"❌ এরর: {e}")

# --- [FLASK ROUTES] ---

@app.route('/')
def home():
    q = request.args.get('search')
    if q:
        movies = list(movies_col.find({"title": {"$regex": q, "$options": "i"}}).sort('_id', -1))
    else:
        movies = list(movies_col.find().sort('_id', -1))
    return render_template_string(HOME_HTML, movies=movies, query=q)

@app.route('/movie/<tmdb_id>')
def movie_details(tmdb_id):
    movie = movies_col.find_one({'tmdb_id': tmdb_id})
    if not movie: return "Not Found", 404
    config = get_config()
    bot_user = ""
    try: bot_user = telebot.TeleBot(config['BOT_TOKEN']).get_me().username
    except: pass

    if 'files' in movie:
        for f in movie['files']:
            f['short_url'] = get_short_link(f"https://t.me/{bot_user}?start=dl_{f['file_id']}")

    seasons_data = {}
    if movie.get('type') == 'tv':
        eps = list(episodes_col.find({'tmdb_id': tmdb_id}).sort([('season', 1), ('episode', 1)]))
        for e in eps:
            if 'files' in e:
                for f in e['files']:
                    f['short_url'] = get_short_link(f"https://t.me/{bot_user}?start=dl_{f['file_id']}")
            s_num = e['season']
            if s_num not in seasons_data: seasons_data[s_num] = []
            seasons_data[s_num].append(e)

    return render_template_string(DETAILS_HTML, m=movie, seasons=seasons_data, bot_user=bot_user)

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
    q = request.args.get('q')
    if q:
        movies = list(movies_col.find({"title": {"$regex": q, "$options": "i"}}).sort('_id', -1))
    else:
        movies = list(movies_col.find().sort('_id', -1))
    return render_template_string(ADMIN_HTML, config=get_config(), movies=movies, q=q)

@app.route('/admin/manual_add', methods=['POST'])
def manual_add():
    if not session.get('logged_in'): return redirect(url_for('login'))
    tmdb_id = request.form.get('tmdb_id') or str(int(time.time()))
    
    movie_info = {
        'tmdb_id': tmdb_id, 'type': 'movie', 'title': request.form.get('title'),
        'year': request.form.get('year'), 'poster': request.form.get('poster'),
        'rating': request.form.get('rating'), 'lang': request.form.get('lang'),
        'quality': request.form.get('quality'), 'story': request.form.get('story'),
        'director': request.form.get('director'), 'cast': request.form.get('cast'),
        'trailer': request.form.get('trailer')
    }
    movies_col.update_one({'tmdb_id': tmdb_id}, {'$set': movie_info}, upsert=True)
    
    file_id = request.form.get('file_id')
    if file_id:
        file_data = {'quality': f"{request.form.get('lang')} {request.form.get('quality')}".strip(), 'file_id': file_id}
        movies_col.update_one({'tmdb_id': tmdb_id}, {'$push': {'files': file_data}})
    
    return redirect(url_for('admin'))

@app.route('/admin/edit/<tmdb_id>')
def edit_movie(tmdb_id):
    if not session.get('logged_in'): return redirect(url_for('login'))
    movie = movies_col.find_one({'tmdb_id': tmdb_id})
    return render_template_string(EDIT_HTML, m=movie)

@app.route('/admin/update', methods=['POST'])
def update_movie():
    if not session.get('logged_in'): return redirect(url_for('login'))
    tid = request.form.get('tmdb_id')
    data = {
        'title': request.form.get('title'), 'year': request.form.get('year'),
        'rating': request.form.get('rating'), 'poster': request.form.get('poster'),
        'trailer': request.form.get('trailer'), 'director': request.form.get('director'),
        'cast': request.form.get('cast'), 'story': request.form.get('story')
    }
    movies_col.update_one({'tmdb_id': tid}, {'$set': data})
    return redirect(url_for('admin'))

@app.route('/admin/delete_file/<tmdb_id>/<file_id>')
def delete_file(tmdb_id, file_id):
    if not session.get('logged_in'): return redirect(url_for('login'))
    movies_col.update_one({'tmdb_id': tmdb_id}, {'$pull': {'files': {'file_id': file_id}}})
    return redirect(url_for('edit_movie', tmdb_id=tmdb_id))

@app.route('/save_config', methods=['POST'])
def save_config():
    if not session.get('logged_in'): return redirect(url_for('login'))
    data = {
        'type': 'core_settings',
        'SITE_URL': request.form.get('site_url').rstrip('/'),
        'BOT_TOKEN': request.form.get('token'),
        'TMDB_API_KEY': request.form.get('tmdb'),
        'ADMIN_ID': request.form.get('admin_id'),
        'STORAGE_CHANNEL_ID': request.form.get('channel_id'),
        'SHORTENER_URL': request.form.get('s_url'),
        'SHORTENER_API': request.form.get('s_api'),
        'AUTO_DELETE_TIME': int(request.form.get('delete_time', 0)),
        'PROTECT_CONTENT': request.form.get('protect')
    }
    config_col.update_one({'type': 'core_settings'}, {'$set': data}, upsert=True)
    return redirect(url_for('admin'))

@app.route('/delete/<tmdb_id>')
def delete_movie(tmdb_id):
    if not session.get('logged_in'): return redirect(url_for('login'))
    movies_col.delete_one({'tmdb_id': tmdb_id})
    episodes_col.delete_many({'tmdb_id': tmdb_id})
    return redirect(url_for('admin'))

@app.route('/webhook', methods=['POST'])
def webhook():
    bot = create_bot()
    if bot:
        register_handlers(bot)
        update = telebot.types.Update.de_json(request.get_data().decode('utf-8'))
        bot.process_new_updates([update])
    return '', 200

# ================== HTML Templates (Full) ==================

COMMON_STYLE = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;600&display=swap');
    body { background: #0b0c10; color: #c5c6c7; font-family: 'Poppins', sans-serif; }
    .neon-card { background: #1f2833; border: 1px solid #45a29e; border-radius: 12px; transition: 0.3s; }
    .neon-card:hover { transform: translateY(-5px); box-shadow: 0 0 15px #66fcf1; border-color: #66fcf1; }
    .btn-neon { background: #66fcf1; color: #0b0c10; font-weight: 600; border-radius: 6px; padding: 10px 20px; text-decoration: none; border: none; }
    .btn-neon:hover { background: #45a29e; color: #fff; }
    .navbar { background: #1f2833; border-bottom: 2px solid #66fcf1; }
    .poster-img { height: 260px; width: 100%; object-fit: cover; border-radius: 12px 12px 0 0; }
    .admin-box { background: white; color: #333; border-radius: 12px; padding: 20px; box-shadow: 0 5px 15px rgba(0,0,0,0.3); }
</style>
"""

HOME_HTML = f"<!DOCTYPE html><html><head><meta name='viewport' content='width=device-width, initial-scale=1.0'><title>Movie Portal</title><link rel='stylesheet' href='https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css'>{COMMON_STYLE}</head><body>" + """
<nav class="navbar navbar-dark sticky-top mb-4"><div class="container">
    <a class="navbar-brand fw-bold text-info" href="/">🎬 PORTAL</a>
    <form class="d-flex" action="/" method="GET">
        <input class="form-control me-2 bg-dark text-white border-info" type="search" name="search" placeholder="Search..." value="{{query or ''}}">
        <button class="btn btn-outline-info" type="submit">🔍</button>
    </form>
</div></nav>
<div class="container"><div class="row row-cols-2 row-cols-md-4 row-cols-lg-6 g-3">
{% for m in movies %}
<div class="col"><a href="/movie/{{m.tmdb_id}}" style="text-decoration:none; color:inherit;">
    <div class="neon-card h-100">
        <img src="{{m.poster}}" class="poster-img">
        <div class="p-2 text-center">
            <div class="small fw-bold text-truncate">{{m.title}}</div>
            <div class="text-info small">⭐ {{m.rating}} | {{m.year}}</div>
        </div>
    </div>
</a></div>
{% endfor %}
</div></div></body></html>"""

DETAILS_HTML = f"<!DOCTYPE html><html><head><meta name='viewport' content='width=device-width, initial-scale=1.0'><title>Details</title><link rel='stylesheet' href='https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css'>{COMMON_STYLE}</head><body>" + """
<div class="container py-5">
    <div class="row">
        <div class="col-md-4 mb-4"><img src="{{m.poster}}" class="w-100 rounded border border-info shadow-lg"></div>
        <div class="col-md-8">
            <h1 class="text-white">{{m.title}} ({{m.year}})</h1>
            <p class="text-info fw-bold">⭐ Rating: {{m.rating}} / 10</p>
            <p><b>Director:</b> {{m.director}} | <b>Cast:</b> {{m.cast}}</p>
            <p><b>Story:</b><br>{{m.story}}</p>
            <hr class="border-secondary">
            <h5 class="text-info">Download Options:</h5>
            {% if m.type == 'movie' %}
                {% if m.files %}
                    {% for f in m.files %}
                    <a href="{{f.short_url}}" target="_blank" class="btn-neon d-inline-block mb-2 me-2">🚀 Download {{f.quality}}</a>
                    {% endfor %}
                {% else %}
                    <a href="https://t.me/{{bot_user}}?start=m_{{m.tmdb_id}}" class="btn-neon">🚀 Get in Bot</a>
                {% endif %}
            {% else %}
                {% for s, eps in seasons.items() %}
                <div class="p-3 border border-info rounded mb-3">
                    <h6 class="text-info">Season {{s}}</h6>
                    {% for ep in eps %}
                    <div class="mb-2">Ep {{ep.episode}}: 
                        {% if ep.files %}
                            {% for f in ep.files %}<a href="{{f.short_url}}" class="btn btn-sm btn-outline-info ms-1">{{f.quality}}</a>{% endfor %}
                        {% else %}
                            <a href="https://t.me/{{bot_user}}?start=e_{{ep._id}}" class="btn btn-sm btn-outline-warning">Bot</a>
                        {% endif %}
                    </div>
                    {% endfor %}
                </div>
                {% endfor %}
            {% endif %}
        </div>
    </div>
    {% if m.trailer %}<div class="mt-5"><h4>Trailer</h4><div class="ratio ratio-16x9 rounded border border-info shadow-lg"><iframe src="{{m.trailer}}" allowfullscreen></iframe></div></div>{% endif %}
</div></body></html>"""

ADMIN_HTML = """<!DOCTYPE html><html><head><title>Admin Dashboard</title><link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css"></head><body class="bg-light py-4 container">
<div class="d-flex justify-content-between mb-4"><h2>⚙️ Admin Panel</h2><a href="/" class="btn btn-dark">Visit Site</a></div>
<div class="row">
    <div class="col-md-5">
        <div class="admin-box mb-4">
            <h5>➕ Manual Add Content</h5>
            <form action="/admin/manual_add" method="POST">
                <input name="title" class="form-control mb-2" placeholder="Title" required>
                <input name="tmdb_id" class="form-control mb-2" placeholder="TMDB ID (Optional)">
                <div class="row g-2 mb-2">
                    <div class="col"><input name="year" class="form-control" placeholder="Year"></div>
                    <div class="col"><input name="rating" class="form-control" placeholder="Rating"></div>
                </div>
                <input name="poster" class="form-control mb-2" placeholder="Poster URL">
                <input name="trailer" class="form-control mb-2" placeholder="Trailer Link">
                <input name="lang" class="form-control mb-2" placeholder="Language (e.g. Hindi)">
                <input name="quality" class="form-control mb-2" placeholder="Quality (e.g. 1080p)">
                <input name="file_id" class="form-control mb-2" placeholder="Storage File Code (Message ID)">
                <textarea name="story" class="form-control mb-2" placeholder="Storyline"></textarea>
                <input name="director" class="form-control mb-2" placeholder="Director">
                <input name="cast" class="form-control mb-2" placeholder="Cast">
                <button class="btn btn-primary w-100">Save Movie</button>
            </form>
        </div>
        <div class="admin-box">
            <h5>🔧 Configuration</h5>
            <form action="/save_config" method="POST">
                <input name="token" class="form-control mb-2" placeholder="Bot Token" value="{{config.BOT_TOKEN}}">
                <input name="tmdb" class="form-control mb-2" placeholder="TMDB Key" value="{{config.TMDB_API_KEY}}">
                <input name="site_url" class="form-control mb-2" placeholder="Site URL" value="{{config.SITE_URL}}">
                <input name="channel_id" class="form-control mb-2" placeholder="Channel ID" value="{{config.STORAGE_CHANNEL_ID}}">
                <input name="s_url" class="form-control mb-2" placeholder="Shortener API URL" value="{{config.SHORTENER_URL}}">
                <input name="s_api" class="form-control mb-2" placeholder="Shortener API Key" value="{{config.SHORTENER_API}}">
                <button class="btn btn-dark w-100">Update Config</button>
            </form>
        </div>
    </div>
    <div class="col-md-7">
        <div class="admin-box">
            <form class="d-flex mb-3"><input name="q" class="form-control me-2" placeholder="Search movies..." value="{{q or ''}}"><button class="btn btn-info">Search</button></form>
            <table class="table table-striped table-sm">
                <thead><tr><th>Title</th><th>Year</th><th>Action</th></tr></thead>
                {% for m in movies %}
                <tr><td>{{m.title}}</td><td>{{m.year}}</td><td>
                    <a href="/admin/edit/{{m.tmdb_id}}" class="btn btn-sm btn-warning">Edit</a>
                    <a href="/delete/{{m.tmdb_id}}" class="btn btn-sm btn-danger" onclick="return confirm('Delete?')">Del</a>
                </td></tr>
                {% endfor %}
            </table>
        </div>
    </div>
</div></body></html>"""

EDIT_HTML = """<!DOCTYPE html><html><head><title>Edit Movie</title><link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css"></head><body class="bg-light container py-5">
<div class="card p-4 shadow">
    <h3>✏️ Edit Content: {{m.title}}</h3><hr>
    <form action="/admin/update" method="POST">
        <input type="hidden" name="tmdb_id" value="{{m.tmdb_id}}">
        <div class="row">
            <div class="col-md-6">
                <label>Title</label><input name="title" class="form-control mb-2" value="{{m.title}}">
                <label>Year</label><input name="year" class="form-control mb-2" value="{{m.year}}">
                <label>Rating</label><input name="rating" class="form-control mb-2" value="{{m.rating}}">
            </div>
            <div class="col-md-6">
                <label>Poster URL</label><input name="poster" class="form-control mb-2" value="{{m.poster}}">
                <label>Trailer Link</label><input name="trailer" class="form-control mb-2" value="{{m.trailer}}">
                <label>Director</label><input name="director" class="form-control mb-2" value="{{m.director}}">
            </div>
        </div>
        <label>Cast</label><input name="cast" class="form-control mb-2" value="{{m.cast}}">
        <label>Storyline</label><textarea name="story" class="form-control mb-3" rows="5">{{m.story}}</textarea>
        <button class="btn btn-success">Save Changes</button> <a href="/admin" class="btn btn-secondary">Cancel</a>
    </form>
    <div class="mt-4">
        <h5>📦 Quality Links (Files):</h5>
        <ul class="list-group">
            {% for f in m.files %}
            <li class="list-group-item d-flex justify-content-between">
                {{f.quality}} (Code: {{f.file_id}})
                <a href="/admin/delete_file/{{m.tmdb_id}}/{{f.file_id}}" class="text-danger">Delete Link</a>
            </li>
            {% endfor %}
        </ul>
    </div>
</div></body></html>"""

LOGIN_HTML = """<!DOCTYPE html><html><head><title>Login</title><link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css"></head><body class="bg-dark d-flex align-items-center" style="height:100vh;">
<div class="card p-4 mx-auto shadow-lg" style="width:340px;">
    <h4 class="text-center">ADMIN LOGIN</h4><hr>
    <form method="POST"><input name="u" class="form-control mb-2" placeholder="User"><input name="p" type="password" class="form-control mb-3" placeholder="Pass"><button class="btn btn-primary w-100">Login</button></form>
</div></body></html>"""

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
