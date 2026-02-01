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

# --- [টেলিগ্রাম বট হ্যান্ডলার - FIXED] ---
def register_handlers(bot_inst):
    if not bot_inst: return

    @bot_inst.message_handler(commands=['start'])
    def start(message):
        uid = message.from_user.id
        first_name = message.from_user.first_name or "N/A"
        last_name = message.from_user.last_name or ""
        full_name = f"{first_name} {last_name}".strip()
        username = f"@{message.from_user.username}" if message.from_user.username else "N/A"
        
        # ডাটাবেসে ইউজার সেভ/আপডেট করা
        users_col.update_one(
            {'user_id': uid}, 
            {'$set': {'user_id': uid, 'name': first_name, 'full_name': full_name, 'username': username}}, 
            upsert=True
        )
            
        config = get_config()

        # ডিপ লিঙ্কিং লজিক
        if len(message.text.split()) > 1:
            cmd_data = message.text.split()[1]
            
            # মুভি সিলেকশন (শুধুমাত্র এডমিন)
            if cmd_data.startswith('sel_'):
                if str(uid) != str(config.get('ADMIN_ID')):
                    bot_inst.reply_to(message, "🚫 আপনি এডমিন নন।")
                    return
                parts = cmd_data.split('_')
                if len(parts) >= 3:
                    _, m_type, m_id = parts[0], parts[1], parts[2]
                    admin_states[uid] = {'type': m_type, 'tmdb_id': m_id, 'temp_files': []}
                    
                    if m_type == 'movie':
                        ask_movie_lang(message, m_id)
                    else:
                        msg = bot_inst.send_message(message.chat.id, "📺 সিজন নম্বর লিখুন (বা /cancel):")
                        bot_inst.register_next_step_handler(msg, get_season)
                return

            # ফাইল ডাউনলোড (সবার জন্য কাজ করবে)
            if cmd_data.startswith('dl_'):
                file_to_send = cmd_data.replace('dl_', '')
                protect = True if config.get('PROTECT_CONTENT') == 'on' else False
                storage_id = config.get('STORAGE_CHANNEL_ID')
                
                if not storage_id:
                    bot_inst.send_message(message.chat.id, "❌ স্টোরেজ চ্যানেল কনফিগারেশন ভুল।")
                    return

                try:
                    sent_msg = bot_inst.copy_message(message.chat.id, int(storage_id), int(file_to_send), protect_content=protect)
                    delay = int(config.get('AUTO_DELETE_TIME', 0))
                    if delay > 0:
                        warn_msg = bot_inst.send_message(message.chat.id, f"⚠️ ফাইলটি {delay} সেকেন্ড পর ডিলিট হবে।")
                        threading.Thread(target=auto_delete_task, args=(bot_inst, message.chat.id, sent_msg.message_id, delay)).start()
                        threading.Thread(target=auto_delete_task, args=(bot_inst, message.chat.id, warn_msg.message_id, delay)).start()
                except:
                    bot_inst.send_message(message.chat.id, "❌ ফাইল পাওয়া যায়নি।")
                return

        # প্রিমিয়াম প্রোফাইল কার্ড এবং স্বাগতম মেসেজ (সবার জন্য)
        welcome_text = (
            f"🎬 *{config.get('SITE_NAME')}* এ আপনাকে স্বাগতম!\n\n"
            f"👤 *আপনার প্রোফাইল তথ্য:*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📝 *First Name:* {first_name}\n"
            f"📝 *Last Name:* {last_name if last_name else 'N/A'}\n"
            f"📛 *Full Name:* {full_name}\n"
            f"🆔 *User ID:* `{uid}`\n"
            f"🌐 *Username:* {username}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"মুভি বা টিভি শো খুঁজতে আমাদের ওয়েবসাইট ভিজিট করুন।"
        )

        markup = types.InlineKeyboardMarkup()
        btn_web = types.InlineKeyboardButton("🌐 Visit Website", url=config.get('SITE_URL') if config.get('SITE_URL') else "https://google.com")
        btn_admin = types.InlineKeyboardButton("👨‍💻 Contact Admin", url=f"tg://user?id={config.get('ADMIN_ID')}")
        markup.add(btn_web)
        markup.add(btn_admin)

        try:
            photos = bot_inst.get_user_profile_photos(uid)
            if photos.total_count > 0:
                photo_file_id = photos.photos[0][-1].file_id
                bot_inst.send_photo(message.chat.id, photo_file_id, caption=welcome_text, parse_mode="Markdown", reply_markup=markup)
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
        
        site_url = config.get('SITE_URL')
        encoded_query = urllib.parse.quote(query)
        selection_url = f"{site_url}/admin/bot_select?q={encoded_query}"
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔍 মুভি সিলেক্ট করুন (লিঙ্ক)", url=selection_url))
        
        bot_inst.send_message(message.chat.id, f"🔎 '{query}' এর জন্য রেজাল্ট দেখতে এবং সিলেক্ট করতে নিচের বাটনে ক্লিক করুন।", reply_markup=markup)

    def ask_movie_lang(message, mid):
        markup = types.InlineKeyboardMarkup()
        for l in ["Bangla", "Hindi", "English", "Multi"]:
            markup.add(types.InlineKeyboardButton(text=l, callback_data=f"lang_m_{mid}_{l}"))
        bot.send_message(message.chat.id, "🌐 ল্যাঙ্গুয়েজ সিলেক্ট করুন:", reply_markup=markup)

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
        bot_inst.send_message(call.message.chat.id, "💎 কোয়ালিটি সিলেক্ট করুন:", reply_markup=markup)

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
            sent_msg = bot_inst.copy_message(int(config['STORAGE_CHANNEL_ID']), message.chat.id, message.message_id)
            file_label = f"{state.get('lang', '')} {state.get('qual', 'HD')}".strip()
            file_data = {'quality': file_label, 'file_id': sent_msg.message_id}
            admin_states[uid]['temp_files'].append(file_data)

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

        bot_inst.send_message(call.message.chat.id, "⌛ ডাটাবেসে সেভ হচ্ছে, অপেক্ষা করুন...")
        
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
            movies_col.update_one({'tmdb_id': movie_info['tmdb_id']}, {'$set': movie_info}, upsert=True)

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
        stats = {'users': users_col.count_documents({}), 'movies': movies_col.count_documents({})}
        return render_template_string(ADMIN_DASHBOARD_HTML, stats=stats, config=config)

@app.route('/admin/bot_select')
def bot_select_page():
    query = request.args.get('q')
    config = get_config()
    tmdb_api = config.get('TMDB_API_KEY')
    bot_username = ""
    try:
        if bot: bot_username = bot.get_me().username
    except: pass
    
    url = f"https://api.themoviedb.org/3/search/multi?api_key={tmdb_api}&query={query}"
    res = []
    try:
        res = requests.get(url).json().get('results', [])
    except: pass
    
    return render_template_string(BOT_SELECT_HTML, results=res, bot_username=bot_username, query=query)

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
                if g['name'] in CATEGORIES:
                    auto_cat = g['name']; break

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
    :root { --neon: #66fcf1; --dark: #0b0c10; --card: #1f2833; --text: #c5c6c7; --duple: #00d2ff; }
    body { background: var(--dark); color: var(--text); font-family: 'Poppins', sans-serif; overflow-x: hidden; }
    
    .hero-slider { margin-bottom: 40px; position: relative; border-radius: 15px; overflow: hidden; }
    .carousel-item { height: 500px; }
    .carousel-item img { height: 100%; width: 100%; object-fit: cover; }
    .carousel-item::after { 
        content: ""; position: absolute; bottom: 0; left: 0; width: 100%; height: 100%; 
        background: linear-gradient(to top, rgba(11, 12, 16, 1) 10%, rgba(11, 12, 16, 0.4) 50%, rgba(0,0,0,0) 100%);
    }
    .carousel-caption { bottom: 50px; left: 5%; text-align: left; z-index: 10; width: 60%; animation: fadeInUp 0.8s ease-in-out; }
    .carousel-caption h3 { font-size: 3rem; font-weight: 700; color: #fff; text-shadow: 0 0 10px rgba(0,0,0,0.5); margin-bottom: 10px; }
    .carousel-caption .meta { font-size: 16px; color: var(--duple); font-weight: 600; margin-bottom: 15px; }
    .carousel-caption p { font-size: 15px; color: #ddd; max-height: 80px; overflow: hidden; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; }
    
    .btn-watch { background: var(--duple); color: #fff; padding: 10px 30px; border-radius: 30px; text-decoration: none; font-weight: 600; display: inline-block; margin-top: 15px; transition: 0.3s; box-shadow: 0 4px 15px rgba(0, 210, 255, 0.4); }
    .btn-watch:hover { background: #fff; color: var(--duple); transform: scale(1.05); }

    .neon-card { background: var(--card); border: 1px solid #45a29e; border-radius: 12px; transition: 0.5s; overflow: hidden; position: relative; }
    .neon-card:hover { transform: translateY(-8px); box-shadow: 0 0 20px var(--neon); border-color: var(--neon); }
    .btn-neon { background: var(--neon); color: var(--dark); font-weight: 600; border-radius: 6px; padding: 10px 20px; text-decoration: none; border: none; transition: 0.3s; display: inline-block; cursor:pointer;}
    .btn-neon:hover { background: #45a29e; color: #fff; box-shadow: 0 0 15px var(--neon); }
    
    .cat-pill { padding: 6px 16px; border-radius: 20px; border: 1px solid var(--neon); color: var(--neon); text-decoration: none; margin: 4px; display: inline-block; font-size: 13px; transition: 0.3s; }
    .cat-pill.active, .cat-pill:hover { background: var(--neon); color: var(--dark); font-weight: bold; }
    
    .sidebar { width: 260px; height: 100vh; background: #1f2833; position: fixed; top: 0; left: 0; padding: 20px 0; border-right: 2px solid var(--neon); z-index: 1001; }
    .sidebar-brand { text-align: center; padding: 0 20px 20px; border-bottom: 1px solid #45a29e; margin-bottom: 20px; }
    .sidebar a { padding: 12px 25px; text-decoration: none; font-size: 15px; color: #fff; display: flex; align-items: center; transition: 0.3s; }
    .sidebar a:hover, .sidebar a.active { background: var(--neon); color: var(--dark); font-weight: bold; }
    
    .main-content { margin-left: 260px; padding: 30px; min-height: 100vh; }
    .admin-card { background: white; color: #333; border-radius: 12px; padding: 20px; box-shadow: 0 5px 15px rgba(0,0,0,0.3); margin-bottom: 25px; }
    .navbar { background: var(--card); border-bottom: 2px solid var(--neon); }
    .logo-img { height: 40px; width: 40px; border-radius: 50%; object-fit: cover; margin-right: 10px; border: 1px solid var(--neon); }

    /* PREMIUM SEARCH UI CSS */
    .search-results-container { 
        background: #161b22; border-radius: 10px; border: 1px solid #30363d; 
        max-height: 450px; overflow-y: auto; padding: 10px; margin-top: 10px;
        box-shadow: 0 10px 30px rgba(0,0,0,0.5);
    }
    .search-item { 
        display: flex; align-items: center; padding: 12px; margin-bottom: 10px;
        background: #0d1117; border-radius: 10px; cursor: pointer; 
        border: 1px solid transparent; transition: 0.3s ease;
    }
    .search-item:hover { border-color: var(--duple); background: #1c2128; transform: translateX(5px); }
    .search-item img { width: 60px; height: 90px; object-fit: cover; border-radius: 8px; margin-right: 15px; box-shadow: 0 4px 10px rgba(0,0,0,0.3); }
    .search-info { flex-grow: 1; }
    .search-info b { display: block; color: var(--duple); font-size: 16px; margin-bottom: 4px; }
    .search-info p { margin: 0; font-size: 13px; color: #8b949e; }
    .search-meta { display: flex; gap: 10px; margin-top: 5px; }
    .search-meta span { font-size: 11px; padding: 2px 8px; border-radius: 5px; background: #21262d; color: #c9d1d9; border: 1px solid #30363d; }
    .search-badge { font-size: 10px; padding: 3px 8px; border-radius: 5px; font-weight: bold; text-transform: uppercase; margin-left: auto; }
    .badge-movie { background: rgba(35, 134, 54, 0.2); color: #3fb950; border: 1px solid #238636; }
    .badge-tv { background: rgba(31, 111, 235, 0.2); color: #58a6ff; border: 1px solid #1f6feb; }

    @keyframes fadeInUp { from { opacity: 0; transform: translateY(30px); } to { opacity: 1; transform: translateY(0); } }

    @media (max-width: 768px) {
        .sidebar { display: none; }
        .main-content { margin-left: 0; }
        .carousel-item { height: 350px; }
        .carousel-caption { width: 90%; bottom: 30px; }
        .carousel-caption h3 { font-size: 1.8rem; }
    }
</style>
"""

# ================== MAIN APP START ==================

if __name__ == '__main__':
    threading.Thread(target=init_bot_service, daemon=True).start()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
