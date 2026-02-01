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
        'SITE_NAME': 'MoviePortal',
        'SITE_LOGO': 'https://cdn-icons-png.flaticon.com/512/4221/4221419.png',
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
        api_endpoint = f"https://{s_url}/api?api={s_api}&url={urllib.parse.quote(long_url)}"
        res = requests.get(api_endpoint).json()
        return res.get('shortenedUrl') or res.get('shortlink') or long_url
    except:
        return long_url

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
                        warn_msg = bot_inst.send_message(message.chat.id, f"⚠️ ফাইলটি {delay} সেকেন্ড পর ডিলিট হবে।")
                        threading.Thread(target=auto_delete_task, args=(bot_inst, message.chat.id, sent_msg.message_id, delay)).start()
                        threading.Thread(target=auto_delete_task, args=(bot_inst, message.chat.id, warn_msg.message_id, delay)).start()
                except:
                    bot_inst.send_message(message.chat.id, "❌ ফাইল পাওয়া যায়নি।")
                return
        bot_inst.reply_to(message, f"🎬 {config.get('SITE_NAME')} এ স্বাগতম! মুভি বা টিভি শো খুঁজতে আমাদের ওয়েবসাইট ভিজিট করুন।")

    @bot_inst.message_handler(commands=['cancel'])
    def cancel_process(message):
        uid = message.from_user.id
        if uid in admin_states:
            del admin_states[uid]
            bot_inst.clear_step_handler_by_chat_id(chat_id=message.chat.id)
            bot_inst.reply_to(message, "✅ বর্তমান আপলোড প্রসেসটি বাতিল করা হয়েছে।")
        else:
            bot_inst.reply_to(message, "ℹ️ কোনো প্রসেস বর্তমানে রানিং নেই।")

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
            bot_inst.reply_to(message, "⚠️ মুভির নাম লিখুন। (যেমন: /post Leo)")
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
        bot_inst.send_message(message.chat.id, "🔍 কি আপলোড করতে চান সিলেক্ট করুন: (বাতিল করতে /cancel লিখুন)", reply_markup=markup)

    @bot_inst.callback_query_handler(func=lambda call: call.data.startswith('sel_'))
    def handle_selection(call):
        _, m_type, m_id = call.data.split('_')
        # মাল্টিপল ফাইল স্টোর করার জন্য 'temp_files' ডিকশনারি
        admin_states[call.from_user.id] = {'type': m_type, 'tmdb_id': m_id, 'temp_files': []}
        
        if m_type == 'movie':
            ask_movie_lang(call.message, m_id)
        else:
            msg = bot_inst.send_message(call.message.chat.id, "📺 সিজন নম্বর লিখুন (বা /cancel):")
            bot_inst.register_next_step_handler(msg, get_season)

    def ask_movie_lang(message, mid):
        markup = types.InlineKeyboardMarkup()
        for l in ["Bangla", "Hindi", "English", "Multi"]:
            markup.add(types.InlineKeyboardButton(text=l, callback_data=f"lang_m_{mid}_{l}"))
        bot_inst.send_message(message.chat.id, "🌐 ল্যাঙ্গুয়েজ সিলেক্ট করুন:", reply_markup=markup)

    def get_season(message):
        if message.text == '/cancel': return cancel_process(message)
        uid = message.from_user.id
        if uid in admin_states:
            admin_states[uid]['season'] = message.text
            msg = bot_inst.send_message(message.chat.id, "🔢 এপিসোড নম্বর লিখুন:")
            bot_inst.register_next_step_handler(msg, get_episode)

    def get_episode(message):
        if message.text == '/cancel': return cancel_process(message)
        uid = message.from_user.id
        if uid in admin_states:
            admin_states[uid]['episode'] = message.text
            msg = bot_inst.send_message(message.chat.id, "📥 কোয়ালিটি লিখুন (যেমন: 720p):")
            bot_inst.register_next_step_handler(msg, get_tv_quality)

    def get_tv_quality(message):
        if message.text == '/cancel': return cancel_process(message)
        uid = message.from_user.id
        if uid in admin_states:
            admin_states[uid]['qual'] = message.text
            bot_inst.send_message(message.chat.id, "📥 ভিডিও ফাইলটি পাঠান (বা /cancel):")

    @bot_inst.callback_query_handler(func=lambda call: call.data.startswith('lang_m_'))
    def movie_qual(call):
        _, _, mid, lang = call.data.split('_')
        markup = types.InlineKeyboardMarkup()
        for q in ["480p", "720p", "1080p", "4K", "Custom"]:
            markup.add(types.InlineKeyboardButton(text=q, callback_data=f"qual_m_{mid}_{lang}_{q}"))
        bot_inst.edit_message_text("💎 কোয়ালিটি সিলেক্ট করুন:", call.message.chat.id, call.message.message_id, reply_markup=markup)

    @bot_inst.callback_query_handler(func=lambda call: call.data.startswith('qual_m_'))
    def movie_file_ask(call):
        uid = call.from_user.id
        _, _, mid, lang, qual = call.data.split('_')
        if uid in admin_states:
            if qual == "Custom":
                admin_states[uid].update({'lang': lang})
                msg = bot_inst.send_message(call.message.chat.id, "🖊️ কাস্টম কোয়ালিটি লিখুন (বা /cancel):")
                bot_inst.register_next_step_handler(msg, get_custom_qual)
            else:
                admin_states[uid].update({'lang': lang, 'qual': qual})
                bot_inst.send_message(call.message.chat.id, f"📥 মুভি ফাইলটি এখানে পাঠান (বা /cancel):")

    def get_custom_qual(message):
        if message.text == '/cancel': return cancel_process(message)
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
            # ফাইল স্টোরেজ চ্যানেলে কপি করা
            sent_msg = bot_inst.copy_message(int(config['STORAGE_CHANNEL_ID']), message.chat.id, message.message_id)
            
            # ফাইলের ডিটেইলস সেভ করা
            file_label = f"{state.get('lang', '')} {state.get('qual', 'HD')}".strip()
            file_data = {'quality': file_label, 'file_id': sent_msg.message_id}
            admin_states[uid]['temp_files'].append(file_data)

            # বাটন দেখানো
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("➕ Add More Quality", callback_data="add_more_qual"))
            markup.add(types.InlineKeyboardButton("✅ Finish Upload", callback_data="finish_upload"))
            
            bot_inst.reply_to(message, f"📥 ফাইল গ্রহণ করা হয়েছে: {file_label}\nএখন কি করতে চান?", reply_markup=markup)
        except Exception as e:
            bot_inst.send_message(message.chat.id, f"❌ এরর: {e}")

    @bot_inst.callback_query_handler(func=lambda call: call.data == "add_more_qual")
    def add_more_files(call):
        uid = call.from_user.id
        if uid in admin_states:
            state = admin_states[uid]
            if state['type'] == 'movie':
                ask_movie_lang(call.message, state['tmdb_id'])
            else:
                msg = bot_inst.send_message(call.message.chat.id, "📥 কোয়ালিটি লিখুন (বা /cancel):")
                bot_inst.register_next_step_handler(msg, get_tv_quality)

    @bot_inst.callback_query_handler(func=lambda call: call.data == "finish_upload")
    def finish_process_and_save(call):
        uid = call.from_user.id
        if uid not in admin_states: return
        config = get_config()
        state = admin_states[uid]
        
        if not state['temp_files']:
            bot_inst.answer_callback_query(call.id, "⚠️ কোনো ফাইল পাঠানো হয়নি!")
            return

        bot_inst.edit_message_text("⌛ ডাটাবেসে সেভ হচ্ছে, অপেক্ষা করুন...", call.message.chat.id, call.message.message_id)
        
        try:
            tmdb_api = config['TMDB_API_KEY']
            tmdb_url = f"https://api.themoviedb.org/3/{state['type']}/{state['tmdb_id']}?api_key={tmdb_api}&append_to_response=credits,videos"
            m = requests.get(tmdb_url).json()
            
            genres_data = m.get('genres', [])
            auto_cat = "Action"
            if state['type'] == 'tv': auto_cat = "Web Series"
            elif genres_data:
                for g in genres_data:
                    if g['name'] in CATEGORIES:
                        auto_cat = g['name']; break

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
                'trailer': f"https://www.youtube.com/embed/{trailer_key}" if trailer_key else ""
            }
            # মেটাডাটা আপডেট/ইনসার্ট
            movies_col.update_one({'tmdb_id': movie_info['tmdb_id']}, {'$set': movie_info}, upsert=True)

            # ফাইলগুলো পুশ করা
            if state['type'] == 'movie':
                movies_col.update_one({'tmdb_id': state['tmdb_id']}, {'$push': {'files': {'$each': state['temp_files']}}})
            else:
                episodes_col.update_one(
                    {'tmdb_id': state['tmdb_id'], 'season': int(state['season']), 'episode': int(state['episode'])},
                    {'$set': {'tmdb_id': state['tmdb_id'], 'season': int(state['season']), 'episode': int(state['episode'])},
                     '$push': {'files': {'$each': state['temp_files']}}}, upsert=True
                )
            
            bot_inst.send_message(call.message.chat.id, f"✅ সফলভাবে পাবলিশ হয়েছে: {title}\n📂 ক্যাটাগরি: {auto_cat}\n💎 কোয়ালিটি সংখ্যা: {len(state['temp_files'])}")
            del admin_states[uid]
        except Exception as e:
            bot_inst.send_message(call.message.chat.id, f"❌ এরর: {e}")

# --- [বট ইনিট ফাংশন] ---
def init_bot_service():
    global bot
    config = get_config()
    token = config.get('BOT_TOKEN')
    site_url = config.get('SITE_URL')
    if token and len(token) > 20:
        try:
            bot = telebot.TeleBot(token, threaded=False)
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

# ================== FLASK ROUTES ==================

@app.route('/')
def home():
    config = get_config()
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
    
    # স্লাইডারের জন্য সর্বশেষ ৬টি মুভি
    slider_movies = list(movies_col.find({}).sort('_id', -1).limit(6))
    
    pages = math.ceil(total / limit)
    return render_template_string(HOME_HTML, movies=movies, slider_movies=slider_movies, query=q, cat=cat, page=page, pages=pages, categories=CATEGORIES, config=config)

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

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/admin')
def admin():
    if not session.get('logged_in'): return redirect(url_for('login'))
    tab = request.args.get('tab', 'dashboard')
    config = get_config()
    
    if tab == 'movies':
        q = request.args.get('q', '')
        movies = list(movies_col.find({"title": {"$regex": q, "$options": "i"}}).sort('_id', -1))
        return render_template_string(ADMIN_MOVIES_HTML, movies=movies, q=q, config=config)
    elif tab == 'add':
        return render_template_string(ADMIN_ADD_HTML, config=config, categories=CATEGORIES)
    elif tab == 'settings':
        return render_template_string(ADMIN_SETTINGS_HTML, config=config)
    else: # dashboard
        stats = {
            'users': users_col.count_documents({}),
            'movies': movies_col.count_documents({})
        }
        return render_template_string(ADMIN_DASHBOARD_HTML, stats=stats, config=config)

@app.route('/admin/search_tmdb', methods=['POST'])
def search_tmdb():
    if not session.get('logged_in'): return jsonify({'error': 'Unauthorized'})
    query = request.form.get('query')
    tmdb_key = get_config().get('TMDB_API_KEY')
    if not tmdb_key: return jsonify({'error': 'TMDB Key missing'})
    url = f"https://api.themoviedb.org/3/search/multi?api_key={tmdb_key}&query={query}"
    try:
        res = requests.get(url).json().get('results', [])
        return jsonify(res)
    except Exception as e: return jsonify({'error': str(e)})

@app.route('/admin/fetch_info', methods=['POST'])
def fetch_info():
    if not session.get('logged_in'): return jsonify({'error': 'Unauthorized'})
    url = request.form.get('url')
    tmdb_key = get_config().get('TMDB_API_KEY')
    if not tmdb_key: return jsonify({'error': 'TMDB Key missing'})

    tmdb_id, media_type = None, "movie"
    imdb_match = re.search(r'tt\d+', url)
    tmdb_match = re.search(r'tmdb.org/(movie|tv)/(\d+)', url)
    only_id_match = re.match(r'^\d+$', url)

    try:
        if imdb_match:
            imdb_id = imdb_match.group(0)
            res = requests.get(f"https://api.themoviedb.org/3/find/{imdb_id}?api_key={tmdb_key}&external_source=imdb_id").json()
            if res.get('movie_results'): tmdb_id, media_type = res['movie_results'][0]['id'], "movie"
            elif res.get('tv_results'): tmdb_id, media_type = res['tv_results'][0]['id'], "tv"
        elif tmdb_match:
            media_type, tmdb_id = tmdb_match.group(1), tmdb_match.group(2)
        elif only_id_match:
            tmdb_id = url
            media_type = request.form.get('type', 'movie')

        if not tmdb_id: return jsonify({'error': 'ID not found'})
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
            'category': auto_cat,
            'trailer': f"https://www.youtube.com/embed/{trailer}" if trailer else ""
        })
    except Exception as e: return jsonify({'error': str(e)})

@app.route('/admin/manual_add', methods=['POST'])
def manual_add():
    if not session.get('logged_in'): return redirect(url_for('login'))
    tid = request.form.get('tmdb_id')
    movie_info = {
        'tmdb_id': tid, 'type': request.form.get('type', 'movie'), 'title': request.form.get('title'),
        'year': request.form.get('year'), 'poster': request.form.get('poster'),
        'rating': request.form.get('rating'), 'story': request.form.get('story'),
        'director': request.form.get('director'), 'cast': request.form.get('cast'),
        'category': request.form.get('category'),
        'trailer': request.form.get('trailer')
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
        'category': request.form.get('category'),
        'trailer': request.form.get('trailer'), 'director': request.form.get('director'),
        'cast': request.form.get('cast'), 'story': request.form.get('story')
    }
    movies_col.update_one({'tmdb_id': tid}, {'$set': data})
    return redirect('/admin?tab=movies')

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
    return redirect('/admin?tab=settings')

@app.route('/delete/<tmdb_id>')
def delete_movie(tmdb_id):
    if not session.get('logged_in'): return redirect(url_for('login'))
    movies_col.delete_one({'tmdb_id': tmdb_id})
    episodes_col.delete_many({'tmdb_id': tmdb_id})
    return redirect('/admin?tab=movies')

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
    :root { --neon: #66fcf1; --dark: #0b0c10; --card: #1f2833; --text: #c5c6c7; }
    body { background: var(--dark); color: var(--text); font-family: 'Poppins', sans-serif; overflow-x: hidden; }
    
    /* Slider Styles */
    .hero-slider { margin-bottom: 40px; border-radius: 15px; overflow: hidden; border: 2px solid var(--neon); box-shadow: 0 0 15px rgba(102, 252, 241, 0.3); }
    .carousel-item img { height: 450px; width: 100%; object-fit: cover; filter: brightness(0.6); }
    .carousel-caption { background: rgba(0,0,0,0.6); border-radius: 10px; padding: 20px; border: 1px solid var(--neon); bottom: 10%; }
    .carousel-caption h3 { color: var(--neon); font-weight: 600; }

    .neon-card { background: var(--card); border: 1px solid #45a29e; border-radius: 12px; transition: 0.5s; overflow: hidden; position: relative; }
    .neon-card:hover { transform: translateY(-8px); box-shadow: 0 0 20px var(--neon); border-color: var(--neon); }
    .btn-neon { background: var(--neon); color: var(--dark); font-weight: 600; border-radius: 6px; padding: 10px 20px; text-decoration: none; border: none; transition: 0.3s; display: inline-block; cursor:pointer;}
    .btn-neon:hover { background: #45a29e; color: #fff; box-shadow: 0 0 15px var(--neon); }
    
    .cat-pill { padding: 6px 16px; border-radius: 20px; border: 1px solid var(--neon); color: var(--neon); text-decoration: none; margin: 4px; display: inline-block; font-size: 13px; transition: 0.3s; }
    .cat-pill.active, .cat-pill:hover { background: var(--neon); color: var(--dark); font-weight: bold; }
    
    .sidebar { width: 260px; height: 100vh; background: #1f2833; position: fixed; top: 0; left: 0; padding: 20px 0; border-right: 2px solid var(--neon); z-index: 1000; }
    .sidebar-brand { text-align: center; padding: 0 20px 20px; border-bottom: 1px solid #45a29e; margin-bottom: 20px; }
    .sidebar a { padding: 12px 25px; text-decoration: none; font-size: 15px; color: #fff; display: flex; align-items: center; transition: 0.3s; }
    .sidebar a:hover, .sidebar a.active { background: var(--neon); color: var(--dark); font-weight: bold; }
    
    .main-content { margin-left: 260px; padding: 30px; min-height: 100vh; }
    .admin-card { background: white; color: #333; border-radius: 12px; padding: 20px; box-shadow: 0 5px 15px rgba(0,0,0,0.3); margin-bottom: 25px; }
    .navbar { background: var(--card); border-bottom: 2px solid var(--neon); }
    .logo-img { height: 40px; width: 40px; border-radius: 50%; object-fit: cover; margin-right: 10px; border: 1px solid var(--neon); }
</style>
"""

HOME_HTML = f"<!DOCTYPE html><html><head><meta name='viewport' content='width=device-width, initial-scale=1.0'><title>{{{{config.SITE_NAME}}}}</title><link rel='stylesheet' href='https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css'>{COMMON_STYLE}</head><body>" + """
<nav class="navbar navbar-dark sticky-top mb-4"><div class="container">
    <a class="navbar-brand fw-bold d-flex align-items-center text-info" href="/">
        <img src="{{config.SITE_LOGO}}" class="logo-img"> {{config.SITE_NAME}}
    </a>
    <form class="d-flex" action="/" method="GET">
        <input class="form-control me-2 bg-dark text-white border-info" type="search" name="search" placeholder="Search..." value="{{query or ''}}">
        <button class="btn btn-outline-info" type="submit">🔍</button>
    </form>
</div></nav>

<div class="container">
    <!-- Slider Section -->
    {% if slider_movies and not query and not cat %}
    <div id="heroSlider" class="carousel slide hero-slider" data-bs-ride="carousel">
        <div class="carousel-inner">
            {% for m in slider_movies %}
            <div class="carousel-item {% if loop.first %}active{% endif %}">
                <a href="/movie/{{m.tmdb_id}}">
                    <img src="{{m.poster}}" class="d-block w-100" alt="{{m.title}}">
                    <div class="carousel-caption d-none d-md-block">
                        <h3>{{m.title}} ({{m.year}})</h3>
                        <p>⭐ Rating: {{m.rating}} | 📂 Category: {{m.category}}</p>
                    </div>
                </a>
            </div>
            {% endfor %}
        </div>
        <button class="carousel-control-prev" type="button" data-bs-target="#heroSlider" data-bs-slide="prev">
            <span class="carousel-control-prev-icon" aria-hidden="true"></span>
        </button>
        <button class="carousel-control-next" type="button" data-bs-target="#heroSlider" data-bs-slide="next">
            <span class="carousel-control-next-icon" aria-hidden="true"></span>
        </button>
    </div>
    {% endif %}

    <div class="container mb-4 text-center">
        <a href="/" class="cat-pill {% if not cat %}active{% endif %}">All</a>
        {% for c in categories %}
        <a href="/?cat={{c}}" class="cat-pill {% if cat == c %}active{% endif %}">{{c}}</a>
        {% endfor %}
    </div>

    <div class="row row-cols-2 row-cols-md-4 row-cols-lg-6 g-3">
    {% for m in movies %}
    <div class="col"><a href="/movie/{{m.tmdb_id}}" style="text-decoration:none; color:inherit;">
        <div class="neon-card">
            <img src="{{m.poster}}" class="w-100" style="height:260px; object-fit:cover;" loading="lazy">
            <div class="p-2 text-center">
                <div class="small fw-bold text-truncate">{{m.title}}</div>
                <div class="text-info small">⭐ {{m.rating}} | {{m.year}}</div>
            </div>
        </div>
    </a></div>
    {% endfor %}
    </div>

    <nav class="mt-4"><ul class="pagination justify-content-center">
        {% for p in range(1, pages + 1) %}
        <li class="page-item {% if p == page %}active{% endif %}"><a class="page-link" href="/?page={{p}}{% if query %}&search={{query}}{% endif %}{% if cat %}&cat={{cat}}{% endif %}">{{p}}</a></li>
        {% endfor %}
    </ul></nav>
</div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body></html>"""

DETAILS_HTML = f"<!DOCTYPE html><html><head><meta name='viewport' content='width=device-width, initial-scale=1.0'>" + """
<title>{{m.title}} ({{m.year}}) - {{config.SITE_NAME}}</title>
<link rel='stylesheet' href='https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css'>""" + f"{COMMON_STYLE}</head><body>" + """
<div class="container py-5">
    <div class="row">
        <div class="col-md-4 mb-4"><img src="{{m.poster}}" class="w-100 rounded border border-info shadow-lg"></div>
        <div class="col-md-8">
            <h1 class="text-white">{{m.title}} ({{m.year}})</h1>
            <p class="text-info fw-bold">⭐ Rating: {{m.rating}} / 10 | 📂 Category: {{m.category}}</p>
            <p><b>Director:</b> {{m.director}} | <b>Cast:</b> {{m.cast}}</p>
            <p><b>Story:</b><br>{{m.story}}</p>
            <hr class="border-secondary">
            <h5 class="text-info">Download Options:</h5>
            {% if m.type == 'movie' %}
                {% if m.files %}
                    {% for f in m.files %}
                    <a href="{{f.short_url}}" target="_blank" class="btn-neon d-inline-block mb-2 me-2">🚀 Download {{f.quality}}</a>
                    {% endfor %}
                {% else %}<p class="text-warning">Links not added yet.</p>{% endif %}
            {% else %}
                {% for s, eps in seasons.items() %}
                <div class="p-3 border border-info rounded mb-3">
                    <h6 class="text-info">Season {{s}}</h6>
                    {% for ep in eps %}
                    <div class="mb-2 text-white">Ep {{ep.episode}}: 
                        {% if ep.files %}{% for f in ep.files %}<a href="{{f.short_url}}" class="btn btn-sm btn-outline-info ms-1">{{f.quality}}</a>{% endfor %}
                        {% else %}<span class="text-muted small">No links</span>{% endif %}
                    </div>
                    {% endfor %}
                </div>
                {% endfor %}
            {% endif %}
        </div>
    </div>
    {% if m.trailer %}<div class="mt-5"><h4>Trailer</h4><div class="ratio ratio-16x9 rounded border border-info shadow-lg"><iframe src="{{m.trailer}}" allowfullscreen></iframe></div></div>{% endif %}
</div></body></html>"""

ADMIN_SIDEBAR = """
<div class="sidebar">
    <div class="sidebar-brand">
        <img src="{{config.SITE_LOGO}}" style="width:70px; height:70px; border-radius:50%; margin-bottom:10px; border:2px solid var(--neon);">
        <h6 class="text-white">{{config.SITE_NAME}}</h6>
    </div>
    <a href="/admin?tab=dashboard" class="{% if request.args.get('tab')=='dashboard' or not request.args.get('tab') %}active{% endif %}">📊 Dashboard</a>
    <a href="/admin?tab=add" class="{% if request.args.get('tab')=='add' %}active{% endif %}">➕ Add Content</a>
    <a href="/admin?tab=movies" class="{% if request.args.get('tab')=='movies' %}active{% endif %}">🎬 Movie List</a>
    <a href="/admin?tab=settings" class="{% if request.args.get('tab')=='settings' %}active{% endif %}">⚙️ Bot Settings</a>
    <a href="/" target="_blank">🌐 View Site</a>
    <a href="/logout" style="margin-top:20px; color:#ff4d4d;">🚪 Logout</a>
</div>
"""

ADMIN_DASHBOARD_HTML = f"<!DOCTYPE html><html><head><title>Admin Dashboard</title><link rel='stylesheet' href='https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css'>{COMMON_STYLE}</head><body>" + ADMIN_SIDEBAR + """
<div class="main-content">
    <h3>Welcome, Administrator</h3><hr>
    <div class="row">
        <div class="col-md-4">
            <div class="admin-card text-center bg-primary text-white">
                <h2>{{stats.users}}</h2><p>Total Bot Users</p>
            </div>
        </div>
        <div class="col-md-4">
            <div class="admin-card text-center bg-success text-white">
                <h2>{{stats.movies}}</h2><p>Total Movies/TV</p>
            </div>
        </div>
    </div>
</div></body></html>"""

ADMIN_ADD_HTML = f"<!DOCTYPE html><html><head><title>Add Content</title><link rel='stylesheet' href='https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css'><script src='https://code.jquery.com/jquery-3.6.0.min.js'></script>{COMMON_STYLE}</head><body>" + ADMIN_SIDEBAR + """
<div class="main-content">
    <h3>➕ Add New Movie/TV Show</h3><hr>
    <div class="row">
        <div class="col-md-6">
            <div class="admin-card position-relative">
                <h5>🔍 TMDb Search</h5>
                <div class="input-group mb-2">
                    <input id="tmdb_search_input" class="form-control" placeholder="Search by name...">
                    <button class="btn btn-primary" onclick="searchTMDB()">Search</button>
                </div>
                <div id="search_results_box" class="search-results" style="display:none;"></div>
                <hr>
                <h5>🔗 Fetch by ID</h5>
                <div class="input-group mb-3"><input id="url_in" class="form-control" placeholder="IMDb Link or TMDb ID..."><button class="btn btn-secondary" onclick="fetchData()">Fetch</button></div>
            </div>
        </div>
        <div class="col-md-6">
            <div class="admin-card">
                <form action="/admin/manual_add" method="POST">
                    <input id="f_title" name="title" class="form-control mb-2" placeholder="Title" required>
                    <input id="f_id" name="tmdb_id" class="form-control mb-2" placeholder="TMDB ID" required>
                    <select id="f_type" name="type" class="form-control mb-2">
                        <option value="movie">Movie</option><option value="tv">TV Series</option>
                    </select>
                    <select id="f_cat" name="category" class="form-control mb-2">
                        {% for cat in categories %}<option value="{{cat}}">{{cat}}</option>{% endfor %}
                    </select>
                    <input id="f_year" name="year" class="form-control mb-2" placeholder="Year">
                    <input id="f_rating" name="rating" class="form-control mb-2" placeholder="Rating">
                    <input id="f_poster" name="poster" class="form-control mb-2" placeholder="Poster URL">
                    <input id="f_trailer" name="trailer" class="form-control mb-2" placeholder="Trailer Link">
                    <textarea id="f_story" name="story" class="form-control mb-2" placeholder="Storyline" rows="3"></textarea>
                    <button class="btn btn-success w-100">Save Metadata</button>
                </form>
            </div>
        </div>
    </div>
</div>
<script>
function searchTMDB() {
    let q = $('#tmdb_search_input').val(); if(!q) return;
    $.post('/admin/search_tmdb', {query: q}, function(data) {
        let h = '';
        data.forEach(i => {
            if(i.media_type=='movie' || i.media_type=='tv') {
                h += `<div class="search-item" onclick="selectFromSearch('${i.media_type}', '${i.id}')"><b>[${i.media_type.toUpperCase()}]</b> ${i.title || i.name} (${(i.release_date || i.first_air_date || '').substring(0,4)})</div>`;
            }
        });
        $('#search_results_box').html(h).show();
    });
}
function selectFromSearch(t, id) { $('#f_type').val(t); $('#url_in').val(id); $('#search_results_box').hide(); fetchData(); }
function fetchData() {
    $.post('/admin/fetch_info', {url: $('#url_in').val(), type: $('#f_type').val()}, function(d) {
        if(d.error) return alert(d.error);
        $('#f_title').val(d.title); $('#f_id').val(d.tmdb_id); $('#f_year').val(d.year);
        $('#f_rating').val(d.rating); $('#f_poster').val(d.poster); $('#f_trailer').val(d.trailer);
        $('#f_story').val(d.story); $('#f_type').val(d.type); $('#f_cat').val(d.category);
    });
}
</script></body></html>"""

ADMIN_MOVIES_HTML = f"<!DOCTYPE html><html><head><title>Movie List</title><link rel='stylesheet' href='https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css'>{COMMON_STYLE}</head><body>" + ADMIN_SIDEBAR + """
<div class="main-content">
    <h3>🎬 Content Library</h3><hr>
    <div class="admin-card">
        <form class="d-flex mb-3"><input name="q" class="form-control me-2" placeholder="Search..." value="{{q}}"><button class="btn btn-info">Search</button></form>
        <table class="table table-hover">
            <thead><tr><th>Poster</th><th>Title</th><th>Category</th><th>Action</th></tr></thead>
            <tbody>
                {% for m in movies %}
                <tr>
                    <td><img src="{{m.poster}}" width="40" height="55" class="rounded"></td>
                    <td>{{m.title}} ({{m.year}})</td>
                    <td>{{m.category}}</td>
                    <td>
                        <a href="/admin/edit/{{m.tmdb_id}}" class="btn btn-sm btn-warning">Edit</a>
                        <a href="/delete/{{m.tmdb_id}}" class="btn btn-sm btn-danger" onclick="return confirm('Delete?')">Del</a>
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</div></body></html>"""

ADMIN_SETTINGS_HTML = f"<!DOCTYPE html><html><head><title>Settings</title><link rel='stylesheet' href='https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css'>{COMMON_STYLE}</head><body>" + ADMIN_SIDEBAR + """
<div class="main-content">
    <h3>⚙️ Portal & Bot Settings</h3><hr>
    <div class="admin-card">
        <form action="/save_config" method="POST">
            <div class="row">
                <div class="col-md-6 mb-3"><label>Site Name</label><input name="site_name" class="form-control" value="{{config.SITE_NAME}}"></div>
                <div class="col-md-6 mb-3"><label>Site Logo URL</label><input name="site_logo" class="form-control" value="{{config.SITE_LOGO}}"></div>
                <div class="col-md-6 mb-3"><label>Site URL (Without last /)</label><input name="site_url" class="form-control" value="{{config.SITE_URL}}"></div>
                <div class="col-md-6 mb-3"><label>Telegram Bot Token</label><input name="token" class="form-control" value="{{config.BOT_TOKEN}}"></div>
                <div class="col-md-6 mb-3"><label>TMDb API Key</label><input name="tmdb" class="form-control" value="{{config.TMDB_API_KEY}}"></div>
                <div class="col-md-6 mb-3"><label>Admin Telegram ID</label><input name="admin_id" class="form-control" value="{{config.ADMIN_ID}}"></div>
                <div class="col-md-6 mb-3"><label>Storage Channel ID</label><input name="channel_id" class="form-control" value="{{config.STORAGE_CHANNEL_ID}}"></div>
                <div class="col-md-6 mb-3"><label>Shortener Domain</label><input name="s_url" class="form-control" value="{{config.SHORTENER_URL}}" placeholder="api.gplinks.com"></div>
                <div class="col-md-6 mb-3"><label>Shortener API Key</label><input name="s_api" class="form-control" value="{{config.SHORTENER_API}}"></div>
                <div class="col-md-6 mb-3"><label>Auto Delete Time (Sec, 0 to disable)</label><input name="delete_time" type="number" class="form-control" value="{{config.AUTO_DELETE_TIME}}"></div>
                <div class="col-md-6 mb-3"><label>Protect Content (on/off)</label><input name="protect" class="form-control" value="{{config.PROTECT_CONTENT}}"></div>
            </div>
            <button class="btn btn-primary w-100 mt-2">💾 Save Configuration</button>
        </form>
    </div>
</div></body></html>"""

EDIT_HTML = f"<!DOCTYPE html><html><head><title>Edit Content</title><link rel='stylesheet' href='https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css'>{COMMON_STYLE}</head><body>" + ADMIN_SIDEBAR + """
<div class="main-content">
    <div class="row">
        <div class="col-md-6">
            <div class="admin-card">
                <h5>✏️ Edit: {{m.title}}</h5><hr>
                <form action="/admin/update" method="POST">
                    <input type="hidden" name="tmdb_id" value="{{m.tmdb_id}}">
                    <label>Title</label><input name="title" class="form-control mb-2" value="{{m.title}}">
                    <label>Category</label>
                    <select name="category" class="form-control mb-2">
                        {% for cat in categories %}<option value="{{cat}}" {% if m.category == cat %}selected{% endif %}>{{cat}}</option>{% endfor %}
                    </select>
                    <label>Year</label><input name="year" class="form-control mb-2" value="{{m.year}}">
                    <label>Rating</label><input name="rating" class="form-control mb-2" value="{{m.rating}}">
                    <label>Poster</label><input name="poster" class="form-control mb-2" value="{{m.poster}}">
                    <label>Trailer</label><input name="trailer" class="form-control mb-2" value="{{m.trailer}}">
                    <label>Storyline</label><textarea name="story" class="form-control mb-3" rows="4">{{m.story}}</textarea>
                    <button class="btn btn-success w-100">Update Metadata</button>
                </form>
            </div>
        </div>
        <div class="col-md-6">
            <div class="admin-card">
                <h5>➕ Add Link (Message ID)</h5><hr>
                <form action="/admin/add_file" method="POST" class="mb-4">
                    <input type="hidden" name="tmdb_id" value="{{m.tmdb_id}}">
                    <input name="quality" class="form-control mb-2" placeholder="e.g. 720p Bangla" required>
                    <input name="file_id" class="form-control mb-2" placeholder="Telegram Msg ID" required>
                    <button class="btn btn-info w-100">Add Link</button>
                </form>
                <h6>Current Links:</h6>
                <ul class="list-group">
                    {% if m.files %}{% for f in m.files %}
                    <li class="list-group-item d-flex justify-content-between">
                        {{f.quality}} (ID: {{f.file_id}})
                        <a href="/admin/delete_file/{{m.tmdb_id}}/{{f.file_id}}" class="btn btn-sm btn-danger">X</a>
                    </li>
                    {% endfor %}{% else %}<li class="list-group-item text-muted">No links.</li>{% endif %}
                </ul>
            </div>
        </div>
    </div>
</div></body></html>"""

LOGIN_HTML = """<!DOCTYPE html><html><head><title>Admin Login</title><link rel='stylesheet' href='https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css'></head><body class='bg-dark d-flex align-items-center' style='height:100vh;'>
<div class='card p-4 mx-auto shadow-lg' style='width:340px;'><h4 class='text-center'>ADMIN LOGIN</h4><hr>
<form method='POST'><input name='u' class='form-control mb-2' placeholder='User'><input name='p' type='password' class='form-control mb-3' placeholder='Pass'><button class='btn btn-primary w-100'>Login</button></form>
</div></body></html>"""

# ================== রান করার অংশ ==================

if __name__ == '__main__':
    threading.Thread(target=init_bot_service, daemon=True).start()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
