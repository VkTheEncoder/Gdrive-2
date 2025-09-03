from __future__ import annotations
import logging
import threading
from telegram.error import BadRequest
from .config import GOOGLE_OAUTH_MODE
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from .config import TELEGRAM_BOT_TOKEN, WEB_HOST, WEB_PORT
from .db import init_db
from .handlers import start, help_cmd, login, logout, me, setfolder_cmd, handle_document, handle_text
from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("gdrive_bot")

async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    import logging, traceback
    logging.exception("Unhandled error while processing update: %s", update)
    if hasattr(update, "effective_message") and update.effective_message:
        try:
            await update.effective_message.reply_text("⚠️ Something went wrong, but I’m still here.")
        except Exception:
            pass

def run_web():
    import uvicorn
    uvicorn.run("app.web:app", host=WEB_HOST, port=WEB_PORT, log_level="info", reload=False)

def main():
    if not TELEGRAM_BOT_TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN is missing")

    init_db()

    # Start FastAPI for OAuth in a background thread
    th = threading.Thread(target=run_web, daemon=True)
    th.start()

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("login", login))
    app.add_handler(CommandHandler("logout", logout))
    app.add_handler(CommandHandler("me", me))
    app.add_handler(CommandHandler("setfolder", setfolder_cmd))
    app.add_handler(
        MessageHandler(
            filters.Document.ALL | filters.VIDEO | filters.ANIMATION,
            handle_document
        )
    )
    # after you build the app:
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_error_handler(on_error)

    log.info("Bot started. Web server on %s:%s", WEB_HOST, WEB_PORT)
    app.run_polling(close_loop=False)
    
if GOOGLE_OAUTH_MODE == "web":
    th = threading.Thread(target=run_web, daemon=True)
    th.start()



if __name__ == "__main__":
    main()
