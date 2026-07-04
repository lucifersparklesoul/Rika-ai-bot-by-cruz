import logging
import asyncio
from telegram import Update, InputMediaPhoto
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

from .config import settings
from . import db
from . import llm

import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initial admin IDs from environment (comma separated). DB-backed admins are authoritative too.
ENV_ADMIN_IDS = [int(x) for x in settings.BOT_ADMIN_IDS.split(',') if x.strip().isdigit()]


def is_caller_admin(user_id: int) -> bool:
    # admin if in env list or present in admins table
    if user_id in ENV_ADMIN_IDS:
        return True
    return db.is_admin(user_id)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hello! I'm Rika — an AI assistant. Send me a message to start a conversation. Use /help for commands.")


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "/start - start the bot\n"
        "/help - this help message\n"
        "/image <prompt> - generate an image\n"
        "/summarize - summarize recent conversation\n"
        "/clearmemory - clear your memory (admin can clear all)\n"
        "/setprompt <text> - (admin) set system prompt\n"
        "/sudo <user_id> - (admin) grant admin to a user\n"
        "/unsudo <user_id> - (admin) revoke admin from a user\n"
        "/listadmins - list DB admins and env admins\n"
        "/ban <user_id> [reason] - (admin) ban a user\n"
        "/unban <user_id> - (admin) unban a user\n"
        "/banlist - list banned users\n"
        "/gban <user_id> [reason] - (admin) global ban a user (removes admin)\n"
        "/ungban <user_id> - (admin) remove global ban\n"
        "/gbanlist - list global bans\n"
        "/banall - (admin) block all non-admin users from using the bot\n"
        "/unbanall - (admin) disable ban-all mode\n"
    )
    await update.message.reply_text(text)


async def setprompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_caller_admin(user.id):
        await update.message.reply_text("You are not authorized to change the prompt.")
        return
    new_prompt = ' '.join(context.args)
    if not new_prompt:
        await update.message.reply_text("Usage: /setprompt <text>")
        return
    db.set_setting("system_prompt", new_prompt)
    await update.message.reply_text("System prompt updated.")


async def clearmemory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if is_caller_admin(user.id) and context.args and context.args[0] == 'all':
        db.clear_memory(None)
        await update.message.reply_text("All memories cleared.")
        return
    db.clear_memory(user.id)
    await update.message.reply_text("Your memory cleared.")


async def summarize(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if db.is_banned(user.id):
        await update.message.reply_text("You are banned from using this bot.")
        return
    msgs = db.get_recent_messages(user.id, limit=30)
    if not msgs:
        await update.message.reply_text("No messages to summarize.")
        return
    combined = '\n'.join([f"{r[1]}: {r[2]}" for r in msgs])
    system = db.get_setting('system_prompt', settings.SYSTEM_PROMPT)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": "Please provide a short summary of the following conversation:\n" + combined}
    ]
    resp = await llm.chat_completion(messages)
    text = resp['choices'][0]['message']['content']
    await update.message.reply_text(text)


async def image_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if db.is_banned(user.id):
        await update.message.reply_text("You are banned from using this bot.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /image <prompt>")
        return
    prompt = ' '.join(context.args)
    await update.message.reply_text("Generating image... This may take a moment.")
    try:
        url = await llm.generate_image(prompt)
        if url:
            await update.message.reply_photo(photo=url, caption=f"Image generated for: {prompt}")
        else:
            await update.message.reply_text("Failed to generate image.")
    except Exception as e:
        logger.exception(e)
        await update.message.reply_text(f"Error generating image: {e}")


# Admin commands
async def sudo_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    caller = update.effective_user
    if not is_caller_admin(caller.id):
        await update.message.reply_text("You are not authorized to grant admin rights.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /sudo <user_id>")
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Invalid user id. Use numeric Telegram user id.")
        return
    ok = db.add_admin(target_id)
    if ok:
        await update.message.reply_text(f"Granted admin to {target_id}.")
    else:
        await update.message.reply_text("Failed to add admin.")


async def unsudo_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    caller = update.effective_user
    if not is_caller_admin(caller.id):
        await update.message.reply_text("You are not authorized to revoke admin rights.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /unsudo <user_id>")
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Invalid user id. Use numeric Telegram user id.")
        return
    ok = db.remove_admin(target_id)
    if ok:
        await update.message.reply_text(f"Revoked admin from {target_id}.")
    else:
        await update.message.reply_text("User was not an admin or removal failed.")


async def listadmins_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    caller = update.effective_user
    if not is_caller_admin(caller.id):
        await update.message.reply_text("You are not authorized to list admins.")
        return
    db_admins = db.list_admins()
    text = f"Env admins: {ENV_ADMIN_IDS}\nDB admins: {db_admins}"
    await update.message.reply_text(text)


# Ban commands
async def ban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    caller = update.effective_user
    if not is_caller_admin(caller.id):
        await update.message.reply_text("You are not authorized to ban users.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /ban <user_id> [reason]")
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Invalid user id. Use numeric Telegram user id.")
        return
    reason = ' '.join(context.args[1:]) if len(context.args) > 1 else ''
    ok = db.add_ban(target_id, reason)
    if ok:
        await update.message.reply_text(f"Banned {target_id}. Reason: {reason}")
    else:
        await update.message.reply_text("Failed to ban user.")


async def unban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    caller = update.effective_user
    if not is_caller_admin(caller.id):
        await update.message.reply_text("You are not authorized to unban users.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /unban <user_id>")
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Invalid user id. Use numeric Telegram user id.")
        return
    ok = db.remove_ban(target_id)
    if ok:
        await update.message.reply_text(f"Unbanned {target_id}.")
    else:
        await update.message.reply_text("User was not banned or unban failed.")


async def banlist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    caller = update.effective_user
    if not is_caller_admin(caller.id):
        await update.message.reply_text("You are not authorized to view the ban list.")
        return
    bans = db.list_bans()
    if not bans:
        await update.message.reply_text("No banned users.")
        return
    # list_bans returns tuples (user_id, reason, created_at, is_global)
    lines = [f"{u} - {reason} ({ts}){' [GLOBAL]' if isg else ''}" for (u, reason, ts, isg) in bans]
    await update.message.reply_text('\n'.join(lines))


async def gban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    caller = update.effective_user
    if not is_caller_admin(caller.id):
        await update.message.reply_text("You are not authorized to global-ban users.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /gban <user_id> [reason]")
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Invalid user id. Use numeric Telegram user id.")
        return
    reason = ' '.join(context.args[1:]) if len(context.args) > 1 else ''
    ok = db.add_global_ban(target_id, reason)
    if ok:
        await update.message.reply_text(f"Globally banned {target_id}. Reason: {reason}")
    else:
        await update.message.reply_text("Failed to global-ban user.")


async def ungban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    caller = update.effective_user
    if not is_caller_admin(caller.id):
        await update.message.reply_text("You are not authorized to remove global bans.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /ungban <user_id>")
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Invalid user id. Use numeric Telegram user id.")
        return
    ok = db.remove_global_ban(target_id)
    if ok:
        await update.message.reply_text(f"Removed global ban for {target_id}.")
    else:
        await update.message.reply_text("Failed to remove global ban or user was not globally banned.")


async def gbanlist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    caller = update.effective_user
    if not is_caller_admin(caller.id):
        await update.message.reply_text("You are not authorized to view the global ban list.")
        return
    bans = db.list_bans()
    global_bans = [b for b in bans if b[3] == 1]
    if not global_bans:
        await update.message.reply_text("No global bans.")
        return
    lines = [f"{u} - {reason} ({ts})" for (u, reason, ts, isg) in global_bans]
    await update.message.reply_text('\n'.join(lines))


async def banall_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    caller = update.effective_user
    if not is_caller_admin(caller.id):
        await update.message.reply_text("You are not authorized to enable ban-all mode.")
        return
    db.set_setting('ban_all', '1')
    await update.message.reply_text("Ban-all mode enabled. Only admins may use the bot.")


async def unbanall_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    caller = update.effective_user
    if not is_caller_admin(caller.id):
        await update.message.reply_text("You are not authorized to disable ban-all mode.")
        return
    db.set_setting('ban_all', '0')
    await update.message.reply_text("Ban-all mode disabled.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text

    # Check bans and ban_all
    if db.is_banned(user.id):
        await update.message.reply_text("You are banned from using this bot.")
        return
    ban_all = db.get_setting('ban_all', '0')
    if ban_all == '1' and not is_caller_admin(user.id):
        await update.message.reply_text("Bot is in ban-all mode. Only admins may interact.")
        return

    # Indicate typing
    try:
        await update.message.chat.do_action('typing')
    except Exception:
        pass

    # save user message
    try:
        embedding = await llm.embed_text(text)
    except Exception:
        embedding = None
    db.save_message(user.id, 'user', text, embedding)

    # retrieve relevant memories
    rel = []
    if embedding is not None:
        rel = db.get_relevant_memories(user.id, embedding, top_k=6, min_score=0.6)

    system = db.get_setting('system_prompt', settings.SYSTEM_PROMPT)

    messages = [{"role": "system", "content": system}]
    # include retrieved memories as context
    for r in rel:
        messages.append({"role": "system", "content": f"Relevant memory (score={r['score']:.2f}): {r['content']}"})
    # include recent chat
    recent = db.get_recent_messages(user.id, limit=8)
    for _id, role, content in recent:
        messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": text})

    try:
        resp = await llm.chat_completion(messages)
        reply = resp['choices'][0]['message']['content']
    except Exception as e:
        logger.exception(e)
        reply = "Sorry, I had an error contacting the language model."
    # save assistant message
    db.save_message(user.id, 'assistant', reply, None)
    await update.message.reply_text(reply)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(msg="Exception while handling an update:", exc_info=context.error)


def main():
    app = ApplicationBuilder().token(settings.TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('help', help_cmd))
    app.add_handler(CommandHandler('setprompt', setprompt))
    app.add_handler(CommandHandler('clearmemory', clearmemory))
    app.add_handler(CommandHandler('summarize', summarize))
    app.add_handler(CommandHandler('image', image_cmd))

    # admin and ban handlers
    app.add_handler(CommandHandler('sudo', sudo_cmd))
    app.add_handler(CommandHandler('unsudo', unsudo_cmd))
    app.add_handler(CommandHandler('listadmins', listadmins_cmd))
    app.add_handler(CommandHandler('ban', ban_cmd))
    app.add_handler(CommandHandler('unban', unban_cmd))
    app.add_handler(CommandHandler('banlist', banlist_cmd))
    app.add_handler(CommandHandler('gban', gban_cmd))
    app.add_handler(CommandHandler('ungban', ungban_cmd))
    app.add_handler(CommandHandler('gbanlist', gbanlist_cmd))
    app.add_handler(CommandHandler('banall', banall_cmd))
    app.add_handler(CommandHandler('unbanall', unbanall_cmd))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)

    webhook_url = settings.WEBHOOK_URL
    token = settings.TELEGRAM_TOKEN
    port = int(os.environ.get('PORT', settings.PORT))

    if webhook_url:
        # construct webhook path and full url
        path = f"/webhook/{token}"
        full = webhook_url.rstrip('/') + path
        logger.info(f"Starting in webhook mode on port {port}, webhook={full}")
        # run webhook server (uses aiohttp internally)
        app.run_webhook(listen='0.0.0.0', port=port, url_path=path, webhook_url=full)
    else:
        logger.info("Starting in polling mode (no WEBHOOK_URL set)")
        app.run_polling()


if __name__ == '__main__':
    main()
