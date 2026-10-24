"""Second-pass rescrape: (A) which UK retailers stock each brand, (B) is each fund's holding current or exited.

python step3.py retail|status|all   -> data/firecrawl/retail_check.jsonl, status_check.jsonl
Free sources first (Open Food Facts, plain HTTP); Firecrawl calls are cached on disk and capped by FC_BUDGET credits.
"""
import json, os, re, sys, time
from urllib.parse import quote, urlparse
from fx import *
from fx import _key

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = json.load(open(os.path.join(ROOT, "site", "data.json")))
RETAIL_P = os.path.join(OUT, "retail_check.jsonl")
STATUS_P = os.path.join(OUT, "status_check.jsonl")
BUDGET = int(os.environ.get("FC_BUDGET", "540"))
SPENT = [0]

RETAILERS = [("Tesco", r"\bTesco\b", "tesco.com"), ("Sainsbury's", r"Sainsbury", "sainsburys.co.uk"),
             ("Asda", r"\bAsda\b", "asda.com"), ("Morrisons", r"Morrisons", "morrisons.com"),
             ("Waitrose", r"Waitrose", "waitrose.com"), ("Ocado", r"\bOcado\b", "ocado.com"),
             ("M&S", r"\bM&S\b|Marks (&|and) Spencer", "marksandspencer.com"), ("Co-op", r"\bCo-?op\b|Co-operative", "coop.co.uk"),
             ("Aldi", r"\bAldi\b", "aldi.co.uk"), ("Lidl", r"\bLidl\b", "lidl.co.uk"),
             ("Boots", r"\bBoots\b", "boots.com"), ("Holland & Barrett", r"Holland (&|and) Barrett", "hollandandbarrett.com")]
SEARCH_PAGES = {  # retailer -> search URL template (JS-rendered; Firecrawl)
    "Asda": "https://groceries.asda.com/search/{q}",
    "Waitrose": "https://www.waitrose.com/ecom/shop/search?searchTerm={q}",
    "Sainsbury's": "https://www.sainsburys.co.uk/gol-ui/SearchResults/{q}",
    "Tesco": "https://www.tesco.com/groceries/en-GB/search?query={q}",
    "Ocado": "https://www.ocado.com/search?entry={q}",
    "Morrisons": "https://groceries.morrisons.com/search?entry={q}",
    "Holland & Barrett": "https://www.hollandandbarrett.com/search/?query={q}",
    "Boots": "https://www.boots.com/search?text={q}",
}
NO_RESULTS = re.compile(r"no matches for|couldn.t find|no results|0 results|sorry, we couldn", re.I)
GENERIC = {"proper", "good", "pure", "simply", "natural", "the", "real", "little", "true", "stocked", "freja", "rude", "only", "fresh",
           "happy", "wild", "green", "daily", "urban", "honest", "better", "super", "mighty", "glow", "free"}
SUFFIX = re.compile(r"\b(snacks?|foods?|drinks?|company|co|ltd|limited|brands?|group|uk|kitchen|bakery|coffee|tea|beverages?)\.?$", re.I)


def spend(n):
    if SPENT[0] + n > BUDGET:
        return False
    SPENT[0] += n
    return True


def fc_scrape_b(url, wait_ms=None):
    if not os.path.exists(_key(url, "fc")) and not spend(1):
        return None
    return fc_scrape(url, wait_ms)


def fc_search_b(q, limit=10, tbs=None):
    if not os.path.exists(_key(q + "|" + str(limit) + str(tbs) + str(None), "fcsearch")) and not spend(2):
        return None
    j = fc_search(q, limit=limit, tbs=tbs)
    return [r for r in ((j.get("data") or {}).get("web") or j.get("web") or [])] if isinstance(j, dict) else []


ALIASES = {"Tyrrells Crisps": "Tyrrells", "PROPER SNACKS": "Propercorn", "Purity Soft Drinks": "Juiceburst",
           "Vibrant Foods": "KTC"}  # on-shelf brand differs from the company name


def name_rx(name):
    """Whole-word brand matcher; also accepts the name minus a generic suffix when that stem is distinctive."""
    n = re.sub(r"\s+", " ", name.replace("’", "'")).strip()
    alts = {n}
    if name in ALIASES:
        alts.add(ALIASES[name])
    stem = SUFFIX.sub("", n).strip()
    if stem != n and len(stem) >= 5 and stem.lower() not in GENERIC:
        alts.add(stem)
    return re.compile(r"(?<![\w])(" + "|".join(re.escape(a).replace(r"\ ", r"[\s\-]?") for a in sorted(alts, key=len, reverse=True)) + r")(?![\w])", re.I)


PRODUCT_URL = re.compile(r"/products?/|/p/|/shop/product|-\d{6,}(\?|$)", re.I)


def title_match(brand, rx, title):
    """Product titles lead with the brand; insist on that for generic-word names like 'Stocked'."""
    if brand.lower() in GENERIC or SUFFIX.sub("", brand).strip().lower() in GENERIC or len(brand) <= 4:
        return bool(re.match(rx.pattern, title.strip(), re.I))
    return bool(rx.search(title))


def retailer_of_url(u):
    h = urlparse(u).netloc.lower()
    for name, _, dom in RETAILERS:
        if h == dom or h.endswith("." + dom):
            return name
    return None


def retailers_in_text(t):
    return [name for name, rx, _ in RETAILERS if re.search(rx, t or "", re.I)]


def slug(n):
    return re.sub(r"[^a-z0-9]+", "-", n.lower().replace("'", "").replace("’", "")).strip("-")


# ---------- (A) retailers ----------

def off_lookup(brand, rx):
    """Open Food Facts UK products for the brand; map their stores field."""
    found = {}
    urls = [f"https://world.openfoodfacts.org/api/v2/search?brands_tags={quote(slug(brand))}&countries_tags=en:united-kingdom"
            f"&fields=product_name,brands,stores&page_size=50",
            f"https://world.openfoodfacts.org/cgi/search.pl?search_terms={quote(brand)}&json=1&page_size=50"
            f"&fields=product_name,brands,stores,countries_tags"]
    for u in urls:
        d = http_get(u, timeout=40)
        try:
            prods = json.loads(d["html"]).get("products") or []
        except Exception:
            continue
        for p in prods:
            if not rx.search(p.get("brands") or ""):
                continue
            if "countries_tags" in p and "en:united-kingdom" not in (p.get("countries_tags") or []):
                continue
            for r in retailers_in_text(p.get("stores")):
                found.setdefault(r, {"name": r, "source": "openfoodfacts", "url": u,
                                     "evidence": f"{p.get('product_name') or ''} (stores: {p.get('stores')})"})
    return found


def search_lookup(brand, rx, have):
    """Google-style site: search across the retailer domains (2 credits per query)."""
    found = {}
    doms = [d for n, _, d in RETAILERS if n not in have]
    for _ in range(2):
        if not doms:
            break
        q = f'"{brand}" ' + " OR ".join("site:" + d for d in doms)
        res = fc_search_b(q, 10)
        if res is None:
            break
        hits = set()
        for r in res:
            ret = retailer_of_url(r.get("url", ""))
            title = r.get("title") or ""
            if ret and PRODUCT_URL.search(r.get("url", "")) and title_match(brand, rx, title):
                hits.add(ret)
                found.setdefault(ret, {"name": ret, "source": "firecrawl_search", "url": r["url"].split("?srsltid")[0],
                                       "evidence": title})
        # results saturated by a few retailers -> one more query without them
        if len(res) >= 10 and hits:
            doms = [d for n, _, d in RETAILERS if n not in have and n not in found]
        else:
            break
    return found


STOCKIST = re.compile(r"stockist|where[-\s]?to[-\s]?buy|find[-\s]?us|retailers|find[-\s]?a[-\s]?store|shop[-\s]?in[-\s]?store|in[-\s]?store", re.I)


def site_lookup(b, rx, use_fc):
    """Brand's own site: stockists / where-to-buy page (HTTP; Firecrawl render if allowed)."""
    found = {}
    web = b.get("website")
    if not web:
        return found
    home = http_get(web)
    pages = []
    if home.get("html"):
        for href, txt in links_of(home["html"], home.get("final_url") or web):
            if STOCKIST.search(href) or STOCKIST.search(txt):
                if urlparse(href).netloc.replace("www.", "") == urlparse(web).netloc.replace("www.", "") and href not in pages:
                    pages.append(href)
    pages = pages[:2] or [web.rstrip("/") + "/stockists"]
    for p in pages:
        d = http_get(p)
        txt = visible_text(d["html"]) if d.get("status") == 200 and d.get("html") else ""
        method = "brand_site_http"
        if not retailers_in_text(txt) and use_fc:
            f = fc_scrape_b(p, 3000)
            if f and f.get("markdown"):
                txt, method = f["markdown"], "brand_site_firecrawl"
        for r in retailers_in_text(txt):
            m = re.search(r"[^\n]{0,80}" + [rx_ for n, rx_, _ in RETAILERS if n == r][0] + r"[^\n]{0,80}", txt, re.I)
            found.setdefault(r, {"name": r, "source": method, "url": p, "evidence": (m.group(0).strip() if m else r)[:200]})
    return found


BLOCKED = {}  # retailer -> reason, once a search page proves unusable


def retailer_page_lookup(brand, rx, have):
    found = {}
    for ret, tpl in SEARCH_PAGES.items():
        if ret in have or ret in found or ret in BLOCKED:
            continue
        u = tpl.format(q=quote(brand))
        f = fc_scrape_b(u, 3000)
        if f is None:
            break  # out of budget
        md = f.get("markdown") or ""
        fu = f.get("final_url") or u
        if f.get("error") or len(md) < 500 or re.search(r"captcha|access denied|are you a robot", md[:3000], re.I):
            BLOCKED[ret] = "blocked: " + (f.get("error") or "empty/captcha")[:80]
            continue
        if not re.search(r"search", fu, re.I):
            BLOCKED[ret] = f"search URL redirects to {fu}"
            continue
        if NO_RESULTS.search(md):
            continue
        for line in md.splitlines():
            t = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", line)
            m = re.search(r"\[\**([^\]]{6,160}?)\**\]\((https?://[^)\s]+)", t)
            if m and rx.search(m.group(1)) and re.search(r"/product", m.group(2)):
                found[ret] = {"name": ret, "source": "retailer_search_page", "url": u, "evidence": m.group(1).strip()}
                break
    return found


NON_FOOD = re.compile(r"vibrator|\bgames?\b|board game|\btoys?\b|\bpans?\b|grill\b|vacuum|jumper|killer|merino|wool|lipstick|"
                      r"body wash|fragrance|\bmist\b|candle|\bbook\b|\bdvd\b|\bmug\b|pint glass|t-shirt|socks|battle set|cushion|"
                      r"shampoo|perfume|\bpen\b|charger|cable|trainers?|dress|sofa", re.I)
EXCLUDE = {"Native Snacks": [r"Native Nutrients"]}  # same-word brands seen in results
PET = re.compile(r"\b(pet|pets|dog|dogs|cat|cats|puppy|kitten|canine|feline)\b|petfood|dogfood|catfood", re.I)


def plausible(b, rx, ent):
    """Second filter over every match: brand leads the product title, the product is food/drink, pet brands sell pet food."""
    ev = ent.get("evidence") or ""
    title = re.sub(r"\s*\(stores:.*$", "", ev).strip()
    if title.startswith("http"):  # no title came back: read the product slug instead
        title = re.sub(r"[-_/]+", " ", urlparse(title).path.split("/")[-1])
    if NON_FOOD.search(title):
        return False
    if ent["source"] in ("firecrawl_search", "retailer_search_page") and not re.match(r"(Reviews for )?" + rx.pattern, title, re.I):
        return False
    if any(re.search(x, title, re.I) for x in EXCLUDE.get(b.get("name"), [])):
        return False
    generic = b.get("name", "").lower() in GENERIC or len(b.get("name", "")) <= 4
    pet_brand = PET.search(" ".join([b.get("description") or "", b.get("blurb") or "",
                                     re.sub(r"[^a-z]+", " ", (b.get("website") or "").lower())])) is not None
    if generic and pet_brand and ent["source"] != "brand_site_http" and not PET.search(title + " " + (ent.get("url") or "")):
        return False
    return True


def clean_retail():
    by = {b["name"]: b for b in DATA["brands"]}
    rows = [json.loads(l) for l in open(RETAIL_P)]
    dropped = 0
    for r in rows:
        b = by.get(r["brand"], {})
        rx = name_rx(r["brand"])
        keep = [e for e in r["retailers"] if plausible(b, rx, e)]
        dropped += len(r["retailers"]) - len(keep)
        r["dropped"] = [e for e in r["retailers"] if e not in keep] + r.get("dropped", [])
        r["retailers"] = keep
    with open(RETAIL_P, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("clean_retail: dropped", dropped, "implausible matches", flush=True)


def run_retail():
    done = {}
    if os.path.exists(RETAIL_P):
        for l in open(RETAIL_P):
            r = json.loads(l)
            done[r["brand"]] = r
    brands = sorted(DATA["brands"], key=lambda b: (bool(b.get("retailers")), -(b.get("fit") or 0)))
    rows = {}
    # pass 1: free sources + one search per brand
    for i, b in enumerate(brands):
        name, rx = b["name"], name_rx(b["name"])
        if name in done and done[name].get("pass", 0) >= 1:
            rows[name] = done[name]
            continue
        q = ALIASES.get(name, name)
        found = off_lookup(q, rx)
        found.update({k: v for k, v in search_lookup(q, rx, found).items() if k not in found})
        found.update({k: v for k, v in site_lookup(b, rx, False).items() if k not in found})
        rows[name] = {"brand": name, "website": b.get("website"), "had_before": [r["name"] for r in b.get("retailers") or []],
                      "retailers": list(found.values()), "pass": 1}
        print(f"[retail 1] {i+1}/{len(brands)} {name}: {sorted(found)} (credits {SPENT[0]})", flush=True)
        write_jsonl(RETAIL_P, rows, done)
    # pass 2: brands still empty -> retailer search pages, then rendered brand stockist page
    for b in brands:
        r = rows[b["name"]]
        if r["retailers"] or r.get("pass", 0) >= 2 or b.get("retailers"):
            continue
        rx = name_rx(b["name"])
        found = retailer_page_lookup(b["name"], rx, set())
        if not found:
            found = site_lookup(b, rx, True)
        r["retailers"] = list(found.values())
        r["pass"] = 2
        print(f"[retail 2] {b['name']}: {sorted(found)} (credits {SPENT[0]}, blocked {sorted(BLOCKED)})", flush=True)
        write_jsonl(RETAIL_P, rows, done)
        if SPENT[0] >= BUDGET - 2:
            print("budget reached", flush=True)
            break
    json.dump(BLOCKED, open(os.path.join(OUT, "raw", "step3_blocked.json"), "w"))
    clean_retail()


def write_jsonl(path, rows, done):
    allr = dict(done)
    allr.update(rows)
    with open(path, "w") as f:
        for v in allr.values():
            f.write(json.dumps(v, ensure_ascii=False) + "\n")


# ---------- (B) holding status ----------

EXIT_LBL = re.compile(r"\b(full exit|exited|exit(?:ed)? in|realised|realized|divested|former investment|past investment|"
                      r"previous investment|alumni|sold to|acquired by)\b", re.I)
SECTION = re.compile(r"^\s*(exited|exits|realised|realized|unrealised|unrealized|past|former|current|active)\b(\s+(investments?|portfolio|companies|holdings))?\s*$", re.I)
PARTIAL = re.compile(r"\bpartial(ly)? exit|partial secondary", re.I)


def portfolio_evidence(fund, brand, rx):
    """Look for an exit label near the brand on the fund's portfolio page / stored profile text."""
    for c in fund.get("_companies", []):
        if rx.search(c.get("name") or ""):
            desc = c.get("description") or ""
            if EXIT_LBL.search(desc) and not PARTIAL.search(desc):
                return "exited", f"portfolio card: {desc[:160]}", c.get("profile_url") or c.get("source_url")
            if PARTIAL.search(desc):
                return "current", f"portfolio card says partial exit (still holds): {desc[:160]}", c.get("source_url")
    labels_on_page = False
    for u in fund["portfolio_urls"][:2]:
        html, fu, method = get(u, need_text_len=800, allow_fc=False)
        if not html:
            continue
        if not re.search(rx, visible_text(html)) or len(visible_text(html)) < 800:
            f = fc_scrape_b(u, 3000)
            if f and f.get("html"):
                html, fu = f["html"], f.get("final_url") or u
        s = BeautifulSoup(html, "lxml")
        for t in s(["script", "style", "noscript"]):
            t.decompose()
        page_txt = s.get_text(" ")
        # a lone 'Current / Exited' filter widget says nothing; cards must carry the labels
        labels_on_page = labels_on_page or len(EXIT_LBL.findall(page_txt)) >= 3
        for node in s.find_all(string=rx):
            el = node.parent
            for _ in range(4):  # the brand's card
                if el.parent is None or len(el.parent.get_text(" ", strip=True)) > 400:
                    break
                el = el.parent
            card = el.get_text(" ", strip=True)
            if len(card) > 400:
                continue
            if PARTIAL.search(card):
                return "current", f"portfolio card says partial exit (still holds): {card[:160]}", fu
            if EXIT_LBL.search(card):
                return "exited", f"portfolio card: {card[:160]}", fu
            head = el.find_previous(["h1", "h2", "h3", "h4"], string=SECTION)  # real headings only; filter buttons say nothing
            if head:
                ht = head.get_text(" ", strip=True)
                if re.search(r"exit|(?<!un)reali[sz]|past|former", ht, re.I):
                    return "exited", f"listed under '{ht[:60]}'", fu
                if re.search(r"current|active|unreali[sz]", ht, re.I):
                    return "current", f"listed under '{ht[:60]}'", fu
        if s.find(string=rx) and labels_on_page:
            return "current?", f"on portfolio page without exit label (page labels exits elsewhere)", fu
    return None, None, None


ACQ = r"(acquired|bought|snapped up|purchased|taken over)"


def fund_tokens(name):
    base = re.sub(r"\s*\(.*?\)", "", name).strip()
    toks = {base.lower()}
    first = base.split()[0].lower()
    if len(first) >= 3 and first not in {"the", "big", "true", "five", "development", "active", "sustainable"}:
        toks.add(first)
    if base.lower().startswith("development bank"):
        toks.add("development bank")
    if base.lower().startswith("active partners"):
        toks.add("active partners")
    return toks


def news_evidence(fund, brand, rx):
    """Exit = a buyer other than the fund takes the brand, or the fund sells. The fund buying in is entry, not exit."""
    fn = re.sub(r"\s*\(.*?\)", "", fund["name"])
    res = fc_search_b(f'"{brand}" (acquired OR acquisition OR "sold to" OR exit) {fn}', 10,
                      tbs="cdr:1,cd_min:10/1/2021,cd_max:10/31/2026")
    if not res:
        return None, None, None
    b = rx.pattern
    ftoks = [t for t in fund_tokens(fund["name"])]
    is_fund = lambda who: any(t in (who or "").lower() for t in ftoks)
    BUYER = r"([A-Z][\w&'.\-]*(?: [A-Z&][\w&'.\-]*){0,4})"
    entry = None
    for r in res:
        txt = " ".join([r.get("title") or "", r.get("description") or ""])
        if not rx.search(txt):
            continue
        yr = re.search(r"\b(202[1-6])\b", txt + " " + (r.get("url") or ""))
        when = f" ({yr.group(1)})" if yr else ""
        if "acquired company?" in txt:  # data-broker Q&A pages, not reporting
            continue
        if re.search(r"partial(ly)? exit[^.]{0,60}" + b + "|" + b + r"[^.]{0,60}partial(ly)? exit|partial secondary", txt, re.I):
            return "current", f"partial exit only, fund still holds: {txt[:140]}{when}", r.get("url")
        m = re.search(re.escape(fn) + r"[^.]{0,40}\b(exits?|exited|sells?|sold|completes? (the )?sale of|realis\w+)\b[^.]{0,40}" + b, txt, re.I)
        if m:
            return "exited", m.group(0)[:160] + when, r.get("url")
        m = re.search(b + r"[^.]{0,60}\b(has been |was |is being )?(acquired|bought|snapped up|taken over) by " + BUYER, txt) or \
            re.search(b + r"[^.]{0,40}\bsold to " + BUYER, txt)
        if m and not is_fund(m.group(m.lastindex)) and not rx.search(m.group(m.lastindex)):
            return "exited", m.group(0)[:160] + when, r.get("url")
        m = re.search(BUYER + r" (acquires|has acquired|acquired|buys|bought|completes acquisition of|snaps up) (?!(a |an )?(majority |minority )?stake)[^.,]{0,20}" + b, txt)
        if m:
            if rx.search(m.group(1)):
                pass  # brand's own holding company / IPO reorganisation
            elif is_fund(m.group(1)):
                entry = entry or (m.group(0)[:160] + when, r.get("url"), yr.group(1) if yr else None)
            else:
                return "exited", m.group(0)[:160] + when, r.get("url")
        m = re.search(r"\b(invests?|invested|backs|backed|acquires (a )?(majority |minority )?stake|led a|leads)\b[^.]{0,60}" + b, txt, re.I)
        if m and is_fund(txt[:m.start()][-80:] + m.group(0)):
            entry = entry or (m.group(0)[:160] + when, r.get("url"), yr.group(1) if yr else None)
    if entry and entry[2] and entry[2] >= "2023":
        return "current", f"fund invested recently, no exit found: {entry[0]}", entry[1]
    return None, None, None


def run_status():
    funds_raw = {f["fund"]: f for f in (json.loads(l) for l in open(os.path.join(OUT, "funds.jsonl")))}
    done = {}
    if os.path.exists(STATUS_P):
        for l in open(STATUS_P):
            r = json.loads(l)
            done[(r["fund"], r["brand"])] = r
    out = dict(done)
    pairs = [(f, b) for f in DATA["funds"] for b in f["brands"] if b["status"] == "unknown"]
    for i, (f, b) in enumerate(pairs):
        if (f["name"], b["brand"]) in done:
            continue
        f["_companies"] = (funds_raw.get(f["name"]) or {}).get("companies") or []
        rx = name_rx(b["brand"])
        st, ev, url = portfolio_evidence(f, b["brand"], rx)
        if st != "exited":
            st2, ev2, url2 = news_evidence(f, b["brand"], rx)
            if st2:
                st, ev, url = st2, ev2, url2
        if st == "current?":
            st = "current"
        row = {"fund": f["name"], "brand": b["brand"], "status": st or "unknown", "evidence": ev, "url": url}
        if row["status"] != "unknown" and not url:
            row["status"] = "unknown"
        out[(f["name"], b["brand"])] = row
        print(f"[status] {i+1}/{len(pairs)} {f['name']} / {b['brand']}: {row['status']} — {ev} (credits {SPENT[0]})", flush=True)
        with open(STATUS_P, "w") as fh:
            for v in out.values():
                fh.write(json.dumps(v, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    if what in ("status", "all"):
        run_status()
    if what in ("retail", "all"):
        run_retail()
    if what == "clean":
        clean_retail()
    print("credits spent this run:", SPENT[0], flush=True)
