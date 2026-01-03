import logging
import requests
import os
import json
import uuid
import sys
import subprocess
from threading import Thread

# ================= AUTO-INSTALL FLASK =================
try:
    from flask import Flask
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "flask"])
    from flask import Flask

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    ApplicationBuilder, 
    ContextTypes, 
    CommandHandler, 
    MessageHandler, 
    CallbackQueryHandler,
    filters, 
    ConversationHandler,
    Application  # <--- FIXED: Added this missing import
)

# ================= KEEP ALIVE SERVER =================
flask_app = Flask('')

@flask_app.route('/')
def home():
    return "Radar is Online & Crash Proof!"

def run_http():
    flask_app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run_http)
    t.start()

# ================= CONFIGURATION =================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GATEKEEPER_ID = os.environ.get("GATEKEEPER_GROUP_ID") 
MASTER_PASSWORD = os.environ.get("MASTER_PASSWORD") 
VIP_GROUP_NAME = "OTB-chat"
DB_FILE = "alerts_db.json"

# Wizard States
ASK_ADDRESS, ASK_TARGET = range(2)

logging.basicConfig(level=logging.INFO)

# ================= DATABASE ENGINE =================
def load_alerts_from_disk():
    if not os.path.exists(DB_FILE): return []
    try:
        with open(DB_FILE, 'r') as f: return json.load(f)
    except: return []

def save_alert_to_disk(alert_data):
    alerts = load_alerts_from_disk()
    alerts.append(alert_data)
    with open(DB_FILE, 'w') as f: json.dump(alerts, f)

def remove_alert_from_disk(job_name):
    alerts = load_alerts_from_disk()
    new_alerts = [a for a in alerts if a['job_name'] != job_name]
    with open(DB_FILE, 'w') as f: json.dump(new_alerts, f)

# ================= HELPER FUNCTIONS =================
def parse_human_number(text):
    text = text.upper().replace('$', '').replace(',', '')
    multiplier = 1
    if text.endswith('K'): multiplier = 1_000
    elif text.endswith('M'): multiplier = 1_000_000
    elif text.endswith('B'): multiplier = 1_000_000_000
    try:
        clean_text = text.rstrip('KMB')
        return float(clean_text) * multiplier
    except: return None

def format_currency(value):
    if value >= 1_000_000: return f"${value/1_000_000:.2f}M"
    elif value >= 1_000: return f"${value:,.0f}"
    elif value >= 1: return f"${value:,.2f}"
    else: return f"${value:.4f}"

async def self_destruct_job(context: ContextTypes.DEFAULT_TYPE):
    msg = context.job.data
    try: await msg.delete()
    except: pass

# ================= AUTH ENGINE =================
def is_admin_override(user_id):
    try:
        if os.path.exists('admins.json'):
            with open('admins.json', 'r') as f:
                admins = json.load(f)
                return str(user_id) in admins
    except: pass
    return False

def add_admin(user_id):
    admins = []
    try:
        if os.path.exists('admins.json'):
            with open('admins.json', 'r') as f: admins = json.load(f)
    except: pass
    if str(user_id) not in admins:
        admins.append(str(user_id))
        with open('admins.json', 'w') as f: json.dump(admins, f)

async def check_access(context: ContextTypes.DEFAULT_TYPE, user_id: int):
    if is_admin_override(user_id): return True, None
    if not GATEKEEPER_ID: return False, "⚠️ System Error: GATEKEEPER_GROUP_ID missing."
    try:
        member = await context.bot.get_chat_member(chat_id=GATEKEEPER_ID, user_id=user_id)
        if member.status in ['member', 'administrator', 'creator']: return True, None
        else: return False, f"❌ Access Denied: You must be a member of <b>{VIP_GROUP_NAME}</b>."
    except Exception as e:
        if "Member not found" in str(e): return False, f"⚠️ Config Error: Bot checked Group ID <code>{GATEKEEPER_ID}</code> but failed."
        return False, f"⚠️ Verification Failed: {e}"

# ================= DATA ENGINE =================
def get_token_data(address):
    try:
        url = f"https://api.dexscreener.com/latest/dex/tokens/{address}"
        data = requests.get(url, timeout=10).json()
        if data.get('pairs'):
            pair = data['pairs'][0]
            mc = pair.get('marketCap') or pair.get('fdv') or 0
            if mc == 0 and address.endswith("pump"): 
                mc = float(pair.get('priceUsd', 0)) * 1_000_000_000
            return {"mc": float(mc), "symbol": pair['baseToken']['symbol'], "price": float(pair.get('priceUsd', 0))}
    except: pass
    return None

# ================= CORE LOGIC =================
async def check_alerts(context: ContextTypes.DEFAULT_TYPE):
    job = context.job.data
    job_name = context.job.name
    data = get_token_data(job['address'])
    if data and data['mc'] > 0:
        hit = False
        if job['cond'] == 'above' and data['mc'] >= job['target']: hit = True
        elif job['cond'] == 'below' and data['mc'] <= job['target']: hit = True
        if hit:
            emoji = "🚀" if job['cond'] == 'above' else "🔻"
            user_tag = f"<a href='tg://user?id={job['user_id']}'>{job['user_name']}</a>"
            fmt_target = format_currency(job['target'])
            fmt_mc = format_currency(data['mc'])
            msg = (f"{emoji} <b>OFFTHEBLOCK ALERT</b>\n🔔 Set by: {user_tag}\n\n💎 <b>{data['symbol']}</b>\nTarget: {fmt_target}\nCurrent MC: <b>{fmt_mc}</b>\nPrice: ${data['price']:.6f}")
            try: await context.bot.send_message(job['chat_id'], msg, parse_mode='HTML')
            except: pass
            remove_alert_from_disk(job_name)
            context.job.schedule_removal()

def create_alert_job(context, chat_id, user_id, user_name, address, target_mc, cond, symbol, job_name=None):
    if not job_name:
        job_name = str(uuid.uuid4())
        alert_data = {'job_name': job_name, 'chat_id': chat_id, 'user_id': user_id, 'user_name': user_name, 'address': address, 'target': target_mc, 'cond': cond, 'symbol': symbol}
        save_alert_to_disk(alert_data)
    context.job_queue.run_repeating(check_alerts, interval=30, first=1, name=job_name, data={'chat_id': chat_id, 'user_id': user_id, 'user_name': user_name, 'address': address, 'target': target_mc, 'cond': cond, 'symbol': symbol})

# ================= INDEPENDENT COMMANDS =================

async def list_alerts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat = update.effective_chat
    
    # 1. Redirect Group to DM
    if chat.type in ['group', 'supergroup']:
        try: await update.message.delete()
        except: pass
        try:
            bot_username = context.bot.username or (await context.bot.get_me()).username
            deep_link = f"https://t.me/{bot_username}?start=manage"
            keyboard = [[InlineKeyboardButton("📂 Manage in DM", url=deep_link)]]
            msg = await context.bot.send_message(chat_id=chat.id, text="👇 View active alerts:", reply_markup=InlineKeyboardMarkup(keyboard))
            context.job_queue.run_once(self_destruct_job, 30, data=msg)
        except: pass
        return

    # 2. Show List (in DM)
    # 🔥 CRITICAL FIX: Only check 'user_id' if data is a dictionary (ignoring cleanup jobs)
    active_jobs = [
        j for j in context.job_queue.jobs() 
        if isinstance(j.data, dict) and j.data.get('user_id') == user_id
    ]

    if not active_jobs:
        await update.message.reply_text("📭 You have no active alerts.")
        return
    keyboard = []
    for job in active_jobs:
        data = job.data
        symbol = data.get('symbol', 'TOKEN')
        target = format_currency(data['target'])
        btn_text = f"{symbol}: {target} ❌"
        callback_data = f"DEL_{job.name}" 
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=callback_data)])
    await update.message.reply_text("📋 <b>Your Active Alerts:</b>\nTap to delete.", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

async def handle_alert_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data.startswith("DEL_"):
        job_name = data.split("DEL_")[1]
        jobs = context.job_queue.get_jobs_by_name(job_name)
        if jobs:
            for job in jobs: job.schedule_removal()
            remove_alert_from_disk(job_name)
            await query.edit_message_text(f"✅ Alert deleted.")
        else: await query.edit_message_text("⚠️ Alert already removed or expired.")

async def override_login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try: await update.message.delete()
    except: pass
    if context.args and context.args[0] == MASTER_PASSWORD:
        add_admin(update.effective_user.id)
        msg = await context.bot.send_message(chat_id=update.effective_chat.id, text="🔓 <b>Master Override Active.</b>", parse_mode='HTML')
        context.job_queue.run_once(self_destruct_job, 5, data=msg)

async def get_id_secure(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    try:
        member = await context.bot.get_chat_member(chat_id=chat.id, user_id=user.id)
        if member.status not in ['administrator', 'creator']:
            try: await update.message.delete()
            except: pass
            return
    except: return
    chat_id = str(chat.id)
    secret_id = str(GATEKEEPER_ID)
    status = "✅ <b>MATCH!</b>" if chat_id == secret_id else f"❌ <b>MISMATCH!</b>\nUpdate Secret to: <code>{chat_id}</code>"
    msg = await context.bot.send_message(chat_id=chat.id, text=f"Group ID: <code>{chat_id}</code>\n{status}", parse_mode='HTML')
    context.job_queue.run_once(self_destruct_job, 60, data=msg)

# ================= WIZARD HANDLERS =================

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args and context.args[0] == 'manage':
        await list_alerts(update, context)
        return ConversationHandler.END
    return await alert_entry(update, context)

async def alert_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat = update.effective_chat
    allowed, fail_reason = await check_access(context, user_id)
    if not allowed:
        try: await update.message.delete()
        except: pass
        msg = await context.bot.send_message(chat_id=chat.id, text=fail_reason, parse_mode='HTML')
        context.job_queue.run_once(self_destruct_job, 20, data=msg)
        return ConversationHandler.END

    if chat.type in ['group', 'supergroup']:
        try: await update.message.delete()
        except: pass
        if context.args and len(context.args) >= 2:
            await run_quick_alert(update, context, chat.id)
            return ConversationHandler.END
        try:
            bot_username = context.bot.username or (await context.bot.get_me()).username
            deep_link = f"https://t.me/{bot_username}?start={chat.id}"
            keyboard = [[InlineKeyboardButton("🛠️ Configure in DM", url=deep_link)]]
            msg = await context.bot.send_message(chat_id=chat.id, text="👇 Tap to configure:", reply_markup=InlineKeyboardMarkup(keyboard))
            context.job_queue.run_once(self_destruct_job, 30, data=msg)
        except: pass
        return ConversationHandler.END

    if chat.type == 'private':
        if context.args and len(context.args) > 0 and context.args[0].replace('-', '').isdigit():
            context.user_data['target_group_id'] = context.args[0]
        if 'target_group_id' not in context.user_data:
            context.user_data['target_group_id'] = GATEKEEPER_ID
        await update.message.reply_text("✅ <b>Setup Mode</b>\n\nPaste the <b>Contract Address (CA)</b>:", parse_mode='HTML')
        return ASK_ADDRESS

async def run_quick_alert(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id):
    try:
        args = context.args
        address = args[0]
        target_mc = parse_human_number(args[1])
        if not target_mc: return
        token_data = get_token_data(address)
        if not token_data:
            msg = await context.bot.send_message(chat_id=chat_id, text="❌ Token not found.")
            context.job_queue.run_once(self_destruct_job, 5, data=msg)
            return
        user = update.effective_user
        cond = 'above' if target_mc > token_data['mc'] else 'below'
        create_alert_job(context, chat_id, user.id, user.first_name, address, target_mc, cond, token_data['symbol'])
        fmt_target = format_currency(target_mc)
        confirm_msg = await context.bot.send_message(chat_id=chat_id, text=f"✅ Alert set, I'll notify you when market cap for <b>{token_data['symbol']}</b> is at <b>{fmt_target}</b>.", parse_mode='HTML')
        context.job_queue.run_once(self_destruct_job, 10, data=confirm_msg)
    except: pass

async def receive_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    address = update.message.text.strip()
    data = get_token_data(address)
    if not data:
        await update.message.reply_text("❌ Token not found. Try again:")
        return ASK_ADDRESS
    context.user_data['address'] = address
    context.user_data['symbol'] = data['symbol']
    context.user_data['current_mc'] = data['mc']
    fmt_mc = format_currency(data['mc'])
    await update.message.reply_text(f"👍 Found <b>{data['symbol']}</b> (MC: {fmt_mc})\n\nSend <b>Target Market Cap</b> (e.g. 1.7M, 500k):", parse_mode='HTML')
    return ASK_TARGET

async def receive_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    target_mc = parse_human_number(text)
    if not target_mc:
        await update.message.reply_text("❌ Invalid format. Use '1M', '500k'. Try again:")
        return ASK_TARGET
    group_id = context.user_data.get('target_group_id', GATEKEEPER_ID)
    current_mc = context.user_data['current_mc']
    cond = 'above' if target_mc > current_mc else 'below'
    user = update.effective_user
    create_alert_job(context, group_id, user.id, user.first_name, context.user_data['address'], target_mc, cond, context.user_data['symbol'])
    fmt_target = format_currency(target_mc)
    await update.message.reply_text(f"✅ Alert set, I'll notify you when market cap for <b>{context.user_data['symbol']}</b> is at <b>{fmt_target}</b>.", parse_mode='HTML')
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Cancelled.")
    return ConversationHandler.END

async def post_init(application: Application):
    alerts = load_alerts_from_disk()
    print(f"🔄 Restoring {len(alerts)} alerts...")
    for a in alerts:
        create_alert_job(application, a['chat_id'], a['user_id'], a['user_name'], a['address'], a['target'], a['cond'], a['symbol'], job_name=a['job_name'])
    
    commands = [
        BotCommand("alert", "Set Target: /alert [CA] [MC]"),
        BotCommand("alerts", "Manage Active Alerts")
    ]
    await application.bot.set_my_commands(commands)
    print("✅ Commands pushed!")

def run_bot():
    keep_alive()
    if not TELEGRAM_TOKEN:
        print("❌ ERROR: TELEGRAM_TOKEN missing.")
        return
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).post_init(post_init).build()

    # Handlers
    app.add_handler(CommandHandler("alerts", list_alerts))
    app.add_handler(CommandHandler("override", override_login))
    app.add_handler(CommandHandler("id", get_id_secure))
    app.add_handler(CallbackQueryHandler(handle_alert_callback))

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("alert", alert_entry),
            CommandHandler("start", start_handler) 
        ],
        states={
            ASK_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_address)],
            ASK_TARGET: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_target)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True
    )
    app.add_handler(conv_handler)

    print("🤖 Radar is Online & Crash Proof...")
    app.run_polling()

if __name__ == '__main__':
    run_bot()
