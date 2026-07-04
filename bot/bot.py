import logging
import asyncio
from telegram import Update, InputMediaPhoto
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

from .config import settings
from .db import save_message, get_recent_messages, embed_text, get_relevant_memories, clear_memory
from .db import save_message as db_save_message
from .llm import chat_completion, embed_text as llm_embed, generate_image
from .db import get_relevant_memories as db_get_relevant_memories
from .db import get_recent_messages as db_get_recent_messages
from .db import conn

import json
import numpy as np

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ADMIN_IDS = [int(x) for x in settings.BOT_ADMIN_IDS.split(',') if x.strip().isdigit()]

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
    )
    await update.message.reply_text(text)

async def setprompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id not in ADMIN_IDS:
        await update.message.reply_text("You are not authorized to change the prompt.")
        return
    new_prompt = ' '.join(context.args)
    if not new_prompt:
        await update.message.reply_text("Usage: /setprompt <text>")
        return
    # save to settings table
    cur = conn.cursor()
    cur.execute('REPLACE INTO settings (key, value) VALUES (?, ?)', ("system_prompt", new_prompt))
    conn.commit()
    await update.message.reply_text("System prompt updated.")

async def clearmemory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id in ADMIN_IDS and context.args and context.args[0] == 'all':
        clear_memory(None)
        await update.message.reply_text("All memories cleared.")
        return
    clear_memory(user.id)
    await update.message.reply_text("Your memory cleared.")

async def summarize(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msgs = db_get_recent_messages(user.id, limit=30)
    if not msgs:
        await update.message.reply_text("No messages to summarize.")
        return
    combined = '\n'.join([f"{r[1]}: {r[2]}" for r in msgs])
    system = conn.execute('SELECT value FROM settings WHERE key = ?', ("system_prompt",)).fetchone()
    system_prompt = system[0] if system else settings.SYSTEM_PROMPT
    messages = [
        {"role":"system","content": system_prompt},
        {"role":"user","content": "Please provide a short summary of the following conversation:\n" + combined}
    ]
    resp = await chat_completion(messages)
    text = resp['choices'][0]['message']['content']
    await update.message.reply_text(text)

async def image_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /image <prompt>")
        return
    prompt = ' '.join(context.args)
    await update.message.reply_text("Generating image... This may take a moment.")
    try:
        url = await generate_image(prompt)
        if url:
            await update.message.reply_photo(photo=url, caption=f"Image generated for: {prompt}")
        else:
            await update.message.reply_text("Failed to generate image.")
    except Exception as e:
        logger.exception(e)
        await update.message.reply_text(f"Error generating image: {e}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text
    await update.message.chat.do_action('typing')
    # save user message
    loop = asyncio.get_event_loop()
    # create embedding
    try:
        embedding = await llm_embed(text)
    except Exception:
        embedding = None
    db_save_message(user.id, 'user', text, embedding)
    # retrieve relevant memories
    rel = []
    if embedding is not None:
        rel = db_get_relevant_memories(user.id, embedding, top_k=6, min_score=0.6)
    system = conn.execute('SELECT value FROM settings WHERE key = ?', ("system_prompt",)).fetchone()
    system_prompt = system[0] if system else settings.SYSTEM_PROMPT
    messages = [{"role":"system","content": system_prompt}]
    # include retrieved memories as context
    for r in rel:
        messages.append({"role":"system","content": f"Relevant memory (score={r['score']:.2f}): {r['content']}"})
    # include recent chat
    recent = db_get_recent_messages(user.id, limit=8)
    for _id, role, content in recent:
        messages.append({"role": role, "content": content})
    messages.append({"role":"user","content": text})
    try:
        resp = await chat_completion(messages)
        reply = resp['choices'][0]['message']['content']
    except Exception as e:
        logger.exception(e)
        reply = "Sorry, I had an error contacting the language model."
    # save assistant message
    db_save_message(user.id, 'assistant', reply, None)
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
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)
    logger.info("Starting bot...")
    app.run_polling()

if __name__ == '__main__':
    main()
