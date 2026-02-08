import logging
import os
from openai import AsyncOpenAI
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters

load_dotenv("token.env")
bot_token = os.getenv("TELEG_BOT")
openai_key = os.getenv("AI")
model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
client = AsyncOpenAI(api_key=openai_key)



async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id=update.effective_chat.id, text="I'm a bot, please talk to me!")

async def name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id=update.effective_chat.id, text="mixa")


async def message_handler(update, context):
    message = update.message
    if not message or not message.text:
        return

    response = await client.responses.create(
        model=model,
        input=[
        {"role": "system", "content": "Classify text into exactly one label: calendar, message, list. Return only one word."},
        {"role": "user", "content": message.text},
        ],
    )
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=response.output_text or "No response from model.",
    )


if __name__ == '__main__':
    if not bot_token:
        raise ValueError("Missing TELEG_BOT in token.env")
    if not openai_key:
        raise ValueError("Missing AI in token.env")

    application = ApplicationBuilder().token(bot_token).build()
    
    start_handler = CommandHandler('start', start)
    name_handler = CommandHandler('whatisname', name)


    application.add_handler(start_handler)
    application.add_handler(name_handler)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    application.run_polling()