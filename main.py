import asyncio
import logging
import time
import threading
import os
import sys
import requests
from flask import Flask
from pyrogram import Client, filters, errors
from pyrogram.enums import ParseMode
from motor.motor_asyncio import AsyncIOMotorClient

# ======================== WEB SERVER (For Render) ========================
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is Running! Serial Forwarder is Online and Stable."

def run_web_server():
    # Render-এর পোর্ট হ্যান্ডেল করার জন্য
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# ======================== কনফিগারেশন ========================
API_ID = 21572774                 
API_HASH = "822fd97cf105c7bfb23050f16b5a4754"       
BOT_TOKEN = "7923450713:AAFHz7vXc6M2i6Z6yc1JldIaLzSD3DdA5-s"     
MONGO_URL = "mongodb+srv://Demo270:Demo270@cluster0.ls1igsg.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"   
ADMIN_ID = 8186554166             

# Render-এর ড্যাশবোর্ড থেকে URL টি নিলে ভালো, নাহলে এটি অটো-ডিটেক্ট করার চেষ্টা করবে
RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL", "")

# ==========================================================

# লগিং সেটআপ
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# ডাটাবেস সেটআপ
db_client = AsyncIOMotorClient(MONGO_URL)
db = db_client["AdvanceForwarderDB"]
settings_col = db["settings"]
queue_col = db["queue"]

# টেলিগ্রাম বট ক্লায়েন্ট
bot = Client(
    "forwarder_pro",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    parse_mode=ParseMode.HTML
)

# --- সময় পার্স করার ফাংশন (Y-M-D-H-M-S to Seconds) ---
def parse_duration(duration_str):
    try:
        parts = list(map(int, duration_str.split('-')))
        if len(parts) != 6: return 0
        y, mo, d, h, m, s = parts
        total_seconds = (y * 31536000) + (mo * 2592000) + (d * 86400) + \
                        (h * 3600) + (m * 60) + s
        return total_seconds
    except:
        # যদি ফরম্যাট ভুল হয় তবে অন্তত সেকেন্ড পার্টটা চেক করবে
        try: return int(duration_str.split('-')[-1])
        except: return 0

# --- সেলফ-পিঙ্গার (বটকে স্লিপ হওয়া থেকে বাঁচাতে) ---
async def self_pinger():
    while True:
        await asyncio.sleep(300) # প্রতি ৫ মিনিট
        if RENDER_URL:
            try:
                requests.get(RENDER_URL, timeout=10)
                logger.info("Self-Ping Successful.")
            except Exception as e:
                logger.error(f"Self-Ping Error: {e}")

# --- কমান্ড হ্যান্ডলারস ---

@bot.on_message(filters.command("start") & filters.private)
async def start_handler(client, message):
    text = (
        "💎 **প্রো সিরিয়াল টাইমড ফরওয়ার্ডার বট**\n\n"
        "🛠 **সেটআপ কমান্ড:**\n"
        "`/set source_id target_id y-m-d-h-m-s limit`\n"
        "**উদাহরণ:** `/set -100111 -100222 0-0-0-0-0-30 5000` \n"
        "*(৩০ সেকেন্ড ডিলে করে সিরিয়াল অনুযায়ী ৫০০০ ফাইল যাবে)*\n\n"
        "📜 **অন্যান্য কমান্ড:**\n"
        "• `/del source_id` - সোর্স চ্যানেল মুছতে\n"
        "• `/list` - সব সেটিংস দেখতে\n"
        "• `/status` - কিউ স্ট্যাটাস দেখতে\n"
        "• `/clear_queue` - সব কিউ মুছতে"
    )
    await message.reply_text(text)

@bot.on_message(filters.command("set") & filters.user(ADMIN_ID))
async def set_mapping(client, message):
    try:
        args = message.text.split()
        if len(args) != 5:
            return await message.reply_text("❌ ফরম্যাট: `/set source_id target_id 0-0-0-0-0-30 5000`")
        
        source, target, duration_str, limit = args[1], args[2], args[3], int(args[4])
        delay = parse_duration(duration_str)

        await settings_col.update_one(
            {"source": source},
            {"$set": {
                "target": target,
                "delay": delay,
                "limit": limit,
                "count": 0,
                "duration_text": duration_str
            }},
            upsert=True
        )
        await message.reply_text(f"✅ **সেটআপ সফল!**\n\n📤 সোর্স: `{source}`\n📥 টার্গেট: `{target}`\n⏳ ডিলে: `{duration_str}`\n🔢 লিমিট: `{limit}`")
    except Exception as e:
        await message.reply_text(f"❌ এরর: {e}")

@bot.on_message(filters.command("del") & filters.user(ADMIN_ID))
async def delete_mapping(client, message):
    args = message.text.split()
    if len(args) < 2:
        return await message.reply_text("❌ সোর্স আইডি দিন।")
    res = await settings_col.delete_one({"source": args[1]})
    if res.deleted_count:
        await message.reply_text(f"🗑️ সোর্স `{args[1]}` ডিলিট করা হয়েছে।")
    else:
        await message.reply_text("❌ আইডিটি ডাটাবেসে নেই।")

@bot.on_message(filters.command("list") & filters.user(ADMIN_ID))
async def list_mappings(client, message):
    cursor = settings_col.find({})
    configs = await cursor.to_list(length=100)
    if not configs:
        return await message.reply_text("📭 লিস্ট খালি।")
    msg = "📋 **আপনার সেটিংস লিস্ট:**\n\n"
    for c in configs:
        msg += f"• `{c['source']}` ➔ `{c['target']}`\n  ডিলে: {c['duration_text']} | লিমিট: {c['count']}/{c['limit']}\n\n"
    await message.reply_text(msg)

@bot.on_message(filters.command("status") & filters.user(ADMIN_ID))
async def status_check(client, message):
    p_count = await queue_col.count_documents({"status": "pending"})
    await message.reply_text(f"⏳ **কিউ স্ট্যাটাস:**\n\n✅ পেন্ডিং মেসেজ: {p_count} টি")

@bot.on_message(filters.command("clear_queue") & filters.user(ADMIN_ID))
async def clear_queue_cmd(client, message):
    await queue_col.delete_many({})
    await message.reply_text("🧹 কিউ থেকে সব পেন্ডিং মেসেজ মুছে ফেলা হয়েছে।")

# --- ফাইল সেভ লজিক ---

@bot.on_message(filters.chat() & ~filters.user(ADMIN_ID))
async def message_listener(client, message):
    source_id = str(message.chat.id)
    config = await settings_col.find_one({"source": source_id})
    
    if config:
        if config['count'] >= config['limit']:
            return

        scheduled_time = time.time() + config['delay']
        
        await queue_col.insert_one({
            "source_id": source_id,
            "target_id": config['target'],
            "message_id": message.id,
            "send_at": scheduled_time,
            "status": "pending"
        })

# --- ফরওয়ার্ডিং ওয়ার্কার (সিরিয়াল মেইনটেইন করে) ---

async def forward_worker():
    while True:
        try:
            current_time = time.time()
            # সিরিয়াল বজায় রাখতে message_id দিয়ে সর্টিং
            cursor = queue_col.find({
                "send_at": {"$lte": current_time},
                "status": "pending"
            }).sort("message_id", 1)

            async for task in cursor:
                try:
                    await bot.copy_message(
                        chat_id=int(task['target_id']),
                        from_chat_id=int(task['source_id']),
                        message_id=task['message_id']
                    )
                    
                    await queue_col.delete_one({"_id": task["_id"]})
                    await settings_col.update_one(
                        {"source": task['source_id']}, 
                        {"$inc": {"count": 1}}
                    )
                    
                    logger.info(f"Forwarded: {task['message_id']}")
                    await asyncio.sleep(2.0) # স্প্যাম প্রোটেকশন
                    
                except errors.FloodWait as e:
                    await asyncio.sleep(e.value)
                except Exception as e:
                    logger.error(f"Forward Error: {e}")
                    await queue_col.update_one({"_id": task["_id"]}, {"$set": {"status": "failed"}})

        except Exception as e:
            logger.error(f"Worker Loop Error: {e}")
        
        await asyncio.sleep(5)

# --- স্টার্ট অল (অটো রিস্টার্ট লজিক সহ) ---

async def start_all():
    while True:
        try:
            if not bot.is_connected:
                await bot.start()
            
            logger.info("Bot is Online!")
            
            # ব্যাকগ্রাউন্ড ওয়ার্কার ও পিঙ্গার চালু করা
            asyncio.create_task(forward_worker())
            asyncio.create_task(self_pinger())
            
            # বট চালু রাখা
            while bot.is_connected:
                await asyncio.sleep(60)
                
        except Exception as e:
            logger.error(f"Restarting bot due to error: {e}")
            await asyncio.sleep(10)
            continue

if __name__ == "__main__":
    # ১. ওয়েব সার্ভার আলাদা থ্রেডে চালানো
    threading.Thread(target=run_web_server, daemon=True).start()
    
    # ২. ইভেন্ট লুপ রান করা
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(start_all())
    except KeyboardInterrupt:
        logger.info("Bot Stopped Manually.")
