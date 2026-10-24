"""Companies House facts for each brand (free public API, no Firecrawl credits).

python step5.py   -> data/firecrawl/companies_house.jsonl
Needs CH_API_KEY (or COMPANIES_HOUSE_API_KEY) in the environment or in the repo's .env.
Per brand: match the registered company, then profile, latest accounts type (-> size band),
share allotments (SH01) and new charges (MR01) in the last 24 months, and PSCs/officers that
name the backing fund.
"""
import hashlib, json, os, re, sys, time
from datetime import date, timedelta
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = json.load(open(os.path.join(ROOT, "site", "data.json")))
OUT_P = os.path.join(ROOT, "data", "firecrawl", "companies_house.jsonl")
CACHE = "/Users/lini/Documents/My Claude/procuros-engine/data/firecrawl/raw/ch"
os.makedirs(CACHE, exist_ok=True)
API = "https://api.company-information.service.gov.uk"
WEB = "https://find-and-update.company-information.service.gov.uk"
AS_OF = date.fromisoformat(DATA.get("as_of") or date.today().isoformat())
SINCE = (AS_OF - timedelta(days=730)).isoformat()


def api_key():
    for k in ("CH_API_KEY", "COMPANIES_HOUSE_API_KEY"):
        if os.environ.get(k):
            return os.environ[k].strip()
    for p in (os.path.join(ROOT, ".env"), "/Users/lini/Documents/My Claude/procuros-engine/.env"):
        if os.path.exists(p):
            for line in open(p):
                m = re.match(r"\s*(CH_API_KEY|COMPANIES_HOUSE_API_KEY)\s*=\s*['\"]?([^'\"\s]+)", line)
                if m:
                    return m.group(2)
    sys.exit("No CH_API_KEY / COMPANIES_HOUSE_API_KEY found")


KEY = None
_last = [0.0]


def ch(path):
    """GET with disk cache; ~2 req/s keeps well under 600 per 5 minutes."""
    p = os.path.join(CACHE, hashlib.md5(path.encode()).hexdigest() + ".json")
    if os.path.exists(p):
        return json.load(open(p))
    for attempt in range(4):
        gap = time.time() - _last[0]
        if gap < 0.55:
            time.sleep(0.55 - gap)
        _last[0] = time.time()
        r = requests.get(API + path, auth=(KEY, ""), timeout=30)
        if r.status_code == 429:
            time.sleep(60)
            continue
        break
    if r.status_code == 401:
        sys.exit("Companies House rejected the key (401). Check it is a Live REST key.")
    d = r.json() if r.status_code == 200 else {"_status": r.status_code}
    json.dump(d, open(p, "w"))
    return d


SUFFIX = re.compile(r"\b(limited|ltd|plc|llp|holdings?|group|uk|the|company|co|trading|international|brands?)\b", re.I)


def norm(s):
    s = re.sub(r"\(.*?\)", "", (s or "").lower().replace("&", " and ").replace("’", "'"))
    return re.sub(r"[^a-z0-9]", "", SUFFIX.sub(" ", s))


FOOD_SIC = re.compile(r"^(10|11|4617|463|4711|472|4791|0[1-3])")  # food/drink manufacture, food agents/wholesale, food retail, online retail, farming
TAIL_OK = {"", "foods", "food", "drinks", "drink", "brewing", "brewingco", "brewery", "coffee", "coffeeco", "crisps", "energy", "products",
           "snacks", "pet", "petcare", "petfood", "distillery", "distillerycompany", "distillers", "bakery", "bakers", "tea", "teas",
           "nutrition", "beverages", "water", "drinksco", "foodsco", "kitchen", "creamery", "dairy", "chocolate", "pizza", "spirits",
           "softdrinks", "potatocrisps", "cereals", "honey", "rum", "gin", "waffles", "roasters", "coffeeroasters", "beer", "groupholdings"}
SIC_PET = {"10920"}
# holding / head-office / catch-all codes that brand companies often file under
NEUTRAL_SIC = {"64209", "64205", "64209", "70100", "82990", "99999", "74990", "74909", "96090", "46900", "47910", "46190",
               "47190", "70229", "73110", "46450", "47750", "96040", "74901", "53202", "56290", "93199", "82110"}


def queries(b):
    name = re.sub(r"\(.*?\)", "", b["name"]).replace("’", "'").strip()
    qs = [name]
    if b.get("website"):
        dom = re.sub(r"^www\.", "", re.sub(r"^https?://", "", b["website"])).split("/")[0].split(".")[0]
        if norm(dom) != norm(name):
            qs.append(re.sub(r"[-_]", " ", dom))
    return list(dict.fromkeys(qs))


def fund_tokens(fund):
    base = re.sub(r"\(.*?\)", "", fund).strip()
    toks = {base.lower()}
    first = base.split()[0].lower()
    if len(first) >= 3 and first not in {"the", "big", "true", "five", "development", "active", "sustainable"}:
        toks.add(first)
    return toks


def score(b, item, prof):
    n_brand, n_item = norm(b["name"]), norm(item.get("title"))
    s, why = 0, []
    if n_item == n_brand:
        s += 50; why.append("exact name")
    elif n_brand and min(len(n_item), len(n_brand)) >= 4 and (
            (n_item.startswith(n_brand) and n_item[len(n_brand):] in TAIL_OK) or
            (n_brand.startswith(n_item) and n_brand[len(n_item):] in TAIL_OK)):
        s += 30; why.append("name + trade suffix")
    elif any(norm(q) == n_item for q in queries(b)[1:]):
        s += 35; why.append("matches website domain")
    else:
        return 0, ["name mismatch"]
    st = prof.get("company_status") or item.get("company_status")
    if st == "active":
        s += 15; why.append("active")
    elif st in ("dissolved", "liquidation", "converted-closed", "removed"):
        s -= 25; why.append(st)
    sics = prof.get("sic_codes") or []
    if any(FOOD_SIC.match(c) or c in SIC_PET for c in sics):
        s += 25; why.append("food/drink SIC")
    elif sics and not any(c in NEUTRAL_SIC for c in sics):
        s -= 30; why.append("unrelated SIC " + ",".join(sics))
    if (prof.get("type") or "") in ("ltd", "plc"):
        s += 5
    return s, why


def size_band(acc_type):
    t = (acc_type or "").lower()
    if not t:
        return None
    if "dormant" in t:
        return "dormant"
    if "micro" in t:
        return "micro (turnover up to £1m)"
    if "small" in t or "total-exemption" in t or "abridged" in t or "unaudited-abridged" in t:
        return "small (turnover up to £15m)"
    if "medium" in t:
        return "medium (turnover up to £54m)"
    if "group" in t:
        return "group accounts (usually medium/large)"
    if "full" in t:
        return "full accounts (medium/large, or chose full filing)"
    return t


def filings(num, category):
    d = ch(f"/company/{num}/filing-history?category={category}&items_per_page=100")
    return d.get("items") or []


def check(b):
    cands = {}
    for q in queries(b):
        res = ch(f"/search/companies?q={requests.utils.quote(q)}&items_per_page=20")
        for it in res.get("items") or []:
            cands.setdefault(it["company_number"], it)
    scored = []
    for num, it in list(cands.items())[:40]:
        if norm(it.get("title"))[:4] != norm(b["name"])[:4] and not any(norm(q)[:4] == norm(it.get("title"))[:4] for q in queries(b)):
            continue
        prof = ch(f"/company/{num}")
        s, why = score(b, it, prof)
        if s:
            scored.append((s, num, it, prof, why))
    row = {"brand": b["name"], "funds": b.get("funds"), "company_number": None, "match_confidence": "none", "candidates": len(cands)}
    if not scored:
        return row
    scored.sort(key=lambda x: -x[0])
    s, num, it, prof, why = scored[0]
    # fund evidence in PSCs / officers can tip a close call and is holding evidence in its own right
    def fund_hits(num):
        hits = []
        psc = ch(f"/company/{num}/persons-with-significant-control?items_per_page=50").get("items") or []
        offs = ch(f"/company/{num}/officers?items_per_page=100").get("items") or []
        for f in b.get("funds") or []:
            toks = fund_tokens(f)
            for p in psc:
                if any(t in (p.get("name") or "").lower() for t in toks):
                    hits.append({"fund": f, "role": "PSC", "name": p.get("name"), "since": p.get("notified_on"),
                                 "ceased": p.get("ceased_on"), "url": f"{WEB}/company/{num}/persons-with-significant-control"})
            for o in offs:
                if any(t in (o.get("name") or "").lower() for t in toks):
                    hits.append({"fund": f, "role": o.get("officer_role"), "name": o.get("name"), "since": o.get("appointed_on"),
                                 "ceased": o.get("resigned_on"), "url": f"{WEB}/company/{num}/officers"})
        return hits, psc, offs
    hits, psc, offs = fund_hits(num)
    if len(scored) > 1 and not hits and scored[1][0] >= s - 10:
        h2 = fund_hits(scored[1][1])
        if h2[0]:
            s, num, it, prof, why = scored[1]
            hits, psc, offs = h2
    if hits:
        s += 20; why.append("fund named in PSC/officers")
    conf = "high" if s >= 85 else "medium" if s >= 60 else "low"
    acc = (prof.get("accounts") or {}).get("last_accounts") or {}
    caps = [f for f in filings(num, "capital") if (f.get("type") or "").upper() == "SH01" and (f.get("date") or "") >= SINCE]
    mort = [f for f in filings(num, "mortgage") if (f.get("type") or "").upper() == "MR01" and (f.get("date") or "") >= SINCE]
    link = lambda f: WEB + f["links"]["self"] if (f.get("links") or {}).get("self") else f"{WEB}/company/{num}/filing-history"
    row.update({
        "company_number": num, "company_name": prof.get("company_name") or it.get("title"),
        "match_confidence": conf, "match_score": s, "match_why": why,
        "status": prof.get("company_status"), "incorporated": prof.get("date_of_creation"),
        "sic_codes": prof.get("sic_codes") or [], "address": it.get("address_snippet"),
        "accounts_type": acc.get("type"), "accounts_made_up_to": acc.get("made_up_to"),
        "size_band": size_band(acc.get("type")),
        "accounts_overdue": (prof.get("accounts") or {}).get("overdue"),
        "share_allotments_24m": [{"date": f.get("date"), "description": (f.get("description_values") or {}).get("capital", f.get("description")),
                                  "url": link(f)} for f in caps],
        "charges_24m": [{"date": f.get("date"), "description": f.get("description"), "url": link(f)} for f in mort],
        "fund_links": hits,
        "psc_count": len(psc), "officer_count": len([o for o in offs if not o.get("resigned_on")]),
        "url": f"{WEB}/company/{num}",
    })
    return row


if __name__ == "__main__":
    KEY = api_key()
    rows = []
    for i, b in enumerate(DATA["brands"]):
        r = check(b)
        rows.append(r)
        print(f"[ch] {i+1}/{len(DATA['brands'])} {b['name']}: {r.get('company_name') or '-'} ({r['match_confidence']}) "
              f"{r.get('size_band') or ''} SH01x{len(r.get('share_allotments_24m') or [])} MR01x{len(r.get('charges_24m') or [])} "
              f"fund_links {len(r.get('fund_links') or [])}", flush=True)
        with open(OUT_P, "w") as f:
            for x in rows:
                f.write(json.dumps(x, ensure_ascii=False) + "\n")
    m = [r for r in rows if r["company_number"]]
    print("matched:", len(m), "| high:", sum(r["match_confidence"] == "high" for r in m),
          "| medium:", sum(r["match_confidence"] == "medium" for r in m), "| low:", sum(r["match_confidence"] == "low" for r in m),
          "| with SH01 in 24m:", sum(1 for r in m if r["share_allotments_24m"]),
          "| with MR01 in 24m:", sum(1 for r in m if r["charges_24m"]),
          "| fund named in PSC/officers:", sum(1 for r in m if r["fund_links"]))
