import telebot
import requests
import os
import time
from telebot import types
from pymongo import MongoClient
from flask import Flask, render_template_string, redirect, url_for, request
from threading import Thread

# ================== ডাটাবেস এবং অ্যাপ সেটআপ ==================
# আপনার রেন্ডার/কোয়েব ড্যাশবোর্ড থেকে MONGO_URI এনভায়রনমেন্ট ভেরিয়েবল সেট করুন।
MONGO_URI = os.environ.get('MONGO_URI') 

client = MongoClient(MONGO_URI)
db = client['movie_portal_db']
config_col = db['bot_config']     # বটের টোকেন ও মেইন সেটিংস
movies_col = db['movies_data']     # মুভি লিস্ট ও ফাইল আইডি
settings_col = db['settings']      # লিঙ্ক শর্টনার সেটিংস

app = Flask(__name__)
admin_states = {} # অ্যাডমিন মুভি আপলোড করার সময় ডাটা মনে রাখার জন্য

# --- [সহায়ক ফাংশনসমূহ] ---
def get_config():
    """ডাটাবেস থেকে বটের কনফিগারেশন আনে"""
    return config_col.find_one({'type': 'core_settings'}) or {}

def get_shortener():
    """ডাটাবেস থেকে শর্টনার সেটিংস আনে"""
    return settings_col.find_one({'type': 'shortener'}) or {'status': 'off', 'api_url': '', 'api_key': ''}

def get_bot_username():
    """বটের ইউজারনেম বের করে (ডাউনলোড লিঙ্কের জন্য)"""
    config = get_config()
    token = config.get('BOT_TOKEN')
    if token:
        try:
            temp_bot = telebot.TeleBot(token)
            return temp_bot.get_me().username
        except: return ""
    return ""

# --- [টেলিগ্রাম বট লজিক অংশ] ---
def run_telegram_bot():
    while True:
        config = get_config()
        token = config.get('BOT_TOKEN')
        
        if token:
            try:
                bot = telebot.TeleBot(token)
                print("✅ টেলিগ্রাম বট অনলাইন হয়েছে...")

                # ১. স্টার্ট কমান্ড (ডাউনলোড হ্যান্ডলার সহ)
                @bot.message_handler(commands=['start'])
                def start_handle(message):
                    # ইউজার যদি ওয়েবসাইট থেকে ডাউনলোড বাটনে ক্লিক করে আসে
                    if len(message.text.split()) > 1:
                        tmdb_id = message.text.split()[1]
                        movie_data = movies_col.find_one({'tmdb_id': str(tmdb_id)})
                        if movie_data:
                            bot.copy_message(message.chat.id, int(config['STORAGE_CHANNEL_ID']), movie_data['file_id'])
                            return
                        else:
                            bot.send_message(message.chat.id, "❌ দুঃখিত, মুভি ফাইলটি পাওয়া যায়নি।")
                            return
                    bot.reply_to(message, "🎬 মুভি খুঁজতে লিখুন: `/post মুভির নাম`", parse_mode="Markdown")

                # ২. অ্যাডমিন প্যানেল লিঙ্ক কমান্ড
                @bot.message_handler(commands=['admin'])
                def send_admin_panel(message):
                    if str(message.from_user.id) == str(config.get('ADMIN_ID')):
                        base_url = request.host_url.rstrip('/') if request else "URL"
                        bot.reply_to(message, f"🔐 **আপনার এডমিন প্যানেল লিঙ্ক:**\n{base_url}/admin", parse_mode="Markdown")
                    else:
                        bot.reply_to(message, "🚫 আপনি এই বটের অ্যাডমিন নন।")

                # ৩. মুভি সার্চ ও পোস্ট জেনারেশন (/post)
                @bot.message_handler(commands=['post'])
                def post_search(message):
                    if str(message.from_user.id) != str(config.get('ADMIN_ID')): return
                    query = message.text.replace('/post', '').strip()
                    if not query:
                        bot.reply_to(message, "⚠️ মুভির নাম লিখুন। যেমন: `/post Avatar`")
                        return
                    
                    # TMDB সার্চ
                    tmdb_api = config.get('TMDB_API_KEY')
                    url = f"https://api.themoviedb.org/3/search/movie?api_key={tmdb_api}&query={query}"
                    res = requests.get(url).json().get('results', [])
                    
                    if not res:
                        bot.reply_to(message, "❌ মুভি পাওয়া যায়নি!")
                        return

                    markup = types.InlineKeyboardMarkup()
                    for m in res[:5]:
                        markup.add(types.InlineKeyboardButton(text=f"{m['title']} ({m.get('release_date','N/A')[:4]})", callback_data=f"sel_{m['id']}"))
                    bot.send_message(message.chat.id, "🔍 তালিকা থেকে মুভিটি বেছে নিন:", reply_markup=markup)

                # ৪. মুভি সিলেক্ট করার পর ভাষা নির্বাচন
                @bot.callback_query_handler(func=lambda call: call.data.startswith('sel_'))
                def select_language(call):
                    movie_id = call.data.split('_')[1]
                    markup = types.InlineKeyboardMarkup()
                    for lang in ["Bangla", "Hindi", "English", "Multi"]:
                        markup.add(types.InlineKeyboardButton(text=lang, callback_data=f"lang_{movie_id}_{lang}"))
                    bot.edit_message_text("🌐 মুভির ভাষা সিলেক্ট করুন:", call.message.chat.id, call.message.message_id, reply_markup=markup)

                # ৫. ভাষা সিলেক্ট করার পর ফাইল চাওয়া
                @bot.callback_query_handler(func=lambda call: call.data.startswith('lang_'))
                def ask_for_file(call):
                    _, mid, lang = call.data.split('_')
                    admin_states[call.from_user.id] = {'tmdb_id': mid, 'lang': lang}
                    bot.edit_message_text("📥 এবার মুভি ফাইলটি (Video/Doc) এখানে পাঠান। এটি অটোমেটিক লিঙ্ক হয়ে যাবে।", call.message.chat.id, call.message.message_id)

                # ৬. ফাইল হ্যান্ডলিং ও ডাটাবেসে সেভ
                @bot.message_handler(content_types=['video', 'document'])
                def save_movie_file(message):
                    uid = message.from_user.id
                    if uid in admin_states:
                        state = admin_states[uid]
                        # ফাইলটি স্টোরেজ চ্যানেলে কপি করা
                        sent_msg = bot.copy_message(int(config['STORAGE_CHANNEL_ID']), message.chat.id, message.message_id)
                        
                        # TMDB থেকে বিস্তারিত তথ্য আনা
                        tmdb_api = config.get('TMDB_API_KEY')
                        m_url = f"https://api.themoviedb.org/3/movie/{state['tmdb_id']}?api_key={tmdb_api}"
                        movie_info = requests.get(m_url).json()
                        
                        # ডাটাবেসে সেভ করা
                        movie_data = {
                            'tmdb_id': str(state['tmdb_id']),
                            'title': movie_info['title'],
                            'lang': state['lang'],
                            'file_id': sent_msg.message_id,
                            'poster': f"https://image.tmdb.org/t/p/w500{movie_info.get('poster_path')}",
                            'rating': movie_info.get('vote_average')
                        }
                        movies_col.update_one({'tmdb_id': movie_data['tmdb_id']}, {'$set': movie_data}, upsert=True)
                        
                        # ফাইনাল পোস্ট তৈরি
                        bot_name = bot.get_me().username
                        long_url = f"https://t.me/{bot_name}?start={state['tmdb_id']}"
                        
                        # শর্টনার চেক
                        sh_set = get_shortener()
                        final_url = long_url
                        if sh_set.get('status') == 'on':
                            try:
                                api_res = requests.get(sh_set['api_url'], params={'api': sh_set['api_key'], 'url': long_url}).json()
                                final_url = api_res.get('shortenedUrl') or api_res.get('short_url') or long_url
                            except: pass

                        markup = types.InlineKeyboardMarkup()
                        markup.add(types.InlineKeyboardButton("🚀 Download Now", url=final_url))
                        
                        caption = f"🎬 **{movie_info['title']}**\n🌐 ভাষা: {state['lang']}\n⭐ রেটিং: {movie_info.get('vote_average')}\n💎 কোয়ালিটি: 480p, 720p, 1080p (Auto Added)"
                        bot.send_photo(message.chat.id, movie_data['poster'], caption=caption, reply_markup=markup, parse_mode="Markdown")
                        
                        del admin_states[uid] # সেশন ক্লিয়ার

                bot.polling(none_stop=True)
            except Exception as e:
                print(f"বট ক্র্যাশ করেছে, রিস্টার্ট হচ্ছে... এরর: {e}")
                time.sleep(10)
        else:
            print("⚠️ ডাটাবেসে বোট টোকেন নেই। অ্যাডমিন প্যানেল থেকে সেটআপ করুন।")
            time.sleep(15)

# --- [ফ্ল্যাস্ক ওয়েবসাইট: ইউজার ও অ্যাডমিন প্যানেল] ---

# হোম পেজ ডিজাইন (ইউজার প্যানেল)
USER_UI = """
<!DOCTYPE html>
<html>
<head>
    <title>Movie Portal</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css">
    <style>
        body { background-color: #0d1117; color: white; font-family: 'Segoe UI', sans-serif; }
        .movie-card { background: #161b22; border: none; border-radius: 12px; transition: 0.3s; height: 100%; }
        .movie-card:hover { transform: translateY(-5px); border: 1px solid #58a6ff; }
        .poster-img { border-radius: 12px 12px 0 0; }
        .card-title { font-size: 0.95rem; font-weight: 600; height: 2.8rem; overflow: hidden; }
        .btn-download { background-color: #238636; color: white; border: none; width: 100%; font-weight: bold; }
    </style>
</head>
<body class="container py-5">
    <h2 class="text-center mb-5 text-info">🎬 Latest Movies</h2>
    <div class="row row-cols-2 row-cols-md-4 row-cols-lg-5 g-4">
        {% for movie in movies %}
        <div class="col">
            <div class="card movie-card shadow">
                <img src="{{ movie.poster }}" class="card-img-top poster-img" alt="poster">
                <div class="card-body p-2 text-center">
                    <h6 class="card-title">{{ movie.title }}</h6>
                    <p class="small text-muted mb-2">{{ movie.lang }} | ⭐ {{ movie.rating }}</p>
                    <a href="https://t.me/{{ bot_username }}?start={{ movie.tmdb_id }}" class="btn btn-download btn-sm">Download</a>
                </div>
            </div>
        </div>
        {% endfor %}
    </div>
    {% if not movies %}<p class="text-center mt-5">No movies found.</p>{% endif %}
</body>
</html>
"""

# অ্যাডমিন প্যানেল ডিজাইন
ADMIN_UI = """
<!DOCTYPE html>
<html>
<head><title>Admin Dashboard</title><link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css"></head>
<body class="container py-5 bg-light">
    <h3 class="mb-4 text-center text-primary">⚙️ Bot Admin Panel</h3>
    <div class="row">
        <div class="col-md-6 mb-4">
            <div class="card p-4 shadow-sm">
                <h5 class="mb-3">Core Settings</h5>
                <form action="/save_config" method="POST">
                    <label>Telegram Bot Token</label>
                    <input type="text" name="token" class="form-control mb-2" value="{{ config.BOT_TOKEN or '' }}">
                    <label>TMDB API Key</label>
                    <input type="text" name="tmdb" class="form-control mb-2" value="{{ config.TMDB_API_KEY or '' }}">
                    <label>Your Telegram ID (Admin)</label>
                    <input type="text" name="admin_id" class="form-control mb-2" value="{{ config.ADMIN_ID or '' }}">
                    <label>Storage Channel ID (ex: -100...)</label>
                    <input type="text" name="channel_id" class="form-control mb-2" value="{{ config.STORAGE_CHANNEL_ID or '' }}">
                    <button class="btn btn-primary w-100 mt-2">Update Bot Configuration</button>
                </form>
            </div>
        </div>
        <div class="col-md-6 mb-4">
            <div class="card p-4 shadow-sm">
                <h5 class="mb-3">Shortener Settings</h5>
                <form action="/save_shortener" method="POST">
                    <label>API URL (e.g. https://gplinks.in/api)</label>
                    <input type="text" name="api_url" class="form-control mb-2" value="{{ shortener.api_url or '' }}">
                    <label>API Key</label>
                    <input type="text" name="api_key" class="form-control mb-2" value="{{ shortener.api_key or '' }}">
                    <label>Shortener Status</label>
                    <select name="status" class="form-control mb-2">
                        <option value="on" {% if shortener.status == 'on' %}selected{% endif %}>ON (Enabled)</option>
                        <option value="off" {% if shortener.status == 'off' %}selected{% endif %}>OFF (Disabled)</option>
                    </select>
                    <button class="btn btn-success w-100 mt-2">Save Shortener</button>
                </form>
            </div>
        </div>
    </div>
    <div class="card p-4 shadow-sm mt-3">
        <h5>Manage Added Movies</h5>
        <table class="table table-hover mt-3">
            <thead><tr><th>Movie Name</th><th>Lang</th><th>Action</th></tr></thead>
            <tbody>
                {% for m in movies %}
                <tr><td>{{ m.title }}</td><td>{{ m.lang }}</td><td><a href="/delete/{{ m.tmdb_id }}" class="btn btn-danger btn-sm">Delete</a></td></tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</body>
</html>
"""

# --- [ফ্ল্যাস্ক রাউটস] ---

@app.route('/')
def home_page():
    config = get_config()
    bot_user = get_bot_username()
    # ডাটাবেস থেকে মুভি লিস্ট আনা (সর্বশেষগুলো আগে)
    movies_list = list(movies_col.find().sort('_id', -1))
    return render_template_string(USER_UI, movies=movies_list, bot_username=bot_user)

@app.route('/admin') # সরাসরি /admin রুট
def admin_page():
    config = get_config()
    shortener = get_shortener()
    movies_list = list(movies_col.find().sort('_id', -1))
    return render_template_string(ADMIN_UI, config=config, shortener=shortener, movies=movies_list)

@app.route('/save_config', methods=['POST'])
def save_config():
    data = {
        'type': 'core_settings',
        'BOT_TOKEN': request.form.get('token'),
        'TMDB_API_KEY': request.form.get('tmdb'),
        'ADMIN_ID': request.form.get('admin_id'),
        'STORAGE_CHANNEL_ID': request.form.get('channel_id')
    }
    config_col.update_one({'type': 'core_settings'}, {'$set': data}, upsert=True)
    return redirect('/admin')

@app.route('/save_shortener', methods=['POST'])
def save_shortener():
    data = {
        'type': 'shortener',
        'api_url': request.form.get('api_url'),
        'api_key': request.form.get('api_key'),
        'status': request.form.get('status')
    }
    settings_col.update_one({'type': 'shortener'}, {'$set': data}, upsert=True)
    return redirect('/admin')

@app.route('/delete/<tmdb_id>')
def delete_movie(tmdb_id):
    movies_col.delete_one({'tmdb_id': tmdb_id})
    return redirect('/admin')

# --- [মেইন রানার] ---
if __name__ == '__main__':
    # বটের জন্য আলাদা থ্রেড
    Thread(target=run_telegram_bot, daemon=True).start()
    # ওয়েবসাইট পোর্ট বাইন্ডিং (রেন্ডার/কোয়েব-এর জন্য)
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
