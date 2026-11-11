# /// script
# requires-python = ">=3.10"
# dependencies = ["markdown==3.10"]
# ///
"""Build the public Russian TOVARNO documentation from repository Markdown."""
from pathlib import Path
import shutil
import markdown

root = Path(__file__).resolve().parents[1]
out = root / "docs-site"
out.mkdir(exist_ok=True)
pages = [
    ("index.html", "Начало", "docs/index.md"),
    ("guide.html", "Руководство", "docs/user-guide.md"),
    ("api.html", "REST API", "docs/supplier-api.md"),
    ("finance.html", "Финансы", "docs/finance-guide.md"),
]
css = """*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:#F5F9FA;color:#192638;font:16px/1.75 'Open Sans',system-ui,sans-serif}
aside{position:fixed;width:260px;height:100vh;background:#fff;border-right:1px solid #d5dfe3;padding:32px 22px}aside img{width:216px;margin:0 0 30px}
nav a{display:block;text-decoration:none;color:#536474;padding:10px 15px;border-radius:8px;margin:4px 0}nav a[aria-current=page]{background:#DDF3EC;color:#192638;font-weight:600}
main{max-width:1160px;margin-left:260px;padding:48px 64px 96px}h1{font-size:clamp(30px,4vw,44px);line-height:1.15;letter-spacing:-1.2px}h2{font-size:25px;line-height:1.3;margin-top:42px}h3{font-size:20px;margin-top:30px}a{color:#246f70;text-underline-offset:3px}p,li{max-width:900px}pre{background:#192638;color:#F5F9FA;padding:20px;border-radius:12px;overflow:auto;line-height:1.6;font-size:13px}code{font-family:ui-monospace,monospace;font-size:.9em}
p code,li code,td code{overflow-wrap:anywhere}table{border-collapse:collapse;width:100%;font-size:14px}th,td{padding:10px;text-align:left;border:1px solid #d5dfe3;overflow-wrap:anywhere}th{background:#DDF3EC}
footer{margin-top:60px;border-top:1px solid #d5dfe3;padding-top:20px;font-size:13px;color:#536474}
.table-wrap{overflow:auto}blockquote{border-left:3px solid #2D8687;margin:20px 0;padding-left:20px}
@font-face{font-family:'Open Sans';src:url('assets/open-sans.ttf');font-weight:300 800;font-display:swap}
@media(max-width:800px){aside{position:static;width:auto;height:auto;padding:18px 16px;border-right:0;border-bottom:1px solid #d5dfe3}aside img{width:200px;margin:0 0 12px}nav{display:flex;flex-wrap:wrap}nav a{padding:7px 10px;font-size:14px;margin:0}main{margin:0;padding:24px 18px 64px}th,td{min-width:110px}pre{font-size:12px}}
"""
(out / "assets").mkdir(exist_ok=True)
shutil.copyfile(root / "prototype/fonts/open-sans.ttf", out / "assets/open-sans.ttf")
shutil.copyfile(root / "prototype/fonts/OFL.txt", out / "assets/OFL.txt")
shutil.copyfile(root / "prototype/brand/tovarno-brand-kit/svg-transparent/tovarno-horizontal-light.svg", out / "assets/logo.svg")
(out / "site.css").write_text(css)
for filename, title, source in pages:
    nav = "".join(f'<a href="{name}"'+(' aria-current="page"' if name == filename else "")+f'>{label}</a>' for name,label,_ in pages)
    content = markdown.markdown((root/source).read_text(), extensions=["tables", "fenced_code", "sane_lists"])
    content = content.replace("<table>", '<div class="table-wrap"><table>').replace("</table>", "</table></div>")
    html = f'<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title} — ТОВАРНО</title><link rel="stylesheet" href="site.css"><aside><a href="index.html"><img src="assets/logo.svg" alt="ТОВАРНО — документация"></a><nav aria-label="Документация">{nav}</nav></aside><main>{content}<footer>ТОВАРНО · Документация<br><a href="https://app.moyskladdemo.xyz/">Кабинет</a> · <a href="https://t.me/tovarkonttolbot">Telegram</a> · <a href="https://github.com/qwwiwi/moysklad-telegram-dashboard-demo">GitHub</a></footer></main></html>'
    (out/filename).write_text(html)
(out/"files").mkdir(exist_ok=True)
shutil.copyfile(root / "demo/imports/supplier-direct-shipment-demo.xlsx", out/"files/supplier-direct-shipment-demo.xlsx")
print("Built 4 documentation pages")
