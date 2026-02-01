import telebot
import requests
import os
import time
import threading
import urllib.parse
import re
import math
from telebot import types
from pymongo import MongoClient
from bson import ObjectId
from flask import Flask, render_template_string, redirect, url_for, request, session, jsonify

# ================== ডাটাবেস সেটআপ ==================
MONGO_URI = os.environ.get('MONGO_URI', "YOUR_MONGODB_URI_HERE") 

try:
    client = MongoClient(MONGO_URI)
    db = client['movie_portal_db']
    config_col = db['bot_config']      
    movies_col = db['movies_data']      
    episodes_col = db['episodes_data']
    users_col = db['bot_users'] 
    print("✅ MongoDB Connected Successfully!")
except Exception as e:
    print(f"❌ MongoDB Connection Error: {e}")

app = Flask(__name__)
app.secret_key = "ultimate_portal_final_secret_key_full_version"

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "password123"

admin_states = {}
bot = None

# মুভির ক্যাটাগরি লিস্ট
CATEGORIES = ["Action", "Adventure", "Animation", "Comedy", "Crime", "Drama", "Fantasy", "Horror", "Mystery", "Romance", "Sci-Fi", "Thriller", "South Hindi", "Bangla Dubbed", "Web Series"]

# --- [সহায়ক ফাংশনসমূহ] ---
def get_config():
    try:
        conf = config_col.find_one({'type': 'core_settings'}) or {}
    except:
        conf = {}
    defaults = {
        'SITE_NAME': 'Movie Portal', # নতুন
        'SITE_LOGO': 'https://i.ibb.co/LzN67Z6/logo.png', # নতুন
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
            # বট স্পিড বাড়ানোর জন্য Threaded=True এবং num_threads দেওয়া হয়েছে
            return telebot.TeleBot(token, threaded=True, num_threads=50)
        except:
            return None
    return None

def auto_delete_task(bot_inst, chat_id, msg_id, delay):
    if delay > 0:
        time.sleep(delay)
        try:
            bot_inst.delete_message(chat_id, msg_id)
        except: pass

# --- [টেলিগ্রাম বট হ্যান্ডলার - আপনার অরিজিনাল কোড সম্পূর্ণ এখানে] ---
def register_handlers(bot_inst):
    if not bot_inst: return

    @bot_inst.message_handler(commands=['start'])
    def start(message):
        if not users_col.find_one({'user_id': message.from_user.id}):
            users_col.insert_one({'user_id': message.from_user.id, 'name': message.from_user.first_name})
            
        config = get_config()
        if len(message.text.split()) > 1:
            cmd_data = message.text.split()[1]
            if cmd_data.startswith('dl_'):
                file_to_send = cmd_data.replace('dl_', '')
                protect = True if config.get('PROTECT_CONTENT') == 'on' else False
                try:
                    sent_msg = bot_inst.copy_message(message.chat.id, int(config['STORAGE_CHANNEL_ID']), int(file_to_send), protect_content=protect)
                    delay = int(config.get('AUTO_DELETE_TIME', 0))
                    if delay > 0:
                        bot_inst.send_message(message.chat.id, f"⚠️ ফাইলটি {delay} সেকেন্ড পর ডিলিট হবে।")
                        threading.Thread(target=auto_delete_task, args=(bot_inst, message.chat.id, sent_msg.message_id, delay)).start()
                except:
                    bot_inst.send_message(message.chat.id, "❌ ফাইল পাওয়া যায়নি।")
                return
        bot_inst.reply_to(message, f"🎬 {config['SITE_NAME']} এ স্বাগতম। মুভি বা টিভি শো খুঁজতে ওয়েবসাইট ভিজিট করুন।")

    @bot_inst.message_handler(commands=['stats'])
    def stats(message):
        config = get_config()
        if str(message.from_user.id) != str(config.get('ADMIN_ID')): return
        u_count = users_col.count_documents({})
        m_count = movies_col.count_documents({})
        bot_inst.reply_to(message, f"📊 বটের অবস্থা:\n\n👤 মোট ইউজার: {u_count}\n🎬 মোট মুভি/শো: {m_count}")

    @bot_inst.message_handler(commands=['broadcast'])
    def broadcast(message):
        config = get_config()
        if str(message.from_user.id) != str(config.get('ADMIN_ID')): return
        if not message.reply_to_message:
            bot_inst.reply_to(message, "⚠️ যে মেসেজটি পাঠাতে চান সেটি রিপ্লাই করে /broadcast লিখুন।")
            return
        users = users_col.find({})
        count = 0
        for u in users:
            try:
                bot_inst.copy_message(u['user_id'], message.chat.id, message.reply_to_message.message_id)
                count += 1
                time.sleep(0.05)
            except: pass
        bot_inst.send_message(message.chat.id, f"✅ {count} জন ইউজারের কাছে পাঠানো হয়েছে।")

    @bot_inst.message_handler(commands=['post'])
    def post_search(message):
        config = get_config()
        if str(message.from_user.id) != str(config.get('ADMIN_ID')):
            bot_inst.reply_to(message, f"🚫 আপনি এডমিন নন।")
            return
        query = message.text.replace('/post', '').strip()
        if not query:
            bot_inst.reply_to(message, "⚠️ মুভির নাম লিখুন।")
            return
        
        tmdb_api = config.get('TMDB_API_KEY')
        url = f"https://api.themoviedb.org/3/search/multi?api_key={tmdb_api}&query={query}"
        try: res = requests.get(url).json().get('results', [])
        except: res = []

        if not res:
            bot_inst.reply_to(message, "❌ কিছুই পাওয়া যায়নি।")
            return

        markup = types.InlineKeyboardMarkup()
        for m in res[:8]:
            if m['media_type'] not in ['movie', 'tv']: continue
            name = m.get('title') or m.get('name')
            year = (m.get('release_date') or m.get('first_air_date') or 'N/A')[:4]
            markup.add(types.InlineKeyboardButton(text=f"[{m['media_type'].upper()}] {name} ({year})", callback_data=f"sel_{m['media_type']}_{m['id']}"))
        bot_inst.send_message(message.chat.id, "🔍 কি আপলোড করতে চান সিলেক্ট করুন:", reply_markup=markup)

    @bot_inst.callback_query_handler(func=lambda call: call.data.startswith('sel_'))
    def handle_selection(call):
        _, m_type, m_id = call.data.split('_')
        admin_states[call.from_user.id] = {'type': m_type, 'tmdb_id': m_id}
        
        if m_type == 'movie':
            markup = types.InlineKeyboardMarkup()
            for l in ["Bangla", "Hindi", "English", "Multi"]:
                markup.add(types.InlineKeyboardButton(text=l, callback_data=f"lang_m_{m_id}_{l}"))
            bot_inst.edit_message_text("🌐 ল্যাঙ্গুয়েজ সিলেক্ট করুন:", call.message.chat.id, call.message.message_id, reply_markup=markup)
        else:
            msg = bot_inst.send_message(call.message.chat.id, "📺 সিজন নম্বর লিখুন:")
            bot_inst.register_next_step_handler(msg, get_season)

    def get_season(message):
        uid = message.from_user.id
        if uid in admin_states:
            admin_states[uid]['season'] = message.text
            bot_inst.send_message(message.chat.id, "🔢 এপিসোড নম্বর লিখুন:")
            bot_inst.register_next_step_handler(message, get_episode)

    def get_episode(message):
        uid = message.from_user.id
        if uid in admin_states:
            admin_states[uid]['episode'] = message.text
            bot_inst.send_message(message.chat.id, "📥 কোয়ালিটি লিখুন (যেমন: 720p):")
            bot_inst.register_next_step_handler(message, get_tv_quality)

    def get_tv_quality(message):
        uid = message.from_user.id
        if uid in admin_states:
            admin_states[uid]['qual'] = message.text
            bot_inst.send_message(message.chat.id, "📥 ভিডিও ফাইলটি পাঠান:")

    @bot_inst.callback_query_handler(func=lambda call: call.data.startswith('lang_m_'))
    def movie_qual(call):
        _, _, mid, lang = call.data.split('_')
        markup = types.InlineKeyboardMarkup()
        for q in ["480p", "720p", "1080p", "4K", "Custom"]:
            markup.add(types.InlineKeyboardButton(text=q, callback_data=f"qual_m_{mid}_{lang}_{q}"))
        bot_inst.edit_message_text("💎 কোয়ালিটি সিলেক্ট করুন:", call.message.chat.id, call.message.message_id, reply_markup=markup)

    @bot_inst.callback_query_handler(func=lambda call: call.data.startswith('qual_m_'))
    def movie_file_ask(call):
        _, _, mid, lang, qual = call.data.split('_')
        if qual == "Custom":
            admin_states[call.from_user.id].update({'lang': lang})
            msg = bot_inst.send_message(call.message.chat.id, "🖊️ কাস্টম কোয়ালিটি লিখুন:")
            bot_inst.register_next_step_handler(msg, get_custom_qual)
        else:
            admin_states[call.from_user.id].update({'lang': lang, 'qual': qual})
            bot_inst.send_message(call.message.chat.id, f"📥 মুভি ফাইলটি এখানে পাঠান:")

    def get_custom_qual(message):
        uid = message.from_user.id
        if uid in admin_states:
            admin_states[uid]['qual'] = message.text
            bot_inst.send_message(message.chat.id, "📥 মুভি ফাইলটি এখানে পাঠান:")

    @bot_inst.message_handler(content_types=['video', 'document'])
    def save_media(message):
        uid = message.from_user.id
        config = get_config()
        if uid not in admin_states: return
        state = admin_states[uid]
        try:
            sent_msg = bot_inst.copy_message(int(config['STORAGE_CHANNEL_ID']), message.chat.id, message.message_id)
            tmdb_api = config['TMDB_API_KEY']
            tmdb_url = f"https://api.themoviedb.org/3/{state['type']}/{state['tmdb_id']}?api_key={tmdb_api}&append_to_response=credits,videos"
            m = requests.get(tmdb_url).json()
            
            genres_data = m.get('genres', [])
            auto_cat = "Action"
            if state['type'] == 'tv':
                auto_cat = "Web Series"
            elif genres_data:
                for g in genres_data:
                    if g['name'] in CATEGORIES:
                        auto_cat = g['name']
                        break

            title = m.get('title') or m.get('name', 'Unknown')
            year = (m.get('release_date') or m.get('first_air_date') or 'N/A')[:4]
            cast = ", ".join([a['name'] for a in m.get('credits', {}).get('cast', [])[:8]])
            director = next((p['name'] for p in m.get('credits', {}).get('crew', []) if p['job'] in ['Director', 'Executive Producer']), 'N/A')
            trailer_key = next((v['key'] for v in m.get('videos', {}).get('results', []) if v['type'] == 'Trailer'), "")

            movie_info = {
                'tmdb_id': str(state['tmdb_id']), 'type': state['type'], 'title': title, 'year': year,
                'poster': f"https://image.tmdb.org/t/p/w500{m.get('poster_path')}",
                'rating': str(round(m.get('vote_average', 0), 1)), 'story': m.get('overview', 'N/A'),
                'cast': cast, 'director': director, 'category': auto_cat,
                'trailer': f"https://www.youtube.com/embed/{trailer_key}" if trailer_key else "",
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
            bot_inst.send_message(message.chat.id, f"✅ সফলভাবে অ্যাড হয়েছে: {title}\n📂 ক্যাটাগরি: {auto_cat}")
            del admin_states[uid]
        except Exception as e:
            bot_inst.send_message(message.chat.id, f"❌ এরর: {e}")

# --- [বট ইনিট ফাংশন] ---
def init_bot_service():
    global bot
    config = get_config()
    token = config.get('BOT_TOKEN')
    site_url = config.get('SITE_URL')
    if token and len(token) > 20:
        try:
            bot = telebot.TeleBot(token, threaded=True, num_threads=50) # স্পিড বাড়ানো হয়েছে
            register_handlers(bot)
            if site_url:
                webhook_url = f"{site_url.rstrip('/')}/webhook"
                bot.remove_webhook()
                time.sleep(1)
                bot.set_webhook(url=webhook_url)
            return bot
        except: return None

# --- [FLASK ROUTES] ---

@app.route('/')
def home():
    conf = get_config()
    q = request.args.get('search')
    cat = request.args.get('cat')
    page = int(request.args.get('page', 1))
    limit = 24 
    skip = (page - 1) * limit
    query_filter = {}
    if q: query_filter["title"] = {"$regex": q, "$options": "i"}
    if cat: query_filter["category"] = cat

    total = movies_col.count_documents(query_filter)
    movies = list(movies_col.find(query_filter).sort('_id', -1).skip(skip).limit(limit))
    pages = math.ceil(total / limit)
    return render_template_string(HOME_HTML, movies=movies, config=conf, query=q, cat=cat, page=page, pages=pages, categories=CATEGORIES)

@app.route('/movie/<tmdb_id>')
def movie_details(tmdb_id):
    movie = movies_col.find_one({'tmdb_id': tmdb_id})
    if not movie: return "Not Found", 404
    config = get_config()
    bot_user = ""
    try:
        if bot: bot_user = bot.get_me().username
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

    return render_template_string(DETAILS_HTML, m=movie, seasons=seasons_data, bot_user=bot_user, config=config)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form.get('u') == ADMIN_USERNAME and request.form.get('p') == ADMIN_PASSWORD:
            session['logged_in'] = True
            return redirect(url_for('admin'))
    return render_template_string(LOGIN_HTML)

# --- [অ্যাডমিন প্যানেল লজিক] ---

@app.route('/admin')
def admin():
    if not session.get('logged_in'): return redirect(url_for('login'))
    q = request.args.get('q')
    movies = list(movies_col.find({"title": {"$regex": q, "$options": "i"}} if q else {}).sort('_id', -1))
    stats = {
        'movies': movies_col.count_documents({}),
        'users': users_col.count_documents({}),
        'series': movies_col.count_documents({'type': 'tv'})
    }
    return render_template_string(ADMIN_HTML, config=get_config(), movies=movies, q=q, categories=CATEGORIES, stats=stats)

@app.route('/admin/search_tmdb', methods=['POST'])
def search_tmdb():
    if not session.get('logged_in'): return jsonify({'error': 'Unauthorized'})
    query = request.form.get('query')
    tmdb_key = get_config().get('TMDB_API_KEY')
    url = f"https://api.themoviedb.org/3/search/multi?api_key={tmdb_key}&query={query}"
    try: return jsonify(requests.get(url).json().get('results', []))
    except: return jsonify([])

@app.route('/admin/fetch_info', methods=['POST'])
def fetch_info():
    if not session.get('logged_in'): return jsonify({'error': 'Unauthorized'})
    url = request.form.get('url')
    tmdb_key = get_config().get('TMDB_API_KEY')
    tmdb_id, media_type = None, "movie"
    imdb_match = re.search(r'tt\d+', url)
    if imdb_match:
        res = requests.get(f"https://api.themoviedb.org/3/find/{imdb_match.group(0)}?api_key={tmdb_key}&external_source=imdb_id").json()
        if res.get('movie_results'): tmdb_id, media_type = res['movie_results'][0]['id'], "movie"
        elif res.get('tv_results'): tmdb_id, media_type = res['tv_results'][0]['id'], "tv"
    elif re.match(r'^\d+$', url):
        tmdb_id = url; media_type = request.form.get('type', 'movie')

    if not tmdb_id: return jsonify({'error': 'Not Found'})
    m = requests.get(f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}?api_key={tmdb_key}&append_to_response=credits,videos").json()
    genres_data = m.get('genres', [])
    auto_cat = "Action"
    if media_type == 'tv': auto_cat = "Web Series"
    elif genres_data:
        for g in genres_data:
            if g['name'] in CATEGORIES: auto_cat = g['name']; break
    
    trailer = next((v['key'] for v in m.get('videos', {}).get('results', []) if v['type'] == 'Trailer'), "")
    return jsonify({
        'tmdb_id': str(tmdb_id), 'type': media_type, 'title': m.get('title') or m.get('name'),
        'year': (m.get('release_date') or m.get('first_air_date') or 'N/A')[:4],
        'rating': str(round(m.get('vote_average', 0), 1)), 'poster': f"https://image.tmdb.org/t/p/w500{m.get('poster_path')}",
        'story': m.get('overview'), 'director': next((p['name'] for p in m.get('credits', {}).get('crew', []) if p['job'] in ['Director', 'Executive Producer']), 'N/A'),
        'cast': ", ".join([a['name'] for a in m.get('credits', {}).get('cast', [])[:8]]),
        'category': auto_cat, 'trailer': f"https://www.youtube.com/embed/{trailer}" if trailer else ""
    })

@app.route('/admin/manual_add', methods=['POST'])
def manual_add():
    if not session.get('logged_in'): return redirect(url_for('login'))
    tid = request.form.get('tmdb_id')
    movie_info = {
        'tmdb_id': tid, 'type': request.form.get('type', 'movie'), 'title': request.form.get('title'),
        'year': request.form.get('year'), 'poster': request.form.get('poster'),
        'rating': request.form.get('rating'), 'story': request.form.get('story'),
        'director': request.form.get('director'), 'cast': request.form.get('cast'),
        'category': request.form.get('category'), 'trailer': request.form.get('trailer')
    }
    movies_col.update_one({'tmdb_id': tid}, {'$set': movie_info}, upsert=True)
    return redirect(url_for('edit_movie', tmdb_id=tid))

@app.route('/admin/add_file', methods=['POST'])
def add_file():
    if not session.get('logged_in'): return redirect(url_for('login'))
    tid = request.form.get('tmdb_id')
    file_data = {'quality': request.form.get('quality'), 'file_id': request.form.get('file_id')}
    movies_col.update_one({'tmdb_id': tid}, {'$push': {'files': file_data}})
    return redirect(url_for('edit_movie', tmdb_id=tid))

@app.route('/admin/edit/<tmdb_id>')
def edit_movie(tmdb_id):
    if not session.get('logged_in'): return redirect(url_for('login'))
    movie = movies_col.find_one({'tmdb_id': tmdb_id})
    return render_template_string(EDIT_HTML, m=movie, categories=CATEGORIES)

@app.route('/admin/update', methods=['POST'])
def update_movie():
    if not session.get('logged_in'): return redirect(url_for('login'))
    tid = request.form.get('tmdb_id')
    data = request.form.to_dict()
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
        'SITE_NAME': request.form.get('site_name'),
        'SITE_LOGO': request.form.get('site_logo'),
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
    threading.Thread(target=init_bot_service).start()
    return redirect(url_for('admin'))

@app.route('/delete/<tmdb_id>')
def delete_movie(tmdb_id):
    if not session.get('logged_in'): return redirect(url_for('login'))
    movies_col.delete_one({'tmdb_id': tmdb_id})
    episodes_col.delete_many({'tmdb_id': tmdb_id})
    return redirect(url_for('admin'))

@app.route('/webhook', methods=['POST'])
def webhook():
    if bot:
        update = telebot.types.Update.de_json(request.get_data().decode('utf-8'))
        bot.process_new_updates([update])
    return '', 200

# ================== HTML Templates (PREMIUM UI) ==================

PREMIUM_STYLE = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;600&display=swap');
    :root { --primary: #00d2ff; --secondary: #3a7bd5; --dark: #0f172a; --card-bg: #1e293b; --text: #f1f5f9; }
    body { background: var(--dark); color: var(--text); font-family: 'Poppins', sans-serif; margin: 0; }
    
    /* Neon Glow Poster */
    .neon-card { background: var(--card-bg); border: 1px solid #334155; border-radius: 12px; transition: 0.3s; overflow: hidden; position: relative; }
    .neon-card:hover { transform: translateY(-5px); border-color: var(--primary); box-shadow: 0 0 15px rgba(0,210,255,0.3); }
    
    .btn-neon { background: linear-gradient(45deg, var(--primary), var(--secondary)); color: white; border: none; border-radius: 8px; padding: 10px 20px; font-weight: 600; text-decoration: none; display: inline-block; transition: 0.3s; }
    .btn-neon:hover { box-shadow: 0 0 20px var(--primary); }
    
    .cat-pill { padding: 6px 15px; border-radius: 20px; border: 1px solid var(--primary); color: var(--primary); text-decoration: none; margin: 3px; display: inline-block; font-size: 13px; transition: 0.3s; }
    .cat-pill.active, .cat-pill:hover { background: var(--primary); color: #000; font-weight: 600; }
    
    /* Premium Sidebar Admin */
    .sidebar { width: 260px; height: 100vh; position: fixed; background: #020617; border-right: 1px solid #1e293b; padding: 25px; transition: 0.3s; z-index: 1000; }
    .main-content { margin-left: 260px; padding: 40px; min-height: 100vh; }
    .nav-link { color: #94a3b8; padding: 12px 15px; border-radius: 10px; margin-bottom: 8px; display: block; text-decoration: none; transition: 0.3s; font-weight: 500; }
    .nav-link:hover, .nav-link.active { background: rgba(0,210,255,0.1); color: var(--primary); }
    
    .stat-box { background: var(--card-bg); padding: 25px; border-radius: 15px; border: 1px solid #334155; text-align: center; }
</style>
"""

HOME_HTML = f"<!DOCTYPE html><html><head><meta name='viewport' content='width=device-width, initial-scale=1.0'><title>{{{{config.SITE_NAME}}}}</title><link rel='stylesheet' href='https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css'>{PREMIUM_STYLE}</head><body>" + """
<nav class="navbar navbar-dark sticky-top border-bottom border-secondary" style="background: rgba(15,23,42,0.9); backdrop-filter: blur(10px);">
    <div class="container">
        <a class="navbar-brand fw-bold d-flex align-items-center" href="/">
            <img src="{{config.SITE_LOGO}}" height="35" class="me-2 rounded-circle"> {{config.SITE_NAME}}
        </a>
        <form class="d-flex" action="/" method="GET">
            <input class="form-control me-2 bg-dark text-white border-secondary" type="search" name="search" placeholder="Search..." value="{{query or ''}}">
            <button class="btn btn-primary" type="submit">🔍</button>
        </form>
    </div>
</nav>
<div class="container my-4 text-center">
    <a href="/" class="cat-pill {% if not cat %}active{% endif %}">All</a>
    {% for c in categories %}<a href="/?cat={{c}}" class="cat-pill {% if cat == c %}active{% endif %}">{{c}}</a>{% endfor %}
</div>
<div class="container"><div class="row row-cols-2 row-cols-md-4 row-cols-lg-6 g-3">
{% for m in movies %}
<div class="col"><a href="/movie/{{m.tmdb_id}}" style="text-decoration:none; color:inherit;">
    <div class="neon-card">
        <img src="{{m.poster}}" class="w-100" style="height:250px; object-fit:cover;">
        <div class="p-2 text-center text-truncate small fw-bold">{{m.title}}</div>
    </div>
</a></div>
{% endfor %}
</div></div></body></html>"""

DETAILS_HTML = f"<!DOCTYPE html><html><head><meta name='viewport' content='width=device-width, initial-scale=1.0'><title>{{{{m.title}}}}</title><link rel='stylesheet' href='https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css'>{PREMIUM_STYLE}</head><body>" + """
<div class="container py-5">
    <div class="row">
        <div class="col-md-4 mb-4"><img src="{{m.poster}}" class="w-100 rounded shadow-lg border border-secondary"></div>
        <div class="col-md-8">
            <h1 class="text-white fw-bold">{{m.title}} ({{m.year}})</h1>
            <p class="text-info fw-bold">⭐ Rating: {{m.rating}} | 📂 Category: {{m.category}}</p>
            <p>{{m.story}}</p>
            <hr class="border-secondary">
            <div class="mt-4">
                {% if m.type == 'movie' %}
                    {% for f in m.files %}<a href="{{f.short_url}}" class="btn-neon me-2 mb-2">🚀 Download {{f.quality}}</a>{% endfor %}
                {% else %}
                    {% for s, eps in seasons.items() %}
                    <div class="p-3 border border-secondary rounded mb-3">
                        <h6 class="text-info">Season {{s}}</h6>
                        {% for ep in eps %}
                        <div class="mb-2">Ep {{ep.episode}}: {% for f in ep.files %}<a href="{{f.short_url}}" class="btn btn-sm btn-outline-info ms-1">{{f.quality}}</a>{% endfor %}</div>
                        {% endfor %}
                    </div>
                    {% endfor %}
                {% endif %}
            </div>
            {% if m.trailer %}<div class="mt-5"><h4>Trailer</h4><div class="ratio ratio-16x9 rounded border border-info shadow-lg"><iframe src="{{m.trailer}}" allowfullscreen></iframe></div></div>{% endif %}
        </div>
    </div>
</div></body></html>"""

ADMIN_HTML = f"<!DOCTYPE html><html><head><title>Admin Dashboard</title><link rel='stylesheet' href='https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css'><script src='https://code.jquery.com/jquery-3.6.0.min.js'></script>{PREMIUM_STYLE}</head><body>" + """
<div class="sidebar">
    <h4 class="text-white fw-bold mb-4">⚙️ PORTAL ADMIN</h4>
    <a href="#" class="nav-link active" onclick="showTab('dash')">📊 Dashboard</a>
    <a href="#" class="nav-link" onclick="showTab('add-movie')">➕ Add Movie/Series</a>
    <a href="#" class="nav-link" onclick="showTab('list')">🎬 Manage Content</a>
    <a href="#" class="nav-link" onclick="showTab('settings')">🔧 Site Settings</a>
    <a href="#" class="nav-link" onclick="showTab('bot')">🤖 Bot Config</a>
    <hr class="border-secondary">
    <a href="/" class="nav-link text-info">🌐 View Site</a>
</div>

<div class="main-content">
    <div id="tab-dash" class="tab-content">
        <h2>Dashboard</h2>
        <div class="row g-4 mt-4">
            <div class="col-md-4"><div class="stat-box"><h3>{{stats.users}}</h3><p>Total Users</p></div></div>
            <div class="col-md-4"><div class="stat-box"><h3>{{stats.movies}}</h3><p>Total Content</p></div></div>
            <div class="col-md-4"><div class="stat-box"><h3>{{stats.series}}</h3><p>TV Series</p></div></div>
        </div>
    </div>

    <div id="tab-add-movie" class="tab-content" style="display:none;">
        <div class="bg-dark p-4 rounded border border-secondary">
            <h5>🔍 Auto Search TMDB</h5>
            <div class="input-group mb-3"><input id="tmdb_in" class="form-control bg-dark text-white" placeholder="Name..."><button class="btn btn-primary" onclick="searchTMDB()">Search</button></div>
            <div id="res_box" class="list-group mb-4"></div>
            <hr class="border-secondary">
            <form action="/admin/manual_add" method="POST">
                <input id="f_title" name="title" class="form-control mb-2 bg-dark text-white border-secondary" placeholder="Title">
                <input id="f_id" name="tmdb_id" class="form-control mb-2 bg-dark text-white border-secondary" placeholder="TMDB ID">
                <select id="f_type" name="type" class="form-control mb-2 bg-dark text-white border-secondary"><option value="movie">Movie</option><option value="tv">TV</option></select>
                <select name="category" class="form-control mb-2 bg-dark text-white border-secondary">{% for c in categories %}<option value="{{c}}">{{c}}</option>{% endfor %}</select>
                <input id="f_year" name="year" class="form-control mb-2 bg-dark text-white border-secondary" placeholder="Year">
                <input id="f_poster" name="poster" class="form-control mb-2 bg-dark text-white border-secondary" placeholder="Poster URL">
                <textarea id="f_story" name="story" class="form-control mb-3 bg-dark text-white border-secondary" placeholder="Story"></textarea>
                <button class="btn btn-success w-100 py-2">Save Metadata</button>
            </form>
        </div>
    </div>

    <div id="tab-list" class="tab-content" style="display:none;">
        <form class="d-flex mb-3"><input name="q" class="form-control me-2" placeholder="Search..." value="{{q or ''}}"><button class="btn btn-info">Search</button></form>
        <table class="table table-dark table-hover">
            <thead><tr><th>Title</th><th>Category</th><th>Action</th></tr></thead>
            {% for m in movies %}
            <tr><td>{{m.title}}</td><td>{{m.category}}</td><td><a href="/admin/edit/{{m.tmdb_id}}" class="btn btn-sm btn-warning">Edit/Link</a> <a href="/delete/{{m.tmdb_id}}" class="btn btn-sm btn-danger">Del</a></td></tr>
            {% endfor %}
        </table>
    </div>

    <div id="tab-settings" class="tab-content" style="display:none;">
        <form action="/save_config" method="POST" class="bg-dark p-4 rounded border border-secondary">
            <h5 class="mb-4">🌍 Site Identity</h5>
            <label>Site Name</label><input name="site_name" class="form-control mb-3 bg-dark text-white border-secondary" value="{{config.SITE_NAME}}">
            <label>Site Logo URL</label><input name="site_logo" class="form-control mb-3 bg-dark text-white border-secondary" value="{{config.SITE_LOGO}}">
            <label>Site URL</label><input name="site_url" class="form-control mb-3 bg-dark text-white border-secondary" value="{{config.SITE_URL}}">
            <button class="btn btn-primary px-5">Save branding</button>
        </form>
    </div>

    <div id="tab-bot" class="tab-content" style="display:none;">
        <form action="/save_config" method="POST" class="bg-dark p-4 rounded border border-secondary">
            <h5 class="mb-4">🤖 Bot & Core Config</h5>
            <div class="row">
                <div class="col-md-12"><label>Telegram Bot Token</label><input name="token" class="form-control mb-3 bg-dark text-white border-secondary" value="{{config.BOT_TOKEN}}"></div>
                <div class="col-md-6"><label>TMDB API Key</label><input name="tmdb" class="form-control mb-3 bg-dark text-white border-secondary" value="{{config.TMDB_API_KEY}}"></div>
                <div class="col-md-6"><label>Admin Telegram ID</label><input name="admin_id" class="form-control mb-3 bg-dark text-white border-secondary" value="{{config.ADMIN_ID}}"></div>
                <div class="col-md-6"><label>Storage Channel ID</label><input name="channel_id" class="form-control mb-3 bg-dark text-white border-secondary" value="{{config.STORAGE_CHANNEL_ID}}"></div>
                <div class="col-md-6"><label>Shortener URL</label><input name="s_url" class="form-control mb-3 bg-dark text-white border-secondary" value="{{config.SHORTENER_URL}}"></div>
                <div class="col-md-6"><label>Shortener API Key</label><input name="s_api" class="form-control mb-3 bg-dark text-white border-secondary" value="{{config.SHORTENER_API}}"></div>
                <div class="col-md-6"><label>Auto Delete Time (Sec)</label><input name="delete_time" type="number" class="form-control bg-dark text-white border-secondary" value="{{config.AUTO_DELETE_TIME}}"></div>
            </div>
            <button class="btn btn-primary w-100 mt-4 py-2">Save bot settings</button>
        </form>
    </div>
</div>

<script>
function showTab(id) {
    $('.tab-content').hide(); $('.nav-link').removeClass('active');
    $('#tab-'+id).show(); $(event.target).addClass('active');
}
function searchTMDB() {
    let q = $('#tmdb_in').val();
    $.post('/admin/search_tmdb', {query: q}, function(data) {
        let h = '';
        data.forEach(i => { h += `<a href="#" class="list-group-item list-group-item-action bg-dark text-white" onclick="fetchData('${i.id}', '${i.media_type}')">${i.title || i.name} (${i.media_type})</a>`; });
        $('#res_box').html(h);
    });
}
function fetchData(id, type) {
    $.post('/admin/fetch_info', {url: id, type: type}, function(d) {
        $('#f_title').val(d.title); $('#f_id').val(d.tmdb_id); $('#f_type').val(d.type);
        $('#f_year').val(d.year); $('#f_poster').val(d.poster); $('#f_story').val(d.story);
        $('#res_box').html('');
    });
}
</script>
</body></html>"""

LOGIN_HTML = """<!DOCTYPE html><html><head><title>Login</title><link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css">{PREMIUM_STYLE}</head><body class="bg-dark d-flex align-items-center justify-content-center" style="height:100vh;">
<form method="POST" class="bg-dark p-4 rounded border border-secondary" style="width:340px;">
    <h4 class="text-center text-info mb-4">ADMIN LOGIN</h4>
    <input name="u" class="form-control mb-2 bg-secondary text-white" placeholder="User"><input name="p" type="password" class="form-control mb-3 bg-secondary text-white" placeholder="Pass"><button class="btn btn-primary w-100">Login</button>
</form></body></html>"""

EDIT_HTML = """<!DOCTYPE html><html><head><title>Edit Content</title><link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css">{PREMIUM_STYLE}</head><body class="main-content">
<div class="bg-dark p-4 border border-secondary rounded">
    <h3>Edit: {{m.title}}</h3>
    <form action="/admin/add_file" method="POST" class="mt-4">
        <input type="hidden" name="tmdb_id" value="{{m.tmdb_id}}">
        <div class="row">
            <div class="col-md-5"><input name="quality" class="form-control bg-dark text-white" placeholder="720p Dual Audio"></div>
            <div class="col-md-5"><input name="file_id" class="form-control bg-dark text-white" placeholder="Telegram Msg ID"></div>
            <div class="col-md-2"><button class="btn btn-primary w-100">Add Link</button></div>
        </div>
    </form>
    <div class="mt-4"><h6>Current Links:</h6>
    <ul class="list-group">{% for f in m.files %}<li class="list-group-item bg-dark text-white border-secondary d-flex justify-content-between">{{f.quality}} <a href="/admin/delete_file/{{m.tmdb_id}}/{{f.file_id}}" class="btn btn-sm btn-danger">Del</a></li>{% endfor %}</ul>
    </div>
    <a href="/admin" class="btn btn-secondary mt-4">Back to Panel</a>
</div></body></html>"""

# ================== রান করার অংশ ==================

if __name__ == '__main__':
    threading.Thread(target=init_bot_service, daemon=True).start()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
