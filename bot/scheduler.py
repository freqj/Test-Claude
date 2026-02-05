import logging
from datetime import datetime, timezone

from telegram.ext import Application

from bot import database as db

logger = logging.getLogger(__name__)


async def send_daily_wishes(app: Application) -> None:
    """Check all paired users and send a random partner wish if it's their notification time."""
    now = datetime.now(timezone.utc)
    current_hour = now.hour
    current_minute = now.minute

    paired_users = db.get_all_paired_users()

    for user in paired_users:
        user_hour = user.get("notification_hour", 9)
        user_minute = user.get("notification_minute", 0)

        if user_hour != current_hour or user_minute != current_minute:
            continue

        partner_id = user["partner_id"]
        random_wish = db.get_random_wish(partner_id)

        if not random_wish:
            continue

        try:
            await app.bot.send_message(
                chat_id=user["telegram_id"],
                text=(
                    "Daily Wish Reminder\n\n"
                    f"Your partner wishes for:\n\n"
                    f"  \"{random_wish['text']}\"\n\n"
                    f"(Wish #{random_wish['id']})\n\n"
                    "Maybe today is the day to make it happen!\n"
                    "Use /partnerwishes to see all their wishes."
                ),
            )
            logger.info(
                "Sent daily wish to user %s (telegram_id=%s)",
                user["id"],
                user["telegram_id"],
            )
        except Exception:
            logger.exception(
                "Failed to send daily wish to user %s (telegram_id=%s)",
                user["id"],
                user["telegram_id"],
            )
