import os
from dotenv import load_dotenv
from bot_setup import build_application


load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


def main():
    ''' CommandHandler reacts to ONE single message like /start or /book and responds ONCE - it has no memory of "what step are you on"
        So, we need something more suitable for this so we'd use "ConversationHandler" which solves this by tracking STATE - it remembers
        "this user is currently on step 2 (waiting for date), not step 1 (waiting for name)" between messages.
        
        entry_points=[CommandHandler("book", book_start)] — this is what TRIGGERS the conversation (someone sends /book)
        fallbacks=[CommandHandler("cancel", cancel)] — lets the user bail out mid-conversation with /cancel
        filters.TEXT & ~filters.COMMAND — means "accept plain text replies, but NOT if they type another command" — 
        keeps the flow from getting confused if someone types /start mid-booking
    '''
    app = build_application(TOKEN)
    print("Bot is running...")
    app.run_polling() # OK, this is an infinite loop constantly asking Telegram "any updates?" BUT this do not work in AWS. Keep it in mind.


if __name__ == "__main__":
    main()


