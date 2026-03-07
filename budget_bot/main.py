import logging
import os

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram.ext import ApplicationBuilder, CommandHandler

import database as db
from handlers import (
    cmd_start,
    cmd_myid,
    cmd_budget,
    cmd_accept,
    cmd_cancel,
    build_link_handler,
    build_addcat_handler,
    build_setbudget_handler,
    build_spend_handler,
    build_history_handler,
    build_delcat_handler,
    _user_display,
)

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")


async def monthly_reset(app):
    groups = await db.get_all_groups()
    for group_id in groups:
        members = await db.get_group_members(group_id)
        await db.reset_monthly_expenses(group_id)
        for member in members:
            try:
                await app.bot.send_message(
                    chat_id=member["telegram_id"],
                    text=(
                        "🔄 <b>Новый месяц — бюджет сброшен!</b>\n"
                        "Все счётчики трат обнулены. Продуктивного месяца! 🎯"
                    ),
                    parse_mode="HTML",
                )
            except Exception:
                pass
    logger.info("Monthly reset done for %d groups.", len(groups))


def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "Переменная окружения BOT_TOKEN не задана.\n"
            "Запуск: BOT_TOKEN=<ваш_токен> python main.py"
        )

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Simple commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("myid", cmd_myid))
    app.add_handler(CommandHandler("budget", cmd_budget))
    app.add_handler(CommandHandler("accept", cmd_accept))

    # Conversation handlers (step-by-step)
    app.add_handler(build_link_handler())
    app.add_handler(build_addcat_handler())
    app.add_handler(build_setbudget_handler())
    app.add_handler(build_spend_handler())
    app.add_handler(build_history_handler())
    app.add_handler(build_delcat_handler())

    # Monthly reset scheduler — 1st of each month at 00:00
    scheduler = AsyncIOScheduler()
    scheduler.add_job(monthly_reset, trigger="cron", day=1, hour=0, minute=0, args=[app])

    async def on_startup(application):
        await db.init_db()
        scheduler.start()
        await application.bot.set_my_commands([
            ("start", "Начало работы"),
            ("myid", "Узнать свой Telegram ID"),
            ("link", "Пригласить партнёра"),
            ("accept", "Принять приглашение"),
            ("addcat", "Добавить категорию"),
            ("setbudget", "Установить бюджет"),
            ("spend", "Записать трату"),
            ("budget", "Посмотреть бюджет"),
            ("history", "История трат"),
            ("delcat", "Удалить категорию"),
        ])
        logger.info("Bot started. DB initialised.")

    async def on_shutdown(application):
        scheduler.shutdown(wait=False)

    app.post_init = on_startup
    app.post_shutdown = on_shutdown

    logger.info("Starting polling…")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
