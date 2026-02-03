import asyncio
import logging
import time
from pyrogram import Client, filters, errors
from pyrogram.enums import ParseMode
from motor.motor_asyncio import AsyncIOMotorClient

# ======================== কনফিগারেশন ========================
API_ID = 21572774                 # আপনার API ID
API_HASH = "822fd97cf105c7bfb23050f16b5a4754"       # আপনার API HASH
BOT_TOKEN = "7923450713:AAFHz7vXc6M2i6Z6yc1JldIaLzSD3DdA5-s"     # আপনার BOT TOKEN
MONGO_URL = "mongodb+srv://Demo270:Demo270@cluster0.ls1igsg.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"   # আপনার MongoDB URI
ADMIN_ID = 8186554166             # আপনার ইউজার আইডি
# ==========================================================

# লগিং সেটআপ
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# ডাটাবেস কানেকশন
db_client = AsyncIOMotorClient(MONGO_URL)
db = db_client["AdvanceForwarderDB"]
settings_col = db["settings"]
queue_col = db["queue"]

# বট ক্লায়েন্ট ইনিশিয়ালাইজেশন
app = Client(
    "forwarder_pro",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    parse_mode=ParseMode.HTML
)

# সময়কে সেকেন্ডে রূপান্তর করার ফাংশন (Y-M-D-H-M-S)
def parse_duration(duration_str):
    try:
        parts = list(map(int, duration_str.split('-')))
        if len(parts) != 6: return 0
        y, mo, d, h, m, s = parts
        # ১ বছর = ৩৬৫ দিন, ১ মাস = ৩০ দিন হিসাবে সেকেন্ড
        total_seconds = (y * 31536000) + (mo * 2592000) + (d * 86400) + (h * 3600) + (m * 60) + s
        return total_seconds
    except Exception:
        return 0

# --- কমান্ড হ্যান্ডলারস ---

@app.on_message(filters.command("start") & filters.private)
async def start_handler(client, message):
    help_text = (
        "💎 **প্রো সিরিয়াল টাইমড ফরওয়ার্ডার বট**\n\n"
        "🛠 **সেটআপ করার কমান্ড:**\n"
        "`/set source_id target_id y-m-d-h-m-s limit`\n"
        "**উদাহরণ:** `/set -100111 -100222 0-0-0-0-0-30 5000` \n"
        "*(এর মানে ৩০ সেকেন্ড দেরি করে সিরিয়াল অনুযায়ী ৫০০০ ফাইল যাবে)*\n\n"
        "📜 **অন্যান্য কমান্ড:**\n"
        "• `/del source_id` - সোর্স চ্যানেল সেটিংস মুছতে\n"
        "• `/list` - সব সোর্স চ্যানেলের লিস্ট দেখতে\n"
        "• `/status` - কিউতে কতটি ফাইল জমা আছে দেখতে\n"
        "• `/clear_queue` - পেন্ডিং সব ফাইল মুছে ফেলতে"
    )
    await message.reply_text(help_text)

@app.on_message(filters.command("set") & filters.user(ADMIN_ID))
async def set_handler(client, message):
    try:
        args = message.text.split()
        if len(args) != 5:
            return await message.reply_text("❌ ফরম্যাট ভুল! সঠিক নিয়ম:\n`/set -100xxx -100yyy 0-0-0-0-1-0 1000`")
        
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
        await message.reply_text(f"✅ **সেটআপ সফল!**\n\n📤 সোর্স: `{source}`\n📥 টার্গেট: `{target}`\n⏳ দেরি: `{duration_str}`\n🔢 লিমিট: `{limit}`")
    except Exception as e:
        await message.reply_text(f"❌ এরর: {e}")

@app.on_message(filters.command("del") & filters.user(ADMIN_ID))
async def del_handler(client, message):
    args = message.text.split()
    if len(args) < 2: return await message.reply_text("❌ সোর্স আইডি দিন।")
    res = await settings_col.delete_one({"source": args[1]})
    if res.deleted_count:
        await message.reply_text(f"🗑️ সোর্স `{args[1]}` ডিলিট করা হয়েছে।")
    else:
        await message.reply_text("❌ এই আইডিটি লিস্টে নেই।")

@app.on_message(filters.command("list") & filters.user(ADMIN_ID))
async def list_handler(client, message):
    cursor = settings_col.find({})
    configs = await cursor.to_list(length=100)
    if not configs: return await message.reply_text("📭 লিস্ট খালি।")
    msg = "📋 **আপনার সক্রিয় সেটিংস:**\n\n"
    for c in configs:
        msg += f"• `{c['source']}` ➔ `{c['target']}`\n  দেরি: {c['duration_text']} | লিমিট: {c['count']}/{c['limit']}\n\n"
    await message.reply_text(msg)

@app.on_message(filters.command("status") & filters.user(ADMIN_ID))
async def status_handler(client, message):
    p_count = await queue_col.count_documents({"status": "pending"})
    f_count = await queue_col.count_documents({"status": "failed"})
    await message.reply_text(f"⏳ **কিউ স্ট্যাটাস:**\n\n✅ পেন্ডিং: {p_count} টি\n❌ ফেইল্ড: {f_count} টি")

@app.on_message(filters.command("clear_queue") & filters.user(ADMIN_ID))
async def clear_handler(client, message):
    await queue_col.delete_many({})
    await message.reply_text("🧹 কিউ থেকে সব পেন্ডিং মেসেজ মুছে ফেলা হয়েছে।")

# --- ফাইল চ্যানেলে নতুন মেসেজ আসলে তা ডাটাবেসে সেভ করা ---

@app.on_message(filters.chat() & ~filters.user(ADMIN_ID))
async def message_listener(client, message):
    source_id = str(message.chat.id)
    # চেক করা এই চ্যানেলটি সেট করা আছে কি না
    config = await settings_col.find_one({"source": source_id})
    
    if config:
        # লিমিট চেক
        if config['count'] >= config['limit']:
            return

        # পাঠাবার সঠিক সময় নির্ধারণ (বর্তমান সময় + ইউজারের ডিলে)
        scheduled_at = time.time() + config['delay']
        
        # কিউতে সেভ করা
        await queue_col.insert_one({
            "source_id": source_id,
            "target_id": config['target'],
            "message_id": message.id,
            "send_at": scheduled_at,
            "status": "pending"
        })
        logger.info(f"Message ID {message.id} added to queue for {source_id}")

# --- ব্যাকগ্রাউন্ড ওয়ার্কার (এটি আসল ফরওয়ার্ডিং করবে) ---

async def forward_worker():
    while True:
        try:
            current_time = time.time()
            # সময় হয়েছে এমন পেন্ডিং মেসেজগুলো বের করা (সিরিয়াল বজায় রাখতে ID দিয়ে সর্ট করা)
            cursor = queue_col.find({
                "send_at": {"$lte": current_time},
                "status": "pending"
            }).sort("message_id", 1) # strict serial logic 1, 2, 3...

            async for task in cursor:
                try:
                    # ফাইল হুবহু কপি করা (সব মিডিয়া, টেক্সট, ডিজাইন সহ)
                    await app.copy_message(
                        chat_id=int(task['target_id']),
                        from_chat_id=int(task['source_id']),
                        message_id=task['message_id']
                    )
                    
                    # সফল হলে ডাটাবেস থেকে মুছে ফেলা এবং কাউন্ট বাড়ানো
                    await queue_col.delete_one({"_id": task["_id"]})
                    await settings_col.update_one(
                        {"source": task['source_id']}, 
                        {"$inc": {"count": 1}}
                    )
                    
                    logger.info(f"Successfully copied message {task['message_id']} to {task['target_id']}")
                    # টেলিগ্রাম ফ্লড প্রোটেকশন
                    await asyncio.sleep(2.0)
                    
                except errors.FloodWait as e:
                    logger.warning(f"FloodWait: Sleeping for {e.value} seconds")
                    await asyncio.sleep(e.value)
                except Exception as e:
                    logger.error(f"Copy Error for ID {task['message_id']}: {e}")
                    # ফেইল হলে স্ট্যাটাস আপডেট করা যাতে লুপে বারবার না আসে
                    await queue_col.update_one({"_id": task["_id"]}, {"$set": {"status": "failed"}})

        except Exception as e:
            logger.error(f"Worker Main Loop Error: {e}")
        
        # প্রতি ৩ সেকেন্ড পর পর ডাটাবেস চেক করবে নতুন মেসেজ আছে কি না
        await asyncio.sleep(3)

# --- রান ফাংশন ---

async def main():
    logger.info("Initializing Forwarder Bot...")
    await app.start()
    logger.info("Bot is Running. Monitoring channels...")
    
    # ব্যাকগ্রাউন্ড ওয়ার্কার টাস্ক শুরু করা
    asyncio.create_task(forward_worker())
    
    # বট অনলাইন রাখা
    await asyncio.Event().wait()

if __name__ == "__main__":
    try:
        app.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot Stopped Manually.")
