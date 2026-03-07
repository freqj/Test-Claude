from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

import database as db


# ───────────────────────── helpers ──────────────────────────

def _user_display(telegram_id: int, username: str | None) -> str:
    if username:
        return f"@{username}"
    return f"#{telegram_id}"


def _progress_bar(spent: float, budget: float, width: int = 10) -> str:
    if budget <= 0:
        return "█" * width
    ratio = min(spent / budget, 1.0)
    filled = round(ratio * width)
    bar = "█" * filled + "░" * (width - filled)
    percent = ratio * 100
    return f"[{bar}] {percent:.0f}%"


async def _notify_group(
    context: ContextTypes.DEFAULT_TYPE,
    group_id: int,
    exclude_telegram_id: int,
    text: str,
):
    members = await db.get_group_members(group_id)
    for member in members:
        if member["telegram_id"] == exclude_telegram_id:
            continue
        try:
            await context.bot.send_message(
                chat_id=member["telegram_id"],
                text=text,
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass


# ───────────────────────── /start ──────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await db.get_or_create_user(user.id, user.username)

    text = (
        "👋 <b>Бот учёта бюджета</b>\n\n"
        "Команды:\n"
        "  /link <code>&lt;ID&gt;</code> — привязать пользователя\n"
        "  /accept <code>&lt;ID&gt;</code> — принять запрос привязки\n"
        "  /addcat <code>&lt;название&gt; &lt;сумма&gt;</code> — добавить категорию\n"
        "  /setbudget <code>&lt;название&gt; &lt;сумма&gt;</code> — изменить бюджет категории\n"
        "  /spend <code>&lt;категория&gt; &lt;сумма&gt; [описание]</code> — добавить трату\n"
        "  /budget — текущий бюджет по всем категориям\n"
        "  /history <code>&lt;категория&gt;</code> — последние 10 трат категории\n"
        "  /delcat <code>&lt;название&gt;</code> — удалить категорию\n"
        "  /myid — показать ваш Telegram ID\n\n"
        "Счёт сбрасывается <b>1-го числа каждого месяца</b>.\n"
        "Чтобы привязаться к другому пользователю:\n"
        "1️⃣ Пользователь A: <code>/link ID_пользователя_B</code>\n"
        "2️⃣ Пользователь B: <code>/accept ID_пользователя_A</code>"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


# ───────────────────────── /myid ──────────────────────────

async def cmd_myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"Ваш Telegram ID: <code>{update.effective_user.id}</code>",
        parse_mode=ParseMode.HTML,
    )


# ───────────────────────── /link ──────────────────────────

async def cmd_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await db.get_or_create_user(user.id, user.username)

    if not context.args:
        await update.message.reply_text(
            "Использование: /link <code>&lt;ID пользователя&gt;</code>\n"
            "Узнать ID можно командой /myid",
            parse_mode=ParseMode.HTML,
        )
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("ID должен быть числом.")
        return

    if target_id == user.id:
        await update.message.reply_text("Нельзя привязаться к самому себе.")
        return

    target = await db.get_user(target_id)
    if target is None:
        await update.message.reply_text(
            "Пользователь не найден. Попросите его написать боту /start."
        )
        return

    # Check if already in same group
    me = await db.get_user(user.id)
    if me["group_id"] and me["group_id"] == target["group_id"]:
        await update.message.reply_text("Вы уже привязаны к этому пользователю.")
        return

    await db.create_link_request(user.id, target_id)

    try:
        await context.bot.send_message(
            chat_id=target_id,
            text=(
                f"🔗 Пользователь {_user_display(user.id, user.username)} "
                f"хочет привязать вас к общему бюджету.\n\n"
                f"Чтобы принять: /accept <code>{user.id}</code>"
            ),
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        pass

    await update.message.reply_text(
        f"✅ Запрос отправлен пользователю <code>{target_id}</code>. "
        f"Ожидайте подтверждения.",
        parse_mode=ParseMode.HTML,
    )


# ───────────────────────── /accept ──────────────────────────

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
        await update.message.reply_text(
            "Запрос не найден. Попросите пользователя отправить /link снова."
        )
        return

    await db.delete_link_request(from_id, user.id)
    await db.link_users(from_id, user.id)

    from_user = await db.get_user(from_id)
    await update.message.reply_text(
        f"✅ Вы привязаны к пользователю {_user_display(from_id, from_user.get('username'))}! "
        f"Теперь у вас общий бюджет."
    )

    try:
        await context.bot.send_message(
            chat_id=from_id,
            text=(
                f"✅ Пользователь {_user_display(user.id, user.username)} "
                f"принял запрос. Теперь у вас общий бюджет!"
            ),
        )
    except Exception:
        pass


# ───────────────────────── /addcat ──────────────────────────

async def cmd_addcat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    me = await db.get_or_create_user(user.id, user.username)

    if len(context.args) < 2:
        await update.message.reply_text(
            "Использование: /addcat <code>&lt;название&gt; &lt;бюджет&gt;</code>\n"
            "Пример: /addcat Продукты 15000",
            parse_mode=ParseMode.HTML,
        )
        return

    name = context.args[0]
    try:
        budget = float(context.args[1])
    except ValueError:
        await update.message.reply_text("Бюджет должен быть числом.")
        return

    if budget <= 0:
        await update.message.reply_text("Бюджет должен быть больше нуля.")
        return

    group_id = me.get("group_id")
    if group_id is None:
        # Create a solo group
        async with __import__("aiosqlite").connect(__import__("database").DB_PATH) as dbc:
            cur = await dbc.execute("INSERT INTO groups DEFAULT VALUES")
            group_id = cur.lastrowid
            await dbc.execute(
                "UPDATE users SET group_id = ? WHERE telegram_id = ?",
                (group_id, user.id),
            )
            await dbc.commit()

    cat = await db.add_category(group_id, name, budget)
    if cat is None:
        # Update existing
        await db.update_category_budget(group_id, name, budget)
        await update.message.reply_text(
            f"📝 Бюджет категории <b>{name}</b> обновлён: <b>{budget:,.2f}</b>",
            parse_mode=ParseMode.HTML,
        )
        return

    await update.message.reply_text(
        f"✅ Категория <b>{name}</b> создана с бюджетом <b>{budget:,.2f}</b>",
        parse_mode=ParseMode.HTML,
    )

    me_fresh = await db.get_user(user.id)
    await _notify_group(
        context,
        me_fresh["group_id"],
        user.id,
        f"📂 {_user_display(user.id, user.username)} создал(а) категорию "
        f"<b>{name}</b> с бюджетом <b>{budget:,.2f}</b>",
    )


# ───────────────────────── /setbudget ──────────────────────────

async def cmd_setbudget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    me = await db.get_or_create_user(user.id, user.username)

    if len(context.args) < 2:
        await update.message.reply_text(
            "Использование: /setbudget <code>&lt;категория&gt; &lt;новый_бюджет&gt;</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    name = context.args[0]
    try:
        budget = float(context.args[1])
    except ValueError:
        await update.message.reply_text("Бюджет должен быть числом.")
        return

    group_id = me.get("group_id")
    if group_id is None:
        await update.message.reply_text("У вас нет категорий. Создайте через /addcat.")
        return

    ok = await db.update_category_budget(group_id, name, budget)
    if not ok:
        await update.message.reply_text(f"Категория «{name}» не найдена.")
        return

    await update.message.reply_text(
        f"✅ Бюджет категории <b>{name}</b> изменён на <b>{budget:,.2f}</b>",
        parse_mode=ParseMode.HTML,
    )
    await _notify_group(
        context,
        group_id,
        user.id,
        f"✏️ {_user_display(user.id, user.username)} изменил(а) бюджет "
        f"категории <b>{name}</b> → <b>{budget:,.2f}</b>",
    )


# ───────────────────────── /spend ──────────────────────────

async def cmd_spend(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    me = await db.get_or_create_user(user.id, user.username)

    if len(context.args) < 2:
        await update.message.reply_text(
            "Использование: /spend <code>&lt;категория&gt; &lt;сумма&gt; [описание]</code>\n"
            "Пример: /spend Продукты 350 Молоко и хлеб",
            parse_mode=ParseMode.HTML,
        )
        return

    cat_name = context.args[0]
    try:
        amount = float(context.args[1])
    except ValueError:
        await update.message.reply_text("Сумма должна быть числом.")
        return

    if amount <= 0:
        await update.message.reply_text("Сумма должна быть больше нуля.")
        return

    description = " ".join(context.args[2:]) if len(context.args) > 2 else None

    group_id = me.get("group_id")
    if group_id is None:
        await update.message.reply_text(
            "У вас нет категорий. Создайте через /addcat."
        )
        return

    cat = await db.get_category_by_name(group_id, cat_name)
    if cat is None:
        cats = await db.get_categories(group_id)
        names = ", ".join(f"<b>{c['name']}</b>" for c in cats) or "нет категорий"
        await update.message.reply_text(
            f"Категория «{cat_name}» не найдена.\nДоступные: {names}",
            parse_mode=ParseMode.HTML,
        )
        return

    await db.add_expense(cat["id"], me["id"], amount, description)
    spent = await db.get_monthly_spent(cat["id"])
    budget = cat["monthly_budget"]
    bar = _progress_bar(spent, budget)
    over = spent > budget

    desc_line = f"\n📝 <i>{description}</i>" if description else ""
    status_icon = "🔴" if over else "🟢"

    msg = (
        f"{status_icon} <b>{cat['name']}</b>{desc_line}\n"
        f"Трата: <b>+{amount:,.2f}</b>\n"
        f"Итого: <b>{spent:,.2f} / {budget:,.2f}</b>\n"
        f"{bar}"
    )
    if over:
        msg += f"\n⚠️ Превышение на <b>{spent - budget:,.2f}</b>!"

    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

    notify_text = (
        f"💸 {_user_display(user.id, user.username)} добавил(а) трату\n"
        f"Категория: <b>{cat['name']}</b>{desc_line}\n"
        f"Сумма: <b>+{amount:,.2f}</b>\n"
        f"Итого: <b>{spent:,.2f} / {budget:,.2f}</b>\n"
        f"{bar}"
    )
    if over:
        notify_text += f"\n⚠️ Превышение на <b>{spent - budget:,.2f}</b>!"

    await _notify_group(context, group_id, user.id, notify_text)


# ───────────────────────── /budget ──────────────────────────

async def cmd_budget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    me = await db.get_or_create_user(user.id, user.username)

    group_id = me.get("group_id")
    if group_id is None:
        await update.message.reply_text(
            "У вас нет категорий. Создайте через /addcat."
        )
        return

    cats = await db.get_categories(group_id)
    if not cats:
        await update.message.reply_text("Категорий пока нет. Добавьте через /addcat.")
        return

    from datetime import datetime
    now = datetime.now()
    lines = [f"📊 <b>Бюджет за {now.strftime('%B %Y')}</b>\n"]

    total_budget = 0.0
    total_spent = 0.0

    for cat in cats:
        spent = await db.get_monthly_spent(cat["id"])
        budget = cat["monthly_budget"]
        total_budget += budget
        total_spent += spent
        bar = _progress_bar(spent, budget)
        icon = "🔴" if spent > budget else "🟢"
        lines.append(
            f"{icon} <b>{cat['name']}</b>\n"
            f"   {spent:,.2f} / {budget:,.2f}\n"
            f"   {bar}"
        )

    lines.append(
        f"\n💰 <b>Всего: {total_spent:,.2f} / {total_budget:,.2f}</b>\n"
        f"{_progress_bar(total_spent, total_budget)}"
    )

    members = await db.get_group_members(group_id)
    member_names = ", ".join(_user_display(m["telegram_id"], m.get("username")) for m in members)
    lines.append(f"\n👥 Участники: {member_names}")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


# ───────────────────────── /history ──────────────────────────

async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    me = await db.get_or_create_user(user.id, user.username)

    if not context.args:
        await update.message.reply_text(
            "Использование: /history <code>&lt;категория&gt;</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    cat_name = context.args[0]
    group_id = me.get("group_id")
    if group_id is None:
        await update.message.reply_text("У вас нет категорий.")
        return

    cat = await db.get_category_by_name(group_id, cat_name)
    if cat is None:
        await update.message.reply_text(f"Категория «{cat_name}» не найдена.")
        return

    history = await db.get_expense_history(cat["id"])
    if not history:
        await update.message.reply_text(f"Трат по категории «{cat['name']}» нет.")
        return

    lines = [f"🗒 <b>История: {cat['name']}</b>\n"]
    for exp in history:
        dt = exp["created_at"][:16].replace("T", " ")
        who = _user_display(exp["telegram_id"], exp.get("username"))
        desc = f" — <i>{exp['description']}</i>" if exp.get("description") else ""
        lines.append(f"• {dt} | {who} | <b>{exp['amount']:,.2f}</b>{desc}")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


# ───────────────────────── /delcat ──────────────────────────

async def cmd_delcat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    me = await db.get_or_create_user(user.id, user.username)

    if not context.args:
        await update.message.reply_text(
            "Использование: /delcat <code>&lt;категория&gt;</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    cat_name = context.args[0]
    group_id = me.get("group_id")
    if group_id is None:
        await update.message.reply_text("У вас нет категорий.")
        return

    ok = await db.delete_category(group_id, cat_name)
    if not ok:
        await update.message.reply_text(f"Категория «{cat_name}» не найдена.")
        return

    await update.message.reply_text(
        f"🗑 Категория <b>{cat_name}</b> и все её траты удалены.",
        parse_mode=ParseMode.HTML,
    )
    await _notify_group(
        context,
        group_id,
        user.id,
        f"🗑 {_user_display(user.id, user.username)} удалил(а) категорию <b>{cat_name}</b>.",
    )
