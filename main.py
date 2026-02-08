import logging
import os
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters

load_dotenv("token.env")

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id=update.effective_chat.id, text="I'm a bot, please talk to me!")

async def name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id=update.effective_chat.id, text="mixa")


async def message_handler(update, context):
    message = update.message
    text = ""
    for i in range(10):
        text+=message.text
    await context.bot.send_message(chat_id=update.effective_chat.id, text=text)


if __name__ == '__main__':
    application = ApplicationBuilder().token(os.getenv('TELEG_BOT')).build()
    
    start_handler = CommandHandler('start', start)
    name_handler = CommandHandler('whatisname', name)


    application.add_handler(start_handler)
    application.add_handler(name_handler)
    application.add_handler(MessageHandler(filters.TEXT, message_handler))

    application.run_polling()