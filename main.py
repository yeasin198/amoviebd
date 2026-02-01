import telebot
import requests
import os
from telebot import types
from pymongo import MongoClient
from flask import Flask, render_template_string, redirect, url_for, request
from threading import Thread
import time

# ================== কনফিগারেশন ==================
# আপনার MongoDB URI রেন্ডার/কোয়েব এর ড্যাশবোর্ডে "Environment Variable" হিসেবে MONGO_URI নামে সেট করবেন।
MONGO_URI = os.environ.get('MONGO_URI') 

client = MongoClient(MONGO_URI)
db = client['movie_store_db']
config_col = db['bot_config']
movies_col = db['movies_data']
settings_col = db['settings']

app = Flask(__name__)
bot_instance = None
admin_states = {}

# হেল্পার ফাংশন
def get_config():
    return config_col.find_one({'type': 'core_settings'}) or {}

def get_shortener():
    return settings_col.find_one({'type': 'shortener'}) or {'status': 'off'}

# --- [বট লজিক] ---
def run_telegram_bot():
    global bot_instance
    while True:
        config = get_config()
        token = config.get('BOT_TOKEN')
        if token:
            try:
                bot = telebot.TeleBot(token)
                bot_instance = bot

                @bot.message_handler(commands=['start'])
                def start(message):
                    if len(message.text.split()) > 1:
                        tmdb_id = message.text.split()[1]
                        movie = movies_col.find_one({'tmdb_id': str(tmdb_id)})
                        if movie:
                            conf = get_config()
                            bot.copy_message(message.chat.id, int(conf['STORAGE_CHANNEL_ID']), movie['file_id'])
                            return
                    bot.reply_to(message, "🎬 মুভি সার্চ করতে লিখুন: `/post Movie Name`", parse_mode="Markdown")

                @bot.message_handler(commands=['post'])
                def post_movie(message):
                    conf = get_config()
                    if str(message.from_user.id) != str(conf.get('ADMIN_ID')): return
                    query = message.text.replace('/post', '').strip()
                    if not query: return
                    url = f"https://api.themoviedb.org/3/search/movie?api_key={conf['TMDB_API_KEY']}&query={query}"
                    results = requests.get(url).json().get('results', [])
                    markup = types.InlineKeyboardMarkup()
                    for m in results[:5]:
                        markup.add(types.InlineKeyboardButton(text=f"{m['title']} ({m.get('release_date','N/A')[:4]})", callback_data=f"sel_{m['id']}"))
                    bot.send_message(message.chat.id, "🔍 মুভিটি সিলেক্ট করুন:", reply_markup=markup)

                @bot.callback_query_handler(func=lambda call: call.data.startswith('sel_'))
                def lang_select(call):
                    movie_id = call.data.split('_')[1]
                    markup = types.InlineKeyboardMarkup()
                    for l in ["Bangla", "Hindi", "English", "Multi"]:
                        markup.add(types.InlineKeyboardButton(text=l, callback_data=f"lang_{movie_id}_{l}"))
                    bot.edit_message_text("🌐 ভাষা সিলেক্ট করুন:", call.message.chat.id, call.message.message_id, reply_markup=markup)

                @bot.callback_query_handler(func=lambda call: call.data.startswith('lang_'))
                def ask_for_file(call):
                    _, mid, lang = call.data.split('_')
                    admin_states[call.from_user.id] = {'tmdb_id': mid, 'lang': lang}
                    bot.edit_message_text("📥 এবার মুভি ফাইলটি পাঠান...", call.message.chat.id, call.message.message_id)

                @bot.message_handler(content_types=['video', 'document'])
                def handle_movie_file(message):
                    conf = get_config()
                    uid = message.from_user.id
                    if uid in admin_states:
                        state = admin_states[uid]
                        sent_msg = bot.copy_message(int(conf['STORAGE_CHANNEL_ID']), message.chat.id, message.message_id)
                        movie_info = requests.get(f"https://api.themoviedb.org/3/movie/{state['tmdb_id']}?api_key={conf['TMDB_API_KEY']}").json()
                        movie_data = {
                            'tmdb_id': str(state['tmdb_id']), 'title': movie_info['title'], 'lang': state['lang'],
                            'file_id': sent_msg.message_id, 'poster': f"https://image.tmdb.org/t/p/w500{movie_info.get('poster_path')}"
                        }
                        movies_col.update_one({'tmdb_id': movie_data['tmdb_id']}, {'$set': movie_data}, upsert=True)
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
                        del admin_states[uid]

                bot.polling(none_stop=True)
            except:
                time.sleep(10)
        else:
            time.sleep(10)

# --- [অ্যাডমিন প্যানেল UI] ---
HTML_ADMIN = """
<!DOCTYPE html>
<html>
<head>
    <title>Bot Admin</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css">
</head>
<body class="container py-4 bg-light">
    <h3 class="text-center">🎬 Movie Bot Admin</h3>
    <div class="row">
        <div class="col-md-6 card p-3 shadow-sm">
            <h5>⚙️ Core Settings</h5>
            <form action="/save_config" method="POST">
                <input type="text" name="token" class="form-control mb-2" placeholder="Bot Token" value="{{ config.BOT_TOKEN }}">
                <input type="text" name="tmdb" class="form-control mb-2" placeholder="TMDB API" value="{{ config.TMDB_API_KEY }}">
                <input type="text" name="admin_id" class="form-control mb-2" placeholder="Admin ID" value="{{ config.ADMIN_ID }}">
                <input type="text" name="channel_id" class="form-control mb-2" placeholder="Storage Channel ID" value="{{ config.STORAGE_CHANNEL_ID }}">
                <button class="btn btn-primary w-100">Save & Restart</button>
            </form>
        </div>
        <div class="col-md-6 card p-3 shadow-sm">
            <h5>🔗 Shortener</h5>
            <form action="/save_shortener" method="POST">
                <input type="text" name="api_url" class="form-control mb-2" placeholder="API URL" value="{{ shortener.api_url }}">
                <input type="text" name="api_key" class="form-control mb-2" placeholder="API Key" value="{{ shortener.api_key }}">
                <select name="status" class="form-control mb-2">
                    <option value="on" {% if shortener.status == 'on' %}selected{% endif %}>ON</option>
                    <option value="off" {% if shortener.status == 'off' %}selected{% endif %}>OFF</option>
                </select>
                <button class="btn btn-success w-100">Save Shortener</button>
            </form>
        </div>
    </div>
</body>
</html>
"""

@app.route('/')
def home():
    return render_template_string(HTML_ADMIN, config=get_config(), shortener=get_shortener())

@app.route('/save_config', methods=['POST'])
def save_config():
    data = {'type': 'core_settings', 'BOT_TOKEN': request.form.get('token'), 'TMDB_API_KEY': request.form.get('tmdb'), 'ADMIN_ID': request.form.get('admin_id'), 'STORAGE_CHANNEL_ID': request.form.get('channel_id')}
    config_col.update_one({'type': 'core_settings'}, {'$set': data}, upsert=True)
    return redirect('/')

@app.route('/save_shortener', methods=['POST'])
def save_shortener():
    data = {'type': 'shortener', 'api_url': request.form.get('api_url'), 'api_key': request.form.get('api_key'), 'status': request.form.get('status')}
    settings_col.update_one({'type': 'shortener'}, {'$set': data}, upsert=True)
    return redirect('/')

# --- [ডিপ্লয়মেন্ট রানার] ---
if __name__ == '__main__':
    Thread(target=run_telegram_bot, daemon=True).start()
    # পোর্ট অটো চিনে নেওয়ার জন্য
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
