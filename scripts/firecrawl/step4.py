"""Hiring signals from public ATS job feeds (plain HTTP only, no Firecrawl credits).

python step4.py   -> data/firecrawl/jobs_check.jsonl
For each brand: find its job board (links on its own careers page first, then slug guesses against
Workable / Greenhouse / Lever / Ashby / Recruitee / Personio / BambooHR / Pinpoint / Teamtailor),
keep ops / supply-chain / order-processing style roles and note ERP or EDI tools named in them.
"""
import json, os, re, sys, time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse
from fx import http_get, links_of, visible_text

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = json.load(open(os.path.join(ROOT, "site", "data.json")))
OUT_P = os.path.join(ROOT, "data", "firecrawl", "jobs_check.jsonl")

ROLE = re.compile(r"operations|\bops\b|supply chain|logistics|planning|planner|demand|forecast|procurement|purchasing|buyer|"
                  r"customer service|customer care|customer experience|order processing|order management|sales order|"
                  r"fulfil+ment|warehouse|inventory|stock control|\bEDI\b|\bERP\b|accounts? (payable|receivable)|credit control|"
                  r"(national|key|grocery|retail|customer) account (manager|executive|director)|"
                  r"account (manager|executive|director)[^.\n]{0,40}(grocery|retail|national|multiple)", re.I)
STRONG = re.compile(r"order processing|sales order processing|\bEDI\b|electronic data interchange|retailer portals?|"
                    r"purchase orders? from (retailers|customers)|supply chain (manager|coordinator|planner|lead)", re.I)
ERP = [("Sage", r"\bSage( (X3|200|50|Intacct|300))?\b"), ("Xero", r"\bXero\b"), ("NetSuite", r"Net ?Suite"),
       ("Business Central", r"Business Central|Navision|\bNAV\b"), ("Dynamics", r"Dynamics( 365)?\b"),
       ("SAP", r"\bSAP\b|S/4 ?HANA"), ("Unleashed", r"\bUnleashed\b"), ("Cin7", r"\bCin7\b"), ("Brightpearl", r"Brightpearl"),
       ("Linnworks", r"Linnworks"), ("Odoo", r"\bOdoo\b"), ("Katana", r"\bKatana\b"), ("Khaos Control", r"Khaos"),
       ("OrderWise", r"OrderWise"), ("QuickBooks", r"QuickBooks"), ("EDI", r"\bEDI\b|electronic data interchange"),
       ("ERP (unnamed)", r"\bERP\b")]
ATS_LINK = re.compile(r"(apply\.workable\.com|[\w-]+\.workable\.com|boards\.greenhouse\.io|job-boards(\.eu)?\.greenhouse\.io|"
                      r"jobs\.(eu\.)?lever\.co|jobs\.ashbyhq\.com|[\w-]+\.recruitee\.com|[\w-]+\.jobs\.personio\.(de|com)|"
                      r"[\w-]+\.bamboohr\.com|[\w-]+\.pinpointhq\.com|[\w-]+\.teamtailor\.com|careers\.[\w-]+\.com)", re.I)
CAREERS = re.compile(r"career|jobs|join[-\s]?(us|the[-\s]?team)|work[-\s]?with[-\s]?us|vacanc|hiring|we.re[-\s]?hiring", re.I)


def jget(url):
    d = http_get(url, timeout=20)
    if d.get("status") != 200:
        return None
    try:
        return json.loads(d["html"])
    except Exception:
        return None


def strip(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or "")).strip()


# --- one fetcher per ATS: slug -> (board_url, company_name or None, [ {title,url,posted,text} ]) or None

def workable(slug):
    j = jget(f"https://apply.workable.com/api/v1/widget/accounts/{slug}?details=true")
    if not j or "jobs" not in j:
        return None
    return (f"https://apply.workable.com/{slug}/", j.get("name"),
            [{"title": x.get("title"), "url": x.get("url") or x.get("shortlink"), "posted": x.get("published_on") or x.get("created_at"),
              "text": strip(x.get("description", "")) + " " + (x.get("country") or "")} for x in j["jobs"]])


def greenhouse(slug):
    b = jget(f"https://boards-api.greenhouse.io/v1/boards/{slug}")
    j = jget(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true")
    if not j or "jobs" not in j:
        return None
    import html as H
    return (f"https://boards.greenhouse.io/{slug}", (b or {}).get("name"),
            [{"title": x.get("title"), "url": x.get("absolute_url"), "posted": (x.get("updated_at") or "")[:10],
              "text": strip(H.unescape(x.get("content", "")))} for x in j["jobs"]])


def lever(slug):
    j = jget(f"https://api.lever.co/v0/postings/{slug}?mode=json")
    if not isinstance(j, list):
        j = jget(f"https://api.eu.lever.co/v0/postings/{slug}?mode=json")
    if not isinstance(j, list):
        return None
    return (f"https://jobs.lever.co/{slug}", None,
            [{"title": x.get("text"), "url": x.get("hostedUrl"),
              "posted": time.strftime("%Y-%m-%d", time.gmtime((x.get("createdAt") or 0) / 1000)),
              "text": x.get("descriptionPlain", "") + " " + " ".join(l.get("content", "") for l in x.get("lists", []))} for x in j])


def ashby(slug):
    j = jget(f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=false")
    if not j or "jobs" not in j:
        return None
    return (f"https://jobs.ashbyhq.com/{slug}", None,
            [{"title": x.get("title"), "url": x.get("jobUrl"), "posted": (x.get("publishedAt") or "")[:10],
              "text": x.get("descriptionPlain") or strip(x.get("descriptionHtml"))} for x in j["jobs"]])


def recruitee(slug):
    j = jget(f"https://{slug}.recruitee.com/api/offers/")
    if not j or "offers" not in j:
        return None
    return (f"https://{slug}.recruitee.com/", None,
            [{"title": x.get("title"), "url": x.get("careers_url"), "posted": (x.get("published_at") or "")[:10],
              "text": strip(x.get("description", "")) + " " + strip(x.get("requirements", ""))} for x in j["offers"]])


def personio(slug):
    for tld in ("de", "com"):
        d = http_get(f"https://{slug}.jobs.personio.{tld}/xml")
        if d.get("status") == 200 and "<workzag-jobs" in (d.get("html") or ""):
            jobs = re.findall(r"<position>(.*?)</position>", d["html"], re.S)
            out = []
            for p in jobs:
                g = lambda t: (re.search(rf"<{t}>(.*?)</{t}>", p, re.S) or [None, ""])[1]
                out.append({"title": strip(g("name")), "url": f"https://{slug}.jobs.personio.{tld}/job/{strip(g('id'))}",
                            "posted": strip(g("createdAt"))[:10], "text": strip(re.sub(r"<!\[CDATA\[|\]\]>", "", p))})
            return (f"https://{slug}.jobs.personio.{tld}/", None, out)
    return None


def bamboohr(slug):
    j = jget(f"https://{slug}.bamboohr.com/careers/list")
    if not j or "result" not in j:
        return None
    return (f"https://{slug}.bamboohr.com/careers", None,
            [{"title": x.get("jobOpeningName"), "url": f"https://{slug}.bamboohr.com/careers/{x.get('id')}", "posted": None,
              "text": x.get("departmentLabel") or ""} for x in j["result"]])


def pinpoint(slug):
    j = jget(f"https://{slug}.pinpointhq.com/postings.json")
    if not j or "data" not in j:
        return None
    return (f"https://{slug}.pinpointhq.com/", None,
            [{"title": x.get("title"), "url": x.get("url"), "posted": None,
              "text": strip(x.get("description", ""))} for x in j["data"]])


def teamtailor(slug):
    d = http_get(f"https://{slug}.teamtailor.com/jobs")
    if d.get("status") != 200 or "teamtailor" not in (d.get("html") or "").lower():
        return None
    jobs = []
    for href, txt in links_of(d["html"], d["final_url"]):
        if re.search(r"/jobs/\d+", href) and txt and href not in [j["url"] for j in jobs]:
            jobs.append({"title": txt[:120], "url": href, "posted": None, "text": ""})
    return (f"https://{slug}.teamtailor.com/jobs", None, jobs)


ATS = {"workable": workable, "greenhouse": greenhouse, "lever": lever, "ashby": ashby, "recruitee": recruitee,
       "personio": personio, "bamboohr": bamboohr, "pinpoint": pinpoint, "teamtailor": teamtailor}


def ats_from_url(u):
    """Board link found on the brand's own site -> (ats, slug)."""
    p = urlparse(u)
    h, parts = p.netloc.lower(), [x for x in p.path.split("/") if x]
    if h == "apply.workable.com" and parts:
        return "workable", parts[0]
    if h.endswith(".workable.com"):
        return "workable", h.split(".")[0]
    if "greenhouse.io" in h:
        if parts and parts[0] == "embed":
            m = re.search(r"for=([\w-]+)", p.query)
            return ("greenhouse", m.group(1)) if m else (None, None)
        return ("greenhouse", parts[0]) if parts else (None, None)
    if "lever.co" in h and parts:
        return "lever", parts[0]
    if h == "jobs.ashbyhq.com" and parts:
        return "ashby", parts[0]
    for ats, dom in (("recruitee", ".recruitee.com"), ("bamboohr", ".bamboohr.com"), ("pinpoint", ".pinpointhq.com"),
                     ("teamtailor", ".teamtailor.com")):
        if h.endswith(dom):
            return ats, h.split(".")[0]
    if ".jobs.personio." in h:
        return "personio", h.split(".")[0]
    return None, None


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def slugs(b):
    name = re.sub(r"\(.*?\)", "", b["name"]).replace("’", "'").strip()
    base = re.sub(r"[^a-z0-9 ]", "", name.lower().replace("&", "and"))
    out = [base.replace(" ", ""), base.replace(" ", "-")]
    if b.get("website"):
        dom = urlparse(b["website"]).netloc.lower().replace("www.", "").split(".")[0]
        out += [dom, re.sub(r"(drinks|foods|food|uk|ltd|coffee|tea|snacks)$", "", dom)]
    return [s for s in dict.fromkeys(out) if len(s) >= 3]


def careers_links(b):
    """Board links found on the brand's homepage and its careers/jobs page."""
    web = b.get("website")
    if not web:
        return [], None
    home = http_get(web)
    if not home.get("html"):
        return [], None
    pages, boards = [], []
    for href, txt in links_of(home["html"], home.get("final_url") or web):
        if ATS_LINK.search(href):
            boards.append(href)
        elif (CAREERS.search(urlparse(href).path) or CAREERS.search(txt)) and href not in pages:
            pages.append(href)
    root = (home.get("final_url") or web).split("/")[0:3]
    for guess in ("/careers", "/jobs", "/pages/careers", "/pages/jobs"):
        pages.append("/".join(root) + guess)
    careers_page = None
    for p in list(dict.fromkeys(pages))[:5]:
        d = http_get(p)
        if d.get("status") != 200 or not d.get("html"):
            continue
        found = [h for h, _ in links_of(d["html"], d["final_url"]) if ATS_LINK.search(h)]
        found += re.findall(r"https?://(?:apply\.workable\.com/[\w-]+|boards(?:-api)?\.greenhouse\.io/(?:embed/job_board/js\?for=)?[\w-]+|"
                            r"jobs\.(?:eu\.)?lever\.co/[\w-]+|jobs\.ashbyhq\.com/[\w-]+|[\w-]+\.(?:recruitee|bamboohr|pinpointhq|teamtailor)\.com)", d["html"])
        if found or CAREERS.search(urlparse(d["final_url"]).path):
            careers_page = careers_page or d["final_url"]
        boards += found
    return list(dict.fromkeys(boards)), careers_page


def owns(b, company, jobs):
    """A guessed slug only counts if the job ads name the brand's own domain (brand names collide too easily)."""
    dom = urlparse(b.get("website") or "").netloc.replace("www.", "").lower()
    blob = " ".join((j.get("text") or "") + " " + (j.get("title") or "") for j in jobs[:15])
    if dom and dom in blob.lower():
        return True
    return False


def check(b):
    boards, careers_page = careers_links(b)
    tried, hit = set(), None
    for u in boards:
        ats, slug = ats_from_url(u)
        if ats and (ats, slug) not in tried:
            tried.add((ats, slug))
            r = ATS[ats](slug)
            if r:
                hit = (ats, slug, r, "linked from brand site")
                break
    if not hit:
        for slug in slugs(b):
            for ats in ("workable", "greenhouse", "lever", "ashby", "recruitee", "personio", "bamboohr", "pinpoint", "teamtailor"):
                if (ats, slug) in tried:
                    continue
                tried.add((ats, slug))
                r = ATS[ats](slug)
                if r and r[2] and owns(b, r[1], r[2]):
                    hit = (ats, slug, r, "slug match, verified by brand domain in ads")
                    break
            if hit:
                break
    row = {"brand": b["name"], "website": b.get("website"), "careers_page": careers_page, "board": None, "url": None,
           "how": None, "open_roles": 0, "roles": []}
    if not hit:
        return row
    ats, slug, (board_url, company, jobs), how = hit
    row.update({"board": ats, "url": board_url, "how": how, "open_roles": len(jobs)})
    for j in jobs:
        blob = (j.get("title") or "") + " " + (j.get("text") or "")
        m = ROLE.search(j.get("title") or "") or STRONG.search(j.get("text") or "")
        erp = [n for n, rx in ERP if re.search(rx, blob)]
        if "ERP (unnamed)" in erp and len(erp) > 1:
            erp.remove("ERP (unnamed)")
        if m or erp:
            row["roles"].append({"title": j.get("title"), "url": j.get("url"), "posted": j.get("posted"),
                                 "matched": m.group(0) if m else None, "erp": erp})
    return row


if __name__ == "__main__":
    rows = []
    with ThreadPoolExecutor(6) as ex:
        for i, r in enumerate(ex.map(check, DATA["brands"])):
            rows.append(r)
            print(f"[jobs] {i+1}/{len(DATA['brands'])} {r['brand']}: {r['board'] or '-'} "
                  f"{r['open_roles']} open, {len(r['roles'])} matched", flush=True)
    with open(OUT_P, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("brands with board:", sum(1 for r in rows if r["board"]),
          "| with matching roles:", sum(1 for r in rows if any(x["matched"] for x in r["roles"])),
          "| with ERP/EDI mentions:", sum(1 for r in rows if any(x["erp"] for x in r["roles"])))
