import logging
import os

from dotenv import load_dotenv
from telegram.ext import ApplicationBuilder, CommandHandler

from bot import database as db
from bot.handlers import (
    addwish,
    fulfillwish,
    help_command,
    mycode,
    mywishes,
    pair,
    partnerwishes,
    removewish,
    settime,
    start,
    unpair,
)
from bot.scheduler import send_daily_wishes

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN environment variable is not set")

    db.init_db()

    app = ApplicationBuilder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("mycode", mycode))
    app.add_handler(CommandHandler("pair", pair))
    app.add_handler(CommandHandler("unpair", unpair))
    app.add_handler(CommandHandler("addwish", addwish))
    app.add_handler(CommandHandler("mywishes", mywishes))
    app.add_handler(CommandHandler("partnerwishes", partnerwishes))
    app.add_handler(CommandHandler("removewish", removewish))
    app.add_handler(CommandHandler("fulfillwish", fulfillwish))
    app.add_handler(CommandHandler("settime", settime))

    # Schedule the daily wish sender to run every minute (checks user-specific times)
    job_queue = app.job_queue
    job_queue.run_repeating(
        callback=lambda ctx: send_daily_wishes(ctx.application),
        interval=60,
        first=10,
        name="daily_wish_sender",
    )

    logger.info("Bot started. Polling for updates...")
    app.run_polling()


if __name__ == "__main__":
    main()
