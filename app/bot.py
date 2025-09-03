from __future__ import annotations
import logging
import threading

from telegram.ext import Application, CommandHandler, MessageHandler, filters
from .config import TELEGRAM_BOT_TOKEN, WEB_HOST, WEB_PORT
from .db import init_db
from .handlers import start, help_cmd, login, logout, me, setfolder_cmd, handle_document, handle_text

logging.basicConfig(
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("gdrive_bot")

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

    app.add_handler(MessageHandler(filters.Document.ALL | filters.Video.ALL | filters.ANIMATION, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    log.info("Bot started. Web server on %s:%s", WEB_HOST, WEB_PORT)
    app.run_polling(close_loop=False)

if __name__ == "__main__":
    main()
