import telebot
import requests
import os
import time
from telebot import types
from pymongo import MongoClient
from flask import Flask, render_template_string, redirect, url_for, request
from threading import Thread

# ================== ডাটাবেস সেটআপ ==================
# রেন্ডার বা কোয়েব ড্যাশবোর্ড থেকে MONGO_URI এনভায়রনমেন্ট ভেরিয়েবল সেট করুন।
MONGO_URI = os.environ.get('MONGO_URI') 

client = MongoClient(MONGO_URI)
db = client['movie_portal_db']
config_col = db['bot_config']
movies_col = db['movies_data']
settings_col = db['settings']

app = Flask(__name__)
admin_states = {}

# হেল্পার ফাংশন
def get_config():
    return config_col.find_one({'type': 'core_settings'}) or {}

def get_shortener():
    return settings_col.find_one({'type': 'shortener'}) or {'status': 'off', 'api_url': '', 'api_key': ''}

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
                    # চেক ডিপ লিঙ্কিং (ডাউনলোড বাটন থেকে আসলে)
                    if len(message.text.split()) > 1:
                        tmdb_id = message.text.split()[1]
                        movie = movies_col.find_one({'tmdb_id': str(tmdb_id)})
                        if movie:
                            bot.copy_message(message.chat.id, int(config['STORAGE_CHANNEL_ID']), movie['file_id'])
                            return
                    bot.reply_to(message, "🎬 মুভি খুঁজতে লিখুন: `/post Movie Name`", parse_mode="Markdown")

                @bot.message_handler(commands=['admin'])
                def send_admin_link(message):
                    if str(message.from_user.id) == str(config.get('ADMIN_ID')):
                        site_url = request.host_url if request else "সাইট ইউআরএল"
                        bot.reply_to(message, f"🔐 **এডমিন প্যানেল লিঙ্ক:**\n{site_url}admin_panel", parse_mode="Markdown")
                    else:
                        bot.reply_to(message, "🚫 আপনি এডমিন নন।")

                @bot.message_handler(commands=['post'])
                def post_movie(message):
                    if str(message.from_user.id) != str(config.get('ADMIN_ID')): return
                    query = message.text.replace('/post', '').strip()
                    if not query: return
                    
                    url = f"https://api.themoviedb.org/3/search/movie?api_key={config['TMDB_API_KEY']}&query={query}"
                    res = requests.get(url).json().get('results', [])
                    
                    if not res:
                        bot.reply_to(message, "❌ মুভি পাওয়া যায়নি।")
                        return

                    markup = types.InlineKeyboardMarkup()
                    for m in res[:5]:
                        markup.add(types.InlineKeyboardButton(text=f"{m['title']} ({m.get('release_date','N/A')[:4]})", callback_data=f"sel_{m['id']}"))
                    bot.send_message(message.chat.id, "🔍 মুভিটি সিলেক্ট করুন:", reply_markup=markup)

                @bot.callback_query_handler(func=lambda call: call.data.startswith('sel_'))
                def select_lang(call):
                    movie_id = call.data.split('_')[1]
                    markup = types.InlineKeyboardMarkup()
                    for l in ["Bangla", "Hindi", "English", "Multi"]:
                        markup.add(types.InlineKeyboardButton(text=l, callback_data=f"lang_{movie_id}_{l}"))
                    bot.edit_message_text("🌐 ভাষা সিলেক্ট করুন:", call.message.chat.id, call.message.message_id, reply_markup=markup)

                @bot.callback_query_handler(func=lambda call: call.data.startswith('lang_'))
                def ask_file(call):
                    _, mid, lang = call.data.split('_')
                    admin_states[call.from_user.id] = {'tmdb_id': mid, 'lang': lang}
                    bot.edit_message_text("📥 এবার মুভি ফাইলটি (Video/Doc) পাঠান। এটি অটো লিঙ্ক হয়ে যাবে।", call.message.chat.id, call.message.message_id)

                @bot.message_handler(content_types=['video', 'document'])
                def handle_file(message):
                    if message.from_user.id in admin_states:
                        state = admin_states[message.from_user.id]
                        sent_msg = bot.copy_message(int(config['STORAGE_CHANNEL_ID']), message.chat.id, message.message_id)
                        
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
                        movies_col.update_one({'tmdb_id': movie_data['tmdb_id']}, {'$set': movie_data}, upsert=True)
                        
                        # ডাউনলোড লিঙ্ক জেনারেট
                        bot_name = bot.get_me().username
                        long_url = f"https://t.me/{bot_name}?start={state['tmdb_id']}"
                        
                        sh_set = get_shortener()
                        final_url = long_url
                        if sh_set.get('status') == 'on':
                            try:
                                api_res = requests.get(sh_set['api_url'], params={'api': sh_set['api_key'], 'url': long_url}).json()
                                final_url = api_res.get('shortenedUrl') or api_res.get('short_url') or long_url
                            except: pass

                        markup = types.InlineKeyboardMarkup()
                        markup.add(types.InlineKeyboardButton("🚀 Download Now", url=final_url))
                        bot.send_photo(message.chat.id, movie_data['poster'], caption=f"🎬 **{movie_info['title']}**\n🌐 Language: {state['lang']}", reply_markup=markup, parse_mode="Markdown")
                        del admin_states[message.from_user.id]

                bot.polling(none_stop=True)
            except Exception as e:
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
    <title>Movie Search Bot - Home</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css">
    <style>
        body { background-color: #0f1014; color: #fff; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
        .movie-card { background: #1a1c23; border: none; border-radius: 10px; transition: 0.3s; }
        .movie-card:hover { transform: scale(1.03); }
        .poster { border-radius: 10px 10px 0 0; }
        .card-title { font-size: 0.95rem; font-weight: 600; height: 2.8rem; overflow: hidden; }
        .btn-dl { background-color: #0088cc; color: white; border: none; font-weight: 600; }
        .btn-dl:hover { background-color: #0077b3; color: #eee; }
    </style>
</head>
<body class="container py-4">
    <h2 class="text-center text-primary mb-4">🎥 Latest Movie Posts</h2>
    <div class="row row-cols-2 row-cols-md-4 row-cols-lg-5 g-3">
        {% for movie in movies %}
        <div class="col">
            <div class="card movie-card h-100 shadow">
                <img src="{{ movie.poster }}" class="card-img-top poster" alt="Poster">
                <div class="card-body p-2 text-center">
                    <h5 class="card-title mb-1">{{ movie.title }}</h5>
                    <p class="small text-muted mb-2">{{ movie.lang }} | ⭐ {{ movie.rating }}</p>
                    <a href="https://t.me/{{ bot_username }}?start={{ movie.tmdb_id }}" class="btn btn-dl btn-sm w-100">Download</a>
                </div>
            </div>
        </div>
        {% endfor %}
    </div>
    {% if not movies %}<p class="text-center mt-5 text-muted">No movies found in database.</p>{% endif %}
</body>
</html>
"""

ADMIN_HTML = """
<!DOCTYPE html>
<html>
<head><title>Admin Dashboard</title><link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css"></head>
<body class="container py-5 bg-light">
    <h3 class="mb-4">⚙️ Admin Control Panel</h3>
    <div class="row">
        <div class="col-md-7 mb-4">
            <div class="card p-4 shadow-sm">
                <h5>Bot Core Settings</h5>
                <form action="/save_config" method="POST">
                    <input type="text" name="token" class="form-control mb-2" placeholder="Bot Token" value="{{ config.BOT_TOKEN or '' }}">
                    <input type="text" name="tmdb" class="form-control mb-2" placeholder="TMDB API" value="{{ config.TMDB_API_KEY or '' }}">
                    <input type="text" name="admin_id" class="form-control mb-2" placeholder="Admin ID" value="{{ config.ADMIN_ID or '' }}">
                    <input type="text" name="channel_id" class="form-control mb-2" placeholder="Storage Channel ID" value="{{ config.STORAGE_CHANNEL_ID or '' }}">
                    <button class="btn btn-primary w-100">Save Config</button>
                </form>
            </div>
        </div>
        <div class="col-md-5 mb-4">
            <div class="card p-4 shadow-sm">
                <h5>Link Shortener</h5>
                <form action="/save_shortener" method="POST">
                    <input type="text" name="api_url" class="form-control mb-2" placeholder="API URL" value="{{ shortener.api_url or '' }}">
                    <input type="text" name="api_key" class="form-control mb-2" placeholder="API Key" value="{{ shortener.api_key or '' }}">
                    <select name="status" class="form-control mb-2">
                        <option value="on" {% if shortener.status == 'on' %}selected{% endif %}>ON</option>
                        <option value="off" {% if shortener.status == 'off' %}selected{% endif %}>OFF</option>
                    </select>
                    <button class="btn btn-success w-100">Update Shortener</button>
                </form>
            </div>
        </div>
    </div>
    <div class="card p-3 shadow-sm">
        <h5>Manage Database Movies</h5>
        <table class="table table-sm mt-2">
            <thead><tr><th>Title</th><th>Language</th><th>Action</th></tr></thead>
            <tbody>
                {% for m in movies %}
                <tr><td>{{ m.title }}</td><td>{{ m.lang }}</td><td><a href="/delete/{{ m.tmdb_id }}" class="text-danger">Delete</a></td></tr>
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
    bot_username = ""
    if config.get('BOT_TOKEN'):
        try: bot_username = telebot.TeleBot(config['BOT_TOKEN']).get_me().username
        except: pass
    movies = list(movies_col.find().sort('_id', -1))
    return render_template_string(USER_HTML, movies=movies, bot_username=bot_username)

@app.route('/admin_panel')
def admin_panel():
    return render_template_string(ADMIN_HTML, config=get_config(), shortener=get_shortener(), movies=list(movies_col.find()))

@app.route('/save_config', methods=['POST'])
def save_config():
    data = {'type': 'core_settings', 'BOT_TOKEN': request.form.get('token'), 'TMDB_API_KEY': request.form.get('tmdb'), 'ADMIN_ID': request.form.get('admin_id'), 'STORAGE_CHANNEL_ID': request.form.get('channel_id')}
    config_col.update_one({'type': 'core_settings'}, {'$set': data}, upsert=True)
    return redirect('/admin_panel')

@app.route('/save_shortener', methods=['POST'])
def save_shortener():
    data = {'type': 'shortener', 'api_url': request.form.get('api_url'), 'api_key': request.form.get('api_key'), 'status': request.form.get('status')}
    settings_col.update_one({'type': 'shortener'}, {'$set': data}, upsert=True)
    return redirect('/admin_panel')

@app.route('/delete/<tmdb_id>')
def delete_movie(tmdb_id):
    movies_col.delete_one({'tmdb_id': tmdb_id})
    return redirect('/admin_panel')

# মেইন রানার
if __name__ == '__main__':
    Thread(target=run_telegram_bot, daemon=True).start()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
