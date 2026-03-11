import aiosqlite
import os
from datetime import datetime

DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(__file__), "budget.db"))


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE NOT NULL,
                username TEXT,
                group_id INTEGER
            );

            CREATE TABLE IF NOT EXISTS groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                monthly_budget REAL NOT NULL,
                UNIQUE(group_id, name),
                FOREIGN KEY (group_id) REFERENCES groups(id)
            );

            CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                description TEXT,
                photo_file_id TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (category_id) REFERENCES categories(id),
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS link_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_telegram_id INTEGER NOT NULL,
                to_telegram_id INTEGER NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            );
        """)
        await db.commit()
        # Migration: add photo_file_id if upgrading from older schema
        try:
            await db.execute("ALTER TABLE expenses ADD COLUMN photo_file_id TEXT")
            await db.commit()
        except Exception:
            pass
        # Migration: add owner_user_id to categories for private category support
        try:
            cursor = await db.execute("PRAGMA table_info(categories)")
            cols = [row[1] for row in await cursor.fetchall()]
            if "owner_user_id" not in cols:
                await db.executescript("""
                    PRAGMA foreign_keys = OFF;
                    CREATE TABLE categories_new (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        group_id INTEGER NOT NULL,
                        name TEXT NOT NULL,
                        monthly_budget REAL NOT NULL,
                        owner_user_id INTEGER NOT NULL DEFAULT 0,
                        UNIQUE(group_id, owner_user_id, name),
                        FOREIGN KEY (group_id) REFERENCES groups(id)
                    );
                    INSERT INTO categories_new (id, group_id, name, monthly_budget, owner_user_id)
                        SELECT id, group_id, name, monthly_budget, 0 FROM categories;
                    DROP TABLE categories;
                    ALTER TABLE categories_new RENAME TO categories;
                    PRAGMA foreign_keys = ON;
                """)
        except Exception:
            pass


async def get_or_create_user(telegram_id: int, username: str = None) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        )
        user = await cursor.fetchone()
        if user is None:
            await db.execute(
                "INSERT INTO users (telegram_id, username) VALUES (?, ?)",
                (telegram_id, username),
            )
            await db.commit()
            cursor = await db.execute(
                "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
            )
            user = await cursor.fetchone()
        return dict(user)


async def get_user(telegram_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_group_members(group_id: int) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM users WHERE group_id = ?", (group_id,)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def create_link_request(from_id: int, to_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM link_requests WHERE from_telegram_id = ? AND to_telegram_id = ?",
            (from_id, to_id),
        )
        await db.execute(
            "INSERT INTO link_requests (from_telegram_id, to_telegram_id) VALUES (?, ?)",
            (from_id, to_id),
        )
        await db.commit()


async def get_link_request(from_id: int, to_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM link_requests WHERE from_telegram_id = ? AND to_telegram_id = ?",
            (from_id, to_id),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def delete_link_request(from_id: int, to_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM link_requests WHERE from_telegram_id = ? AND to_telegram_id = ?",
            (from_id, to_id),
        )
        await db.commit()


async def link_users(user1_telegram_id: int, user2_telegram_id: int):
    """Merge two users into one group (or create a new group)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        cur1 = await db.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (user1_telegram_id,)
        )
        u1 = dict(await cur1.fetchone())
        cur2 = await db.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (user2_telegram_id,)
        )
        u2 = dict(await cur2.fetchone())

        g1 = u1.get("group_id")
        g2 = u2.get("group_id")

        if g1 is None and g2 is None:
            # Create new group
            cur = await db.execute("INSERT INTO groups DEFAULT VALUES")
            group_id = cur.lastrowid
        elif g1 is not None and g2 is None:
            group_id = g1
        elif g1 is None and g2 is not None:
            group_id = g2
        else:
            # Both in groups — merge g2 into g1
            group_id = g1
            await db.execute(
                "UPDATE categories SET group_id = ? WHERE group_id = ?", (g1, g2)
            )
            await db.execute(
                "UPDATE users SET group_id = ? WHERE group_id = ?", (g1, g2)
            )
            await db.execute("DELETE FROM groups WHERE id = ?", (g2,))

        await db.execute(
            "UPDATE users SET group_id = ? WHERE telegram_id IN (?, ?)",
            (group_id, user1_telegram_id, user2_telegram_id),
        )
        await db.commit()
        return group_id


async def add_category(group_id: int, name: str, budget: float) -> dict | None:
    """Returns None if category with this name already exists in group."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        try:
            cur = await db.execute(
                "INSERT INTO categories (group_id, name, monthly_budget) VALUES (?, ?, ?)",
                (group_id, name, budget),
            )
            await db.commit()
            cur2 = await db.execute(
                "SELECT * FROM categories WHERE id = ?", (cur.lastrowid,)
            )
            return dict(await cur2.fetchone())
        except aiosqlite.IntegrityError:
            return None


async def update_category_budget(group_id: int, name: str, budget: float) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "UPDATE categories SET monthly_budget = ? WHERE group_id = ? AND owner_user_id = 0 AND name = ?",
            (budget, group_id, name),
        )
        await db.commit()
        return cur.rowcount > 0


async def get_categories(group_id: int) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM categories WHERE group_id = ? AND owner_user_id = 0 ORDER BY name", (group_id,)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_category_by_name(group_id: int, name: str) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM categories WHERE group_id = ? AND owner_user_id = 0 AND LOWER(name) = LOWER(?)",
            (group_id, name),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_user_categories(group_id: int, user_id: int) -> list[dict]:
    """Returns shared categories + private categories owned by user_id."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """SELECT * FROM categories
               WHERE group_id = ? AND (owner_user_id = 0 OR owner_user_id = ?)
               ORDER BY owner_user_id, name""",
            (group_id, user_id),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def add_private_category(owner_user_id: int, group_id: int, name: str, budget: float) -> dict | None:
    """Returns None if a private category with this name already exists for this user."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        try:
            cur = await db.execute(
                "INSERT INTO categories (group_id, name, monthly_budget, owner_user_id) VALUES (?, ?, ?, ?)",
                (group_id, name, budget, owner_user_id),
            )
            await db.commit()
            cur2 = await db.execute("SELECT * FROM categories WHERE id = ?", (cur.lastrowid,))
            return dict(await cur2.fetchone())
        except aiosqlite.IntegrityError:
            return None


async def get_private_category_by_name(owner_user_id: int, group_id: int, name: str) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM categories WHERE group_id = ? AND owner_user_id = ? AND LOWER(name) = LOWER(?)",
            (group_id, owner_user_id, name),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def update_private_category_budget(owner_user_id: int, group_id: int, name: str, budget: float) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "UPDATE categories SET monthly_budget = ? WHERE group_id = ? AND owner_user_id = ? AND LOWER(name) = LOWER(?)",
            (budget, group_id, owner_user_id, name),
        )
        await db.commit()
        return cur.rowcount > 0


async def delete_private_category(owner_user_id: int, group_id: int, name: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur_cat = await db.execute(
            "SELECT id FROM categories WHERE group_id = ? AND owner_user_id = ? AND LOWER(name) = LOWER(?)",
            (group_id, owner_user_id, name),
        )
        cat = await cur_cat.fetchone()
        if not cat:
            return False
        await db.execute("DELETE FROM expenses WHERE category_id = ?", (cat["id"],))
        await db.execute("DELETE FROM categories WHERE id = ?", (cat["id"],))
        await db.commit()
        return True


async def add_expense(
    category_id: int,
    user_id: int,
    amount: float,
    description: str = None,
    photo_file_id: str = None,
) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "INSERT INTO expenses (category_id, user_id, amount, description, photo_file_id) VALUES (?, ?, ?, ?, ?)",
            (category_id, user_id, amount, description, photo_file_id),
        )
        await db.commit()
        cur2 = await db.execute(
            "SELECT * FROM expenses WHERE id = ?", (cur.lastrowid,)
        )
        return dict(await cur2.fetchone())


async def get_monthly_spent(category_id: int) -> float:
    """Sum of expenses for the current calendar month."""
    async with aiosqlite.connect(DB_PATH) as db:
        now = datetime.now()
        month_start = f"{now.year}-{now.month:02d}-01"
        cursor = await db.execute(
            """SELECT COALESCE(SUM(amount), 0) as total
               FROM expenses
               WHERE category_id = ?
                 AND created_at >= ?""",
            (category_id, month_start),
        )
        row = await cursor.fetchone()
        return row[0]


async def get_monthly_spent_by_user(category_id: int, user_id: int) -> float:
    """Sum of expenses for the current calendar month by a specific internal user_id."""
    async with aiosqlite.connect(DB_PATH) as db:
        now = datetime.now()
        month_start = f"{now.year}-{now.month:02d}-01"
        cursor = await db.execute(
            """SELECT COALESCE(SUM(amount), 0) as total
               FROM expenses
               WHERE category_id = ?
                 AND user_id = ?
                 AND created_at >= ?""",
            (category_id, user_id, month_start),
        )
        row = await cursor.fetchone()
        return row[0]


async def get_expense_history(category_id: int, limit: int = 10) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """SELECT e.*, u.username, u.telegram_id
               FROM expenses e
               JOIN users u ON e.user_id = u.id
               WHERE e.category_id = ?
               ORDER BY e.created_at DESC
               LIMIT ?""",
            (category_id, limit),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def delete_category(group_id: int, name: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur_cat = await db.execute(
            "SELECT id FROM categories WHERE group_id = ? AND owner_user_id = 0 AND LOWER(name) = LOWER(?)",
            (group_id, name),
        )
        cat = await cur_cat.fetchone()
        if not cat:
            return False
        await db.execute("DELETE FROM expenses WHERE category_id = ?", (cat["id"],))
        await db.execute("DELETE FROM categories WHERE id = ?", (cat["id"],))
        await db.commit()
        return True


async def reset_monthly_expenses(group_id: int):
    """Delete all expenses for this group (called on monthly reset)."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """DELETE FROM expenses WHERE category_id IN (
                   SELECT id FROM categories WHERE group_id = ?
               )""",
            (group_id,),
        )
        await db.commit()


async def get_all_groups() -> list[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT id FROM groups")
        rows = await cursor.fetchall()
        return [r[0] for r in rows]
