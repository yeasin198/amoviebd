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
    # নতুন ফিউচার: SITE_NAME এবং SITE_LOGO ডিফল্ট হিসেবে যোগ করা হয়েছে
    defaults = {
        'SITE_NAME': 'Movie Portal',
        'SITE_LOGO': 'https://cdn-icons-png.flaticon.com/512/705/705062.png',
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
        res = requests.get(api_endpoint, timeout=5).json()
        return res.get('shortenedUrl') or res.get('shortlink') or long_url
    except:
        return long_url

def create_bot():
    config = get_config()
    token = config.get('BOT_TOKEN')
    if token and len(token) > 20:
        try:
            # বটের বাটন এবং কমান্ড ফাস্ট করার জন্য threaded=True
            return telebot.TeleBot(token, threaded=True)
        except:
            return None
    return None

def auto_delete_task(bot_inst, chat_id, msg_id, delay):
    if delay > 0:
        time.sleep(delay)
        try:
            bot_inst.delete_message(chat_id, msg_id)
        except: pass

# --- [টেলিগ্রাম বট হ্যান্ডলার] ---
def register_handlers(bot_inst):
    if not bot_inst: return

    @bot_inst.message_handler(commands=['start'])
    def start(message):
        # ফাস্ট করার জন্য ইউজার সেভ করার প্রসেসটি আলাদা থ্রেডে পাঠানো হয়েছে
        def save_user():
            if not users_col.find_one({'user_id': message.from_user.id}):
                users_col.insert_one({'user_id': message.from_user.id, 'name': message.from_user.first_name})
        threading.Thread(target=save_user).start()
            
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
                        warn = bot_inst.send_message(message.chat.id, f"⚠️ ফাইলটি {delay} সেকেন্ড পর ডিলিট হবে।")
                        # ডিলিট টাস্ক
                        def del_logic():
                            time.sleep(delay)
                            try:
                                bot_inst.delete_message(message.chat.id, sent_msg.message_id)
                                bot_inst.delete_message(message.chat.id, warn.message_id)
                            except: pass
                        threading.Thread(target=del_logic).start()
                except:
                    bot_inst.send_message(message.chat.id, "❌ ফাইল পাওয়া যায়নি।")
                return
        bot_inst.reply_to(message, f"🎬 {config['SITE_NAME']} এ স্বাগতম!\nমুভি খুঁজতে আমাদের ওয়েবসাইট ভিজিট করুন।")

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
        try: res = requests.get(url, timeout=5).json().get('results', [])
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
            m = requests.get(tmdb_url, timeout=5).json()
            
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
            bot = telebot.TeleBot(token, threaded=True) # Threaded True for Speed
            register_handlers(bot)
            if site_url:
                webhook_url = f"{site_url.rstrip('/')}/webhook"
                bot.remove_webhook()
                time.sleep(1)
                bot.set_webhook(url=webhook_url)
                print(f"✅ Webhook Active: {webhook_url}")
            return bot
        except Exception as e:
            print(f"❌ Bot Initialization Failure: {e}")
    return None

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
    return render_template_string(HOME_HTML, movies=movies, query=q, cat=cat, page=page, pages=pages, categories=CATEGORIES, conf=conf)

@app.route('/movie/<tmdb_id>')
def movie_details(tmdb_id):
    conf = get_config()
    movie = movies_col.find_one({'tmdb_id': tmdb_id})
    if not movie: return "Not Found", 404
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

    return render_template_string(DETAILS_HTML, m=movie, seasons=seasons_data, bot_user=bot_user, conf=conf)

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
    movies_list = list(movies_col.find({"title": {"$regex": q, "$options": "i"}} if q else {}).sort('_id', -1))
    
    # ড্যাশবোর্ড স্ট্যাটস
    stats = {
        'users': users_col.count_documents({}),
        'movies': movies_col.count_documents({})
    }
    return render_template_string(ADMIN_HTML, config=get_config(), movies=movies_list, q=q, categories=CATEGORIES, stats=stats)

@app.route('/admin/search_tmdb', methods=['POST'])
def search_tmdb():
    if not session.get('logged_in'): return jsonify({'error': 'Unauthorized'})
    query = request.form.get('query')
    tmdb_key = get_config().get('TMDB_API_KEY')
    url = f"https://api.themoviedb.org/3/search/multi?api_key={tmdb_key}&query={query}"
    try:
        res = requests.get(url, timeout=5).json().get('results', [])
        return jsonify(res)
    except: return jsonify([])

@app.route('/admin/fetch_info', methods=['POST'])
def fetch_info():
    if not session.get('logged_in'): return jsonify({'error': 'Unauthorized'})
    url = request.form.get('url')
    tmdb_key = get_config().get('TMDB_API_KEY')
    tmdb_id, media_type = None, "movie"
    imdb_match = re.search(r'tt\d+', url)
    if imdb_match:
        res = requests.get(f"https://api.themoviedb.org/3/find/{imdb_match.group(0)}?api_key={tmdb_key}&external_source=imdb_id", timeout=5).json()
        if res.get('movie_results'): tmdb_id, media_type = res['movie_results'][0]['id'], "movie"
        elif res.get('tv_results'): tmdb_id, media_type = res['tv_results'][0]['id'], "tv"
    else: tmdb_id, media_type = url, request.form.get('type', 'movie')

    try:
        m = requests.get(f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}?api_key={tmdb_key}&append_to_response=credits,videos", timeout=5).json()
        genres_data = m.get('genres', [])
        auto_cat = "Web Series" if media_type == 'tv' else (genres_data[0]['name'] if genres_data else "Action")
        trailer = next((v['key'] for v in m.get('videos', {}).get('results', []) if v['type'] == 'Trailer'), "")
        return jsonify({
            'tmdb_id': str(tmdb_id), 'type': media_type, 'title': m.get('title') or m.get('name'),
            'year': (m.get('release_date') or m.get('first_air_date') or 'N/A')[:4],
            'rating': str(round(m.get('vote_average', 0), 1)), 'poster': f"https://image.tmdb.org/t/p/w500{m.get('poster_path')}",
            'story': m.get('overview'), 'director': next((p['name'] for p in m.get('credits', {}).get('crew', []) if p['job'] in ['Director', 'Executive Producer']), 'N/A'),
            'cast': ", ".join([a['name'] for a in m.get('credits', {}).get('cast', [])[:8]]),
            'category': auto_cat, 'trailer': f"https://www.youtube.com/embed/{trailer}" if trailer else ""
        })
    except: return jsonify({'error': 'Failed'})

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
    return render_template_string(EDIT_HTML, m=movie, categories=CATEGORIES, config=get_config())

@app.route('/admin/update', methods=['POST'])
def update_movie():
    if not session.get('logged_in'): return redirect(url_for('login'))
    tid = request.form.get('tmdb_id')
    data = {
        'title': request.form.get('title'), 'year': request.form.get('year'),
        'rating': request.form.get('rating'), 'poster': request.form.get('poster'),
        'category': request.form.get('category'), 'trailer': request.form.get('trailer'),
        'director': request.form.get('director'), 'cast': request.form.get('cast'), 'story': request.form.get('story')
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

# ================== HTML Templates ==================

COMMON_STYLE = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;600&display=swap');
    body { background: #0b0c10; color: #c5c6c7; font-family: 'Poppins', sans-serif; overflow-x: hidden; }
    .neon-text { color: #66fcf1; text-shadow: 0 0 10px #66fcf1; }
    .neon-card { background: #1f2833; border: 1px solid #45a29e; border-radius: 12px; transition: 0.5s; overflow: hidden; position: relative; }
    .neon-card:hover { transform: translateY(-8px); box-shadow: 0 0 20px #66fcf1; border-color: #66fcf1; }
    .navbar { background: #1f2833; border-bottom: 2px solid #66fcf1; }
    .site-logo { width: 35px; height: 35px; border-radius: 50%; margin-right: 10px; border: 1px solid #66fcf1; }
    .poster-img { height: 260px; width: 100%; object-fit: cover; }
    .cat-pill { padding: 6px 16px; border-radius: 20px; border: 1px solid #66fcf1; color: #66fcf1; text-decoration: none; margin: 4px; display: inline-block; font-size: 13px; transition: 0.3s; }
    .cat-pill.active, .cat-pill:hover { background: #66fcf1; color: #0b0c10; font-weight: bold; }
    /* Admin Premium UI */
    .admin-container { background: #fff; color: #333; border-radius: 15px; padding: 25px; margin-top: 30px; box-shadow: 0 10px 30px rgba(0,0,0,0.5); }
    .nav-tabs .nav-link { color: #45a29e; font-weight: 600; cursor: pointer; }
    .nav-tabs .nav-link.active { color: #1f2833; border-bottom: 3px solid #45a29e; }
    .search-results-box { position: absolute; background: white; width: 100%; z-index: 1000; max-height: 200px; overflow-y: auto; border: 1px solid #ddd; }
    .search-item { padding: 10px; border-bottom: 1px solid #eee; cursor: pointer; }
    .search-item:hover { background: #f8f9fa; }
</style>
"""

HOME_HTML = f"<!DOCTYPE html><html><head><meta name='viewport' content='width=device-width, initial-scale=1.0'><title>{{{{conf.SITE_NAME}}}}</title><link rel='stylesheet' href='https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css'>{COMMON_STYLE}</head><body>" + """
<nav class="navbar navbar-dark sticky-top mb-4"><div class="container">
    <a class="navbar-brand fw-bold neon-text d-flex align-items-center" href="/">
        <img src="{{conf.SITE_LOGO}}" class="site-logo"> {{conf.SITE_NAME}}
    </a>
    <form class="d-flex" action="/" method="GET">
        <input class="form-control me-2 bg-dark text-white border-info" type="search" name="search" placeholder="Search...">
        <button class="btn btn-outline-info" type="submit">🔍</button>
    </form>
</div></nav>
<div class="container mb-4 text-center">
    <a href="/" class="cat-pill {% if not cat %}active{% endif %}">All</a>
    {% for c in categories %}
    <a href="/?cat={{c}}" class="cat-pill {% if cat == c %}active{% endif %}">{{c}}</a>
    {% endfor %}
</div>
<div class="container"><div class="row row-cols-2 row-cols-md-4 row-cols-lg-6 g-3">
{% for m in movies %}
<div class="col"><a href="/movie/{{m.tmdb_id}}" style="text-decoration:none; color:inherit;">
    <div class="neon-card">
        <img src="{{m.poster}}" class="poster-img" loading="lazy">
        <div class="p-2 text-center">
            <div class="small fw-bold text-truncate">{{m.title}}</div>
            <div class="text-info small">⭐ {{m.rating}} | {{m.year}}</div>
        </div>
    </div>
</a></div>
{% endfor %}
</div></div></body></html>"""

DETAILS_HTML = f"<!DOCTYPE html><html><head><meta name='viewport' content='width=device-width, initial-scale=1.0'><title>{{{{m.title}}}}</title><link rel='stylesheet' href='https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css'>{COMMON_STYLE}</head><body>" + """
<nav class="navbar navbar-dark mb-4"><div class="container">
    <a class="navbar-brand fw-bold neon-text d-flex align-items-center" href="/"><img src="{{conf.SITE_LOGO}}" class="site-logo">{{conf.SITE_NAME}}</a>
</div></nav>
<div class="container py-4">
    <div class="row">
        <div class="col-md-4 mb-4"><img src="{{m.poster}}" class="w-100 rounded border border-info shadow-lg"></div>
        <div class="col-md-8">
            <h1 class="neon-text">{{m.title}} ({{m.year}})</h1>
            <p class="text-info fw-bold">⭐ Rating: {{m.rating}} | 📂 Category: {{m.category}}</p>
            <p><b>Story:</b><br>{{m.story}}</p>
            <hr class="border-secondary">
            {% if m.type == 'movie' %}
                {% for f in m.files %}<a href="{{f.short_url}}" class="btn btn-info me-2 mb-2">Download {{f.quality}}</a>{% endfor %}
            {% else %}
                {% for s, eps in seasons.items() %}
                <div class="p-3 border border-info rounded mb-3">
                    <h6 class="text-info">Season {{s}}</h6>
                    {% for ep in eps %}
                    <div class="mb-1">Ep {{ep.episode}}: {% for f in ep.files %}<a href="{{f.short_url}}" class="btn btn-sm btn-outline-info ms-1">{{f.quality}}</a>{% endfor %}</div>
                    {% endfor %}
                </div>
                {% endfor %}
            {% endif %}
        </div>
    </div>
</div></body></html>"""

ADMIN_HTML = """<!DOCTYPE html><html><head><title>Admin Panel</title><link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css"><script src="https://code.jquery.com/jquery-3.6.0.min.js"></script><script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>""" + COMMON_STYLE + """</head><body class="bg-dark">
<div class="container admin-container">
    <div class="d-flex justify-content-between align-items-center mb-4">
        <h2 class="fw-bold">⚙️ Admin Panel</h2>
        <a href="/" class="btn btn-outline-dark">Visit Site</a>
    </div>
    <ul class="nav nav-tabs mb-4" id="adminTab" role="tablist">
        <li class="nav-item"><button class="nav-link active" data-bs-toggle="tab" data-bs-target="#tab-stats">📊 Stats</button></li>
        <li class="nav-item"><button class="nav-link" data-bs-toggle="tab" data-bs-target="#tab-add">➕ Add Content</button></li>
        <li class="nav-item"><button class="nav-link" data-bs-toggle="tab" data-bs-target="#tab-manage">📂 Manage List</button></li>
        <li class="nav-item"><button class="nav-link" data-bs-toggle="tab" data-bs-target="#tab-settings">🛠️ Settings</button></li>
    </ul>
    <div class="tab-content">
        <div class="tab-pane fade show active" id="tab-stats">
            <div class="row text-center">
                <div class="col-md-6"><div class="card p-4 mb-3 bg-light"><h3>{{stats.users}}</h3><p>Total Users</p></div></div>
                <div class="col-md-6"><div class="card p-4 mb-3 bg-light"><h3>{{stats.movies}}</h3><p>Total Movies/Shows</p></div></div>
            </div>
        </div>
        <div class="tab-pane fade" id="tab-add">
            <div class="row">
                <div class="col-md-5">
                    <h5>🔍 TMDb Search</h5>
                    <div class="position-relative">
                        <input id="tmdb_in" class="form-control mb-2" placeholder="Search name..." onkeyup="searchTMDB()">
                        <div id="tmdb_results" class="search-results-box" style="display:none;"></div>
                    </div>
                    <hr>
                    <h5>🔗 ID Fetch</h5>
                    <div class="input-group mb-3"><input id="url_in" class="form-control" placeholder="TMDb ID or IMDb Link"><button class="btn btn-primary" onclick="fetchData()">Fetch</button></div>
                </div>
                <div class="col-md-7">
                    <form action="/admin/manual_add" method="POST">
                        <input id="f_title" name="title" class="form-control mb-2" placeholder="Title" required>
                        <input id="f_id" name="tmdb_id" class="form-control mb-2" placeholder="ID" required>
                        <select id="f_type" name="type" class="form-control mb-2"><option value="movie">Movie</option><option value="tv">TV</option></select>
                        <select id="f_cat" name="category" class="form-control mb-2">{% for c in categories %}<option value="{{c}}">{{c}}</option>{% endfor %}</select>
                        <input id="f_year" name="year" class="form-control mb-2" placeholder="Year">
                        <input id="f_rating" name="rating" class="form-control mb-2" placeholder="Rating">
                        <input id="f_poster" name="poster" class="form-control mb-2" placeholder="Poster URL">
                        <textarea id="f_story" name="story" class="form-control mb-2" placeholder="Story"></textarea>
                        <button class="btn btn-success w-100">Save Metadata</button>
                    </form>
                </div>
            </div>
        </div>
        <div class="tab-pane fade" id="tab-manage">
            <form class="d-flex mb-3"><input name="q" class="form-control me-2" placeholder="Search..."><button class="btn btn-dark">Search</button></form>
            <table class="table table-sm"><thead><tr><th>Title</th><th>Action</th></tr></thead><tbody>
                {% for m in movies %}<tr><td>{{m.title}}</td><td><a href="/admin/edit/{{m.tmdb_id}}" class="btn btn-sm btn-warning">Edit</a> <a href="/delete/{{m.tmdb_id}}" class="btn btn-sm btn-danger">Del</a></td></tr>{% endfor %}
            </tbody></table>
        </div>
        <div class="tab-pane fade" id="tab-settings">
            <form action="/save_config" method="POST">
                <label>Site Name</label><input name="site_name" class="form-control mb-2" value="{{config.SITE_NAME}}">
                <label>Site Logo URL</label><input name="site_logo" class="form-control mb-2" value="{{config.SITE_LOGO}}">
                <label>Site URL</label><input name="site_url" class="form-control mb-2" value="{{config.SITE_URL}}">
                <label>Bot Token</label><input name="token" class="form-control mb-2" value="{{config.BOT_TOKEN}}">
                <label>TMDB Key</label><input name="tmdb" class="form-control mb-2" value="{{config.TMDB_API_KEY}}">
                <label>Admin ID</label><input name="admin_id" class="form-control mb-2" value="{{config.ADMIN_ID}}">
                <label>Channel ID</label><input name="channel_id" class="form-control mb-2" value="{{config.STORAGE_CHANNEL_ID}}">
                <button class="btn btn-dark w-100 mt-3">Save All Settings</button>
            </form>
        </div>
    </div>
</div>
<script>
function searchTMDB() {
    let q = $('#tmdb_in').val(); if(q.length < 3) return;
    $.post('/admin/search_tmdb', {query: q}, function(res) {
        let h = ''; res.forEach(i => { if(i.media_type != 'person') {
            h += `<div class="search-item" onclick="selectTMDB('${i.media_type}','${i.id}')">${i.title || i.name} (${(i.release_date || i.first_air_date || '').substring(0,4)})</div>`;
        }}); $('#tmdb_results').html(h).show();
    });
}
function selectTMDB(type, id) { $('#f_type').val(type); $('#url_in').val(id); $('#tmdb_results').hide(); fetchData(); }
function fetchData() {
    let u = $('#url_in').val(), t = $('#f_type').val();
    $.post('/admin/fetch_info', {url: u, type: t}, function(d) {
        if(d.error) return alert(d.error);
        $('#f_title').val(d.title); $('#f_id').val(d.tmdb_id); $('#f_year').val(d.year);
        $('#f_rating').val(d.rating); $('#f_poster').val(d.poster); $('#f_story').val(d.story); $('#f_cat').val(d.category);
    });
}
</script>
</body></html>"""

EDIT_HTML = """<!DOCTYPE html><html><head><title>Edit</title><link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css"></head><body class="bg-light container py-5">
<div class="row">
    <div class="col-md-6"><div class="card p-4 shadow mb-4">
        <h5>Edit: {{m.title}}</h5>
        <form action="/admin/update" method="POST">
            <input type="hidden" name="tmdb_id" value="{{m.tmdb_id}}">
            <input name="title" class="form-control mb-2" value="{{m.title}}">
            <select name="category" class="form-control mb-2">{% for c in categories %}<option value="{{c}}" {% if m.category==c %}selected{% endif %}>{{c}}</option>{% endfor %}</select>
            <input name="year" class="form-control mb-2" value="{{m.year}}">
            <input name="poster" class="form-control mb-2" value="{{m.poster}}">
            <textarea name="story" class="form-control mb-2" rows="4">{{m.story}}</textarea>
            <button class="btn btn-success w-100">Update</button>
        </form>
    </div></div>
    <div class="col-md-6"><div class="card p-4 shadow">
        <h5>Manage Links</h5>
        <form action="/admin/add_file" method="POST" class="mb-4">
            <input type="hidden" name="tmdb_id" value="{{m.tmdb_id}}">
            <input name="quality" class="form-control mb-2" placeholder="720p Dual" required>
            <input name="file_id" class="form-control mb-2" placeholder="Msg ID" required>
            <button class="btn btn-info w-100">Add Link</button>
        </form>
        <ul class="list-group">{% for f in m.files %}<li class="list-group-item d-flex justify-content-between">{{f.quality}} <a href="/admin/delete_file/{{m.tmdb_id}}/{{f.file_id}}" class="text-danger">Del</a></li>{% endfor %}</ul>
    </div><a href="/admin" class="btn btn-secondary mt-3">Back</a></div>
</div></body></html>"""

LOGIN_HTML = """<!DOCTYPE html><html><head><title>Login</title><link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css"></head><body class="bg-dark d-flex align-items-center" style="height:100vh;">
<div class="card p-4 mx-auto shadow" style="width:340px;">
    <h4 class="text-center">ADMIN LOGIN</h4><hr>
    <form method="POST"><input name="u" class="form-control mb-2" placeholder="User"><input name="p" type="password" class="form-control mb-3" placeholder="Pass"><button class="btn btn-primary w-100">Login</button></form>
</div></body></html>"""

if __name__ == '__main__':
    threading.Thread(target=init_bot_service, daemon=True).start()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
