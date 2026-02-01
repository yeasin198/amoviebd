import telebot
import requests
import os
import time
from telebot import types
from pymongo import MongoClient
from flask import Flask, render_template_string, redirect, url_for, request
from threading import Thread

# ================== ডাটাবেস সেটআপ ==================
# রেন্ডার বা কোয়েব ড্যাশবোর্ড থেকে MONGO_URI অবশ্যই সেট করবেন।
MONGO_URI = os.environ.get('MONGO_URI') 

client = MongoClient(MONGO_URI)
db = client['movie_portal_db']
config_col = db['bot_config']
movies_col = db['movies_data']
settings_col = db['settings']

app = Flask(__name__)
admin_states = {}

# --- [সহায়ক ফাংশনসমূহ] ---
def get_config():
    return config_col.find_one({'type': 'core_settings'}) or {}

def get_shortener():
    return settings_col.find_one({'type': 'shortener'}) or {'status': 'off', 'api_url': '', 'api_key': ''}

def get_bot_username(token):
    try:
        temp_bot = telebot.TeleBot(token)
        return temp_bot.get_me().username
    except:
        return ""

# --- [টেলিগ্রাম বট লজিক] ---
def run_telegram_bot():
    while True:
        config = get_config()
        token = config.get('BOT_TOKEN')
        if token:
            try:
                bot = telebot.TeleBot(token)
                
                @bot.message_handler(commands=['start'])
                def start(message):
                    # ডিপ লিঙ্কিং: ইউজার যখন সাইট থেকে ডাউনলোড বাটনে ক্লিক করে আসবে
                    if len(message.text.split()) > 1:
                        tmdb_id = message.text.split()[1]
                        movie = movies_col.find_one({'tmdb_id': str(tmdb_id)})
                        if movie:
                            bot.copy_message(message.chat.id, int(config['STORAGE_CHANNEL_ID']), movie['file_id'])
                            return
                        else:
                            bot.send_message(message.chat.id, "❌ দুঃখিত, মুভিটি ডাটাবেসে পাওয়া যায়নি।")
                            return
                    bot.reply_to(message, "🎬 মুভি খুঁজতে লিখুন: `/post Movie Name`", parse_mode="Markdown")

                @bot.message_handler(commands=['admin'])
                def send_admin_link(message):
                    if str(message.from_user.id) == str(config.get('ADMIN_ID')):
                        # সাইট ইউআরএল অটো ডিটেক্ট করবে
                        base_url = request.host_url.rstrip('/') if request else "আপনার সাইট লিঙ্ক"
                        admin_url = f"{base_url}/admin_dashboard"
                        bot.reply_to(message, f"🔐 **এডমিন ড্যাশবোর্ড লিঙ্ক:**\n{admin_url}", parse_mode="Markdown")
                    else:
                        bot.reply_to(message, "🚫 আপনি এডমিন নন।")

                @bot.message_handler(commands=['post'])
                def post_movie(message):
                    if str(message.from_user.id) != str(config.get('ADMIN_ID')): return
                    query = message.text.replace('/post', '').strip()
                    if not query:
                        bot.reply_to(message, "⚠️ মুভির নাম লিখুন। উদা: `/post Avatar`")
                        return
                    
                    url = f"https://api.themoviedb.org/3/search/movie?api_key={config['TMDB_API_KEY']}&query={query}"
                    res = requests.get(url).json().get('results', [])
                    
                    if not res:
                        bot.reply_to(message, "❌ মুভি পাওয়া যায়নি।")
                        return

                    markup = types.InlineKeyboardMarkup()
                    for m in res[:5]:
                        btn_text = f"{m['title']} ({m.get('release_date','N/A')[:4]})"
                        markup.add(types.InlineKeyboardButton(text=btn_text, callback_data=f"sel_{m['id']}"))
                    bot.send_message(message.chat.id, "🔍 মুভিটি সিলেক্ট করুন:", reply_markup=markup)

                @bot.callback_query_handler(func=lambda call: call.data.startswith('sel_'))
                def select_lang(call):
                    movie_id = call.data.split('_')[1]
                    markup = types.InlineKeyboardMarkup()
                    for l in ["Bangla", "Hindi", "English", "Multi"]:
                        markup.add(types.InlineKeyboardButton(text=l, callback_data=f"lang_{movie_id}_{l}"))
                    bot.edit_message_text("🌐 মুভির ভাষা সিলেক্ট করুন:", call.message.chat.id, call.message.message_id, reply_markup=markup)

                @bot.callback_query_handler(func=lambda call: call.data.startswith('lang_'))
                def ask_file(call):
                    _, mid, lang = call.data.split('_')
                    admin_states[call.from_user.id] = {'tmdb_id': mid, 'lang': lang}
                    bot.edit_message_text("📥 এবার মুভি ফাইলটি (Video/Doc) পাঠান। এটি অটো লিঙ্ক হয়ে যাবে।", call.message.chat.id, call.message.message_id)

                @bot.message_handler(content_types=['video', 'document'])
                def handle_file(message):
                    uid = message.from_user.id
                    if uid in admin_states:
                        state = admin_states[uid]
                        # ফাইলটি স্টোরেজ চ্যানেলে পাঠানো
                        sent_msg = bot.copy_message(int(config['STORAGE_CHANNEL_ID']), message.chat.id, message.message_id)
                        
                        # মুভির ডিটেইলস আনা
                        movie_info = requests.get(f"https://api.themoviedb.org/3/movie/{state['tmdb_id']}?api_key={config['TMDB_API_KEY']}").json()
                        
                        movie_data = {
                            'tmdb_id': str(state['tmdb_id']),
                            'title': movie_info['title'],
                            'lang': state['lang'],
                            'file_id': sent_msg.message_id,
                            'poster': f"https://image.tmdb.org/t/p/w500{movie_info.get('poster_path')}",
                            'rating': movie_info.get('vote_average'),
                            'year': movie_info.get('release_date','N/A')[:4]
                        }
                        # ডাটাবেসে সেভ
                        movies_col.update_one({'tmdb_id': movie_data['tmdb_id']}, {'$set': movie_data}, upsert=True)
                        
                        # কনফার্মেশন পোস্ট
                        bot_username = bot.get_me().username
                        long_url = f"https://t.me/{bot_username}?start={state['tmdb_id']}"
                        
                        sh_set = get_shortener()
                        final_url = long_url
                        if sh_set.get('status') == 'on':
                            try:
                                api_res = requests.get(sh_set['api_url'], params={'api': sh_set['api_key'], 'url': long_url}).json()
                                final_url = api_res.get('shortenedUrl') or api_res.get('short_url') or long_url
                            except: pass

                        markup = types.InlineKeyboardMarkup()
                        markup.add(types.InlineKeyboardButton("🚀 Download Now", url=final_url))
                        bot.send_photo(message.chat.id, movie_data['poster'], caption=f"🎬 **{movie_info['title']}**\n🌐 Language: {state['lang']}\n⭐ Rating: {movie_info.get('vote_average')}", reply_markup=markup, parse_mode="Markdown")
                        del admin_states[uid]

                bot.polling(none_stop=True)
            except Exception as e:
                print(f"Bot Error: {e}")
                time.sleep(10)
        else:
            time.sleep(10)

# --- [ওয়েবসাইট অংশ: ইউজার ও এডমিন প্যানেল] ---

USER_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Movie Portal</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css">
    <style>
        body { background-color: #0f1014; color: white; font-family: sans-serif; }
        .movie-card { background: #1a1c23; border: none; border-radius: 12px; transition: 0.3s; }
        .movie-card:hover { transform: scale(1.03); }
        .btn-dl { background-color: #0088cc; color: white; border-radius: 5px; font-weight: 600; }
        .card-title { font-size: 0.9rem; height: 2.5rem; overflow: hidden; }
    </style>
</head>
<body class="container py-4">
    <h2 class="text-center text-primary mb-4">🎬 Latest Movie Posts</h2>
    <div class="row row-cols-2 row-cols-md-4 row-cols-lg-5 g-3">
        {% for movie in movies %}
        <div class="col">
            <div class="card movie-card h-100 shadow-sm">
                <img src="{{ movie.poster }}" class="card-img-top" style="border-radius:12px 12px 0 0;">
                <div class="card-body p-2 text-center">
                    <h6 class="card-title">{{ movie.title }}</h6>
                    <p class="small text-muted mb-2">{{ movie.lang }} | ⭐ {{ movie.rating }}</p>
                    <a href="https://t.me/{{ bot_username }}?start={{ movie.tmdb_id }}" class="btn btn-dl btn-sm w-100">Download</a>
                </div>
            </div>
        </div>
        {% endfor %}
    </div>
    {% if not movies %}<p class="text-center mt-5 text-muted">No movies added yet.</p>{% endif %}
</body>
</html>
"""

ADMIN_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Admin Dashboard</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css">
</head>
<body class="container py-5">
    <h3 class="text-center mb-4">⚙️ Bot Admin Dashboard</h3>
    
    <div class="row">
        <!-- সেটিংস ফর্ম -->
        <div class="col-md-6 mb-4">
            <div class="card p-4 shadow">
                <h5>Core Settings</h5>
                <form action="/save_config" method="POST">
                    <label>Bot Token</label>
                    <input type="text" name="token" class="form-control mb-2" value="{{ config.BOT_TOKEN or '' }}" required>
                    <label>TMDB API Key</label>
                    <input type="text" name="tmdb" class="form-control mb-2" value="{{ config.TMDB_API_KEY or '' }}" required>
                    <label>Admin Telegram ID</label>
                    <input type="text" name="admin_id" class="form-control mb-2" value="{{ config.ADMIN_ID or '' }}" required>
                    <label>Storage Channel ID</label>
                    <input type="text" name="channel_id" class="form-control mb-2" value="{{ config.STORAGE_CHANNEL_ID or '' }}" required>
                    <button class="btn btn-primary w-100 mt-2">Update Configuration</button>
                </form>
            </div>
        </div>

        <!-- শর্টনার ফর্ম -->
        <div class="col-md-6 mb-4">
            <div class="card p-4 shadow">
                <h5>Shortener Settings</h5>
                <form action="/save_shortener" method="POST">
                    <label>Shortener API URL</label>
                    <input type="text" name="api_url" class="form-control mb-2" value="{{ shortener.api_url or '' }}">
                    <label>API Key</label>
                    <input type="text" name="api_key" class="form-control mb-2" value="{{ shortener.api_key or '' }}">
                    <label>Status</label>
                    <select name="status" class="form-control mb-2">
                        <option value="on" {% if shortener.status == 'on' %}selected{% endif %}>ON</option>
                        <option value="off" {% if shortener.status == 'off' %}selected{% endif %}>OFF</option>
                    </select>
                    <button class="btn btn-success w-100 mt-2">Save Shortener</button>
                </form>
            </div>
        </div>
    </div>

    <!-- মুভি লিস্ট ম্যানেজমেন্ট -->
    <div class="card p-4 shadow">
        <h5>Manage Movies ({{ movies|length }})</h5>
        <table class="table table-striped table-hover mt-3">
            <thead>
                <tr>
                    <th>Title</th>
                    <th>Language</th>
                    <th>Action</th>
                </tr>
            </thead>
            <tbody>
                {% for m in movies %}
                <tr>
                    <td>{{ m.title }}</td>
                    <td>{{ m.lang }}</td>
                    <td>
                        <a href="/delete/{{ m.tmdb_id }}" class="btn btn-danger btn-sm" onclick="return confirm('ডিলিট করতে চান?')">Delete</a>
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</body>
</html>
"""

@app.route('/')
def user_panel():
    config = get_config()
    bot_user = get_bot_username(config.get('BOT_TOKEN'))
    movies = list(movies_col.find().sort('_id', -1))
    return render_template_string(USER_HTML, movies=movies, bot_username=bot_user)

@app.route('/admin_dashboard')
def admin_dashboard():
    config = get_config()
    shortener = get_shortener()
    movies = list(movies_col.find().sort('_id', -1))
    return render_template_string(ADMIN_HTML, config=config, shortener=shortener, movies=movies)

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
    return redirect(url_for('admin_dashboard'))

@app.route('/save_shortener', methods=['POST'])
def save_shortener():
    data = {
        'type': 'shortener',
        'api_url': request.form.get('api_url'),
        'api_key': request.form.get('api_key'),
        'status': request.form.get('status')
    }
    settings_col.update_one({'type': 'shortener'}, {'$set': data}, upsert=True)
    return redirect(url_for('admin_dashboard'))

@app.route('/delete/<tmdb_id>')
def delete_movie(tmdb_id):
    movies_col.delete_one({'tmdb_id': tmdb_id})
    return redirect(url_for('admin_dashboard'))

# মেইন থ্রেড রানার
if __name__ == '__main__':
    # বটের জন্য আলাদা থ্রেড
    Thread(target=run_telegram_bot, daemon=True).start()
    # Flask ওয়েবসাইট পোর্ট বাইন্ডিং
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
