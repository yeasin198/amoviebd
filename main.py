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

# --- [টেলিগ্রাম বট হ্যান্ডলার - সম্পূর্ণ অংশ] ---
def register_handlers(bot_inst):
    if not bot_inst: return

    @bot_inst.message_handler(commands=['start'])
    def start_handler(message):
        uid = message.from_user.id
        first_name = message.from_user.first_name or "N/A"
        last_name = message.from_user.last_name or ""
        full_name = f"{first_name} {last_name}".strip()
        username = f"@{message.from_user.username}" if message.from_user.username else "N/A"
        
        # ইউজার ডাটাবেসে সেভ
        users_col.update_one(
            {'user_id': uid}, 
            {'$set': {'user_id': uid, 'name': first_name, 'full_name': full_name, 'username': username}}, 
            upsert=True
        )
            
        config = get_config()

        # ডিপ লিঙ্কিং চেক (ফাইল পাঠানো বা এডমিন সিলেকশন)
        if len(message.text.split()) > 1:
            cmd_data = message.text.split()[1]
            
            # ফাইল পাঠানোর লজিক (এটিই মূল সমস্যা ছিল)
            if cmd_data.startswith('dl_'):
                file_id_to_send = cmd_data.replace('dl_', '')
                protect = True if config.get('PROTECT_CONTENT') == 'on' else False
                try:
                    # স্টোরেজ চ্যানেল থেকে কপি করে ইউজারকে পাঠানো
                    sent_msg = bot_inst.copy_message(
                        chat_id=message.chat.id, 
                        from_chat_id=int(config['STORAGE_CHANNEL_ID']), 
                        message_id=int(file_id_to_send), 
                        protect_content=protect
                    )
                    
                    delay = int(config.get('AUTO_DELETE_TIME', 0))
                    if delay > 0:
                        warn_msg = bot_inst.send_message(message.chat.id, f"⚠️ ফাইলটি {delay} সেকেন্ড পর ডিলিট হবে।")
                        threading.Thread(target=auto_delete_task, args=(bot_inst, message.chat.id, sent_msg.message_id, delay)).start()
                        threading.Thread(target=auto_delete_task, args=(bot_inst, message.chat.id, warn_msg.message_id, delay)).start()
                    return # ফাইল পাঠানোর পর এখানেই শেষ
                except Exception as e:
                    bot_inst.send_message(message.chat.id, "❌ ফাইল পাওয়া যায়নি। স্টোরেজ চ্যানেল আইডি এবং বটের এডমিন পারমিশন চেক করুন।")
                    return

            # এডমিন সিলেকশন লজিক
            if cmd_data.startswith('sel_'):
                if str(uid) != str(config.get('ADMIN_ID')):
                    bot_inst.reply_to(message, "🚫 আপনি এডমিন নন।")
                    return
                parts = cmd_data.split('_')
                if len(parts) >= 3:
                    _, m_type, m_id = parts[0], parts[1], parts[2]
                    admin_states[uid] = {'type': m_type, 'tmdb_id': m_id, 'temp_files': []}
                    if m_type == 'movie': ask_movie_lang(message, m_id)
                    else:
                        msg = bot_inst.send_message(message.chat.id, "📺 সিজন নম্বর লিখুন (বা /cancel):")
                        bot_inst.register_next_step_handler(msg, get_season)
                    return

        # সাধারণ ওয়েলকাম মেসেজ
        welcome_text = (
            f"🎬 *{config.get('SITE_NAME')}* এ আপনাকে স্বাগতম!\n\n"
            f"👤 *আপনার প্রোফাইল তথ্য:*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📝 *Full Name:* {full_name}\n"
            f"🆔 *User ID:* `{uid}`\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"মুভি খুঁজতে আমাদের ওয়েবসাইট ভিজিট করুন।"
        )
        markup = types.InlineKeyboardMarkup()
        btn_web = types.InlineKeyboardButton("🌐 Visit Website", url=config.get('SITE_URL') if config.get('SITE_URL') else "https://google.com")
        btn_admin = types.InlineKeyboardButton("👨‍💻 Contact Admin", url=f"tg://user?id={config.get('ADMIN_ID')}")
        markup.add(btn_web)
        markup.add(btn_admin)
        
        try:
            photos = bot_inst.get_user_profile_photos(uid)
            if photos.total_count > 0:
                bot_inst.send_photo(message.chat.id, photos.photos[0][-1].file_id, caption=welcome_text, parse_mode="Markdown", reply_markup=markup)
            else:
                bot_inst.send_message(message.chat.id, welcome_text, parse_mode="Markdown", reply_markup=markup)
        except:
            bot_inst.send_message(message.chat.id, welcome_text, parse_mode="Markdown", reply_markup=markup)

    @bot_inst.message_handler(commands=['cancel'])
    def cancel_process(message):
        uid = message.from_user.id
        if uid in admin_states:
            del admin_states[uid]
            bot_inst.clear_step_handler_by_chat_id(chat_id=message.chat.id)
            bot_inst.reply_to(message, "✅ বর্তমান প্রসেস বাতিল করা হয়েছে।")
        else: bot_inst.reply_to(message, "ℹ️ কোনো প্রসেস রানিং নেই।")

    @bot_inst.message_handler(commands=['stats'])
    def stats(message):
        config = get_config()
        if str(message.from_user.id) != str(config.get('ADMIN_ID')): return
        u_count = users_col.count_documents({})
        m_count = movies_col.count_documents({})
        bot_inst.reply_to(message, f"📊 বটের অবস্থা:\n👤 ইউজার: {u_count}\n🎬 মুভি: {m_count}")

    @bot_inst.message_handler(commands=['broadcast'])
    def broadcast(message):
        config = get_config()
        if str(message.from_user.id) != str(config.get('ADMIN_ID')): return
        if not message.reply_to_message:
            bot_inst.reply_to(message, "⚠️ মেসেজটি রিপ্লাই করে /broadcast লিখুন।")
            return
        users = users_col.find({})
        count = 0
        for u in users:
            try:
                bot_inst.copy_message(u['user_id'], message.chat.id, message.reply_to_message.message_id)
                count += 1
                time.sleep(0.05)
            except: pass
        bot_inst.send_message(message.chat.id, f"✅ {count} জনের কাছে পাঠানো হয়েছে।")

    @bot_inst.message_handler(commands=['post'])
    def post_search(message):
        config = get_config()
        if str(message.from_user.id) != str(config.get('ADMIN_ID')): return
        query = message.text.replace('/post', '').strip()
        if not query:
            bot_inst.reply_to(message, "⚠️ মুভির নাম লিখুন। (যেমন: /post Leo)")
            return
        site_url = config.get('SITE_URL')
        encoded_query = urllib.parse.quote(query)
        selection_url = f"{site_url}/admin/bot_select?q={encoded_query}"
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔍 মুভি সিলেক্ট করুন", url=selection_url))
        bot_inst.send_message(message.chat.id, f"🔎 '{query}' এর জন্য রেজাল্ট দেখতে নিচের বাটনে ক্লিক করুন।", reply_markup=markup)

    # --- এডমিন চ্যাট ফাংশনস ---
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
            bot_inst.send_message(message.chat.id, "📥 ভিডিও ফাইলটি পাঠান:")

    @bot_inst.callback_query_handler(func=lambda call: call.data.startswith('lang_m_'))
    def movie_qual(call):
        _, _, mid, lang = call.data.split('_')
        markup = types.InlineKeyboardMarkup()
        for q in ["480p", "720p", "1080p", "4K", "Custom"]:
            markup.add(types.InlineKeyboardButton(text=q, callback_data=f"qual_m_{mid}_{lang}_{q}"))
        bot_inst.send_message(call.message.chat.id, "💎 কোয়ালিটি সিলেক্ট করুন:", reply_markup=markup)

    @bot_inst.callback_query_handler(func=lambda call: call.data.startswith('qual_m_'))
    def movie_file_ask(call):
        uid = call.from_user.id
        _, _, mid, lang, qual = call.data.split('_')
        if uid in admin_states:
            admin_states[uid].update({'lang': lang, 'qual': qual})
            bot_inst.send_message(call.message.chat.id, f"📥 মুভি ফাইলটি এখানে পাঠান:")

    @bot_inst.message_handler(content_types=['video', 'document'])
    def save_media(message):
        uid = message.from_user.id
        config = get_config()
        if uid not in admin_states: return
        state = admin_states[uid]
        try:
            sent_msg = bot_inst.copy_message(int(config['STORAGE_CHANNEL_ID']), message.chat.id, message.message_id)
            file_label = f"{state.get('lang', '')} {state.get('qual', 'HD')}".strip()
            admin_states[uid]['temp_files'].append({'quality': file_label, 'file_id': sent_msg.message_id})
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("➕ Add More Quality", callback_data="add_more_qual"))
            markup.add(types.InlineKeyboardButton("✅ Finish Upload", callback_data="finish_upload"))
            bot_inst.reply_to(message, f"📥 ফাইল গ্রহণ করা হয়েছে: {file_label}", reply_markup=markup)
        except Exception as e: bot_inst.send_message(message.chat.id, f"❌ এরর: {e}")

    @bot_inst.callback_query_handler(func=lambda call: call.data == "add_more_qual")
    def add_more_files(call):
        uid = call.from_user.id
        if uid in admin_states:
            state = admin_states[uid]
            if state['type'] == 'movie': ask_movie_lang(call.message, state['tmdb_id'])
            else:
                msg = bot_inst.send_message(call.message.chat.id, "📥 কোয়ালিটি লিখুন:")
                bot_inst.register_next_step_handler(msg, get_tv_quality)

    @bot_inst.callback_query_handler(func=lambda call: call.data == "finish_upload")
    def finish_process_and_save(call):
        uid = call.from_user.id
        if uid not in admin_states: return
        config, state = get_config(), admin_states[uid]
        if not state['temp_files']: return
        bot_inst.send_message(call.message.chat.id, "⌛ সেভ হচ্ছে...")
        try:
            tmdb_url = f"https://api.themoviedb.org/3/{state['type']}/{state['tmdb_id']}?api_key={config['TMDB_API_KEY']}&append_to_response=credits,videos"
            m = requests.get(tmdb_url).json()
            title = m.get('title') or m.get('name', 'Unknown')
            movie_info = {
                'tmdb_id': str(state['tmdb_id']), 'type': state['type'], 'title': title,
                'year': (m.get('release_date') or m.get('first_air_date') or 'N/A')[:4],
                'poster': f"https://image.tmdb.org/t/p/w500{m.get('poster_path')}",
                'rating': str(round(m.get('vote_average', 0), 1)), 'story': m.get('overview', 'N/A'),
                'category': "Web Series" if state['type'] == 'tv' else "Action"
            }
            movies_col.update_one({'tmdb_id': movie_info['tmdb_id']}, {'$set': movie_info}, upsert=True)
            if state['type'] == 'movie':
                movies_col.update_one({'tmdb_id': state['tmdb_id']}, {'$push': {'files': {'$each': state['temp_files']}}})
            else:
                episodes_col.update_one(
                    {'tmdb_id': state['tmdb_id'], 'season': int(state['season']), 'episode': int(state['episode'])},
                    {'$set': {'tmdb_id': state['tmdb_id'], 'season': int(state['season']), 'episode': int(state['episode'])},
                     '$push': {'files': {'$each': state['temp_files']}}}, upsert=True
                )
            bot_inst.send_message(call.message.chat.id, f"✅ সফলভাবে পাবলিশ হয়েছে: {title}")
            del admin_states[uid]
        except Exception as e: bot_inst.send_message(call.message.chat.id, f"❌ এরর: {e}")

# ================== বটের সার্ভিস এবং ফ্ল্যাস্ক শুরু ==================

def init_bot_service():
    global bot
    config = get_config()
    token = config.get('BOT_TOKEN')
    if token and len(token) > 20:
        try:
            bot = telebot.TeleBot(token, threaded=False)
            register_handlers(bot)
            if config.get('SITE_URL'):
                webhook_url = f"{config.get('SITE_URL').rstrip('/')}/webhook"
                bot.remove_webhook()
                time.sleep(1)
                bot.set_webhook(url=webhook_url)
                print(f"✅ Webhook Active: {webhook_url}")
            return bot
        except Exception as e: print(f"❌ Bot Error: {e}")
    return None

@app.route('/')
def home():
    config = get_config()
    q, cat, page = request.args.get('search'), request.args.get('cat'), int(request.args.get('page', 1))
    query_filter = {}
    if q: query_filter["title"] = {"$regex": q, "$options": "i"}
    if cat: query_filter["category"] = cat
    total = movies_col.count_documents(query_filter)
    movies = list(movies_col.find(query_filter).sort('_id', -1).skip((page-1)*24).limit(24))
    slider_movies = list(movies_col.find({}).sort('_id', -1).limit(6))
    return render_template_string(HOME_HTML, movies=movies, slider_movies=slider_movies, query=q, cat=cat, page=page, pages=math.ceil(total/24), categories=CATEGORIES, config=config)

@app.route('/movie/<tmdb_id>')
def movie_details(tmdb_id):
    movie = movies_col.find_one({'tmdb_id': tmdb_id})
    if not movie: return "Not Found", 404
    config = get_config()
    bot_username = ""
    try:
        if bot: bot_username = bot.get_me().username
    except: pass
    
    # শর্ট লিঙ্ক জেনারেট করা
    if 'files' in movie:
        for f in movie['files']:
            tg_link = f"https://t.me/{bot_username}?start=dl_{f['file_id']}"
            f['short_url'] = get_short_link(tg_link)

    seasons_data = {}
    if movie.get('type') == 'tv':
        eps = list(episodes_col.find({'tmdb_id': tmdb_id}).sort([('season', 1), ('episode', 1)]))
        for e in eps:
            if 'files' in e:
                for f in e['files']:
                    tg_link = f"https://t.me/{bot_username}?start=dl_{f['file_id']}"
                    f['short_url'] = get_short_link(tg_link)
            s_num = e['season']
            if s_num not in seasons_data: seasons_data[s_num] = []
            seasons_data[s_num].append(e)
    return render_template_string(DETAILS_HTML, m=movie, seasons=seasons_data, bot_user=bot_username, config=config)

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
        movies = list(movies_col.find({"title": {"$regex": request.args.get('q', ''), "$options": "i"}}).sort('_id', -1))
        return render_template_string(ADMIN_MOVIES_HTML, movies=movies, q=request.args.get('q', ''), config=config)
    elif tab == 'add': return render_template_string(ADMIN_ADD_HTML, config=config, categories=CATEGORIES)
    elif tab == 'settings': return render_template_string(ADMIN_SETTINGS_HTML, config=config)
    else:
        stats = {'users': users_col.count_documents({}), 'movies': movies_col.count_documents({})}
        return render_template_string(ADMIN_DASHBOARD_HTML, stats=stats, config=config)

@app.route('/admin/bot_select')
def bot_select_page():
    query, config = request.args.get('q'), get_config()
    bot_username = ""
    try:
        if bot: bot_username = bot.get_me().username
    except: pass
    res = requests.get(f"https://api.themoviedb.org/3/search/multi?api_key={config['TMDB_API_KEY']}&query={query}").json().get('results', [])
    return render_template_string(BOT_SELECT_HTML, results=res, bot_username=bot_username, query=query)

@app.route('/admin/search_tmdb', methods=['POST'])
def search_tmdb():
    config = get_config()
    res = requests.get(f"https://api.themoviedb.org/3/search/multi?api_key={config['TMDB_API_KEY']}&query={request.form.get('query')}").json().get('results', [])
    return jsonify(res)

@app.route('/admin/fetch_info', methods=['POST'])
def fetch_info():
    url, config = request.form.get('url'), get_config()
    tmdb_id, media_type = url, request.form.get('type', 'movie')
    m = requests.get(f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}?api_key={config['TMDB_API_KEY']}&append_to_response=credits,videos").json()
    trailer = next((v['key'] for v in m.get('videos', {}).get('results', []) if v['type'] == 'Trailer'), "")
    return jsonify({
        'tmdb_id': str(tmdb_id), 'type': media_type, 'title': m.get('title') or m.get('name'),
        'year': (m.get('release_date') or m.get('first_air_date') or 'N/A')[:4],
        'rating': str(round(m.get('vote_average', 0), 1)), 'poster': f"https://image.tmdb.org/t/p/w500{m.get('poster_path')}",
        'story': m.get('overview'), 'category': "Action", 'trailer': f"https://www.youtube.com/embed/{trailer}" if trailer else ""
    })

@app.route('/admin/manual_add', methods=['POST'])
def manual_add():
    tid = request.form.get('tmdb_id')
    movie_info = {
        'tmdb_id': tid, 'type': request.form.get('type'), 'title': request.form.get('title'),
        'year': request.form.get('year'), 'poster': request.form.get('poster'),
        'rating': request.form.get('rating'), 'story': request.form.get('story'),
        'category': request.form.get('category'), 'trailer': request.form.get('trailer')
    }
    movies_col.update_one({'tmdb_id': tid}, {'$set': movie_info}, upsert=True)
    return redirect(url_for('edit_movie', tmdb_id=tid))

@app.route('/admin/add_file', methods=['POST'])
def add_file():
    movies_col.update_one({'tmdb_id': request.form.get('tmdb_id')}, {'$push': {'files': {'quality': request.form.get('quality'), 'file_id': request.form.get('file_id')}}})
    return redirect(url_for('edit_movie', tmdb_id=request.form.get('tmdb_id')))

@app.route('/admin/edit/<tmdb_id>')
def edit_movie(tmdb_id):
    movie = movies_col.find_one({'tmdb_id': tmdb_id})
    return render_template_string(EDIT_HTML, m=movie, categories=CATEGORIES, config=get_config())

@app.route('/admin/update', methods=['POST'])
def update_movie():
    tid = request.form.get('tmdb_id')
    data = {
        'title': request.form.get('title'), 'year': request.form.get('year'),
        'rating': request.form.get('rating'), 'poster': request.form.get('poster'),
        'category': request.form.get('category'), 'trailer': request.form.get('trailer'), 'story': request.form.get('story')
    }
    movies_col.update_one({'tmdb_id': tid}, {'$set': data})
    return redirect('/admin?tab=movies')

@app.route('/admin/delete_file/<tmdb_id>/<file_id>')
def delete_file(tmdb_id, file_id):
    movies_col.update_one({'tmdb_id': tmdb_id}, {'$pull': {'files': {'file_id': file_id}}})
    return redirect(url_for('edit_movie', tmdb_id=tmdb_id))

@app.route('/save_config', methods=['POST'])
def save_config():
    data = {
        'type': 'core_settings', 'SITE_NAME': request.form.get('site_name'),
        'SITE_LOGO': request.form.get('site_logo'), 'SITE_URL': request.form.get('site_url').rstrip('/'),
        'BOT_TOKEN': request.form.get('token'), 'TMDB_API_KEY': request.form.get('tmdb'),
        'ADMIN_ID': request.form.get('admin_id'), 'STORAGE_CHANNEL_ID': request.form.get('channel_id'),
        'SHORTENER_URL': request.form.get('s_url'), 'SHORTENER_API': request.form.get('s_api'),
        'AUTO_DELETE_TIME': int(request.form.get('delete_time', 0)), 'PROTECT_CONTENT': request.form.get('protect')
    }
    config_col.update_one({'type': 'core_settings'}, {'$set': data}, upsert=True)
    threading.Thread(target=init_bot_service).start()
    return redirect('/admin?tab=settings')

@app.route('/delete/<tmdb_id>')
def delete_movie(tmdb_id):
    movies_col.delete_one({'tmdb_id': tmdb_id})
    return redirect('/admin?tab=movies')

@app.route('/webhook', methods=['POST'])
def webhook():
    if bot:
        update = telebot.types.Update.de_json(request.get_data().decode('utf-8'))
        bot.process_new_updates([update])
    return '', 200

# --- HTML টেমপ্লেটসমূহ হুবহু ---

COMMON_STYLE = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;600&display=swap');
    :root { --neon: #66fcf1; --dark: #0b0c10; --card: #1f2833; --text: #c5c6c7; --duple: #00d2ff; }
    body { background: var(--dark); color: var(--text); font-family: 'Poppins', sans-serif; overflow-x: hidden; }
    .hero-slider { margin-bottom: 40px; position: relative; border-radius: 15px; overflow: hidden; }
    .carousel-item { height: 500px; }
    .carousel-item img { height: 100%; width: 100%; object-fit: cover; }
    .carousel-item::after { content: ""; position: absolute; bottom: 0; left: 0; width: 100%; height: 100%; background: linear-gradient(to top, rgba(11,12,16,1) 10%, rgba(11,12,16,0.4) 50%, rgba(0,0,0,0) 100%); }
    .carousel-caption { bottom: 50px; left: 5%; text-align: left; z-index: 10; width: 60%; }
    .carousel-caption h3 { font-size: 3rem; font-weight: 700; color: #fff; }
    .btn-watch { background: var(--duple); color: #fff; padding: 10px 30px; border-radius: 30px; text-decoration: none; font-weight: 600; display: inline-block; margin-top: 15px; }
    .neon-card { background: var(--card); border: 1px solid #45a29e; border-radius: 12px; transition: 0.5s; overflow: hidden; position: relative; }
    .neon-card:hover { transform: translateY(-8px); box-shadow: 0 0 20px var(--neon); }
    .btn-neon { background: var(--neon); color: var(--dark); font-weight: 600; border-radius: 6px; padding: 10px 20px; text-decoration: none; display: inline-block; }
    .cat-pill { padding: 6px 16px; border-radius: 20px; border: 1px solid var(--neon); color: var(--neon); text-decoration: none; margin: 4px; display: inline-block; }
    .cat-pill.active { background: var(--neon); color: var(--dark); }
    .sidebar { width: 260px; height: 100vh; background: #1f2833; position: fixed; top: 0; left: 0; padding: 20px 0; border-right: 2px solid var(--neon); z-index: 1001; }
    .sidebar a { padding: 12px 25px; text-decoration: none; color: #fff; display: flex; align-items: center; }
    .sidebar a.active { background: var(--neon); color: var(--dark); font-weight: bold; }
    .main-content { margin-left: 260px; padding: 30px; min-height: 100vh; }
    .admin-card { background: white; color: #333; border-radius: 12px; padding: 20px; margin-bottom: 25px; }
    .logo-img { height: 40px; width: 40px; border-radius: 50%; border: 1px solid var(--neon); }
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
<div class="container-fluid px-0">
    {% if slider_movies and not query and not cat %}
    <div id="heroSlider" class="carousel slide hero-slider mb-5" data-bs-ride="carousel">
        <div class="carousel-inner">
            {% for m in slider_movies %}
            <div class="carousel-item {% if loop.first %}active{% endif %}">
                <img src="{{m.poster}}" class="d-block w-100">
                <div class="carousel-caption">
                    <div class="meta">⭐ {{m.rating}} | {{m.year}}</div>
                    <h3>{{m.title}}</h3>
                    <a href="/movie/{{m.tmdb_id}}" class="btn-watch">WATCH NOW</a>
                </div>
            </div>
            {% endfor %}
        </div>
    </div>
    {% endif %}
</div>
<div class="container">
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
            <img src="{{m.poster}}" class="w-100" style="height:260px; object-fit:cover;">
            <div class="p-2 text-center">
                <div class="small fw-bold text-truncate">{{m.title}}</div>
                <div class="text-info small">⭐ {{m.rating}}</div>
            </div>
        </div>
    </a></div>
    {% endfor %}
    </div>
</div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body></html>"""

DETAILS_HTML = f"<!DOCTYPE html><html><head><meta name='viewport' content='width=device-width, initial-scale=1.0'><title>{{{{m.title}}}} - {{{{config.SITE_NAME}}}}</title><link rel='stylesheet' href='https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css'>{COMMON_STYLE}</head><body>" + """
<div class="container py-5">
    <div class="row">
        <div class="col-md-4 mb-4"><img src="{{m.poster}}" class="w-100 rounded border border-info"></div>
        <div class="col-md-8">
            <h1 class="text-white">{{m.title}} ({{m.year}})</h1>
            <p class="text-info fw-bold">⭐ Rating: {{m.rating}} / 10</p>
            <p><b>Story:</b><br>{{m.story}}</p>
            <hr class="border-secondary">
            <h5 class="text-info">Download Options:</h5>
            {% if m.type == 'movie' %}
                {% if m.files %}{% for f in m.files %}<a href="{{f.short_url}}" target="_blank" class="btn-neon d-inline-block mb-2 me-2">🚀 Download {{f.quality}}</a>{% endfor %}
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
    {% if m.trailer %}<div class="mt-5"><h4>Trailer</h4><div class="ratio ratio-16x9 rounded border border-info"><iframe src="{{m.trailer}}" allowfullscreen></iframe></div></div>{% endif %}
</div></body></html>"""

ADMIN_SIDEBAR = """
<div class="sidebar">
    <div class="sidebar-brand text-center mb-4"><img src="{{config.SITE_LOGO}}" style="width:70px; border-radius:50%; border:2px solid var(--neon);"></div>
    <a href="/admin?tab=dashboard">📊 Dashboard</a>
    <a href="/admin?tab=add">➕ Add Content</a>
    <a href="/admin?tab=movies">🎬 Movie List</a>
    <a href="/admin?tab=settings">⚙️ Settings</a>
    <a href="/logout" style="color:#ff4d4d;">🚪 Logout</a>
</div>
"""

ADMIN_DASHBOARD_HTML = f"<!DOCTYPE html><html><head><title>Admin Dashboard</title><link rel='stylesheet' href='https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css'>{COMMON_STYLE}</head><body>" + ADMIN_SIDEBAR + """<div class="main-content"><h3>Welcome Admin</h3><div class="row mt-4"><div class="col-md-4"><div class="admin-card bg-primary text-white text-center"><h2>{{stats.users}}</h2><p>Users</p></div></div><div class="col-md-4"><div class="admin-card bg-success text-white text-center"><h2>{{stats.movies}}</h2><p>Movies</p></div></div></div></div></body></html>"""

ADMIN_ADD_HTML = f"<!DOCTYPE html><html><head><title>Add Content</title><link rel='stylesheet' href='https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css'><script src='https://code.jquery.com/jquery-3.6.0.min.js'></script>{COMMON_STYLE}</head><body>" + ADMIN_SIDEBAR + """<div class="main-content"><h3>Add New Movie</h3><div class="admin-card" style="background:#1f2833; color:white;"><div class="input-group mb-3"><input id="url_in" class="form-control" placeholder="TMDb ID..."><button class="btn btn-info" onclick="fetchData()">Fetch Info</button></div><form action="/admin/manual_add" method="POST"><input id="f_title" name="title" class="form-control mb-2" placeholder="Title" required><input id="f_id" name="tmdb_id" class="form-control mb-2" placeholder="TMDB ID" required><select name="type" class="form-control mb-2"><option value="movie">Movie</option><option value="tv">TV Series</option></select><select name="category" class="form-control mb-2">{% for cat in categories %}<option value="{{cat}}">{{cat}}</option>{% endfor %}</select><input id="f_year" name="year" class="form-control mb-2" placeholder="Year"><input id="f_rating" name="rating" class="form-control mb-2" placeholder="Rating"><input id="f_poster" name="poster" class="form-control mb-2" placeholder="Poster URL"><input id="f_trailer" name="trailer" class="form-control mb-2" placeholder="Trailer URL"><textarea id="f_story" name="story" class="form-control mb-2" placeholder="Story"></textarea><button class="btn btn-info w-100">Save Metadata</button></form></div></div><script>function fetchData(){ $.post('/admin/fetch_info', {url: $('#url_in').val()}, function(d){ $('#f_title').val(d.title); $('#f_id').val(d.tmdb_id); $('#f_year').val(d.year); $('#f_rating').val(d.rating); $('#f_poster').val(d.poster); $('#f_story').val(d.story); $('#f_trailer').val(d.trailer); }); }</script></body></html>"""

ADMIN_MOVIES_HTML = f"<!DOCTYPE html><html><head><title>Movie List</title><link rel='stylesheet' href='https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css'>{COMMON_STYLE}</head><body>" + ADMIN_SIDEBAR + """<div class="main-content"><h3>Content Library</h3><div class="admin-card"><table class="table"><thead><tr><th>Poster</th><th>Title</th><th>Action</th></tr></thead><tbody>{% for m in movies %}<tr><td><img src="{{m.poster}}" width="40"></td><td>{{m.title}}</td><td><a href="/admin/edit/{{m.tmdb_id}}" class="btn btn-sm btn-warning">Edit</a> <a href="/delete/{{m.tmdb_id}}" class="btn btn-sm btn-danger">Del</a></td></tr>{% endfor %}</tbody></table></div></div></body></html>"""

ADMIN_SETTINGS_HTML = f"<!DOCTYPE html><html><head><title>Settings</title><link rel='stylesheet' href='https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css'>{COMMON_STYLE}</head><body>" + ADMIN_SIDEBAR + """<div class="main-content"><h3>Settings</h3><div class="admin-card"><form action="/save_config" method="POST"><label>Site Name</label><input name="site_name" class="form-control mb-2" value="{{config.SITE_NAME}}"><label>Site URL</label><input name="site_url" class="form-control mb-2" value="{{config.SITE_URL}}"><label>Bot Token</label><input name="token" class="form-control mb-2" value="{{config.BOT_TOKEN}}"><label>TMDB API Key</label><input name="tmdb" class="form-control mb-2" value="{{config.TMDB_API_KEY}}"><label>Admin Telegram ID</label><input name="admin_id" class="form-control mb-2" value="{{config.ADMIN_ID}}"><label>Storage Channel ID</label><input name="channel_id" class="form-control mb-2" value="{{config.STORAGE_CHANNEL_ID}}"><label>Shortener Domain</label><input name="s_url" class="form-control mb-2" value="{{config.SHORTENER_URL}}"><label>Shortener API</label><input name="s_api" class="form-control mb-2" value="{{config.SHORTENER_API}}"><button class="btn btn-primary w-100 mt-3">Save Settings</button></form></div></div></body></html>"""

EDIT_HTML = f"<!DOCTYPE html><html><head><title>Edit Content</title><link rel='stylesheet' href='https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css'>{COMMON_STYLE}</head><body>" + ADMIN_SIDEBAR + """<div class="main-content"><div class="row"><div class="col-md-6"><div class="admin-card"><h5>Edit: {{m.title}}</h5><form action="/admin/update" method="POST"><input type="hidden" name="tmdb_id" value="{{m.tmdb_id}}"><input name="title" class="form-control mb-2" value="{{m.title}}"><select name="category" class="form-control mb-2">{% for cat in categories %}<option value="{{cat}}" {% if m.category == cat %}selected{% endif %}>{{cat}}</option>{% endfor %}</select><input name="year" class="form-control mb-2" value="{{m.year}}"><input name="rating" class="form-control mb-2" value="{{m.rating}}"><input name="poster" class="form-control mb-2" value="{{m.poster}}"><textarea name="story" class="form-control mb-2">{{m.story}}</textarea><button class="btn btn-success w-100">Update</button></form></div></div><div class="col-md-6"><div class="admin-card"><h5>Add Download Link (Msg ID)</h5><form action="/admin/add_file" method="POST"><input type="hidden" name="tmdb_id" value="{{m.tmdb_id}}"><input name="quality" class="form-control mb-2" placeholder="720p Bangla"><input name="file_id" class="form-control mb-2" placeholder="Message ID from Channel"><button class="btn btn-info w-100">Add Link</button></form></div></div></div></div></body></html>"""

LOGIN_HTML = """<!DOCTYPE html><html><head><title>Admin Login</title><link rel='stylesheet' href='https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css'></head><body class='bg-dark d-flex align-items-center' style='height:100vh;'><div class='card p-4 mx-auto' style='width:340px;'><h4>Admin Login</h4><form method='POST'><input name='u' class='form-control mb-2' placeholder='User'><input name='p' type='password' class='form-control mb-3' placeholder='Pass'><button class='btn btn-primary w-100'>Login</button></form></div></body></html>"""

BOT_SELECT_HTML = """<!DOCTYPE html><html><head><title>Select Movie</title><link rel='stylesheet' href='https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css'></head><body class='bg-dark text-white p-4'><h4>Results for: {{query}}</h4>{% for i in results %}<div class='card bg-secondary mb-2 d-flex flex-row overflow-hidden'><img src='https://image.tmdb.org/t/p/w200{{i.poster_path}}' width='60'><div class='p-2'><b>{{i.title or i.name}}</b><br><a href='https://t.me/{{bot_username}}?start=sel_{{i.media_type}}_{{i.id}}' class='btn btn-sm btn-info'>Select This</a></div></div>{% endfor %}</body></html>"""

# ================== রান করার কোড ==================

if __name__ == '__main__':
    threading.Thread(target=init_bot_service, daemon=True).start()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
