import os
import tempfile
import markdown
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes, CommandHandler
from playwright.async_api import async_playwright
from pygments.formatters import HtmlFormatter

# دریافت استایل رنگی کدها از کتابخانه Pygments
CODE_STYLE = HtmlFormatter(style="friendly").get_style_defs('.codehilite')

# سرور وب در پس‌زمینه برای زنده نگه داشتن محیط Back4App
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

HTML_TEMPLATE = f"""
<!DOCTYPE html>
<html dir="auto">
<head>
    <meta charset="utf-8">
    <!-- بارگذاری فونت‌های استاندارد Inter، Vazirmatn و JetBrains Mono -->
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&family=Vazirmatn:wght@400;500;600;700&display=swap" rel="stylesheet">
    
    <style>
        :root {{
            --text-main: #1f2328;
            --text-muted: #656d76;
            --bg-code: #f6f8fa;
            --border-color: #d0d7de;
            --accent-color: #0969da;
        }}

        body {{
            font-family: 'Inter', 'Vazirmatn', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            color: var(--text-main);
            line-height: 1.7;
            padding: 35px;
            font-size: 15px;
            letter-spacing: -0.01em;
        }}

        h1, h2, h3, h4, h5, h6 {{
            color: var(--text-main);
            font-weight: 600;
            line-height: 1.3;
            margin-top: 24px;
            margin-bottom: 12px;
        }}

        h1 {{ font-size: 26px; border-bottom: 2px solid var(--border-color); padding-bottom: 8px; }}
        h2 {{ font-size: 20px; border-bottom: 1px solid var(--border-color); padding-bottom: 6px; }}
        h3 {{ font-size: 17px; }}

        p {{ margin-bottom: 14px; }}

        /* هایلایت کدهای برنامه‌نویسی */
        pre, .codehilite {{
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
        }}

        code {{
            font-family: 'JetBrains Mono', monospace;
            background-color: rgba(175, 184, 193, 0.2);
            padding: 2px 6px;
            border-radius: 5px;
            font-size: 85%;
            direction: ltr;
            display: inline-block;
        }}

        pre code {{
            background-color: transparent !important;
            padding: 0;
            display: block;
        }}

        /* جداول مدرن */
        table {{
            border-collapse: collapse;
            width: 100%;
            margin: 20px 0;
            font-size: 14px;
            border-radius: 6px;
            overflow: hidden;
            box-shadow: 0 0 0 1px var(--border-color);
        }}

        th, td {{
            padding: 10px 14px;
            border: 1px solid var(--border-color);
        }}

        th {{
            background-color: var(--bg-code);
            font-weight: 600;
            text-align: inherit;
        }}

        tr:nth-child(even) {{
            background-color: #fafbfc;
        }}

        /* نقل‌قول‌ها */
        blockquote {{
            margin: 16px 0;
            padding: 4px 18px;
            color: var(--text-muted);
            border-inline-start: 4px solid var(--accent-color);
            background: #f8fafc;
            border-radius: 0 6px 6px 0;
        }}

        /* تصاویر */
        img {{
            max-width: 100%;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
            margin: 12px 0;
        }}

        hr {{
            height: 1px;
            background-color: var(--border-color);
            border: none;
            margin: 24px 0;
        }}

        {CODE_STYLE}
    </style>
    
    <!-- تنظیمات MathJax برای رندر ریاضیات -->
    <script>
        window.MathJax = {{
            tex: {{
                inlineMath: [['$', '$'], ['\\\\(', '\\\\)']],
                displayMath: [['$$', '$$'], ['\\\\[', '\\\\]']]
            }},
            svg: {{ fontCache: 'global' }}
        }};
    </script>
    <script id="MathJax-script" async src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-chtml.js"></script>
</head>
<body>
    {{content}}
</body>
</html>
"""

async def generate_pdf(md_text, output_pdf_path):
    # فعال‌سازی اکستنشن‌های markdown برای کد و جداول
    html_content = markdown.markdown(
        md_text, 
        extensions=['fenced_code', 'codehilite', 'tables', 'nl2br', 'mdx_math'],
        extension_configs={{
            'codehilite': {{
                'guess_lang': False,
                'css_class': 'codehilite'
            }}
        }}
    )
    full_html = HTML_TEMPLATE.replace('{{content}}', html_content)
    
    with tempfile.NamedTemporaryFile(delete=False, suffix='.html', mode='w', encoding='utf-8') as f:
        f.write(full_html)
        temp_html_path = f.name
        
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage', '--disable-gpu']
        )
        page = await browser.new_page()
        
        # بارگذاری صفحه و فونت‌های وب
        await page.goto(f"file://{temp_html_path}", wait_until="networkidle")
        
        # منتظر ماندن برای دانلود کامل فونت‌ها و رندر MathJax
        await page.evaluate("""
            async () => {
                await document.fonts.ready;
                if (window.MathJax && window.MathJax.typesetPromise) {
                    await window.MathJax.typesetPromise();
                }
            }
        """)
        
        await page.pdf(
            path=output_pdf_path, 
            format="A4", 
            print_background=True, 
            margin={"top": "20mm", "bottom": "20mm", "left": "20mm", "right": "20mm"}
        )
        await browser.close()
        
    os.remove(temp_html_path)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("سلام! فایل Markdown (.md) خود را بفرستید تا با قالب جدید و زیباسازی‌شده به PDF تبدیل کنم.")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    document = update.message.document
    if not document.file_name.lower().endswith('.md'):
        await update.message.reply_text("⛔ لطفاً فقط فایل `.md` بفرستید.")
        return
        
    status_msg = await update.message.reply_text("📥 در حال پردازش و استایل‌دهی به سند...")
    try:
        file = await context.bot.get_file(document.file_id)
        md_path = f"{document.file_id}.md"
        pdf_path = f"{document.file_id}.pdf"
        await file.download_to_drive(md_path)
        
        with open(md_path, 'r', encoding='utf-8') as f:
            md_text = f.read()
            
        await generate_pdf(md_text, pdf_path)
        await context.bot.edit_message_text(chat_id=update.message.chat_id, message_id=status_msg.message_id, text="✅ فایل با موفقیت آماده شد!")
        
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
        print("❌ Error: BOT_TOKEN is missing!")
    else:
        threading.Thread(target=run_dummy_server, daemon=True).start()
        print("✅ Starting Telegram Bot...")
        app = Application.builder().token(TOKEN).build()
        app.add_handler(CommandHandler("start", start))
        app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
        app.run_polling()

