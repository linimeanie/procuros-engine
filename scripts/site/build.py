"""Wrap site/page.html (the artifact-form page) into a standalone site/index.html for Vercel."""
from pathlib import Path

SITE = Path(__file__).resolve().parents[2] / "site"
page = (SITE / "page.html").read_text()
head_end = page.index("</style>") + len("</style>")
html = ("<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1, viewport-fit=cover\">\n"
        "<style>:root{padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}"
        "body{margin:0}img{max-width:100%}[hidden]{display:none!important}</style>\n"
        + page[:head_end] + "\n</head>\n<body>\n" + page[head_end:] + "\n</body>\n</html>\n")
(SITE / "index.html").write_text(html)
print("wrote", SITE / "index.html")
