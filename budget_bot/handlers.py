from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)
from telegram.constants import ParseMode

import database as db

# ── Conversation states ──────────────────────────────────────────────────────
(
    ADDCAT_NAME,
    ADDCAT_BUDGET,
    SETBUDGET_CAT,
    SETBUDGET_AMOUNT,
    SPEND_CAT,
    SPEND_AMOUNT,
    SPEND_DESC,
    SPEND_PHOTO,
    LINK_ID,
    DELCAT_NAME,
    DELCAT_CONFIRM,
    HISTORY_CAT,
) = range(12)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _user_display(telegram_id: int, username: str | None) -> str:
    return f"@{username}" if username else f"#{telegram_id}"


def _progress_bar(spent: float, budget: float, width: int = 10) -> str:
    if budget <= 0:
        return "█" * width
    ratio = min(spent / budget, 1.0)
    filled = round(ratio * width)
    bar = "█" * filled + "░" * (width - filled)
    return f"[{bar}] {ratio * 100:.0f}%"


def _skip_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("⏭ Пропустить", callback_data="skip")]])


def _group_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[KeyboardButton("💸 Spend"), KeyboardButton("📊 Budget")]],
        resize_keyboard=True,
    )


async def _ensure_group(user_id: int) -> int | None:
    """Return group_id, creating a solo group if needed. Returns None on DB error."""
    import aiosqlite
    me = await db.get_user(user_id)
    if me and me.get("group_id"):
        return me["group_id"]
    async with aiosqlite.connect(db.DB_PATH) as dbc:
        cur = await dbc.execute("INSERT INTO groups DEFAULT VALUES")
        group_id = cur.lastrowid
        await dbc.execute(
            "UPDATE users SET group_id = ? WHERE telegram_id = ?", (group_id, user_id)
        )
        await dbc.commit()
    return group_id


async def _notify_group(
    context: ContextTypes.DEFAULT_TYPE,
    group_id: int,
    exclude_telegram_id: int,
    text: str,
    photo_file_id: str | None = None,
):
    members = await db.get_group_members(group_id)
    for member in members:
        if member["telegram_id"] == exclude_telegram_id:
            continue
        try:
            if photo_file_id:
                await context.bot.send_photo(
                    chat_id=member["telegram_id"],
                    photo=photo_file_id,
                    caption=text,
                    parse_mode=ParseMode.HTML,
                )
            else:
                await context.bot.send_message(
                    chat_id=member["telegram_id"],
                    text=text,
                    parse_mode=ParseMode.HTML,
                )
        except Exception:
            pass


async def _build_expense_message(
    who: str,
    cat_name: str,
    amount: float,
    spent: float,
    budget: float,
    description: str | None,
) -> str:
    bar = _progress_bar(spent, budget)
    over = spent > budget
    icon = "🔴" if over else "🟢"
    desc_line = f"\n📝 <i>{description}</i>" if description else ""
    msg = (
        f"{icon} <b>{cat_name}</b>{desc_line}\n"
        f"{'💸 ' + who + ' добавил(а) трату' if who else 'Трата'}: <b>+{amount:,.2f}</b>\n"
        f"Итого: <b>{spent:,.2f} / {budget:,.2f}</b>\n"
        f"{bar}"
    )
    if over:
        msg += f"\n⚠️ Превышение на <b>{spent - budget:,.2f}</b>!"
    return msg


async def _cat_list_keyboard(group_id: int) -> InlineKeyboardMarkup | None:
    cats = await db.get_categories(group_id)
    if not cats:
        return None
    buttons = [[InlineKeyboardButton(c["name"], callback_data=f"cat:{c['name']}")] for c in cats]
    return InlineKeyboardMarkup(buttons)


# ── /cancel ──────────────────────────────────────────────────────────────────

async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    me = await db.get_user(update.effective_user.id)
    kb = _group_keyboard() if (me and me.get("group_id")) else None
    await update.message.reply_text("❌ Отменено.", reply_markup=kb)
    return ConversationHandler.END


# ── /start ───────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    me = await db.get_or_create_user(user.id, user.username)
    text = (
        "👋 <b>Бот учёта бюджета</b>\n\n"
        "<b>Команды:</b>\n"
        "  /addcat — создать категорию с бюджетом\n"
        "  /setbudget — изменить бюджет категории\n"
        "  /spend — добавить трату (с фото и описанием)\n"
        "  /budget — текущий бюджет по всем категориям\n"
        "  /history — история трат категории\n"
        "  /delcat — удалить категорию\n"
        "  /link — привязать другого пользователя\n"
        "  /accept — принять запрос привязки\n"
        "  /myid — ваш Telegram ID\n"
        "  /cancel — отменить текущую операцию\n\n"
        "Все команды работают пошагово — просто введите команду без аргументов.\n"
        "Счёт сбрасывается <b>1‑го числа каждого месяца</b>."
    )
    kb = _group_keyboard() if me.get("group_id") else None
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)


# ── /myid ────────────────────────────────────────────────────────────────────

async def cmd_myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"Ваш Telegram ID: <code>{update.effective_user.id}</code>",
        parse_mode=ParseMode.HTML,
    )


# ── /budget ──────────────────────────────────────────────────────────────────

async def cmd_budget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    me = await db.get_or_create_user(user.id, user.username)
    group_id = me.get("group_id")
    if not group_id:
        await update.message.reply_text("У вас нет категорий. Создайте через /addcat.")
        return

    cats = await db.get_categories(group_id)
    if not cats:
        await update.message.reply_text("Категорий пока нет. Добавьте через /addcat.")
        return

    now = datetime.now()
    lines = [f"📊 <b>Бюджет за {now.strftime('%B %Y')}</b>\n"]
    total_budget = total_spent = 0.0

    for cat in cats:
        spent = await db.get_monthly_spent(cat["id"])
        budget = cat["monthly_budget"]
        total_budget += budget
        total_spent += spent
        icon = "🔴" if spent > budget else "🟢"
        lines.append(
            f"{icon} <b>{cat['name']}</b>\n"
            f"   {spent:,.2f} / {budget:,.2f}\n"
            f"   {_progress_bar(spent, budget)}"
        )

    lines.append(
        f"\n💰 <b>Всего: {total_spent:,.2f} / {total_budget:,.2f}</b>\n"
        f"{_progress_bar(total_spent, total_budget)}"
    )
    members = await db.get_group_members(group_id)
    member_names = ", ".join(_user_display(m["telegram_id"], m.get("username")) for m in members)
    lines.append(f"\n👥 Участники: {member_names}")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


# ── /accept ──────────────────────────────────────────────────────────────────

async def cmd_accept(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await db.get_or_create_user(user.id, user.username)

    if not context.args:
        await update.message.reply_text(
            "Использование: /accept <code>&lt;ID пользователя&gt;</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    try:
        from_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("ID должен быть числом.")
        return

    req = await db.get_link_request(from_id, user.id)
    if req is None:
        await update.message.reply_text("Запрос не найден. Попросите пользователя отправить /link снова.")
        return

    await db.delete_link_request(from_id, user.id)
    await db.link_users(from_id, user.id)

    from_user = await db.get_user(from_id)
    await update.message.reply_text(
        f"✅ Вы привязаны к {_user_display(from_id, from_user.get('username'))}! Теперь у вас общий бюджет.",
        reply_markup=_group_keyboard(),
    )
    try:
        await context.bot.send_message(
            chat_id=from_id,
            text=f"✅ {_user_display(user.id, user.username)} принял(а) запрос. Теперь у вас общий бюджет!",
            reply_markup=_group_keyboard(),
        )
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
# ConversationHandler: /link
# ══════════════════════════════════════════════════════════════════════════════

async def link_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await db.get_or_create_user(user.id, user.username)

    if context.args:
        return await _do_link(update, context, context.args[0])

    await update.message.reply_text(
        "🔗 Введите Telegram ID пользователя, которого хотите привязать.\n"
        "Его ID можно узнать командой /myid\n\n"
        "/cancel — отмена"
    )
    return LINK_ID


async def link_receive_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await _do_link(update, context, update.message.text.strip())


async def _do_link(update: Update, context: ContextTypes.DEFAULT_TYPE, raw_id: str):
    user = update.effective_user
    try:
        target_id = int(raw_id)
    except ValueError:
        await update.message.reply_text("❗ ID должен быть числом. Попробуйте снова:")
        return LINK_ID

    if target_id == user.id:
        await update.message.reply_text("❗ Нельзя привязаться к самому себе.")
        return ConversationHandler.END

    target = await db.get_user(target_id)
    if target is None:
        await update.message.reply_text("❗ Пользователь не найден. Попросите его написать боту /start.")
        return ConversationHandler.END

    me = await db.get_user(user.id)
    if me["group_id"] and me["group_id"] == target["group_id"]:
        await update.message.reply_text("Вы уже привязаны к этому пользователю.")
        return ConversationHandler.END

    await db.create_link_request(user.id, target_id)
    try:
        await context.bot.send_message(
            chat_id=target_id,
            text=(
                f"🔗 {_user_display(user.id, user.username)} хочет привязать вас к общему бюджету.\n\n"
                f"Чтобы принять: /accept <code>{user.id}</code>"
            ),
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        pass

    me = await db.get_user(user.id)
    kb = _group_keyboard() if (me and me.get("group_id")) else None
    await update.message.reply_text(
        f"✅ Запрос отправлен пользователю <code>{target_id}</code>. Ожидайте подтверждения.",
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )
    return ConversationHandler.END


def build_link_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("link", link_entry)],
        states={
            LINK_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, link_receive_id)],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
        per_user=True,
    )


# ══════════════════════════════════════════════════════════════════════════════
# ConversationHandler: /addcat
# ══════════════════════════════════════════════════════════════════════════════

async def addcat_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await db.get_or_create_user(user.id, user.username)

    if len(context.args) >= 2:
        return await _do_addcat(update, context, context.args[0], context.args[1])

    await update.message.reply_text(
        "📂 Введите <b>название</b> новой категории:\n\n/cancel — отмена",
        parse_mode=ParseMode.HTML,
    )
    return ADDCAT_NAME


async def addcat_receive_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if not name:
        await update.message.reply_text("❗ Название не может быть пустым. Попробуйте снова:")
        return ADDCAT_NAME
    context.user_data["addcat_name"] = name
    await update.message.reply_text(
        f"💰 Введите <b>месячный бюджет</b> для категории «{name}»:\n\n/cancel — отмена",
        parse_mode=ParseMode.HTML,
    )
    return ADDCAT_BUDGET


async def addcat_receive_budget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await _do_addcat(
        update, context,
        context.user_data.pop("addcat_name", ""),
        update.message.text.strip(),
    )


async def _do_addcat(update: Update, context: ContextTypes.DEFAULT_TYPE, name: str, raw_budget: str):
    try:
        budget = float(raw_budget.replace(",", "."))
    except ValueError:
        await update.message.reply_text("❗ Бюджет должен быть числом. Попробуйте снова:")
        return ADDCAT_BUDGET
    if budget <= 0:
        await update.message.reply_text("❗ Бюджет должен быть больше нуля. Попробуйте снова:")
        return ADDCAT_BUDGET

    user = update.effective_user
    group_id = await _ensure_group(user.id)

    cat = await db.add_category(group_id, name, budget)
    if cat is None:
        await db.update_category_budget(group_id, name, budget)
        await update.message.reply_text(
            f"📝 Бюджет категории <b>{name}</b> обновлён: <b>{budget:,.2f}</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=_group_keyboard(),
        )
    else:
        await update.message.reply_text(
            f"✅ Категория <b>{name}</b> создана с бюджетом <b>{budget:,.2f}</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=_group_keyboard(),
        )
        await _notify_group(
            context, group_id, user.id,
            f"📂 {_user_display(user.id, user.username)} создал(а) категорию <b>{name}</b> с бюджетом <b>{budget:,.2f}</b>",
        )
    return ConversationHandler.END


def build_addcat_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("addcat", addcat_entry)],
        states={
            ADDCAT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, addcat_receive_name)],
            ADDCAT_BUDGET: [MessageHandler(filters.TEXT & ~filters.COMMAND, addcat_receive_budget)],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
        per_user=True,
    )


# ══════════════════════════════════════════════════════════════════════════════
# ConversationHandler: /setbudget
# ══════════════════════════════════════════════════════════════════════════════

async def setbudget_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    me = await db.get_or_create_user(user.id, user.username)

    if len(context.args) >= 2:
        return await _do_setbudget(update, context, context.args[0], context.args[1])

    group_id = me.get("group_id")
    if not group_id:
        await update.message.reply_text("У вас нет категорий. Создайте через /addcat.")
        return ConversationHandler.END

    kb = await _cat_list_keyboard(group_id)
    if kb is None:
        await update.message.reply_text("У вас нет категорий. Создайте через /addcat.")
        return ConversationHandler.END

    await update.message.reply_text(
        "✏️ Выберите категорию или введите её название:\n\n/cancel — отмена",
        reply_markup=kb,
    )
    return SETBUDGET_CAT


async def setbudget_receive_cat_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    name = update.callback_query.data.split(":", 1)[1]
    context.user_data["setbudget_cat"] = name
    await update.callback_query.message.reply_text(
        f"💰 Введите новый бюджет для «{name}»:\n\n/cancel — отмена"
    )
    return SETBUDGET_AMOUNT


async def setbudget_receive_cat_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["setbudget_cat"] = update.message.text.strip()
    await update.message.reply_text(
        f"💰 Введите новый бюджет для «{context.user_data['setbudget_cat']}»:\n\n/cancel — отмена"
    )
    return SETBUDGET_AMOUNT


async def setbudget_receive_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await _do_setbudget(
        update, context,
        context.user_data.pop("setbudget_cat", ""),
        update.message.text.strip(),
    )


async def _do_setbudget(update: Update, context: ContextTypes.DEFAULT_TYPE, name: str, raw_budget: str):
    try:
        budget = float(raw_budget.replace(",", "."))
    except ValueError:
        await update.message.reply_text("❗ Бюджет должен быть числом. Попробуйте снова:")
        return SETBUDGET_AMOUNT
    if budget <= 0:
        await update.message.reply_text("❗ Бюджет должен быть больше нуля. Попробуйте снова:")
        return SETBUDGET_AMOUNT

    user = update.effective_user
    me = await db.get_user(user.id)
    group_id = me.get("group_id") if me else None
    if not group_id:
        await update.message.reply_text("У вас нет категорий.")
        return ConversationHandler.END

    ok = await db.update_category_budget(group_id, name, budget)
    if not ok:
        await update.message.reply_text(f"❗ Категория «{name}» не найдена.")
        return ConversationHandler.END

    await update.message.reply_text(
        f"✅ Бюджет <b>{name}</b> изменён на <b>{budget:,.2f}</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=_group_keyboard(),
    )
    await _notify_group(
        context, group_id, user.id,
        f"✏️ {_user_display(user.id, user.username)} изменил(а) бюджет <b>{name}</b> → <b>{budget:,.2f}</b>",
    )
    return ConversationHandler.END


def build_setbudget_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("setbudget", setbudget_entry)],
        states={
            SETBUDGET_CAT: [
                CallbackQueryHandler(setbudget_receive_cat_cb, pattern=r"^cat:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, setbudget_receive_cat_text),
            ],
            SETBUDGET_AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, setbudget_receive_amount),
            ],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
        per_user=True,
    )


# ══════════════════════════════════════════════════════════════════════════════
# ConversationHandler: /spend
# ══════════════════════════════════════════════════════════════════════════════

async def spend_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    me = await db.get_or_create_user(user.id, user.username)
    group_id = me.get("group_id")

    if not group_id:
        await update.message.reply_text("У вас нет категорий. Создайте через /addcat.")
        return ConversationHandler.END

    # If full args provided: /spend Cat 100 [desc] — skip to photo step
    if len(context.args or []) >= 2:
        cat_name = context.args[0]
        raw_amount = context.args[1]
        description = " ".join(context.args[2:]) if len(context.args or []) > 2 else None
        try:
            amount = float(raw_amount.replace(",", "."))
        except ValueError:
            await update.message.reply_text("❗ Сумма должна быть числом.")
            return ConversationHandler.END
        if amount <= 0:
            await update.message.reply_text("❗ Сумма должна быть больше нуля.")
            return ConversationHandler.END

        cat = await db.get_category_by_name(group_id, cat_name)
        if cat is None:
            cats = await db.get_categories(group_id)
            names = ", ".join(f"<b>{c['name']}</b>" for c in cats) or "нет категорий"
            await update.message.reply_text(
                f"❗ Категория «{cat_name}» не найдена.\nДоступные: {names}",
                parse_mode=ParseMode.HTML,
            )
            return ConversationHandler.END

        context.user_data["spend"] = {
            "cat": cat, "amount": amount, "description": description, "group_id": group_id
        }
        await update.message.reply_text(
            "📷 Прикрепите фото чека или нажмите «Пропустить»:",
            reply_markup=_skip_keyboard(),
        )
        return SPEND_PHOTO

    # Step-by-step: show category list
    kb = await _cat_list_keyboard(group_id)
    await update.message.reply_text(
        "💸 Выберите категорию или введите название:\n\n/cancel — отмена",
        reply_markup=kb,
    )
    return SPEND_CAT


async def spend_receive_cat_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    name = update.callback_query.data.split(":", 1)[1]
    user = update.effective_user
    me = await db.get_user(user.id)
    group_id = me.get("group_id")
    cat = await db.get_category_by_name(group_id, name)
    if cat is None:
        await update.callback_query.message.reply_text("❗ Категория не найдена.")
        return ConversationHandler.END
    context.user_data.setdefault("spend", {})["cat"] = cat
    context.user_data["spend"]["group_id"] = group_id
    await update.callback_query.message.reply_text(
        f"💰 Введите сумму для <b>{cat['name']}</b>:\n\n/cancel — отмена",
        parse_mode=ParseMode.HTML,
    )
    return SPEND_AMOUNT


async def spend_receive_cat_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    user = update.effective_user
    me = await db.get_user(user.id)
    group_id = me.get("group_id")
    cat = await db.get_category_by_name(group_id, name)
    if cat is None:
        cats = await db.get_categories(group_id)
        names = ", ".join(c["name"] for c in cats) or "нет категорий"
        await update.message.reply_text(
            f"❗ Категория «{name}» не найдена.\nДоступные: {names}\n\nПопробуйте снова:"
        )
        return SPEND_CAT
    context.user_data.setdefault("spend", {})["cat"] = cat
    context.user_data["spend"]["group_id"] = group_id
    await update.message.reply_text(
        f"💰 Введите сумму для <b>{cat['name']}</b>:\n\n/cancel — отмена",
        parse_mode=ParseMode.HTML,
    )
    return SPEND_AMOUNT


async def spend_receive_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw = update.message.text.strip()
    try:
        amount = float(raw.replace(",", "."))
    except ValueError:
        await update.message.reply_text("❗ Введите число. Попробуйте снова:")
        return SPEND_AMOUNT
    if amount <= 0:
        await update.message.reply_text("❗ Сумма должна быть больше нуля. Попробуйте снова:")
        return SPEND_AMOUNT

    context.user_data.setdefault("spend", {})["amount"] = amount
    await update.message.reply_text(
        "📝 Введите описание траты или нажмите «Пропустить»:\n\n/cancel — отмена",
        reply_markup=_skip_keyboard(),
    )
    return SPEND_DESC


async def spend_receive_desc_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data["spend"]["description"] = None
    await update.callback_query.message.reply_text(
        "📷 Прикрепите фото чека или нажмите «Пропустить»:",
        reply_markup=_skip_keyboard(),
    )
    return SPEND_PHOTO


async def spend_receive_desc_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["spend"]["description"] = update.message.text.strip()
    await update.message.reply_text(
        "📷 Прикрепите фото чека или нажмите «Пропустить»:",
        reply_markup=_skip_keyboard(),
    )
    return SPEND_PHOTO


async def spend_receive_photo_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await _finalize_spend(update, context, photo_file_id=None)
    return ConversationHandler.END


async def spend_receive_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo_file_id = update.message.photo[-1].file_id
    await _finalize_spend(update, context, photo_file_id=photo_file_id)
    return ConversationHandler.END


async def _finalize_spend(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    photo_file_id: str | None,
):
    user = update.effective_user
    data = context.user_data.pop("spend", {})
    cat = data["cat"]
    amount = data["amount"]
    description = data.get("description")
    group_id = data["group_id"]

    me = await db.get_user(user.id)
    await db.add_expense(cat["id"], me["id"], amount, description, photo_file_id)
    spent = await db.get_monthly_spent(cat["id"])

    msg = await _build_expense_message(
        who="", cat_name=cat["name"], amount=amount,
        spent=spent, budget=cat["monthly_budget"], description=description,
    )
    # Send to self
    effective_message = update.message or update.callback_query.message
    if photo_file_id:
        await effective_message.reply_photo(photo=photo_file_id, caption=msg, parse_mode=ParseMode.HTML, reply_markup=_group_keyboard())
    else:
        await effective_message.reply_text(msg, parse_mode=ParseMode.HTML, reply_markup=_group_keyboard())

    # Notify others
    notify_msg = await _build_expense_message(
        who=_user_display(user.id, user.username),
        cat_name=cat["name"], amount=amount,
        spent=spent, budget=cat["monthly_budget"], description=description,
    )
    await _notify_group(context, group_id, user.id, notify_msg, photo_file_id=photo_file_id)


def build_spend_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CommandHandler("spend", spend_entry),
            MessageHandler(filters.Text(["💸 Spend"]), spend_entry),
        ],
        states={
            SPEND_CAT: [
                CallbackQueryHandler(spend_receive_cat_cb, pattern=r"^cat:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, spend_receive_cat_text),
            ],
            SPEND_AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, spend_receive_amount),
            ],
            SPEND_DESC: [
                CallbackQueryHandler(spend_receive_desc_skip, pattern=r"^skip$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, spend_receive_desc_text),
            ],
            SPEND_PHOTO: [
                CallbackQueryHandler(spend_receive_photo_skip, pattern=r"^skip$"),
                MessageHandler(filters.PHOTO, spend_receive_photo),
            ],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
        per_user=True,
    )


# ══════════════════════════════════════════════════════════════════════════════
# ConversationHandler: /history
# ══════════════════════════════════════════════════════════════════════════════

async def history_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    me = await db.get_or_create_user(user.id, user.username)
    group_id = me.get("group_id")
    if not group_id:
        await update.message.reply_text("У вас нет категорий.")
        return ConversationHandler.END

    if context.args:
        return await _do_history(update, context, context.args[0])

    kb = await _cat_list_keyboard(group_id)
    await update.message.reply_text(
        "🗒 Выберите категорию или введите название:\n\n/cancel — отмена",
        reply_markup=kb,
    )
    return HISTORY_CAT


async def history_receive_cat_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    name = update.callback_query.data.split(":", 1)[1]
    return await _do_history(update, context, name)


async def history_receive_cat_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await _do_history(update, context, update.message.text.strip())


async def _do_history(update: Update, context: ContextTypes.DEFAULT_TYPE, cat_name: str):
    user = update.effective_user
    me = await db.get_user(user.id)
    group_id = me.get("group_id") if me else None
    if not group_id:
        msg = "У вас нет категорий."
        if update.callback_query:
            await update.callback_query.message.reply_text(msg)
        else:
            await update.message.reply_text(msg)
        return ConversationHandler.END

    cat = await db.get_category_by_name(group_id, cat_name)
    effective_message = update.message or update.callback_query.message
    if cat is None:
        await effective_message.reply_text(f"❗ Категория «{cat_name}» не найдена.")
        return ConversationHandler.END

    history = await db.get_expense_history(cat["id"])
    if not history:
        await effective_message.reply_text(f"Трат по «{cat['name']}» пока нет.", reply_markup=_group_keyboard())
        return ConversationHandler.END

    lines = [f"🗒 <b>История: {cat['name']}</b>\n"]
    for exp in history:
        dt = exp["created_at"][:16].replace("T", " ")
        who = _user_display(exp["telegram_id"], exp.get("username"))
        desc = f" — <i>{exp['description']}</i>" if exp.get("description") else ""
        photo_icon = " 📷" if exp.get("photo_file_id") else ""
        lines.append(f"• {dt} | {who} | <b>{exp['amount']:,.2f}</b>{desc}{photo_icon}")

    await effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=_group_keyboard())
    return ConversationHandler.END


def build_history_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("history", history_entry)],
        states={
            HISTORY_CAT: [
                CallbackQueryHandler(history_receive_cat_cb, pattern=r"^cat:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, history_receive_cat_text),
            ],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
        per_user=True,
    )


# ══════════════════════════════════════════════════════════════════════════════
# ConversationHandler: /delcat
# ══════════════════════════════════════════════════════════════════════════════

async def delcat_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    me = await db.get_or_create_user(user.id, user.username)
    group_id = me.get("group_id")
    if not group_id:
        await update.message.reply_text("У вас нет категорий.")
        return ConversationHandler.END

    if context.args:
        context.user_data["delcat_name"] = context.args[0]
        return await _delcat_ask_confirm(update, context)

    kb = await _cat_list_keyboard(group_id)
    await update.message.reply_text(
        "🗑 Выберите категорию для удаления или введите название:\n\n/cancel — отмена",
        reply_markup=kb,
    )
    return DELCAT_NAME


async def delcat_receive_cat_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data["delcat_name"] = update.callback_query.data.split(":", 1)[1]
    return await _delcat_ask_confirm(update, context)


async def delcat_receive_cat_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["delcat_name"] = update.message.text.strip()
    return await _delcat_ask_confirm(update, context)


async def _delcat_ask_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = context.user_data["delcat_name"]
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Да, удалить", callback_data="delcat:yes"),
            InlineKeyboardButton("❌ Отмена", callback_data="delcat:no"),
        ]
    ])
    effective_message = update.message or update.callback_query.message
    await effective_message.reply_text(
        f"Удалить категорию <b>{name}</b> и все её траты?",
        reply_markup=kb,
        parse_mode=ParseMode.HTML,
    )
    return DELCAT_CONFIRM


async def delcat_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    choice = update.callback_query.data.split(":", 1)[1]
    name = context.user_data.pop("delcat_name", "")

    if choice == "no":
        await update.callback_query.message.reply_text("Отменено.", reply_markup=_group_keyboard())
        return ConversationHandler.END

    user = update.effective_user
    me = await db.get_user(user.id)
    group_id = me.get("group_id") if me else None
    ok = await db.delete_category(group_id, name) if group_id else False

    if not ok:
        await update.callback_query.message.reply_text(f"❗ Категория «{name}» не найдена.", reply_markup=_group_keyboard())
        return ConversationHandler.END

    await update.callback_query.message.reply_text(
        f"🗑 Категория <b>{name}</b> и все её траты удалены.",
        parse_mode=ParseMode.HTML,
        reply_markup=_group_keyboard(),
    )
    await _notify_group(
        context, group_id, user.id,
        f"🗑 {_user_display(user.id, user.username)} удалил(а) категорию <b>{name}</b>.",
    )
    return ConversationHandler.END


def build_delcat_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("delcat", delcat_entry)],
        states={
            DELCAT_NAME: [
                CallbackQueryHandler(delcat_receive_cat_cb, pattern=r"^cat:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, delcat_receive_cat_text),
            ],
            DELCAT_CONFIRM: [
                CallbackQueryHandler(delcat_confirm, pattern=r"^delcat:"),
            ],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
        per_user=True,
    )
