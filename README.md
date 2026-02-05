# Couple Wish Reminder Bot

A Telegram bot for couples to share and track wishes. Each partner can add wishes to their list, view their partner's wishes, and receive daily reminders with a random wish from their partner.

## Features

- **Pair with your partner** using a unique code
- **Add wishes** to your personal wish list
- **View partner's wishes** anytime
- **Daily notifications** with a random wish from your partner's list
- **Configurable notification time** (per user, in UTC)
- **Fulfill wishes** to mark them as done

## Setup

### 1. Create a Telegram Bot

1. Open Telegram and message [@BotFather](https://t.me/BotFather)
2. Send `/newbot` and follow the prompts
3. Copy the bot token

### 2. Configure

```bash
cp .env.example .env
```

Edit `.env` and add your bot token:

```
TELEGRAM_BOT_TOKEN=your-token-here
```

### 3. Install & Run

```bash
pip install -r requirements.txt
python main.py
```

## Commands

| Command | Description |
|---------|-------------|
| `/start` | Register and get your pair code |
| `/help` | Show all available commands |
| `/pair <code>` | Pair with your partner using their code |
| `/unpair` | Unpair from your partner |
| `/mycode` | Show your pair code |
| `/addwish <text>` | Add a wish to your list |
| `/mywishes` | View your wishes |
| `/partnerwishes` | View your partner's wishes |
| `/removewish <id>` | Remove one of your wishes |
| `/fulfillwish <id>` | Mark a partner's wish as fulfilled |
| `/settime HH:MM` | Set daily notification time (UTC) |

## How It Works

1. Both partners `/start` the bot and receive a unique pair code
2. One partner sends `/pair <code>` with the other's code to link accounts
3. Both can add wishes with `/addwish`
4. Every day at the configured time (default 09:00 UTC), each partner receives a random wish from the other's list
5. Partners can mark wishes as fulfilled with `/fulfillwish`

## Tech Stack

- Python 3.10+
- [python-telegram-bot](https://python-telegram-bot.org/) v21
- SQLite for persistence
- APScheduler (via python-telegram-bot's JobQueue)
