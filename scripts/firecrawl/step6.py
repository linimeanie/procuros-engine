"""Intro paths: who at each fund sits on (or near) each target brand's board.

python step6.py   -> data/firecrawl/intro_paths.jsonl
Needs the Companies House key like step5.py (reuses its cache, so most calls are free).
Per shortlisted fund: read its team pages (free HTTP first, Firecrawl if the page is JS-only).
Per target brand: list its Companies House officers. A board link is an officer whose first and
last name appear on the backing fund's team page; a corporate director or PSC named after the
fund also counts.
"""
import json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import step5
from fx import http_get, fc_scrape, visible_text, links_of
from urllib.parse import urlparse

ROOT = step5.ROOT
DATA = step5.DATA
OUT_P = os.path.join(ROOT, "data", "firecrawl", "intro_paths.jsonl")
FUNDS = {json.loads(l)["fund"]: json.loads(l) for l in open(os.path.join(ROOT, "data", "firecrawl", "funds.jsonl"))}
CHROWS = {json.loads(l)["brand"]: json.loads(l) for l in open(os.path.join(ROOT, "data", "firecrawl", "companies_house.jsonl"))}
TEAM_PATHS = ["team", "our-team", "people", "our-people", "about/team", "about-us/team", "about/our-team", "about-us/our-team",
              "about-us/our-people", "about/people", "meet-the-team", "who-we-are", "about", "about-us"]
TEAM_LINK = re.compile(r"team|people|who we are|about", re.I)


def page_text(url):
    d = http_get(url)
    txt = visible_text(d["html"]) if d and d.get("status") == 200 and d.get("html") else ""
    if len(txt) < 600:
        fc = fc_scrape(url)
        if fc and fc.get("html"):
            txt = visible_text(fc["html"])
    return txt, (d or {}).get("html") or ""


def team_text(fund):
    f = FUNDS[fund]
    site = f["website"].rstrip("/")
    urls = list(dict.fromkeys((f.get("team_pages_checked") or []) + [f"{site}/{p}" for p in TEAM_PATHS]))
    got, texts = [], []
    home = http_get(site)
    for h, t in (links_of(home["html"], home["final_url"]) if home and home.get("html") else []):
        if TEAM_LINK.search(t or "") and urlparse(h).netloc.replace("www.", "") == urlparse(site).netloc.replace("www.", ""):
            urls.insert(0, h)
    for u in urls:
        if len(got) >= 3:
            break
        d = http_get(u)
        if not d or d.get("status") != 200:
            continue
        txt, _ = page_text(u)
        if len(txt) > 300 and txt not in texts:
            got.append(u); texts.append(txt)
    return got, " \n ".join(texts)


def norm(s):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z ]", " ", (s or "").lower())).strip()


def officer_names(o):
    """CH gives 'SURNAME, First Middle'; return the 'first last' form to look for on a team page."""
    n = o.get("name") or ""
    if "," not in n:
        return None
    last, rest = n.split(",", 1)
    first = (rest.split() or [""])[0]
    return norm(f"{first} {last}") if first else None


def main():
    step5.KEY = step5.api_key()
    shortlist = [f for f in json.load(open(os.path.join(ROOT, "data", "scored", "funds_scored.json"))) if f["brands"]]
    team = {}
    for f in shortlist:
        urls, txt = team_text(f["fund"])
        team[f["fund"]] = (urls, " " + norm(txt) + " ")
        print(f["fund"], "team pages:", urls, len(txt))
    rows = []
    for f in shortlist:
        urls, txt = team[f["fund"]]
        toks = step5.fund_tokens(f["fund"])
        for b in f["brands"]:
            chrow = CHROWS.get(b["brand"]) or {}
            num = chrow.get("company_number")
            row = {"fund": f["fund"], "brand": b["brand"], "team_pages": urls, "company_number": num,
                   "board_people": [], "fund_entity": [], "officers_checked": 0}
            if num:
                offs = step5.ch(f"/company/{num}/officers?items_per_page=100").get("items") or []
                psc = step5.ch(f"/company/{num}/persons-with-significant-control?items_per_page=50").get("items") or []
                row["officers_checked"] = len(offs)
                for o in offs:
                    nm = officer_names(o)
                    if nm and f" {nm} " in txt:
                        row["board_people"].append({"name": o["name"], "role": o.get("officer_role"), "appointed": o.get("appointed_on"),
                                                    "resigned": o.get("resigned_on"), "occupation": o.get("occupation"),
                                                    "ch_url": f"{step5.WEB}/company/{num}/officers", "team_page": urls[0] if urls else None})
                    elif any(t in (o.get("name") or "").lower() for t in toks):
                        row["fund_entity"].append({"name": o["name"], "role": o.get("officer_role"), "since": o.get("appointed_on"),
                                                   "ceased": o.get("resigned_on"), "ch_url": f"{step5.WEB}/company/{num}/officers"})
                for p in psc:
                    if any(t in (p.get("name") or "").lower() for t in toks):
                        row["fund_entity"].append({"name": p["name"], "role": "PSC", "since": p.get("notified_on"), "ceased": p.get("ceased_on"),
                                                   "ch_url": f"{step5.WEB}/company/{num}/persons-with-significant-control"})
            rows.append(row)
            if row["board_people"] or row["fund_entity"]:
                print("  ", f["fund"], "->", b["brand"], [p["name"] for p in row["board_people"]], [e["role"] for e in row["fund_entity"]])
    with open(OUT_P, "w") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(len(rows), "pairs;", sum(1 for r in rows if r["board_people"]), "with a named board link;",
          sum(1 for r in rows if r["fund_entity"]), "with the fund itself on the register")


if __name__ == "__main__":
    main()
