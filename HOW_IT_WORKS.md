# Telegram Booking Bot — Study Notes

Reference notes for the Reiki/Bio-magnetism booking bot project. Covers setup, the code so far, and the concepts behind it.

---

## Project Setup

**IDE:** VS Code
**Virtual environment (why):** keeps this project's libraries isolated from your global Python install — avoids the "externally-managed-environment" conflict and keeps dependencies clean per-project.

```bash
mkdir telegram-booking-bot
cd telegram-booking-bot
python3 -m venv .venv
source .venv/bin/activate   # prompt should show (.venv) when active
```

**Check you're actually inside the venv:**
```bash
which python
# should point to .../telegram-booking-bot/.venv/bin/python
# if it points to /usr/bin/python3 instead, the venv isn't active
```

**Libraries installed:**
```bash
pip install python-telegram-bot google-api-python-client google-auth-httplib2 google-auth-oauthlib python-dotenv
```
- `python-telegram-bot` — Telegram bot SDK
- `google-api-python-client` + `google-auth-*` — for Google Calendar integration (later phase)
- `python-dotenv` — loads secrets from a `.env` file instead of hardcoding them

**Bot creation:** via Telegram's **@BotFather** (verified account) → `/newbot` → gives display name + username (must end in `bot`) → returns an **API token**.

**Token storage — `.env` file (never hardcode tokens in code):**
```
TELEGRAM_BOT_TOKEN=your_actual_token_here
```

---

## Project Build Order (Phased)

1. **Phase 1 (current):** Bot conversation flow — collect name/date/time, no real calendar or payment yet.
2. **Phase 2:** Google Calendar integration — check availability, prevent double-booking, send reminders, handle cancellation/rebooking.
3. **Phase 3:** Booking fee / payment integration (Stripe or a Mexican processor like Clip/Conekta/MercadoPago) — deliberately saved for last since it's the most complex piece (security, refunds, compliance).

Reasoning: build the simplest working version first (MVP), add complexity in layers, so bugs are easier to isolate and you have a usable tool sooner rather than a half-finished project.

---

## The Code So Far (`bot.py`)

```python
import os
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, ContextTypes,
    ConversationHandler, MessageHandler, filters
)

load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

NAME, DATE, TIME = range(3)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hey! I'm your booking assistant. Send /book to schedule an appointment.")

async def book_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Let's book your session! What's your name?")
    return NAME

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = update.message.text
    await update.message.reply_text("Great! What date works for you? (e.g. 2026-07-25)")
    return DATE

async def get_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["date"] = update.message.text
    await update.message.reply_text("What time? (e.g. 14:00)")
    return TIME

async def get_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["time"] = update.message.text
    name = context.user_data["name"]
    date = context.user_data["date"]
    time = context.user_data["time"]
    await update.message.reply_text(f"Booking confirmed: {name}, {date} at {time}. (Not saved anywhere yet — that's next!)")
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Booking cancelled.")
    return ConversationHandler.END

def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))

    booking_handler = ConversationHandler(
        entry_points=[CommandHandler("book", book_start)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_date)],
            TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_time)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(booking_handler)

    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
```

To stop the running bot: `Ctrl+C` in the terminal.

---

## Concepts Explained

### `context` parameter
Every handler function **must** accept `(update, context)` — that's the fixed signature Telegram's library expects, similar to how `self` is required in class methods even if unused in a given method.

`context` carries bot-level tools and per-user memory:
- `context.user_data` — a dict that persists across multiple messages from the SAME user (used here to remember name/date/time between steps)
- `context.bot` — lets you send messages proactively, not just replies
- `context.job_queue` — for scheduling things later (e.g. reminders)

### Why `CommandHandler` alone isn't enough for multi-step booking
`CommandHandler` reacts to a single message and responds once — it has no memory of "what step are we on." Booking needs several sequential questions (name → date → time), so the bot needs to track **state**: which question is this reply answering?

### `ConversationHandler`
Tracks state between messages so the bot knows which question a reply is responding to.

- `entry_points` — what starts the conversation (e.g. `/book`)
- `states` — a dict mapping each "checkpoint" (NAME, DATE, TIME) to the handler function that processes the answer for that checkpoint
- `fallbacks` — an escape hatch (e.g. `/cancel`) so the user isn't stuck if they want to bail mid-flow

**Analogy:** `CommandHandler` = a vending machine button (press it, get one instant result, no memory). `ConversationHandler` = a receptionist who remembers what she already asked you, so your next answer is understood in context.

### `NAME, DATE, TIME = range(3)`
Just labels (0, 1, 2) marking which checkpoint the conversation is currently at. Each function handles one checkpoint, then returns the *next* checkpoint to move to.

### `async` / `await` — what they actually mean
- `async` marks a function as asynchronous — it can pause and let other work happen while waiting on something slow (usually network I/O).
- `await` does **not** mean "wait for the human to type." It means "pause this function here until this specific operation (usually a network call — sending/receiving data from Telegram's servers) finishes, and let other code run in the meantime."

**Why the bot needs this:** the bot isn't handling one linear conversation in isolation — it's potentially listening to many different users at once, and sending/receiving network requests takes real time. Without async, the bot would freeze entirely while waiting on one network call, unable to respond to anyone else in the meantime.

**Analogy:** synchronous = a waiter who takes one table's order, stares at the kitchen door until that dish is ready, then finally moves to the next table. Asynchronous = a waiter who takes table 1's order, goes and takes table 2's order while table 1's food cooks, then comes back to whichever table is ready first. Same waiter, way more efficient.

### `filters.TEXT & ~filters.COMMAND`
Means "accept plain text messages, but NOT if the user types another command (like `/start`) mid-conversation" — keeps the booking flow from getting confused by an unrelated command sneaking in.

**Why `~` and `&` work here (operator overloading):** `~` is normally Python's bitwise NOT, and `&` is normally bitwise AND — but the `filters` library overloads both operators to work meaningfully on filter *objects* instead of raw bits, same concept as overloading `__add__`/`__eq__` on a custom class (e.g. the `Vector`/`Perro` examples).

- `filters.TEXT` — "this message is text"
- `~filters.COMMAND` — "this message is NOT a command" (the `~` flips the condition)
- `&` — combines both conditions with AND logic

Put together: *"Accept this message only if it's plain text AND it's not a command."* Without the `~filters.COMMAND` part, typing `/cancel` mid-conversation could get swallowed as a literal answer (e.g. treated as the user's "name") instead of triggering the actual `/cancel` fallback.


---

## Troubleshooting Notes

**`externally-managed-environment` error on `pip install`:**
Use `pip install <package> --break-system-packages`, or better, always install inside an activated venv.

**`telegram.error.NetworkError: httpx.ReadError` while bot is running:**
Usually a transient connectivity blip (the bot holds a long-polling connection open to Telegram's servers; a brief wifi/ISP hiccup can interrupt it). The library has built-in retry logic and usually recovers on its own. Worth checking only if it happens *repeatedly* — could indicate an unstable connection, VPN, or firewall interfering with long-held connections.

**VS Code "packages installed into global environment" popup:**
Run `which python` in the VS Code terminal — if it points to your `.venv` path, you're fine, dismiss the popup. If it points to the system Python, the venv wasn't actually active when you installed, and you should re-activate and reinstall to be safe.

## Google Calendar Integration 

**Google Cloud Console setup:**

Go to https://console.cloud.google.com/
Create a new project (top-left dropdown → "New Project") — name it something like booking-bot
Once created, in the search bar at top, type "Google Calendar API" → click it → click Enable

**`Step 2 — Create credentials:`**

Left sidebar → APIs & Services → Credentials
Click + Create Credentials → OAuth client ID
If it asks you to configure a "consent screen" first (likely, cuz, since this is a new project) — choose External user type, fill in basic app info (app name, your email), you can leave most fields default for now since this is just for personal/testing use
Back at credentials creation — Application type: Desktop app (this is the easiest OAuth flow for a personal script like this)
Name it anything, click Create
It'll show you a Client ID and Client Secret — click Download JSON — this file is your credentials.json

**`Step 3, cuz:`**
Move that downloaded credentials.json file into your telegram-booking-bot project folder.

**`First, cuz — quick concept check before code:`** Google's OAuth flow works like this: the FIRST time your script runs, it'll pop open a browser window asking YOU to log in and grant permission ("this app wants to access your Google Calendar"). Once you approve, Google gives your script a token that it saves locally (usually in a file called token.json), so future runs DON'T need you to re-approve every single time — it just reuses that saved token.

**`Phase 2: Google Calendar Integration`**

**Step 1 — install one more library, cuz (if not already there from the earlier install):**

```bash
pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client
```