"""Score UK funds on their ability to introduce Procuros to ICP-fit grocery brands.

Reads data/firecrawl/{funds,brands}.jsonl plus overrides.json, writes data/scored/.
Every signal value carries its evidence (source URLs) so the dashboard can show why.
"""
import json
import math
import re
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CFG = json.loads((Path(__file__).parent / "config.json").read_text())
OVR = json.loads((Path(__file__).parent / "overrides.json").read_text())
AS_OF = date.fromisoformat(CFG["as_of"])
CUTOFF = AS_OF - timedelta(days=30 * CFG["recent_months"])

GROCERS = CFG["major_grocers"]
GROCER_RE = {g: re.compile(r"\b" + re.escape(g).replace("\\'", "['’]?") + r"\b", re.I) for g in GROCERS}
GROCER_RE["M&S"] = re.compile(r"\bM&S\b|Marks (&|and) Spencer", re.I)
GROCER_RE["Sainsbury's"] = re.compile(r"Sainsbury", re.I)
TRADE_DOMAINS = ("thegrocer", "grocerygazette", "foodmanufacture", "foodanddrinktechnology", "foodbev", "just-food",
                 "just-drinks", "conveniencestore", "talkingretail", "betterretailing", "scottishgrocer", "grocerytrader",
                 "wholesalemanager", "petfoodindustry", "petfoodprocessing", "petbusinessworld", "thespiritsbusiness",
                 "thedrinksbusiness", "drinksretailingnews", "bakeryinfo", "vegconomist", "plantbasednews", "retailtimes",
                 "insidermedia", "thebusinessdesk", "realdeals", "privateequitywire", "asiantrader", "snackandbakery")
FOOD_CONTEXT = re.compile(r"\b(brand|food|drink|snack|launch|range|listing|stock|retail|supermarket|raise|funding|"
                          r"invest|acquir|deal|sales|growth|pet|beer|coffee|soda|crisps|chocolate|vegan|plant)\w*", re.I)
LISTING_RE = re.compile(r"\b(listing|listed|lands|launch(es|ed)? (in|into|at)|rolls? out|enters|secures .* (deal|listing)|"
                        r"stock(ed|s)? (in|by|at)|shelves|nationwide)\b", re.I)
# Bare "fund" matched "innocent funds regenerative agriculture projects" and bare "buy" matched
# "the One I'd Buy Every Time", so both are narrowed to their transactional forms.
FUNDING_RE = re.compile(r"\b(rais|funding|fundrais|invest|backing|backed|round|seed|series [a-d]|crowdfund|stake|"
                        r"acquir|bought|buyout|buy-out|deal|merge|takeover|sold)\w*", re.I)
# Consumer reviews, taste tests, round-ups and interviews are not business events, however many
# funding-ish words their headlines contain.
NOT_EVENT_RE = re.compile(r"\b(review|reviewed|i tried|we tried|tried \d+|taste test|best \d+|top \d+|round-?up|"
                          r"comparison|compared|versus|vs\.?|recipe|how to|interview|guilty|favourite|favorite)\b", re.I)
EXPORT_RE = re.compile(r"\b(export|international|US|USA|Europe|overseas|global|expan)\w*", re.I)
AMBIGUOUS = {"STOCKED", "Pure", "THIS", "Sneak", "Graze", "Grounded", "Punchy", "Ingenious", "MOTH", "Runa", "Griddle",
             "Reformed", "Freja", "All Things", "Some Grub", "Hovis"}


def parse_date(s):
    if not s:
        return None
    s = s.strip()
    m = re.match(r"(\d{4}-\d{2}-\d{2})", s)
    if m:
        return date.fromisoformat(m.group(1))
    s = s.replace("Sept", "Sep")
    for fmt in ("%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def core_name(brand):
    n = re.sub(r"[®™]|\(.*?\)", "", brand).strip()
    n = re.sub(r"\b(Investment|Group|Company|Foods?|Ltd|St Andrews|London)\b", "", n, flags=re.I).strip(" -,")
    return n or brand


def relevant_news(brand, items):
    """Keep articles from the last 24 months whose headline names the brand (stricter for ambiguous names)."""
    name = core_name(brand)
    pat = re.compile(r"\b" + re.escape(name).replace("\\-", "[- ]?") + r"\b", re.I)
    keep = []
    for n in items:
        d = parse_date(n.get("date"))
        head = n.get("headline") or ""
        dom = n.get("url", "").split("/")[2] if n.get("url", "").count("/") >= 2 else ""
        if not d or d < CUTOFF or d > AS_OF:
            continue
        if not pat.search(head) and name.lower().replace(" ", "-") not in n.get("url", "").lower():
            continue
        if brand in AMBIGUOUS or name in AMBIGUOUS:
            if not (any(t in dom for t in TRADE_DOMAINS) and FOOD_CONTEXT.search(head)):
                continue
        keep.append({**n, "date_parsed": d.isoformat(), "trade_press": any(t in dom for t in TRADE_DOMAINS)})
    return keep


def norm(values, log=False):
    """Min-max to 0..1 across the universe; log1p for counts so one giant fund doesn't flatten the rest."""
    xs = [math.log1p(v) if log else v for v in values]
    lo, hi = min(xs), max(xs)
    return [0.0 if hi == lo else (x - lo) / (hi - lo) for x in xs]


def status_key(raw, override=None):
    if override:
        return override
    s = (raw or "unknown").lower()
    if s.startswith("current"):
        return "current"
    if "exit" in s or "realis" in s:
        return "exited_old"
    return "unknown"


def jsonl(name):
    path = ROOT / "data/firecrawl" / name
    return [json.loads(l) for l in open(path)] if path.exists() else []


# Second-pass sources (scripts/firecrawl/step3-5.py): retailer checks, holding status, job boards, Companies House.
RETAIL2 = {r["brand"]: r["retailers"] for r in jsonl("retail_check.jsonl")}
STATUS2 = {(r["fund"], r["brand"]): r for r in jsonl("status_check.jsonl") if r["status"] != "unknown"}
JOBS2 = {r["brand"]: r.get("roles", []) for r in jsonl("jobs_check.jsonl")}
CH = {r["brand"]: r for r in jsonl("companies_house.jsonl") if r.get("match_confidence") in ("high", "medium")}
CH_SIZE = {"micro": 0.2, "small": 0.7, "medium": 1.0, "full accounts": 1.0, "group accounts": 1.0}


def ch_size(row):
    band = (row or {}).get("size_band") or ""
    return next((v for k, v in CH_SIZE.items() if band.startswith(k)), None)


def exit_status(evidence, ceased=None):
    """Exited within the recent window counts as a warm relationship; older exits don't."""
    if ceased:
        return "exited_recent" if date.fromisoformat(ceased[:10]) >= CUTOFF else "exited_old"
    years = [int(y) for y in re.findall(r"\b(20[0-2]\d)\b", evidence or "")]
    return "exited_recent" if years and max(years) >= CUTOFF.year + 1 else "exited_old"


def load():
    funds = [json.loads(l) for l in open(ROOT / "data/firecrawl/funds.jsonl")]
    brands = [json.loads(l) for l in open(ROOT / "data/firecrawl/brands.jsonl")]
    return funds, brands


def build_brands(brands):
    drop = OVR["drop_brands"]
    cat = {b: k for k, names in OVR["category"].items() for b in names}
    out = []
    for b in brands:
        if b["brand"] in drop or b.get("backer_types") == ["angel/crowdfunding listing"]:
            continue
        funds = [f for f in b["funds"] if f != "Angel Investment Network"]
        if not funds:
            continue
        out.append({"brand": b["brand"], "website": b.get("website"), "description": b.get("description"),
                    "funds": funds, "fund_sources": b.get("fund_sources", []),
                    "status_raw": {f: b["status_by_fund"].get(f) for f in funds},
                    "retailers_site": b.get("retailers", []), "ops_roles": b.get("ops_roles", []),
                    "news_raw": b.get("news", []), "erp_mentions": b.get("erp_mentions", []), "added_manually": False})
    for a in OVR["add_brands"]:
        ex = next((x for x in out if x["brand"] == a["brand"]), None)
        if ex:
            ex["funds"].append(a["fund"]); ex["fund_sources"].append(a["source"]); ex["status_raw"][a["fund"]] = a["status"]
            continue
        out.append({"brand": a["brand"], "website": None, "description": a["description"], "funds": [a["fund"]],
                    "fund_sources": [a["source"]], "status_raw": {a["fund"]: a["status"]}, "retailers_site": [],
                    "ops_roles": [], "news_raw": [], "erp_mentions": [], "added_manually": True})

    for b in out:
        news = relevant_news(b["brand"], b["news_raw"])
        retail = {r["name"]: r["source_url"] for r in b["retailers_site"] if r["name"] in GROCERS}
        for r in RETAIL2.get(b["brand"], []):  # union: a missed re-check never removes a retailer found earlier
            if r["name"] in GROCERS:
                retail.setdefault(r["name"], r["url"])
        listing_news, funding_news, export_news = [], [], []
        for n in news:
            head = n["headline"]
            named = [g for g, rx in GROCER_RE.items() if rx.search(head)]
            for g in named:
                retail.setdefault(g, n["url"])
            event = not NOT_EVENT_RE.search(head)  # a review that mentions a grocer is not a new listing
            if event and (named or LISTING_RE.search(head) or n.get("type") == "retailer_listing" and n["trade_press"]):
                listing_news.append(n)
            if event and (FUNDING_RE.search(head) or n.get("type") in ("funding", "acquisition")):
                funding_news.append(n)
            if event and (n.get("type") == "export" or EXPORT_RE.search(head)):
                export_news.append(n)
        ch = CH.get(b["brand"])
        if ch:
            # Filings the press missed: one funding item per month with share allotments (max 2), one per new charge (max 1).
            months = sorted({a["date"][:7]: a for a in ch.get("share_allotments_24m", [])}.items(), reverse=True)[:2]
            for _, a in months:
                funding_news.append({"date_parsed": a["date"], "headline": "Share allotment filed at Companies House",
                                     "url": a["url"], "trade_press": False, "source": "companies_house"})
            for c in ch.get("charges_24m", [])[:1]:
                funding_news.append({"date_parsed": c["date"], "headline": "New charge (debt facility) filed at Companies House",
                                     "url": c["url"], "trade_press": False, "source": "companies_house"})
        for role in JOBS2.get(b["brand"], []):
            if not any(role["url"] == o.get("url") for o in b["ops_roles"]):
                b["ops_roles"].append({"title": role["title"], "url": role["url"], "source": "job board"})
        category = cat.get(b["brand"], "branded_grocery")
        b.update({
            "companies_house": ({k: ch.get(k) for k in ("company_number", "company_name", "size_band", "url", "match_confidence")}
                                | {"share_allotments_24m": len(ch.get("share_allotments_24m", [])),
                                   "charges_24m": len(ch.get("charges_24m", []))}) if ch else None,
            "category": category,
            "retailers": [{"name": k, "source_url": v} for k, v in retail.items()],
            "news": news, "listing_news": listing_news, "funding_news": funding_news, "export_news": export_news,
        })
        cat_score = {"branded_grocery": 1.0, "manufacturer_own_label": 0.8, "supplements": 0.6, "meal_kit_dtc": 0.4}[category]
        # Turnover itself is not published for companies this size, so size starts as a proxy from retail reach
        # and trade coverage and is then overridden by the accounts type filed at Companies House wherever one
        # exists, which is 90 of the 110 brands. The proxy is the fallback, not the primary.
        trade_funding = any(n["trade_press"] for n in funding_news)
        if len(retail) >= 2 or category == "manufacturer_own_label":
            size = 1.0
        elif retail or trade_funding:
            size = 0.5
        else:
            size = 0.2
        known = ch_size(ch)
        if known is not None:  # filed accounts beat the retail-reach proxy; micro filers are below the ICP band
            size = known if known < 0.5 else max(size, known)
        b["size_proxy"] = size
        w = CFG["brand_fit"]
        b["fit"] = round(w["retail"] * min(len(retail) / 4, 1) + w["size_proxy"] * size + w["category"] * cat_score
                         + w["ops_gap"] * (1.0 if b["ops_roles"] else 0.0) + w["status"] * 1.0, 3)
        p = CFG["pain"]
        b["pain_parts"] = {
            "listings": min(decayed(listing_news) / 2, 1),
            "funding": min(decayed(funding_news) / 2, 1),
            "ops_hiring": min(len(b["ops_roles"]) / 3, 1),  # open roles are live today, so no decay
            "momentum": min(decayed(news) / 6, 1),
            "expansion": min(decayed(export_news), 1),
        }
        base = sum(p[k] * v for k, v in b["pain_parts"].items())
        # Trigger stack: distinct signals landing in the same window are the buying moment, so they compound.
        st = CFG["stack"]
        fresh = lambda ns: any(age_months(n) <= st["window_months"] for n in ns)
        active = [k for k, on in (("listings", fresh(listing_news)), ("funding", fresh(funding_news)),
                                  ("ops_hiring", bool(b["ops_roles"])), ("expansion", fresh(export_news))) if on]
        mult = min(1 + st["bonus_per_extra_signal"] * max(len(active) - 1, 0), st["max_multiplier"])
        b["stack"] = active
        b["pain_base"] = round(base, 3)
        b["pain"] = round(min(base * mult, 1.0), 3)
    return out


def age_months(n):
    return max((AS_OF - date.fromisoformat(n["date_parsed"][:10])).days / 30.4, 0)


def decayed(news):
    """Recency-weighted count: a story loses half its weight every `recency_half_life_months`."""
    return sum(0.5 ** (age_months(n) / CFG["recency_half_life_months"]) for n in news)


def size_stage(fund):
    return OVR["fund_size_stage"].get(fund, 0.5)


PLATFORM_TITLE = re.compile(r"value creation|portfolio (director|partner|operations|manager|team)|operating (partner|director)|"
                            r"operations partner|platform|talent|community|head of operations", re.I)
NOT_A_NAME = re.compile(r"team|stories|sectors|services|assistant|advisors|investment|our |find out", re.I)
COMMUNITY_RE = re.compile(r"community|network|event|programme|program|founder stories|perks|sherpa|club|summit|academy", re.I)
VENDOR_RE = re.compile(r"perks|partner(s|ship)? (programme|network)|network plus|exchange lab|non-exec network|growth network|"
                       r"value acceleration|corporate programs", re.I)
ECOSYSTEM_RE = re.compile(r"program|accelerator|sherpa|growth network|events|summit|exchange lab|corporate", re.I)


def score_funds(funds, brands):
    rows = []
    customers = [c.lower() for c in CFG["procuros_customers"]]
    for f in funds:
        if f["fund_type"] in CFG["excluded_fund_types"]:
            continue
        name = f["fund"]
        mine = []
        for b in brands:
            if name not in b["funds"]:
                continue
            ov = OVR["status_override"].get(f"{b['brand']}|{name}")
            st = status_key(b["status_raw"].get(name), ov[0] if ov else None)
            src = ov[1] if ov else "portfolio page"
            if st == "unknown":  # also upgrades a manual "unknown" when the rescrape found evidence
                chk = STATUS2.get((name, b["brand"]))
                link = next((l for l in (CH.get(b["brand"]) or {}).get("fund_links", []) if l["fund"] == name), None)
                if link:  # the public register is the hardest evidence
                    st = exit_status(None, link["ceased"]) if link.get("ceased") else "current"
                    src = f"Companies House {link['role']}: {link['name']} ({link['url']})"
                elif chk:
                    st = "current" if chk["status"] == "current" else exit_status(f"{chk['evidence']} {chk['url']}")
                    src = f"{chk['evidence']} ({chk['url']})"
            mine.append({"brand": b, "status": st, "status_source": src,
                         "w": CFG["status_weight"][st]})
        # Only brands the fund still holds, that aren't Procuros customers already and fit the ICP size band, are doors.
        is_customer = lambda m: any(c in m["brand"]["brand"].lower() for c in customers)
        overlap = [m["brand"]["brand"] for m in mine if is_customer(m) and m["status"] in ("current", "unknown")]
        set_aside = []
        for m in mine:
            # Sold is tested before any size judgement. The other order reported brands as "over the £100m
            # band" when the fund had already exited them, which made a hand-written list look like it was
            # doing seven brands' worth of filtering when the holding test had removed six of them anyway.
            why_out = ("already a Procuros customer" if is_customer(m)
                       else "sold" if m["status"] in ("exited_recent", "exited_old")
                       else f"over the £100m ICP band ({OVR['over_icp_size'][m['brand']['brand']]})" if m["brand"]["brand"] in OVR["over_icp_size"]
                       else None)
            if why_out:
                set_aside.append({"brand": m["brand"]["brand"], "reason": why_out, "status": m["status"]})
        out_names = {x["brand"] for x in set_aside}
        mine = [m for m in mine if m["brand"]["brand"] not in out_names]
        people = [p for p in f.get("team_platform_people", [])
                  if PLATFORM_TITLE.search(p.get("title", "")) and not NOT_A_NAME.search(p.get("name", ""))
                  and "investor relations" not in p.get("title", "").lower()]
        seen = set(); people = [p for p in people if not (p["name"] in seen or seen.add(p["name"]))]
        if f["fund"] in OVR.get("replace_people", {}):
            people = [{"name": x["name"], "title": x["title"], "url": x["url"]} for x in OVR["replace_people"][f["fund"]]]
        comm = [c for c in f.get("community_signals", []) if COMMUNITY_RE.search(c.get("text", ""))]
        vendor = [c for c in f.get("community_signals", []) if VENDOR_RE.search(c.get("text", ""))]
        eco = [c for c in f.get("community_signals", []) if ECOSYSTEM_RE.search(c.get("text", ""))]
        weighted_count = sum(m["w"] for m in mine)
        live = [m for m in mine if m["status"] in ("current", "unknown", "exited_recent")]
        top = sorted(mine, key=lambda m: m["brand"]["pain"] * m["w"], reverse=True)[:CFG["pain_top_n"]]
        recent = [m for m in live if m["brand"]["funding_news"] and
                  any(name.split()[0].lower() in (n["headline"] + n["url"]).lower() for n in m["brand"]["funding_news"])]
        halo = max([len(m["brand"]["retailers"]) for m in live] or [0])
        rows.append({
            "fund": name, "fund_type": f["fund_type"], "website": f.get("website"), "scrape_status": f["scrape_status"],
            "portfolio_urls": f.get("portfolio_urls", []), "company_count": f.get("company_count") or len(f.get("companies", [])),
            "brands": [{"brand": m["brand"]["brand"], "status": m["status"], "status_source": m["status_source"],
                        "fit": m["brand"]["fit"], "pain": m["brand"]["pain"],
                        "retailers": [r["name"] for r in m["brand"]["retailers"]]} for m in mine],
            "raw": {
                "icp_count": sum(m["brand"]["fit"] * m["w"] for m in mine),
                "fmcg_share": weighted_count / max(f.get("company_count") or 1, 1),
                "avg_brand_fit": (sum(m["brand"]["fit"] * m["w"] for m in mine) / weighted_count) if weighted_count else 0,
                "recent_deals": len(recent) + sum(1 for m in mine if m["brand"]["added_manually"] and m["status"] == "current"),
                "pain_top": (sum(m["brand"]["pain"] * m["w"] for m in top) / len(top)) if top else 0,
                "platform_team": min(len(people), 3),
                "community": min(len(comm), 3),
                "size_stage": size_stage(name),
                "vendor_openness": 1.0 if vendor else 0.0,
                "procuros_overlap": len(overlap),
                "brand_halo": halo,
                "ecosystem": min(len(eco), 2),
            },
            "_live_brands": [m["brand"] for m in live],
            "set_aside": set_aside,
            "evidence": {"platform_people": people, "community": comm, "vendor": vendor, "procuros_overlap": overlap,
                         "recent_deal_brands": [m["brand"]["brand"] for m in recent]},
        })
    return rows


def combine(rows, cfg=CFG):
    keys_log = {"icp_count", "recent_deals"}
    keys = list(rows[0]["raw"].keys())
    normed = {k: norm([r["raw"][k] for r in rows], log=k in keys_log) for k in keys}
    for i, r in enumerate(rows):
        n = {k: normed[k][i] for k in keys}
        n["pain_top"] = r["raw"]["pain_top"]  # already 0..1 on an absolute scale
        n["size_stage"] = r["raw"]["size_stage"]
        n["vendor_openness"] = r["raw"]["vendor_openness"]
        fit = sum(cfg["fit"][k] * n[k] for k in cfg["fit"])
        pain = n["pain_top"]
        access = sum(cfg["access"][k] * n[k] for k in cfg["access"])
        strat = sum(cfg["strategic"][k] * n[k] for k in cfg["strategic"])
        # Reach and strategic value only matter if there are brands to reach: gate them by live brand depth.
        live_n = sum(1 for b in r["brands"] if b["status"] != "exited_old")
        gate = min(live_n / cfg["gate_brands"], 1.0)
        access, strat = access * gate, strat * gate
        P = cfg["pillars"]
        r["gate"] = round(gate, 2)
        r["pillars"] = {"fit": round(fit, 3), "pain": round(pain, 3), "access": round(access, 3), "strategic": round(strat, 3)}
        r["normalised"] = {k: round(v, 6) for k, v in n.items()}  # 6dp so the site reproduces scores exactly
        r["score"] = round(100 * (P["fit"] * fit + P["pain"] * pain + P["access"] * access + P["strategic"] * strat), 1)
        live = [b for b in r["brands"] if b["status"] != "exited_old"]
        r["live_brand_count"] = len(live)
        t = cfg["tiers"]
        r["tier"] = ("A" if r["score"] >= t["A"]["min_score"] and len(live) >= t["A"]["min_brands"]
                     else "B" if r["score"] >= t["B"]["min_score"] or (r["score"] >= t["A"]["min_score"]) else "C")
        # Coverage: how many of the 16 signals have any data behind them, so a low score can be told from missing data.
        sig = [r["raw"][k] for k in ("icp_count", "fmcg_share", "avg_brand_fit", "recent_deals", "platform_team",
                                    "community", "vendor_openness", "procuros_overlap", "brand_halo", "ecosystem")]
        pain_parts = [any(b2["pain_parts"][k] > 0 for b2 in r["_live_brands"]) for k in cfg["pain"]]
        size_known = r["fund"] in OVR["fund_size_stage"]
        filled = sum(1 for v in sig if v) + sum(pain_parts) + (1 if size_known else 0)
        r["coverage"] = {"scrape_status": r["scrape_status"], "signals_with_data": filled, "signals_total": 16}
    rows.sort(key=lambda r: r["score"], reverse=True)
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows


def why(r, brands_by_name):
    live = sorted([b for b in r["brands"] if b["status"] != "exited_old"], key=lambda b: (-len(b["retailers"]), -b["pain"]))
    parts = []
    if live:
        names = ", ".join(f"{b['brand']} ({'/'.join(b['retailers'][:3])})" if b["retailers"] else b["brand"] for b in live[:3])
        parts.append(f"{len(live)} UK grocery brand{'s' if len(live) != 1 else ''} still held, incl. {names}")
    hot = []
    for b in live:
        bb = brands_by_name[b["brand"]]
        trig = sorted([n for n in bb["funding_news"] + bb["listing_news"] if n["trade_press"]], key=lambda n: (n["trade_press"], n["date_parsed"]), reverse=True)
        for n in trig[:1]:
            hot.append(f"{b['brand']}: \"{n['headline'][:90]}\" ({n['date_parsed'][:7]})")
    if hot:
        parts.append("recent trigger: " + hot[0])
    ev = r["evidence"]
    if ev["platform_people"]:
        p = ev["platform_people"][0]
        parts.append(f"named portfolio/platform contact: {p['name']} ({p['title']})")
    if ev["procuros_overlap"]:
        parts.append("already backs Procuros customer " + ", ".join(sorted(set(ev["procuros_overlap"]))))
    return "; ".join(parts) + "."


def main():
    funds, brands_raw = load()
    brands = build_brands(brands_raw)
    rows = combine(score_funds(funds, brands))
    by_name = {b["brand"]: b for b in brands}
    for r in rows:
        r["why"] = why(r, by_name)
    out = ROOT / "data/scored"
    out.mkdir(exist_ok=True)
    for b in brands:
        b.pop("news_raw", None)
    for r in rows:
        r.pop("_live_brands", None)
    (out / "brands_scored.json").write_text(json.dumps(brands, indent=1, ensure_ascii=False))
    (out / "funds_scored.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False, default=str))
    with open(out / "shortlist.csv", "w") as fh:
        fh.write("rank,fund,type,tier,score,fit,pain,access,strategic,live_brands,why\n")
        for r in rows:
            p = r["pillars"]
            fh.write(f"{r['rank']},\"{r['fund']}\",{r['fund_type']},{r['tier']},{r['score']},{p['fit']},{p['pain']},"
                     f"{p['access']},{p['strategic']},{r['live_brand_count']},\"{r['why'].replace(chr(34), chr(39))}\"\n")
    for r in rows[:30]:
        print(r["rank"], r["fund"], r["tier"], r["score"], r["pillars"], r["live_brand_count"])


if __name__ == "__main__":
    main()
