from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from bot import database as db


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    db_user = db.register_user(user.id, user.username, user.first_name)

    if db_user.get("partner_id"):
        await update.message.reply_text(
            f"Welcome back, {user.first_name}! You're already paired.\n"
            "Use /help to see available commands."
        )
        return

    await update.message.reply_text(
        f"Welcome, {user.first_name}!\n\n"
        f"Your pair code is: <code>{db_user['pair_code']}</code>\n\n"
        "Share this code with your partner so they can pair with you, "
        "or use /pair <code> to pair with them.\n\n"
        "Use /help to see all available commands.",
        parse_mode="HTML",
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "<b>Couple Wish Bot - Commands</b>\n\n"
        "/start - Register and get your pair code\n"
        "/pair &lt;code&gt; - Pair with your partner\n"
        "/unpair - Unpair from your partner\n"
        "/mycode - Show your pair code\n\n"
        "<b>Wishes</b>\n"
        "/addwish &lt;wish&gt; - Add a wish to your list\n"
        "/mywishes - View your wishes\n"
        "/partnerwishes - View your partner's wishes\n"
        "/removewish &lt;id&gt; - Remove one of your wishes\n"
        "/fulfillwish &lt;id&gt; - Mark a partner's wish as fulfilled\n\n"
        "<b>Notifications</b>\n"
        "/settime HH:MM - Set daily notification time (UTC)\n\n"
        "Each day you'll receive a random wish from your partner's list!",
        parse_mode="HTML",
    )


async def mycode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db_user = db.get_user_by_telegram_id(update.effective_user.id)
    if not db_user:
        await update.message.reply_text("Please /start first.")
        return
    await update.message.reply_text(
        f"Your pair code: <code>{db_user['pair_code']}</code>",
        parse_mode="HTML",
    )


async def pair(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    db_user = db.get_user_by_telegram_id(user.id)

    if not db_user:
        await update.message.reply_text("Please /start first.")
        return

    if db_user.get("partner_id"):
        await update.message.reply_text("You're already paired! Use /unpair first if you want to pair with someone else.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /pair <partner_code>")
        return

    partner_code = context.args[0].strip().upper()
    partner = db.get_user_by_pair_code(partner_code)

    if not partner:
        await update.message.reply_text("Invalid pair code. Ask your partner for their code (/mycode).")
        return

    if partner["id"] == db_user["id"]:
        await update.message.reply_text("You can't pair with yourself!")
        return

    if partner.get("partner_id"):
        await update.message.reply_text("That person is already paired with someone else.")
        return

    success = db.pair_users(db_user["id"], partner["id"])
    if success:
        partner_name = partner.get("first_name") or partner.get("username") or "your partner"
        await update.message.reply_text(
            f"Successfully paired with {partner_name}!\n"
            "You can now add wishes and view each other's lists.\n"
            "You'll both receive daily wish reminders!"
        )
        try:
            await context.bot.send_message(
                chat_id=partner["telegram_id"],
                text=f"{db_user.get('first_name', 'Your partner')} has paired with you!\n"
                "Start adding wishes with /addwish <your wish>",
            )
        except Exception:
            pass
    else:
        await update.message.reply_text("Something went wrong. Please try again.")


async def unpair(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db_user = db.get_user_by_telegram_id(update.effective_user.id)
    if not db_user:
        await update.message.reply_text("Please /start first.")
        return

    if not db_user.get("partner_id"):
        await update.message.reply_text("You're not paired with anyone.")
        return

    partner_id = db_user["partner_id"]
    db.unpair_user(db_user["id"], partner_id)
    await update.message.reply_text("You've been unpaired. Use /pair <code> to pair with someone new.")


async def addwish(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db_user = db.get_user_by_telegram_id(update.effective_user.id)
    if not db_user:
        await update.message.reply_text("Please /start first.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /addwish <your wish>\nExample: /addwish A weekend trip to the mountains")
        return

    wish_text = " ".join(context.args)
    if len(wish_text) > 500:
        await update.message.reply_text("Wish is too long! Please keep it under 500 characters.")
        return

    wish = db.add_wish(db_user["id"], wish_text)
    count = len(db.get_wishes(db_user["id"]))
    await update.message.reply_text(
        f"Wish added! (#{wish['id']})\n"
        f"You now have {count} active wish(es)."
    )


async def mywishes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db_user = db.get_user_by_telegram_id(update.effective_user.id)
    if not db_user:
        await update.message.reply_text("Please /start first.")
        return

    wishes = db.get_wishes(db_user["id"])
    if not wishes:
        await update.message.reply_text("You have no wishes yet. Add one with /addwish <wish>")
        return

    lines = ["<b>Your Wishes:</b>\n"]
    for w in wishes:
        lines.append(f"  #{w['id']} - {w['text']}")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def partnerwishes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db_user = db.get_user_by_telegram_id(update.effective_user.id)
    if not db_user:
        await update.message.reply_text("Please /start first.")
        return

    if not db_user.get("partner_id"):
        await update.message.reply_text("You're not paired with anyone. Use /pair <code> first.")
        return

    wishes = db.get_wishes(db_user["partner_id"])
    if not wishes:
        await update.message.reply_text("Your partner has no wishes yet. Nudge them to add some!")
        return

    lines = ["<b>Your Partner's Wishes:</b>\n"]
    for w in wishes:
        lines.append(f"  #{w['id']} - {w['text']}")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def removewish(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db_user = db.get_user_by_telegram_id(update.effective_user.id)
    if not db_user:
        await update.message.reply_text("Please /start first.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /removewish <wish_id>")
        return

    try:
        wish_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Please provide a valid wish ID number.")
        return

    deleted = db.remove_wish(wish_id, db_user["id"])
    if deleted:
        await update.message.reply_text(f"Wish #{wish_id} removed.")
    else:
        await update.message.reply_text("Wish not found or it doesn't belong to you.")


async def fulfillwish(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db_user = db.get_user_by_telegram_id(update.effective_user.id)
    if not db_user:
        await update.message.reply_text("Please /start first.")
        return

    if not db_user.get("partner_id"):
        await update.message.reply_text("You're not paired with anyone.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /fulfillwish <wish_id>")
        return

    try:
        wish_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Please provide a valid wish ID number.")
        return

    partner_wishes = db.get_wishes(db_user["partner_id"])
    partner_wish_ids = {w["id"] for w in partner_wishes}

    if wish_id not in partner_wish_ids:
        await update.message.reply_text("That wish doesn't belong to your partner or doesn't exist.")
        return

    fulfilled = db.fulfill_wish(wish_id)
    if fulfilled:
        await update.message.reply_text(f"Wish #{wish_id} marked as fulfilled! How sweet!")
    else:
        await update.message.reply_text("Something went wrong. Try again.")


async def settime(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db_user = db.get_user_by_telegram_id(update.effective_user.id)
    if not db_user:
        await update.message.reply_text("Please /start first.")
        return

    if not context.args:
        current_h = db_user.get("notification_hour", 9)
        current_m = db_user.get("notification_minute", 0)
        await update.message.reply_text(
            f"Current notification time: {current_h:02d}:{current_m:02d} UTC\n"
            "Usage: /settime HH:MM (24h format, UTC)"
        )
        return

    time_str = context.args[0]
    try:
        parts = time_str.split(":")
        hour = int(parts[0])
        minute = int(parts[1])
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
    except (ValueError, IndexError):
        await update.message.reply_text("Invalid format. Use HH:MM (e.g., 09:00, 21:30)")
        return

    db.set_notification_time(db_user["id"], hour, minute)
    await update.message.reply_text(
        f"Notification time set to {hour:02d}:{minute:02d} UTC.\n"
        "You'll receive a random wish from your partner at this time daily."
    )
