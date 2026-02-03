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

# ======================== WEB SERVER ========================
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is Running! Batch Serial Forwarder is Online."

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# ======================== কনফিগারেশন ========================
API_ID = 21572774                 
API_HASH = "822fd97cf105c7bfb23050f16b5a4754"       
BOT_TOKEN = "7923450713:AAFHz7vXc6M2i6Z6yc1JldIaLzSD3DdA5-s"     
MONGO_URL = "mongodb+srv://Demo270:Demo270@cluster0.ls1igsg.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"   
ADMIN_ID = 8186554166             

RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL", "")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

db_client = AsyncIOMotorClient(MONGO_URL)
db = db_client["AdvanceForwarderDB"]
settings_col = db["settings"]
queue_col = db["queue"]

bot = Client(
    "forwarder_pro",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    parse_mode=ParseMode.HTML
)

def parse_duration(duration_str):
    try:
        parts = list(map(int, duration_str.split('-')))
        if len(parts) != 6: return 0
        y, mo, d, h, m, s = parts
        total_seconds = (y * 31536000) + (mo * 2592000) + (d * 86400) + \
                        (h * 3600) + (m * 60) + s
        return total_seconds
    except:
        try: return int(duration_str.split('-')[-1])
        except: return 0

async def self_pinger():
    while True:
        await asyncio.sleep(300)
        if RENDER_URL:
            try:
                requests.get(RENDER_URL, timeout=10)
            except: pass

# ======================== কমান্ডস ========================

@bot.on_message(filters.command("start") & filters.private)
async def start_handler(client, message):
    text = (
        "🚀 **ব্যাচ সিরিয়াল ফরওয়ার্ডার বট**\n\n"
        "🛠 **সেটআপ:** `/set source_id target_id y-m-d-h-m-s batch_limit`\n"
        "**উদাহরণ:** `/set -100111 -100222 0-0-0-0-0-30 5` \n"
        "(প্রতি ৩০ সেকেন্ডে ৫টি করে মেসেজ যাবে)\n\n"
        "📜 `/list`, `/status`, `/del source_id`, `/clear_queue`"
    )
    await message.reply_text(text)

@bot.on_message(filters.command("set") & filters.user(ADMIN_ID))
async def set_mapping(client, message):
    try:
        args = message.text.split()
        if len(args) != 5:
            return await message.reply_text("❌ ফরম্যাট: `/set source_id target_id 0-0-0-0-0-30 5` (এখানে ৫ হলো ব্যাচ লিমিট)")
        
        source, target, duration_str, limit = args[1], args[2], args[3], int(args[4])
        delay = parse_duration(duration_str)

        await settings_col.update_one(
            {"source": str(source)},
            {"$set": {
                "target": str(target),
                "delay": delay,
                "batch_limit": limit,
                "last_sent": 0, # শেষ ফরওয়ার্ড করার সময়
                "duration_text": duration_str
            }},
            upsert=True
        )
        await message.reply_text(f"✅ **সেটআপ সফল!**\n\n📤 সোর্স: `{source}`\n📥 টার্গেট: `{target}`\n⏳ বিরতি: `{duration_str}`\n🔢 ব্যাচ লিমিট: `{limit}`")
    except Exception as e:
        await message.reply_text(f"❌ এরর: {e}")

@bot.on_message(filters.command("list") & filters.user(ADMIN_ID))
async def list_mappings(client, message):
    cursor = settings_col.find({})
    configs = await cursor.to_list(length=100)
    if not configs: return await message.reply_text("📭 লিস্ট খালি।")
    msg = "📋 **আপনার সেটিংস:**\n\n"
    for c in configs:
        msg += f"• `{c['source']}` ➔ `{c['target']}`\n  বিরতি: {c['duration_text']} | ব্যাচ: {c['batch_limit']}টি\n\n"
    await message.reply_text(msg)

@bot.on_message(filters.command("clear_queue") & filters.user(ADMIN_ID))
async def clear_queue_cmd(client, message):
    await queue_col.delete_many({})
    await message.reply_text("🧹 কিউ থেকে সব পেন্ডিং মেসেজ ডিলিট করা হয়েছে।")

# ======================== লিসেনার: মেসেজ সেভ করা ========================

@bot.on_message(filters.all & (filters.channel | filters.group))
async def message_listener(client, message):
    try:
        source_id = str(message.chat.id)
        config = await settings_col.find_one({"source": source_id})
        
        if config:
            # শুধু ডাটাবেসে সেভ করা হচ্ছে, টাইমিং ওয়ার্কার হ্যান্ডেল করবে
            await queue_col.insert_one({
                "source_id": source_id,
                "target_id": config['target'],
                "message_id": message.id,
                "status": "pending",
                "timestamp": time.time() # ইনসার্ট টাইম
            })
            # logger.info(f"📥 Message {message.id} added to queue from {source_id}")
    except Exception as e:
        logger.error(f"Listener Error: {e}")

# ======================== ওয়ার্কার: ব্যাচ ফরওয়ার্ডিং লজিক ========================

async def batch_forward_worker():
    while not bot.is_connected:
        await asyncio.sleep(1)

    logger.info("🚀 Batch Forward Worker Started!")
    
    while True:
        try:
            current_time = time.time()
            # সব সোর্স কনফিগারেশন চেক করা
            cursor = settings_col.find({})
            async for config in cursor:
                last_sent = config.get("last_sent", 0)
                delay = config.get("delay", 0)
                
                # যদি ডিলে সময় পার হয়ে যায়
                if current_time >= (last_sent + delay):
                    source_id = config['source']
                    batch_limit = config.get('batch_limit', 1)
                    
                    # কিউ থেকে ওই সোর্সের মেসেজ তোলা (সিরিয়াল অনুযায়ী: message_id 1)
                    pending_messages = await queue_col.find({
                        "source_id": source_id,
                        "status": "pending"
                    }).sort("message_id", 1).limit(batch_limit).to_list(length=batch_limit)

                    if not pending_messages:
                        continue

                    logger.info(f"📦 Processing batch for {source_id}: {len(pending_messages)} messages")

                    for task in pending_messages:
                        try:
                            await bot.copy_message(
                                chat_id=int(task['target_id']),
                                from_chat_id=int(task['source_id']),
                                message_id=int(task['message_id'])
                            )
                            # ফরওয়ার্ড সফল হলে কিউ থেকে ডিলিট
                            await queue_col.delete_one({"_id": task["_id"]})
                            await asyncio.sleep(1.5) # প্রতি মেসেজের মাঝে ছোট গ্যাপ (টেলিগ্রাম লিমিট এড়াতে)
                        except errors.FloodWait as e:
                            await asyncio.sleep(e.value)
                        except Exception as e:
                            logger.error(f"Forwarding Error: {e}")
                            await queue_col.delete_one({"_id": task["_id"]})

                    # ব্যাচ পাঠানো শেষ হলে 'last_sent' আপডেট করা
                    await settings_col.update_one(
                        {"source": source_id},
                        {"$set": {"last_sent": time.time()}}
                    )

        except Exception as e:
            logger.error(f"Worker Loop Error: {e}")
        
        await asyncio.sleep(5) # প্রতি ৫ সেকেন্ড পর পর চেক করবে পরবর্তী ব্যাচের সময় হয়েছে কি না

# ======================== রানার ========================

async def start_all():
    while True:
        try:
            if not bot.is_connected:
                await bot.start()
            
            if not hasattr(start_all, "tasks_started"):
                asyncio.create_task(batch_forward_worker())
                asyncio.create_task(self_pinger())
                start_all.tasks_started = True
            
            while bot.is_connected:
                await asyncio.sleep(60)
        except Exception as e:
            logger.error(f"Restarting... {e}")
            await asyncio.sleep(10)

if __name__ == "__main__":
    threading.Thread(target=run_web_server, daemon=True).start()
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(start_all())
    except KeyboardInterrupt:
        pass
