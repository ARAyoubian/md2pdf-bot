"""md2pdf.app"""
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
import os
import sys
import threading
from md2pdf.assets import (ensure_assets)
from md2pdf.config import (BOT_VERSION, logger)
from md2pdf.handlers import (button_callback, error_handler, handle_document, handle_text, start)
from md2pdf.health import (run_dummy_server)
from md2pdf.pdf_render import (close_browser, ensure_browser)
from md2pdf.selftest import (selftest)




async def post_init(application: Application):
    try:
        await ensure_browser()
    except Exception:
        logger.exception("Browser warm-up failed; it will be retried on the first request")




async def post_shutdown(application: Application):
    await close_browser()




def main():
    if "--fetch-assets" in sys.argv:
        ensure_assets(force=True)
        return

    token = os.environ.get("BOT_TOKEN")
    if not token:
        logger.error("BOT_TOKEN is missing!")
        sys.exit(1)

    threading.Thread(target=run_dummy_server, daemon=True).start()
    ensure_assets()

    logger.info("Starting Telegram Bot... version=%s", BOT_VERSION)
    app = (
        Application.builder()
        .token(token)
        .concurrent_updates(True)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    app.add_handler(CommandHandler(["start", "help", "settings"], start))
    app.add_handler(CommandHandler("selftest", selftest))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_error_handler(error_handler)

    app.run_polling()
