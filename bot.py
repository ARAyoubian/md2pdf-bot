import os
import tempfile
import markdown
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes, CommandHandler
from playwright.async_api import async_playwright

HTML_TEMPLATE = """
<!DOCTYPE html>
<html dir="auto">
<head>
    <meta charset="utf-8">
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Vazirmatn", "Helvetica Neue", Arial, sans-serif; line-height: 1.6; padding: 40px; font-size: 16px; }
        pre { background: #f4f4f4; padding: 15px; border-radius: 8px; overflow-x: auto; direction: ltr; }
        code { background: #f4f4f4; padding: 2px 5px; border-radius: 4px; font-family: monospace; }
        table { border-collapse: collapse; width: 100%; margin-bottom: 20px; }
        th, td { border: 1px solid #ddd; padding: 10px; text-align: left; }
        th { background-color: #f8f9fa; }
        img { max-width: 100%; height: auto; border-radius: 8px; }
        blockquote { border-left: 4px solid #ddd; margin: 0; padding-left: 15px; color: #555; }
    </style>
    <script>
        MathJax = {
            tex: { inlineMath: [['$', '$'], ['\\\\(', '\\\\)']], displayMath: [['$$', '$$'], ['\\\\[', '\\\\]']] },
            startup: { pageReady: () => { return MathJax.startup.defaultPageReady().then(() => { document.body.innerHTML += '<div id="mathjax-done"></div>'; }); } }
        };
    </script>
    <script id="MathJax-script" async src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script>
</head>
<body>
    {{content}}
</body>
</html>
"""

async def generate_pdf(md_text, output_pdf_path):
    html_content = markdown.markdown(md_text, extensions=['fenced_code', 'tables', 'nl2br', 'mdx_math'])
    full_html = HTML_TEMPLATE.replace('{{content}}', html_content)

    with tempfile.NamedTemporaryFile(delete=False, suffix='.html', mode='w', encoding='utf-8') as f:
        f.write(full_html)
        temp_html_path = f.name

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(f"file://{temp_html_path}")
        await page.wait_for_selector('#mathjax-done', timeout=15000)
        await page.pdf(path=output_pdf_path, format="A4", print_background=True, margin={"top": "20mm", "bottom": "20mm", "left": "20mm", "right": "20mm"})
        await browser.close()

    os.remove(temp_html_path)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("سلام! یک فایل Markdown (.md) بفرست تا اون رو به PDF تبدیل کنم.")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    document = update.message.document
    if not document.file_name.lower().endswith('.md'):
        await update.message.reply_text("⛔ لطفاً فقط فایل `.md` بفرست.")
        return

    status_msg = await update.message.reply_text("📥 در حال پردازش فایل...")
    try:
        file = await context.bot.get_file(document.file_id)
        md_path, pdf_path = f"{document.file_id}.md", f"{document.file_id}.pdf"
        await file.download_to_drive(md_path)

        with open(md_path, 'r', encoding='utf-8') as f:
            md_text = f.read()

        await generate_pdf(md_text, pdf_path)
        
        await context.bot.edit_message_text(chat_id=update.message.chat_id, message_id=status_msg.message_id, text="✅ فایل آماده شد!")
        
        with open(pdf_path, 'rb') as f:
            await update.message.reply_document(document=f, filename=document.file_name.replace('.md', '.pdf'))

    except Exception as e:
        await context.bot.edit_message_text(chat_id=update.message.chat_id, message_id=status_msg.message_id, text=f"❌ خطایی رخ داد: {str(e)}")
    finally:
        if os.path.exists(md_path): os.remove(md_path)
        if os.path.exists(pdf_path): os.remove(pdf_path)

if __name__ == '__main__':
    TOKEN = os.getenv("BOT_TOKEN")
    if not TOKEN:
        raise ValueError("خطا: توکن یافت نشد! متغیر محیطی BOT_TOKEN در سرور تنظیم نشده است.")
    
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.run_polling()
