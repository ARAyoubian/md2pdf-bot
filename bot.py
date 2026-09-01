import os
import re
import tempfile
import markdown
import threading
import asyncio
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import Update
from telegram.ext import (
    Application,
    MessageHandler,
    filters,
    ContextTypes,
    CommandHandler
)
from playwright.async_api import async_playwright
from pygments.formatters import HtmlFormatter

# استایل‌های Pygments برای حالت روز و شب
CODE_STYLE_LIGHT = HtmlFormatter(style="friendly").get_style_defs('.codehilite')
CODE_STYLE_DARK = HtmlFormatter(style="monokai").get_style_defs('.codehilite')

# قفل همزمانی و متغیرهای سراسری مرورگر
conversion_lock = asyncio.Lock()
global_browser = None
playwright_instance = None
user_themes = {}  # ذخیره تنظیمات تم کاربران: {chat_id: 'light' | 'dark'}

def run_dummy_server():
    port = int(os.environ.get("PORT", 8080))
    class RequestHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(b"Bot is Running successfully on Back4App!")
    server = HTTPServer(('0.0.0.0', port), RequestHandler)
    server.serve_forever()

HTML_TEMPLATE = """
<!DOCTYPE html>
<html dir="auto">
<head>
    <meta charset="utf-8">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&family=Vazirmatn:wght@400;500;600;700&display=swap" rel="stylesheet">
    
    <style>
        :root {
            /* تنظیمات تم روشن */
            --bg-body: #ffffff;
            --text-main: #1f2328;
            --text-muted: #656d76;
            --bg-code: #f6f8fa;
            --border-color: #d0d7de;
            --accent-color: #0969da;
            --table-even: #fafbfc;
            --footer-color: #8c959f;
        }

        body.dark-theme {
            /* تنظیمات تم تاریک */
            --bg-body: #0d1117;
            --text-main: #e6edf3;
            --text-muted: #8b949e;
            --bg-code: #161b22;
            --border-color: #30363d;
            --accent-color: #58a6ff;
            --table-even: #161b22;
            --footer-color: #6e7681;
        }

        body {
            background-color: var(--bg-body);
            font-family: 'Inter', 'Vazirmatn', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            color: var(--text-main);
            line-height: 1.7;
            padding: 10px 25px;
            font-size: 15px;
            letter-spacing: -0.01em;
        }

        h1, h2, h3, h4, h5, h6 {
            color: var(--text-main);
            font-weight: 600;
            line-height: 1.3;
            margin-top: 24px;
            margin-bottom: 12px;
        }

        h1 { font-size: 26px; border-bottom: 2px solid var(--border-color); padding-bottom: 8px; }
        h2 { font-size: 20px; border-bottom: 1px solid var(--border-color); padding-bottom: 6px; }
        h3 { font-size: 17px; }

        p { margin-bottom: 14px; }

        pre, .codehilite {
            background-color: var(--bg-code) !important;
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 14px 16px;
            overflow-x: auto;
            direction: ltr !important;
            text-align: left !important;
            font-family: 'JetBrains Mono', monospace;
            font-size: 13.5px;
            line-height: 1.5;
            margin: 16px 0;
        }

        code {
            font-family: 'JetBrains Mono', monospace;
            background-color: var(--bg-code);
            border: 1px solid var(--border-color);
            padding: 2px 6px;
            border-radius: 5px;
            font-size: 85%;
            direction: ltr;
            display: inline-block;
        }

        pre code {
            border: none;
            background-color: transparent !important;
            padding: 0;
            display: block;
        }

        table {
            border-collapse: collapse;
            width: 100%;
            margin: 20px 0;
            font-size: 14px;
            border-radius: 6px;
            overflow: hidden;
            box-shadow: 0 0 0 1px var(--border-color);
        }

        th, td {
            padding: 10px 14px;
            border: 1px solid var(--border-color);
        }

        th {
            background-color: var(--bg-code);
            font-weight: 600;
            text-align: inherit;
        }

        tr:nth-child(even) {
            background-color: var(--table-even);
        }

        blockquote {
            margin: 16px 0;
            padding: 4px 18px;
            color: var(--text-muted);
            border-inline-start: 4px solid var(--accent-color);
            background: var(--bg-code);
            border-radius: 0 6px 6px 0;
        }

        img {
            max-width: 100%;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
            margin: 12px 0;
        }

        hr {
            height: 1px;
            background-color: var(--border-color);
            border: none;
            margin: 24px 0;
        }

        /* فهرست مطالب (TOC) */
        .toc {
            background: var(--bg-code);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 14px 20px;
            margin-bottom: 24px;
        }
        .toc ul { padding-inline-start: 20px; margin: 5px 0; }
        .toc a { color: var(--accent-color); text-decoration: none; }

        /* PYGMENTS_INJECTION */
    </style>
    
    <script>
        window.MathJax = {
            tex: {
                inlineMath: [['$', '$'], ['\\\\(', '\\\\)']],
                displayMath: [['$$', '$$'], ['\\\\[', '\\\\]']]
            },
            svg: { fontCache: 'global' }
        };
    </script>
    <script id="MathJax-script" async src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-chtml.js"></script>
</head>
<body class="{{BODY_CLASS}}">
    {{content}}
</body>
</html>
"""

def extract_title(md_text, default_name="Document"):
    match = re.search(r'^#\s+(.+)$', md_text, re.MULTILINE)
    if match:
        clean = re.sub(r'[\\/*?:"<>|]', '', match.group(1)).strip()
        if clean:
            return clean[:40]
    return default_name

async def init_browser():
    global global_browser, playwright_instance
    if not global_browser:
        playwright_instance = await async_playwright().start()
        global_browser = await playwright_instance.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage', '--disable-gpu']
        )
        print("✅ Global Browser Instance Initialized.")

async def generate_pdf(md_text, output_pdf_path, theme="light"):
    await init_browser()
    
    configs = {
        'codehilite': {
            'guess_lang': False,
            'css_class': 'codehilite'
        }
    }
    
    html_content = markdown.markdown(
        md_text, 
        extensions=['fenced_code', 'codehilite', 'tables', 'nl2br', 'mdx_math', 'toc'],
        extension_configs=configs
    )
    
    code_css = CODE_STYLE_DARK if theme == "dark" else CODE_STYLE_LIGHT
    body_class = "dark-theme" if theme == "dark" else ""
    
    full_html = HTML_TEMPLATE.replace('/* PYGMENTS_INJECTION */', code_css)
    full_html = full_html.replace('{{BODY_CLASS}}', body_class)
    full_html = full_html.replace('{{content}}', html_content)
    
    with tempfile.NamedTemporaryFile(delete=False, suffix='.html', mode='w', encoding='utf-8') as f:
        f.write(full_html)
        temp_html_path = f.name
        
    page = await global_browser.new_page()
    try:
        await page.goto(f"file://{temp_html_path}", wait_until="networkidle")
        await page.evaluate("""
            async () => {
                await document.fonts.ready;
                if (window.MathJax && window.MathJax.typesetPromise) {
                    await window.MathJax.typesetPromise();
                }
            }
        """)
        
        footer_color = "#6e7681" if theme == "dark" else "#8c959f"
        footer_html = f"""
        <div style="font-family: 'Inter', -apple-system, sans-serif; font-size: 10px; width: 100%; text-align: center; color: {footer_color}; padding-bottom: 5px;">
            Page <span class="pageNumber"></span> of <span class="totalPages"></span>
        </div>
        """
        
        await page.pdf(
            path=output_pdf_path, 
            format="Letter", 
            print_background=True,
            display_header_footer=True,
            header_template="<div></div>",
            footer_template=footer_html,
            margin={"top": "20mm", "bottom": "25mm", "left": "20mm", "right": "20mm"}
        )
    finally:
        await page.close()
        if os.path.exists(temp_html_path):
            os.remove(temp_html_path)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    theme = user_themes.get(update.effective_chat.id, "light")
    await update.message.reply_text(
        f"سلام! 👋\n\n"
        f"📄 فایل `.md` یا متن Markdown خود را بفرستید تا فوراً آن را با سایز Letter و تم دلخواه به PDF تبدیل کنم.\n\n"
        f"⚙️ تم فعلی شما: **{theme.upper()}**\n"
        f"• تغییر به تم تاریک: /dark\n"
        f"• تغییر به تم روشن: /light\n"
        f"• قرار دادن فهرست خودکار: نوشتن `[TOC]` در متن"
    )

async def set_light(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_themes[update.effective_chat.id] = "light"
    await update.message.reply_text("☀️ تم خروجی به **روشن (Light)** تغییر یافت.")

async def set_dark(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_themes[update.effective_chat.id] = "dark"
    await update.message.reply_text("🌙 تم خروجی به **تاریک (Dark)** تغییر یافت.")

async def process_conversion(update: Update, context: ContextTypes.DEFAULT_TYPE, md_text: str, file_title: str):
    chat_id = update.effective_chat.id
    theme = user_themes.get(chat_id, "light")
    
    status_msg = await update.message.reply_text("⏳ در صف پردازش...")
    
    async with conversion_lock:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=status_msg.message_id,
            text=f"⚙️ در حال تولید PDF (تم {theme})..."
        )
        pdf_path = f"temp_{update.message.message_id}.pdf"
        try:
            await generate_pdf(md_text, pdf_path, theme=theme)
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=status_msg.message_id,
                text="✅ فایل با موفقیت آماده شد!"
            )
            with open(pdf_path, 'rb') as f:
                await update.message.reply_document(document=f, filename=f"{file_title}.pdf")
        except Exception as e:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=status_msg.message_id,
                text=f"❌ خطایی رخ داد: {str(e)}"
            )
        finally:
            if os.path.exists(pdf_path):
                os.remove(pdf_path)

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not doc.file_name.lower().endswith('.md'):
        await update.message.reply_text("⛔ لطفاً فقط فایل با پسوند `.md` ارسال کنید یا متن آن را مستقیماً بفرستید.")
        return
        
    file = await context.bot.get_file(doc.file_id)
    md_temp = f"dl_{doc.file_id}.md"
    await file.download_to_drive(md_temp)
    
    with open(md_temp, 'r', encoding='utf-8') as f:
        md_text = f.read()
    os.remove(md_temp)
    
    file_title = doc.file_name.rsplit('.', 1)[0]
    await process_conversion(update, context, md_text, file_title)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text.startswith('/'):
        return
    file_title = extract_title(text, default_name=f"Note_{update.message.message_id}")
    await process_conversion(update, context, text, file_title)

if __name__ == '__main__':
    TOKEN = os.getenv("BOT_TOKEN")
    if not TOKEN:
        print("❌ Error: BOT_TOKEN is missing!")
    else:
        threading.Thread(target=run_dummy_server, daemon=True).start()
        print("✅ Starting Telegram Bot...")
        app = Application.builder().token(TOKEN).build()
        
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("light", set_light))
        app.add_handler(CommandHandler("dark", set_dark))
        app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
        
        app.run_polling()
