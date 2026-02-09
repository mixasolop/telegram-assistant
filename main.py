import logging
import os
import datetime
import asyncio
import re
import tempfile
from openai import AsyncOpenAI
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from callendar import create_event, update_event_by_name, delete_event_by_name

load_dotenv("token.env")
bot_token = os.getenv("TELEG_BOT")
openai_key = os.getenv("AI")
model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
transcribe_model = os.getenv("OPENAI_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe")

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
client = AsyncOpenAI(api_key=openai_key)

logger = logging.getLogger(__name__)

WEEKDAY_MAP = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


def parse_description_fields(description_line: str) -> dict[str, str]:
    raw = description_line.split(":", 1)[1] if ":" in description_line else description_line
    fields: dict[str, str] = {}
    for part in raw.split(","):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        fields[key.strip().lower()] = value.strip()
    return fields


def align_start_with_weekday_hint(user_text: str, start_iso: str) -> str:
    text = user_text.lower()
    if re.search(r"\d{4}-\d{2}-\d{2}", text):
        return start_iso

    target_weekday = None
    for day_name, day_value in WEEKDAY_MAP.items():
        if day_name in text:
            target_weekday = day_value
            break

    if target_weekday is None:
        return start_iso

    try:
        start_dt = datetime.datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
    except ValueError:
        return start_iso

    now = datetime.datetime.now(start_dt.tzinfo) if start_dt.tzinfo else datetime.datetime.now()
    days_ahead = (target_weekday - now.weekday()) % 7
    candidate_date = now.date() + datetime.timedelta(days=days_ahead)
    aligned = start_dt.replace(year=candidate_date.year, month=candidate_date.month, day=candidate_date.day)
    return aligned.isoformat()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id=update.effective_chat.id, text="I'm a bot, please talk to me!")

async def name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id=update.effective_chat.id, text="mixa")


async def handle_user_text(update, context, user_text: str):
    response = await client.responses.create(
        model=model,
        input=[
        {"role": "system", "content": "You are an intent picker. Pick EXACTLY ONE of the three categories:"
"calendar, message, list"
"Output format (3 lines, always):"
"category: <ONE_WORD>"
"subcategory: <ONE_WORD>"
"description: <SHORT_TEXT>"

"Rules:"
"- category MUST be exactly one of: calendar | message | list (one word, lowercase)."
"- subcategory MUST be one word, lowercase."
"- description is a short human-readable summary (a few words/sentence)."

"Calendar rules:"
f"todays date is {datetime.datetime.now().strftime('%Y-%m-%dT%H:%M')}"
"- If category=calendar, then subcategory MUST be exactly one of: add | remove | change"
"- If subcategory=add, description MUST include:"
"  - name=<event_name>  (required)"
"  - start=<ISO_8601_datetime> (required)"
"  - end=<ISO_8601_datetime> (optional, only if provided)"
"  - details=<text> (optional, only if provided)"
"  Example description: name=Dentist,start=2026-02-10T14:00,end=2026-02-10T15:00,details=Bring x-rays"
"- If subcategory=remove, description MUST include at least one identifier:"
"  - id=<event_id> OR name=<event_name> (+ optionally date=<YYYY-MM-DD> or start=<ISO_8601_datetime>)"
"- If subcategory=change, description MUST include:"
"  - target=<id or name> (required)"
"  - update=<what changes> (required; e.g., time/name/details)"},
        {"role": "user", "content": user_text},],)
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=response.output_text or "No response from model.",
    )
    parsed_res = response.output_text.splitlines()
    category = parsed_res[0].split(':')[1].strip()
    subcategory = parsed_res[1].split(':')[1].strip()
    print(category)
    if(category == "calendar"):
        print('I AM HERE!')
        if(subcategory == "add"):
            description = parsed_res[2] if len(parsed_res) >= 3 else ""
            fields = parse_description_fields(description)
            name = fields.get("name", "")
            start = fields.get("start", "")
            end = fields.get("end", "")
            descr = fields.get("details", "")
            start = align_start_with_weekday_hint(user_text, start)
            if not name or not start:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="Calendar add failed: missing name or start.",
                )
                return

            try:
                event = create_event(name, start, end, descr)
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=event.get('id') or "No response from model.",
                )
            except Exception as exc:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=f"Calendar add failed: {exc}",
                )


async def message_handler(update, context):
    message = update.message
    if not message or not message.text:
        return
    await handle_user_text(update, context, message.text)


async def voice_handler(update, context):
    message = update.message
    if not message or not message.voice:
        return

    temp_path = None
    try:
        file_info = await context.bot.get_file(message.voice.file_id)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".ogg") as tmp:
            temp_path = tmp.name
        await file_info.download_to_drive(custom_path=temp_path)

        with open(temp_path, "rb") as audio_file:
            transcript = await client.audio.transcriptions.create(
                model=transcribe_model,
                file=audio_file,
            )

        spoken_text = (getattr(transcript, "text", "") or "").strip()
        if not spoken_text:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="I couldn't understand the voice message.",
            )
            return

        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"Voice text: {spoken_text}",
        )
        await handle_user_text(update, context, spoken_text)
    except Exception as exc:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"Voice processing failed: {exc}",
        )
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)


async def app_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.exception("Unhandled bot error", exc_info=context.error)


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
    application.add_handler(MessageHandler(filters.VOICE, voice_handler))
    application.add_error_handler(app_error_handler)

    application.run_polling()
