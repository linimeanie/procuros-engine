import json, re, sys, os
from concurrent.futures import ThreadPoolExecutor
from fx import *

STAGE = sys.argv[1]
FUNDS_P = os.path.join(OUT, "funds.jsonl")
CAND_P = os.path.join(OUT, "grocery_candidates.json")
BRANDS_P = os.environ.get("BRANDS_P") or os.path.join(OUT, "brands.jsonl")

FOOD = re.compile(r"\b(food|foods|drink|drinks|beverage|beverages|snack|snacks|snacking|chocolate|chocolatier|confectioner|sweets|coffee|tea|teas|"
                  r"beer|brewery|brewer|brewing|ale|lager|cider|gin|distiller|distillery|spirits|whisky|whiskey|vodka|rum|tequila|wine|winery|"
                  r"prosecco|juice|juices|smoothie|soft drink|soda|kombucha|kefir|protein bar|cereal|cereals|granola|porridge|oats|crisps|popcorn|"
                  r"baker|bakery|baked|bread|biscuit|biscuits|cake|cakes|sauce|sauces|condiment|condiments|seasoning|spice|spices|plant-based|"
                  r"vegan|dairy|milk|cheese|yoghurt|yogurt|ice cream|gelato|frozen|chilled|ready meal|ready meals|meal kit|baby food|infant|"
                  r"weaning|toddler food|pet food|dog food|cat food|treats|nutrition|superfood|health food|fmcg|grocery|groceries|"
                  r"supermarket|supermarkets|butcher|meat|poultry|seafood|fish|honey|jam|nut butter|peanut butter|hummus|pasta|noodle|"
                  r"pizza|soup|broth|crackers|nuts|dried fruit|sugar|syrup|mixer|mixers|tonic|cocktail|non-alcoholic|alcohol-free|low alcohol|"
                  r"energy drink|water brand|sparkling water|hydration|electrolyte|supplement|supplements|vitamins|gummies|food and drink|"
                  r"food & drink|food manufacturer|food producer|own-label|private label)\b", re.I)
EXCL = re.compile(r"\b(restaurant|restaurants|pub|pubs|bar group|bars|café|cafe|cafes|coffee shop|coffee shops|hospitality|dining|"
                  r"saas|software|platform|app\b|marketplace|agtech|ag-tech|agritech|vertical farm|cultivated|cultured meat|cell-based|"
                  r"bioworks|biotech|precision fermentation|fintech|insurtech|logistics provider|recruitment|consultancy|"
                  r"wholesaler|foodservice|catering|contract caterer|takeaway|delivery app|quick service|qsr|franchise|"
                  r"packaging manufacturer|machinery|equipment|ingredients supplier|b2b)\b", re.I)
STRONG = re.compile(r"\b(brand|brands|stocked|stockists|supermarket|supermarkets|tesco|sainsbury|waitrose|ocado|asda|morrisons|"
                    r"m&s|marks & spencer|holland & barrett|boots|co-op|aldi|lidl|fmcg|consumer goods|retailers)\b", re.I)
UK = re.compile(r"\b(UK|U\.K\.|United Kingdom|Britain|British|England|English|Scotland|Scottish|Wales|Welsh|Northern Ireland|London|"
                r"Manchester|Birmingham|Leeds|Bristol|Edinburgh|Glasgow|Cardiff|Yorkshire|Cornwall|Devon|Somerset|Kent|Sussex|"
                r"Norfolk|Suffolk|Lancashire|Cheshire|Midlands|Hampshire|Surrey|Dorset|Liverpool|Newcastle|Sheffield|Nottingham)\b")
UK_FUNDS = {"BGF", "LDC", "Piper", "Livingbridge", "Palatine", "YFM Equity Partners", "Mobeus", "NorthEdge", "Kester Capital",
            "Elaghmore", "Penta Capital", "Rutland Partners", "Inverleith", "Primary Capital", "ECI Partners", "Gresham House Ventures",
            "Literacy Capital", "JamJar Investments", "Beringea", "Pembroke VCT", "Foresight Group", "Maven Capital Partners",
            "Puma Private Equity", "SFC Capital", "Blackfinch Ventures", "Development Bank of Wales", "Mercia Ventures",
            "Hambro Perks", "Fuel Ventures", "Ascension", "Angel Investment Network", "Active Partners", "Smedvig Capital",
            "Langholm Capital", "Cairngorm Capital", "CBPE", "Synova", "Endless", "Tenzing", "Exponent", "Silverfleet"}
RETAILERS = [("Tesco", r"\bTesco\b"), ("Sainsbury's", r"Sainsbury"), ("Asda", r"\bAsda\b|\bASDA\b"), ("Morrisons", r"Morrisons"),
             ("Waitrose", r"Waitrose"), ("Ocado", r"\bOcado\b"), ("Co-op", r"\bCo-?op\b|Co-operative"),
             ("M&S", r"\bM&S\b|M&amp;S|Marks (&|and) Spencer"), ("Boots", r"\bBoots\b"), ("Holland & Barrett", r"Holland (&|and) Barrett"),
             ("Aldi", r"\bAldi\b|\bALDI\b"), ("Lidl", r"\bLidl\b|\bLIDL\b"), ("Amazon", r"\bAmazon\b"), ("Booker", r"\bBooker\b")]
ROLE_RX = re.compile(r"supply chain|operations|operational|order processing|order management|\bERP\b|\bEDI\b|logistics|customer service|"
                     r"customer care|customer experience|planner|planning|procurement|purchasing|demand|fulfilment|fulfillment|warehouse|"
                     r"inventory|stock controller|account(s)? (receivable|payable)|sales order|ecommerce operations|ops\b", re.I)
ERP_RX = re.compile(r"\b(SAP|S/4HANA|NetSuite|Microsoft Dynamics|Dynamics 365|Business Central|Navision|Sage (X3|200|50|Intacct)|Sage\b|"
                    r"Xero|Odoo|Unleashed|Brightpearl|Cin7|Linnworks|Khaos Control|OrderWise|Sanderson|Xentral|weclapp|Infor|Epicor|"
                    r"Oracle (ERP|Fusion)|Exact Online|SAP Business One|Sage X3|Access Dimensions|Katana|Tradegecko|QuickBooks|"
                    r"\bEDI\b|electronic data interchange|\bERP\b)\b", re.I)


def norm(n):
    return re.sub(r"[^a-z0-9]", "", (n or "").lower())


def classify():
    funds = [json.loads(l) for l in open(FUNDS_P)]
    cands = {}
    H = json.load(open("homes.json")) if os.path.exists("homes.json") else {}
    from collections import Counter
    for f in funds:
        def ctext(c):
            hm = {}
            if c.get("website"):
                p = urlparse(c["website"]); hm = H.get(f"{p.scheme}://{p.netloc}", {})
            c["_home"] = (hm.get("title", "") + " " + hm.get("desc", "")).strip()
            return " ".join(str(c.get(k) or "") for k in ("name", "description", "sector_tag_on_site")) + " " + c["_home"] + " " + (c.get("_text") or "")[:2500]
        tf = Counter()
        for c in f["companies"]:
            for t in set(m.lower() for m in FOOD.findall(ctext(c))):
                tf[t] += 1
        n = len(f["companies"])
        chrome = {t for t, k in tf.items() if n >= 8 and k > 0.3 * n}
        for c in f["companies"]:
            txt = ctext(c)
            food = set(m.lower() for m in FOOD.findall(txt)) - chrome
            excl = set(m.lower() for m in EXCL.findall(" ".join(str(c.get(k) or "") for k in ("description", "sector_tag_on_site")) + " " + (c.get("_text") or "")[:1200]))
            strong = bool(STRONG.search(txt))
            uk = bool(UK.search(txt)) or (c.get("website") or "").rstrip("/").endswith((".co.uk", ".uk")) or f["fund"] in UK_FUNDS
            score = len(food) + (2 if strong else 0) - 2 * len(excl)
            if len(food) >= 1 and score >= 1:
                k = norm(c["name"])
                e = cands.setdefault(k, {"brand": c["name"], "website": c.get("website"), "funds": [], "sources": [],
                                         "food_terms": sorted(food), "excl_terms": sorted(excl), "uk_signal": uk, "score": score,
                                         "description": (c.get("description") or c.get("_home") or "")[:300]})
                if f["fund"] not in e["funds"]:
                    e["funds"].append(f["fund"])
                e["sources"].append(c.get("profile_url") or c.get("source_url"))
                e["website"] = e["website"] or c.get("website")
                e["uk_signal"] = e["uk_signal"] or uk
    json.dump(cands, open(CAND_P, "w"), indent=1, ensure_ascii=False)
    print(len(cands))
    for k, v in sorted(cands.items(), key=lambda kv: -kv[1]["score"]):
        print(f"{v['score']:3} {'UK' if v['uk_signal'] else '--'} {v['brand'][:30]:30} {','.join(v['funds'])[:30]:30} {str(v['website'])[:35]:35} {' '.join(v['food_terms'][:6])} | X:{' '.join(v['excl_terms'][:4])}")


def site_root(u):
    p = urlparse(u)
    return f"{p.scheme}://{p.netloc}"


def find_links(html, base, rx):
    out = []
    for h, t in links_of(html, base):
        if rx.search(h) or rx.search(t):
            out.append(h)
    return list(dict.fromkeys(out))


STOCK_RX = re.compile(r"stockist|where-?to-?buy|where to buy|find-?us|find us|retailers|shop-?near|buy-?local|store-?locator|"
                      r"find a store|find-a-store|where-to-find|available-at|stockists", re.I)
CAREER_RX = re.compile(r"careers?|jobs|vacanc|join-?us|join our team|work-?with-?us|work for us|recruit|teamtailor|workable|"
                       r"greenhouse\.io|lever\.co|bamboohr|personio|recruitee|hibob|pinpointhq|jobs\.ashby", re.I)


def absdate(d):
    import datetime
    today = datetime.date(2026, 10, 24)
    m = re.match(r"(\d+) (day|week|month|year)s? ago", d or "")
    if not m:
        return d
    n = int(m.group(1)); days = {"day": 1, "week": 7, "month": 30, "year": 365}[m.group(2)] * n
    return (today - datetime.timedelta(days=days)).isoformat() + " (approx, from '" + d + "')"


def enrich(b):
    out = {"brand": b["brand"], "website": b.get("website"), "funds": b["funds"], "fund_sources": list(dict.fromkeys(b["sources"]))[:5],
           "retailers": [], "ops_roles": [], "news": [], "erp_mentions": [], "pages_checked": [], "notes": []}
    web = b.get("website")
    if b.get("review_note"):
        out["notes"].append(b["review_note"])
    if not web and not b.get("no_search"):
        j = fc_search(f'"{b["brand"]}" official website UK', limit=3)
        rs = ((j.get("data") or {}).get("web") or [])
        for r in rs:
            u = r.get("url", "")
            if not re.search(r"linkedin|facebook|instagram|wikipedia|amazon|tesco|sainsbury|ocado|crunchbase|companieshouse|pitchbook|twitter|youtube|tiktok|bgf|ldc|piper|news|gov\.uk", u, re.I):
                web = site_root(u)
                out["website"] = web
                out["notes"].append(f"website found via Firecrawl search: {u}")
                break
    if not web:
        out["notes"].append("no website found")
    else:
        root = site_root(web)
        html, final, how = get(root, need_text_len=400, allow_fc=True)
        pages = []
        if html:
            pages.append((final, html, how))
            st = find_links(html, final, STOCK_RX)[:2]
            cr = find_links(html, final, CAREER_RX)[:2]
            for u in st + cr:
                h2, f2, how2 = get(u, need_text_len=300, allow_fc=True)
                if h2:
                    pages.append((f2, h2, how2))
                    if CAREER_RX.search(u):
                        # follow embedded ATS links one level
                        for a in find_links(h2, f2, re.compile(r"teamtailor|workable|greenhouse|lever\.co|bamboohr|personio|recruitee|hibob|pinpointhq|ashby|indeed|/jobs?/|/vacanc|/role", re.I))[:3]:
                            if a != f2:
                                h3, f3, how3 = get(a, need_text_len=200, allow_fc=False)
                                if h3:
                                    pages.append((f3, h3, how3))
        else:
            out["notes"].append(f"homepage fetch failed: {how}")
        seen_r = set()
        for u, h, how in pages:
            out["pages_checked"].append({"url": u, "method": how})
            t = visible_text(h)
            for name, rx in RETAILERS:
                if name not in seen_r and re.search(rx, t):
                    seen_r.add(name)
                    out["retailers"].append({"name": name, "source_url": u})
            if CAREER_RX.search(u) or re.search(r"teamtailor|workable|greenhouse|lever|bamboo|personio|recruitee|hibob|pinpoint|ashby", u):
                for line in t.split("\n"):
                    line = line.strip()
                    if 5 < len(line) < 90 and ROLE_RX.search(line) and not re.search(r"cookie|privacy|©", line, re.I):
                        if line not in [r["title"] for r in out["ops_roles"]]:
                            out["ops_roles"].append({"title": line, "url": u})
            for m in ERP_RX.finditer(t):
                s = t[max(0, m.start() - 100): m.end() + 100].replace("\n", " ")
                if re.search(r"sage", m.group(0), re.I) and not re.search(r"sage (x3|200|50|intacct|erp|accounting|software)", s, re.I):
                    continue
                if len(out["erp_mentions"]) < 6:
                    out["erp_mentions"].append({"text": s.strip(), "url": u})
        out["ops_roles"] = out["ops_roles"][:15]
    # news
    terms = [t for t in b.get("food_terms", []) if t not in ("food", "foods", "brand", "brands")]
    hint = "drinks" if any(re.search(r"drink|beer|gin|spirit|whisky|wine|juice|soda|water|coffee|tea|cider|rum|liqueur", t) for t in terms + [b["brand"].lower()]) else ("pet food" if any("pet" in t or "dog" in t or "cat" in t for t in terms) else "food")
    j = fc_search(f'"{b["brand"]}" {hint}', limit=8, tbs="cdr:1,cd_min:10/24/2024,cd_max:10/24/2026", sources="news")
    if j.get("error"):
        out["notes"].append("news search failed: " + j["error"][:100])
    for r in ((j.get("data") or {}).get("news") or []):
        title = r.get("title") or ""
        sn = r.get("snippet") or ""
        blob = title + " " + sn
        if norm(b["brand"])[:6] not in norm(blob):
            continue
        if not re.search(r"food|drink|snack|brand|beer|brew|gin|spirit|whisky|wine|juice|soda|coffee|tea|retail|supermarket|grocer|tesco|sainsbury|waitrose|ocado|asda|morrisons|aldi|lidl|funding|raise|invest|acqui|launch|pet|dog|cat|bakery|chocolate|dairy|cheese|plant|vegan|protein|nutrition|range|listing|sales|revenue|profit|export|ceo|founder", blob, re.I):
            continue
        typ = "other"
        if re.search(r"rais|funding|investment|invests|backs|backed|round|crowdfund|series [ab]|seed", blob, re.I): typ = "funding"
        if re.search(r"acquir|acquisition|buys|bought|takeover|snapped up|sold to|sells|sale of|merger", blob, re.I): typ = "acquisition"
        if re.search(r"tesco|sainsbury|waitrose|ocado|asda|morrisons|\bm&s\b|marks (&|and) spencer|co-op|boots|holland (&|and) barrett|aldi|lidl|booker|listing|stocked|stockist|where to buy", blob, re.I) and typ == "other": typ = "retailer_listing"
        if re.search(r"export|international|overseas|\bUS\b|USA|America|Europe|launch(es)? in [A-Z]", blob) and typ == "other": typ = "export"
        if ERP_RX.search(blob):
            typ = "erp" if typ == "other" else typ
            out["erp_mentions"].append({"text": blob[:250], "url": r.get("url")})
        out["news"].append({"date": absdate(r.get("date")), "headline": title, "url": r.get("url"), "type": typ})
    return out


if STAGE == "classify":
    classify()
elif STAGE == "enrich":
    sel = json.load(open(sys.argv[2]))  # list of candidate keys
    cands = json.load(open(CAND_P))
    done = {}
    if os.path.exists(BRANDS_P):
        for l in open(BRANDS_P):
            r = json.loads(l); done[norm(r["brand"])] = r
    todo = [k for k in sel if k not in done]
    def run(k):
        try:
            return k, enrich(cands[k])
        except Exception as e:
            return k, {"brand": cands[k]["brand"], "website": cands[k].get("website"), "funds": cands[k]["funds"],
                       "retailers": [], "ops_roles": [], "news": [], "erp_mentions": [], "notes": ["error: " + str(e)[:200]]}
    with ThreadPoolExecutor(3) as ex:
        for k, r in ex.map(run, todo):
            done[k] = r
            with open(BRANDS_P, "w") as fh:
                for kk in sel:
                    if kk in done:
                        fh.write(json.dumps(done[kk], ensure_ascii=False) + "\n")
            print(f"{r['brand'][:30]:30} ret={len(r['retailers'])} roles={len(r['ops_roles'])} news={len(r['news'])} erp={len(r['erp_mentions'])} {r.get('notes')}", flush=True)
