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
from datetime import datetime, timedelta

# ======================== WEB SERVER ========================
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is Running! Pro Batch Forwarder is Online."

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

# --- ইউটিলিটি ফাংশন ---
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
            try: requests.get(RENDER_URL, timeout=10)
            except: pass

# ======================== কমান্ড হ্যান্ডলারস ========================

@bot.on_message(filters.command("start") & filters.private)
async def start_handler(client, message):
    text = (
        "💎 **প্রো সিরিয়াল ব্যাচ ফরওয়ার্ডার**\n\n"
        "🛠 **সেটআপ কমান্ড:**\n"
        "`/set source_id target_id y-m-d-h-m-s total_limit batch` \n\n"
        "**উদাহরণ:** `/set -100111 -100222 0-0-0-0-0-30 5000 5` \n"
        "(এর মানে: প্রতি ৩০ সেকেন্ডে ৫টি করে মেসেজ যাবে, মোট ৫০০০টি পর্যন্ত)\n\n"
        "📜 **অন্যান্য কমান্ড:**\n"
        "• `/list` - সব সেটিংস ও প্রগ্রেস দেখতে\n"
        "• `/status` - কিউতে কত মেসেজ বাকি দেখতে\n"
        "• `/del source_id` - সোর্স মুছতে\n"
        "• `/clear_queue` - সব মেসেজ কিউ থেকে মুছতে"
    )
    await message.reply_text(text)

@bot.on_message(filters.command("set") & filters.user(ADMIN_ID))
async def set_mapping(client, message):
    try:
        args = message.text.split()
        if len(args) != 6:
            return await message.reply_text("❌ ফরম্যাট ভুল! \nইউজ: `/set source_id target_id 0-0-0-0-0-30 5000 5` \n(সোর্স, টার্গেট, ডিলে, টোটাল লিমিট, ব্যাচ লিমিট)")
        
        source, target, duration_str, total_limit, batch_limit = args[1], args[2], args[3], int(args[4]), int(args[5])
        delay = parse_duration(duration_str)

        await settings_col.update_one(
            {"source": str(source)},
            {"$set": {
                "target": str(target),
                "delay": delay,
                "total_limit": total_limit,
                "batch_limit": batch_limit,
                "forwarded_count": 0,
                "last_sent": 0,
                "duration_text": duration_str
            }},
            upsert=True
        )
        await message.reply_text(f"✅ **সেটআপ সফল!**\n\n📤 সোর্স: `{source}`\n📥 টার্গেট: `{target}`\n⏳ বিরতি: `{duration_str}`\n🔢 টোটাল লিমিট: `{total_limit}`\n📦 ব্যাচ প্রতি: `{batch_limit}` টি")
    except Exception as e:
        await message.reply_text(f"❌ এরর: {e}")

@bot.on_message(filters.command("list") & filters.user(ADMIN_ID))
async def list_mappings(client, message):
    cursor = settings_col.find({})
    configs = await cursor.to_list(length=100)
    if not configs: return await message.reply_text("📭 কোন সেটিংস নেই।")
    
    msg = "📋 **আপনার সেটিংস ও প্রগ্রেস:**\n\n"
    for c in configs:
        msg += (f"🔹 **Source:** `{c['source']}`\n"
                f"➔ **Target:** `{c['target']}`\n"
                f"⏱ **Delay:** {c['duration_text']} | **Batch:** {c['batch_limit']}\n"
                f"📊 **Progress:** {c['forwarded_count']}/{c['total_limit']}\n\n")
    await message.reply_text(msg)

@bot.on_message(filters.command("status") & filters.user(ADMIN_ID))
async def status_check(client, message):
    p_count = await queue_col.count_documents({"status": "pending"})
    await message.reply_text(f"⏳ **বর্তমান কিউ স্ট্যাটাস:**\n\n✅ ডাটাবেসে মোট `{p_count}` টি মেসেজ ফরওয়ার্ড হওয়ার অপেক্ষায় আছে।")

@bot.on_message(filters.command("del") & filters.user(ADMIN_ID))
async def delete_mapping(client, message):
    args = message.text.split()
    if len(args) < 2: return await message.reply_text("❌ সোর্স আইডি দিন।")
    await settings_col.delete_one({"source": str(args[1])})
    await message.reply_text(f"🗑️ সোর্স `{args[1]}` ডিলিট করা হয়েছে।")

@bot.on_message(filters.command("clear_queue") & filters.user(ADMIN_ID))
async def clear_queue_cmd(client, message):
    await queue_col.delete_many({})
    await message.reply_text("🧹 কিউ ক্লিয়ার করা হয়েছে।")

# ======================== লিসেনার (মেসেজ সংগ্রহ) ========================

@bot.on_message(filters.all & (filters.channel | filters.group))
async def message_listener(client, message):
    try:
        source_id = str(message.chat.id)
        config = await settings_col.find_one({"source": source_id})
        
        if config:
            # যদি টোটাল লিমিট শেষ হয়ে না থাকে
            if config['forwarded_count'] < config['total_limit']:
                await queue_col.insert_one({
                    "source_id": source_id,
                    "target_id": config['target'],
                    "message_id": message.id,
                    "status": "pending",
                    "timestamp": time.time()
                })
    except Exception as e:
        logger.error(f"Listener Error: {e}")

# ======================== ওয়ার্কার (সিরিয়াল ব্যাচ ফরওয়ার্ডিং) ========================

async def pro_forward_worker():
    while not bot.is_connected:
        await asyncio.sleep(1)

    logger.info("🚀 Pro Batch Forward Worker Started!")
    
    while True:
        try:
            current_time = time.time()
            cursor = settings_col.find({})
            
            async for config in cursor:
                source_id = config['source']
                target_id = config['target']
                last_sent = config.get("last_sent", 0)
                delay = config.get("delay", 0)
                total_limit = config.get("total_limit", 0)
                forwarded_count = config.get("forwarded_count", 0)
                batch_limit = config.get("batch_limit", 1)

                # ১. লিমিট চেক
                if forwarded_count >= total_limit:
                    continue

                # ২. সময় (Delay) চেক
                if current_time >= (last_sent + delay):
                    # কিউ থেকে মেসেজ বের করা (সিরিয়াল বজায় রাখতে message_id অনুযায়ী সর্ট)
                    pending_tasks = await queue_col.find({
                        "source_id": source_id,
                        "status": "pending"
                    }).sort("message_id", 1).limit(batch_limit).to_list(length=batch_limit)

                    if not pending_tasks:
                        continue

                    for task in pending_tasks:
                        try:
                            # লিমিট আবার চেক করছি লুপের ভেতর (নিরাপত্তার জন্য)
                            current_config = await settings_col.find_one({"source": source_id})
                            if current_config['forwarded_count'] >= total_limit:
                                break

                            await bot.copy_message(
                                chat_id=int(target_id),
                                from_chat_id=int(source_id),
                                message_id=int(task['message_id'])
                            )
                            
                            # প্রগ্রেস আপডেট
                            await queue_col.delete_one({"_id": task["_id"]})
                            await settings_col.update_one(
                                {"source": source_id},
                                {"$inc": {"forwarded_count": 1}}
                            )
                            await asyncio.sleep(2) # Flood avoidance

                        except errors.FloodWait as e:
                            await asyncio.sleep(e.value)
                        except Exception as e:
                            logger.error(f"Task Error: {e}")
                            await queue_col.delete_one({"_id": task["_id"]})

                    # ব্যাচ শেষ হলে সময় আপডেট
                    await settings_col.update_one(
                        {"source": source_id},
                        {"$set": {"last_sent": time.time()}}
                    )

        except Exception as e:
            logger.error(f"Worker Loop Error: {e}")
        
        await asyncio.sleep(5)

# ======================== মেইন রানার ========================

async def start_all():
    while True:
        try:
            if not bot.is_connected:
                await bot.start()
            
            if not hasattr(start_all, "tasks_started"):
                asyncio.create_task(pro_forward_worker())
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
