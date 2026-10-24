import json, re, sys, os
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from fx import *
from config import C

SITES = json.load(open("sites.json"))
SMAPS = json.load(open("sitemaps.json"))
FCMAPS = json.load(open("fcmaps.json")) if os.path.exists("fcmaps.json") else {}
STAGE = sys.argv[1] if len(sys.argv) > 1 else "list"
ONLY = sys.argv[2:] if len(sys.argv) > 2 else None

SOCIAL = re.compile(r"linkedin|twitter|x\.com|facebook|instagram|youtube|vimeo|tiktok|google\.|apple\.com|spotify|"
                    r"cookie|onetrust|hubspot|mailchimp|wordpress|wix|squarespace|webflow|gstatic|cloudflare|"
                    r"companieshouse|find-and-update|fca\.org|bvca|ico\.org|pitchbook|crunchbase|medium\.com|"
                    r"maps\.|w3\.org|schema\.org|gov\.uk|cyber|vimeo|flickr|issuu|calendly|typeform|soundcloud|"
                    r"podcasts|anchor\.fm|substack|wa\.me|whatsapp|bit\.ly|goo\.gl|sharepoint|addtoany|feedburner|"
                    r"ftadviser|unpri|investorsinpeople|b-?corp|bcorporation|ukbaa|level20|investeurope|"
                    r"londonstockexchange|investegate|creativecommons|adobe|microsoft|github", re.I)
AUTO_PARENT = re.compile(r"portfolio|invest|compan|brand|case|commitment|nwo|project|profile|business-proposal", re.I)
TITLE_RX = re.compile(r"portfolio (operations|support|director|manager|team|partner|talent)|platform|value creation|"
                      r"operating partner|operating director|operations partner|community|talent|"
                      r"head of operations|portfolio development|investor relations|events|ecosystem|founder success|"
                      r"chief operating", re.I)
COMM_RX = re.compile(r"communit|event|founder-?network|perk|academy|programme|program|summit|portfolio-support|"
                     r"value-?creation|value-?acceleration|platform|network|leadership|masterclass|exchange|forum|"
                     r"founder-stories|founders-club|club|retreat|resources-for-founders|playbook", re.I)
NAME_RX = re.compile(r"^[A-Z][a-zA-Z'\-\.]+( [A-Z][a-zA-Z'\-\.]+){1,3}$")


def path(u):
    return urlparse(u).path or "/"


def same_site(u, base):
    a, b = urlparse(u).netloc.replace("www.", ""), urlparse(base).netloc.replace("www.", "")
    return a == b


def page(url, fc):
    if fc == "force":
        f = fc_scrape(url, wait_ms=5000)
        if f.get("html"):
            return f["html"], f.get("final_url") or url, "firecrawl"
    if fc:
        d = http_get(url)
        if d["status"] == 200 and len(visible_text(d["html"] or "")) > 1500:
            return d["html"], d["final_url"], "http"
        f = fc_scrape(url, wait_ms=2500)
        if f.get("html"):
            return f["html"], f.get("final_url") or url, "firecrawl"
        return None, url, "failed:" + str(d.get("status")) + "/" + str(f.get("error", ""))[:150]
    return get(url, need_text_len=300, allow_fc=True, wait_ms=2500)


def clean_name(t, fund):
    t = re.sub(r"\s+", " ", t or "").strip()
    for sep in [" | ", " - ", " – ", " — ", " :: "]:
        if sep in t:
            parts = [p for p in t.split(sep) if p.strip()]
            # drop parts naming the fund / generic words
            keep = [p for p in parts if not re.search(re.escape(fund.split()[0]) + r"|portfolio|investment|case stud|private equity|capital|ventures|partners|home", p, re.I)]
            t = (keep or parts)[0].strip()
    return t[:120]


JUNK_ANCHOR = re.compile(r"^(here|read more.*|click here|log ?in|investor.*login.*|investors?|adviser.*|group|careers?|news|about|"
                         r"blog|privacy.*|cookie.*|terms.*|help.*|faqs?|contact.*|fees|web design.*|site design.*|built by.*|"
                         r"upgrade your browser|instructions.*|chat with us|livechat|online form|investments|asset management|"
                         r"property|energy|iht|aim|cms|eis|vct|mps|tps|portal.*|.*portal|.*hub|partnerships|mobile app|spain|france|germany)$", re.I)
JUNK_DOM = re.compile(r"pearonline|octopusinvest|octopus-realestate|octopusgroup|blackfinch|pumainvest|pumacapital|pumagrowth|pumaproperty|"
                      r"fscs|financial-ombudsman|becdn|efrontcloud|intralinks|altareturn|browsehappy|enable-javascript|"
                      r"designwildwest|thewebkitchen|builtbybuffalo|redmayne|safelinks|mobeusvcts|theaic|livechat|cityhub|"
                      r"unilevernotices|libsyn|foresightsolar|fgen\.com|seedrs|republic|crowdcube|lnkd\.in|zapflow|"
                      r"lcatterton|angelinvestmentnetwork|godaddy|trustpilot|talent\.|jobs\.|careers\.", re.I)


def ext_names(html, base, site):
    """External links on a portfolio list page -> [(url, name, context_text)]."""
    s = BeautifulSoup(html, "lxml")
    out, seen = [], set()
    for a in s.find_all("a", href=True):
        h = urljoin(base, a["href"].strip())
        if not h.startswith("http") or same_site(h, site) or same_site(h, base) or SOCIAL.search(h) or JUNK_DOM.search(h):
            continue
        dom = urlparse(h).netloc.lower().replace("www.", "")
        if dom in seen:
            continue
        t = re.sub(r"\s+", " ", a.get_text(" ")).strip()
        if JUNK_ANCHOR.match(t) or re.search(r"read more|→", t, re.I):
            continue
        name = None
        hd = a.find(["h1", "h2", "h3", "h4", "h5", "strong"])
        if hd and hd.get_text(strip=True):
            name = hd.get_text(" ", strip=True)
        if not name:
            img = a.find("img", alt=True)
            if img and img["alt"].strip() and not re.search(r"logo$|^image|\.(png|jpe?g|svg)", img["alt"].strip(), re.I):
                name = img["alt"].strip()
        generic = re.match(r"^(visit|view)( the)? (web)?site$|^www\.|^https?://|^$", t, re.I)
        if not name and t and not generic and len(t) <= 40:
            name = t
        ctx = t if len(t) > 40 else ""
        node = a
        for _ in range(4):
            node = node.parent
            if node is None or len([x for x in node.find_all("a", href=True) if x["href"].startswith("http")]) > 2:
                break
            hd = node.find(["h2", "h3", "h4", "h5"])
            if not name and hd and hd.get_text(strip=True) and len(hd.get_text(strip=True)) < 60:
                name = hd.get_text(" ", strip=True)
            if not ctx:
                cc = re.sub(r"\s+", " ", node.get_text(" ")).strip()
                if len(cc) > 60:
                    ctx = cc
                    break
        if not name:
            name = re.sub(r"^www\.", "", dom).split(".")[0].replace("-", " ").title()
        seen.add(dom)
        out.append((h, re.sub(r"^Exited\s+", "", name)[:80], ctx[:300]))
    return out


def list_stage(fund):
    c = C[fund]
    site = SITES[fund]
    res = {"fund": fund, "website": site, "list_pages": [], "cands": {}, "externals": []}
    urls = list(c["list"])
    seenp = set(u.rstrip("/") for u in urls)
    i = 0
    while i < len(urls) and i < 25:
        lu = urls[i]; i += 1
        html, final, how = page(lu, c.get("fc") if i <= len(c["list"]) else False)
        res["list_pages"].append({"url": lu, "final": final, "how": how, "ok": bool(html)})
        if not html:
            continue
        base_path = path(c["list"][0]).rstrip("/")
        for h, t in links_of(html, final):
            if same_site(h, site) or same_site(h, final):
                res["cands"].setdefault(h.rstrip("/"), t)
                if re.search(r"/page/\d+|[?&](page|pg|paged|p|letter|sf_paged)=\w+", h) and path(h).rstrip("/").split("/page/")[0] == base_path \
                        and h.rstrip("/") not in seenp and not c.get("fc"):
                    seenp.add(h.rstrip("/")); urls.append(h)
        res["externals"] += ext_names(html, final, site)
    # sitemap / map urls
    extra = SMAPS.get(fund, []) + FCMAPS.get(fund, [])
    if c.get("map_search"):
        extra += fc_map(site, search=c["map_search"], limit=300)
    rx = c.get("rx")
    prof = {}
    if rx:
        R = re.compile(rx)
        for h, t in list(res["cands"].items()) + [(u.rstrip("/"), "") for u in extra]:
            target = h if "investments=" in rx else path(h)
            if R.search(target) and not re.search(r"/(page|category|tag|feed)/|\?(sector|filter)", h):
                if h not in prof or (t and not prof[h]):
                    prof[h] = t
    else:
        groups = defaultdict(dict)
        for h, t in res["cands"].items():
            segs = [s for s in path(h).split("/") if s]
            if len(segs) >= 2:
                parent = "/".join(segs[:-1])
                if AUTO_PARENT.search(parent):
                    groups[parent][h] = t
        if groups:
            best = max(groups.items(), key=lambda kv: len(kv[1]))
            if len(best[1]) >= 3:
                prof = best[1]
                res["auto_parent"] = best[0]
    # drop the list pages themselves
    for lu in urls + [u for u in prof if re.search(r"/page/\d+", u)]:
        prof.pop(lu.rstrip("/"), None)
    res["profiles"] = prof
    return res


SITE_DESC = {}


def site_desc(site):
    if site not in SITE_DESC:
        d = http_get(site)
        m = BeautifulSoup(d.get("html") or "", "lxml").find("meta", attrs={"name": "description"})
        SITE_DESC[site] = (m.get("content") or "").strip() if m else ""
    return SITE_DESC[site]


def extract_profile(url, fund, site, fc):
    site_desc(site)
    html, final, how = get(url, need_text_len=200, allow_fc=False)
    if not html:
        return {"profile_url": url, "fetch": how}
    s = BeautifulSoup(html, "lxml")
    og = s.find("meta", property="og:title")
    h1 = s.find("h1")
    name = clean_name((h1.get_text(" ") if h1 and h1.get_text(strip=True) else (og["content"] if og and og.get("content") else (s.title.string if s.title else ""))), fund)
    md = s.find("meta", attrs={"name": "description"}) or s.find("meta", property="og:description")
    desc = (md.get("content") or "").strip() if md else ""
    txt = visible_text(html)
    if len(desc) < 40 or desc[:50] == SITE_DESC.get(site, "")[:50]:
        desc = ""
        for p in s.find_all("p"):
            t = p.get_text(" ", strip=True)
            if len(t) > 80 and not re.search(r"cookie|privacy", t, re.I):
                desc = t
                break
    web = None
    for a in s.find_all("a", href=True):
        h = a["href"].strip()
        if not h.startswith("http") or same_site(h, site) or same_site(h, final) or SOCIAL.search(h):
            continue
        t = a.get_text(" ", strip=True)
        if re.search(r"visit|website|www\.|\.com|\.co\.uk|\.io|view site|go to", t, re.I) or \
           re.sub(r"[^a-z]", "", name.lower())[:6] in re.sub(r"[^a-z]", "", urlparse(h).netloc.lower()):
            web = h
            break
    sector = None
    m = re.search(r"\b(Sector|Industry|Sectors)\s*:?\s*\n\s*([^\n]{2,60})", txt) or re.search(r"\b(Sector|Industry)\s*:\s*([^\n]{2,60})", txt)
    if m:
        sector = m.group(2).strip()
    status = "unknown"
    m = re.search(r"\bStatus\s*:?\s*\n?\s*(Current|Active|Exited|Realised|Realized|Fully realised|Live)", txt, re.I)
    if m:
        status = "exited" if re.search(r"exit|realis|realiz", m.group(1), re.I) else "current"
    elif re.search(r"\b(Exited|Realised investment|Realized investment|Investment realised|Former investment|Past investment)\b", txt[:4000]) and not re.search(r"Realised investments\s*\n", txt[:800]):
        status = "exited?"
    year = None
    m = re.search(r"(Date of investment|Investment date|Invested|Year invested|Initial investment|Date invested|Investment year|Year of investment|Investment Date|Date)\s*:?\s*\n?\s*(?:[A-Za-z]+\s)?((?:19|20)\d\d)", txt)
    if m:
        year = int(m.group(2))
    return {"name": name, "website": web, "description": desc[:400], "sector_tag_on_site": sector,
            "status": status, "investment_year": year, "profile_url": final, "fetch": how,
            "_text": txt[:2500]}


def team_and_community(fund, lres):
    site = SITES[fund]
    c = C[fund]
    allurls = set(lres["cands"].keys()) | set(u.rstrip("/") for u in SMAPS.get(fund, []) + FCMAPS.get(fund, []))
    home = http_get(site)
    hl = links_of(home["html"], home["final_url"]) if home.get("html") else []
    for h, t in hl:
        if same_site(h, site):
            allurls.add(h.rstrip("/"))
    anchors = {h.rstrip("/"): t for h, t in hl}
    anchors.update(lres["cands"])
    teamc = sorted([u for u in allurls if re.search(r"/(our-)?(team|people)(-[\w]+)?/?$|/meet-the-team/?$|/about-us/our-people/?$|/felix-team$|/team-1$", u, re.I)], key=len)
    people, tsrc = [], None
    for tu in teamc[:2]:
        html, final, how = page(tu, c.get("fc"))
        if not html:
            continue
        tsrc = final
        lines = [l.strip() for l in visible_text(html).split("\n") if l.strip()]
        for i, l in enumerate(lines):
            if len(l) < 90 and TITLE_RX.search(l) and i > 0:
                for back in (1, 2):
                    if i - back >= 0 and NAME_RX.match(lines[i - back]) and not TITLE_RX.search(lines[i - back]):
                        people.append({"name": lines[i - back], "title": l, "url": final})
                        break
        if people:
            break
    # team member profile slugs whose URL itself carries a title keyword are rare; also scan individual pages? skip (cost)
    seen = set(); P = []
    for p in people:
        k = (p["name"], p["title"])
        if k not in seen:
            seen.add(k); P.append(p)
    comm, seen = [], set()
    for u in sorted(allurls):
        segs = path(u).strip("/")
        if COMM_RX.search(segs) and not re.search(r"/(news|stories|blog|insights?|latest-news|fund_news|news-and-events|news-media|newsroom|company-news|portfolio-news|wp-content|cy|topics|category|tag|author)/", "/" + segs + "/"):
            if len(segs.split("/")) <= 2 and u not in seen:
                seen.add(u)
                comm.append({"text": (anchors.get(u) or segs.split("/")[-1].replace("-", " ")).strip()[:120], "url": u})
    return P[:25], tsrc, teamc[:3], comm[:15]


if __name__ == "__main__":
    funds = ONLY or list(C.keys())
    if STAGE == "list":
        def run(f):
            try:
                return f, list_stage(f)
            except Exception as e:
                return f, {"fund": f, "error": str(e)}
        with ThreadPoolExecutor(4) as ex:
            L = dict(ex.map(run, funds))
        old = json.load(open("lists.json")) if os.path.exists("lists.json") else {}
        old.update(L)
        json.dump(old, open("lists.json", "w"), indent=0)
        for f in funds:
            r = L[f]
            print(f"{f[:32]:32} prof={len(r.get('profiles', {})):4} ext={len(r.get('externals', [])):4} auto={r.get('auto_parent')} pages={[p['how'] for p in r.get('list_pages', [])]} {r.get('error','')}")


MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"


def special_companies(fund):
    out = []
    if fund == "Inflexion":
        src = "https://www.inflexion.com/media/arhdgxnv/inflexion-portfolio_-160926.pdf"
        t = open("dl/inflexion.txt").read()
        for m in re.finditer(r"^\s*(.+)\s+(Financial Services|Industrials|Consumer|Healthcare|Business Services|Technology)\s+(?:%s)\s+((?:19|20)\d\d)" % MONTHS, t, re.M):
            out.append({"name": m.group(1).strip(), "website": None, "description": None, "sector_tag_on_site": m.group(2),
                        "status": "current", "investment_year": int(m.group(3)), "profile_url": src, "source_url": src})
    if fund == "Langholm Capital":
        src = "https://www.langholm.com/portfolio"
        for n, d in [("WoolOvers", "British lifestyle brand (sold to Verdane, Oct 2021)"),
                     ("Purity Soft Drinks", "UK based juice manufacturer (sold to Verdane, Oct 2021)"),
                     ("Lumene", "Nordic natural skincare and beauty brand (sold to Verdane, Oct 2021)"),
                     ("Dorset Cereals", "Previous investment"), ("Tyrrells Crisps", "Previous investment"),
                     ("Bart Spices", "Previous investment"), ("Just Retirement", "Previous investment")]:
            out.append({"name": n, "website": None, "description": d, "sector_tag_on_site": None, "status": "exited",
                        "investment_year": None, "profile_url": src, "source_url": src})
    return out


def norm_v(v):
    return re.sub(r"[^a-z0-9]", "", str(v).lower())[:80]


def slug_name(u):
    seg = [s for s in path(u).split("/") if s and s.lower() != "default.aspx"]
    q = re.search(r"investments=([^&]+)", u)
    sl = q.group(1) if q else (seg[-1] if seg else u)
    return re.sub(r"-(investment-page|\d+)$", "", sl).replace("-", " ").replace("_", " ").strip().title()


NOTES = {
    "CPT Capital": "cptcapital.com is a parked domain for sale (GoDaddy); no official portfolio site found via Firecrawl search.",
    "Distill Ventures": "distillventures.com failed (TLS/connection error) via both HTTP and Firecrawl.",
    "ZX Ventures": "zx-ventures.com DNS resolution failed; no standalone portfolio site found.",
    "SnackFutures (Mondelez)": "snackfutures.com shows 'under maintenance' page.",
    "L Catterton (Europe)": "Investments page renders brand grid via JS images only; no names extractable from HTML/Firecrawl markdown.",
    "Langholm Capital": "Fund wound down: site states remaining portfolio sold to Verdane in Oct 2021; companies taken from that page text.",
    "Crowdcube (food & drink raises)": "Explore page behind Cloudflare/JS; Firecrawl render returned no campaign list.",
    "Republic Europe/Seedrs (food & drink raises)": "Behind Cloudflare/JS; Firecrawl render returned no campaign list.",
    "Cairngorm Capital": "Portfolio pages rendered empty via HTTP and Firecrawl.",
    "Foresight Group": "Portfolio page gated by FCA intermediary disclaimer/JS; only a few companies visible.",
    "Mercia Ventures": "Portfolio page paginated client-side; only first page of companies captured.",
    "Octopus Ventures": "Portfolio loads client-side; only companies present in the rendered page captured.",
    "Inflexion": "Companies taken from the 'current portfolio' PDF linked on the portfolio page (as at 13/10/2025).",
    "Hambro Perks": "Hambro Perks renamed Salica Investments; salicainvestments.com used.",
    "Primary Capital": "primary.pe used (primarycapital.co.uk did not resolve).",
    "NorthEdge": "northedge.co.uk is parked; northedge.com used.",
    "The Craftory": "thecraftory.com is parked; thecraftory.io used.",
    "Puma Private Equity": "Portfolio taken from investor.pumainvestments.co.uk (Puma Investments VCT/EIS portfolio).",
    "Gresham House Ventures": "greshamhouseventures.com used.",
    "Bridgepoint Development Capital": "BDC = Bridgepoint 'lower-mid-cap' portfolio URLs from Firecrawl map of bridgepointgroup.com.",
    "Angel Investment Network": "Food & beverage business proposals listed on the network (seeking investment, not completed deals).",
}


def build(fund, L):
    lres = L[fund]
    site = SITES[fund]
    c = C[fund]
    comps = []
    profs = list(lres.get("profiles", {}).items())[:450]
    def one(item):
        u, t = item
        r = extract_profile(u, fund, site, False)
        if not r.get("name") or len(r["name"]) < 2 or re.search(r"404|not found|page not found|just a moment", r.get("name", ""), re.I):
            r["name"] = (t if t and not re.search(r"read more|view|learn more|^$", t, re.I) else slug_name(u))
            r["name_source"] = "anchor_text" if t and not re.search(r"read more|view|learn more", t, re.I) else "url_slug"
        r["source_url"] = u
        return r
    if fund.startswith("Crowdcube"):
        profs = []
    with ThreadPoolExecutor(4) as ex:
        comps += list(ex.map(one, profs))
    # values repeated across many profile pages are page chrome, not company data
    from collections import Counter
    for fld in ("name", "website", "description", "sector_tag_on_site"):
        cnt = Counter(norm_v(x.get(fld)) for x in comps if x.get(fld))
        for x, (u, t) in zip(comps, profs):
            if x.get(fld) and cnt[norm_v(x[fld])] > 2 and len(comps) > 3:
                if fld == "name":
                    good = t and not re.search(r"read more|view|learn more|find out|discover", t, re.I) and len(t) < 60
                    x["name"] = t if good else slug_name(u)
                    x["name_source"] = "anchor_text" if good else "url_slug"
                else:
                    x[fld] = None
    lp = next((p["final"] for p in lres.get("list_pages", []) if p.get("ok")), c["list"][0] if c["list"] else site)
    exts = lres.get("externals", [])
    from collections import Counter
    nc = Counter(norm_v(e[1]) for e in exts); cc = Counter(norm_v(e[2]) for e in exts)
    fixed = []
    for h, n, ctx in exts:
        if nc[norm_v(n)] > 2 or re.match(r"^(details|about|more|visit|view)\b", n or "", re.I):
            n = re.sub(r"^www\.", "", urlparse(h).netloc.lower()).split(".")[0].replace("-", " ").title()
        if cc[norm_v(ctx)] > 2:
            ctx = None
        fixed.append((h, n, ctx))
    for h, n, ctx in fixed:
        if isinstance(n, str):
            comps.append({"name": n, "website": h, "description": ctx or None, "sector_tag_on_site": None, "status": "unknown",
                          "investment_year": None, "profile_url": None, "source_url": lp})
    comps += special_companies(fund)
    # dedupe by normalized name / website
    seen, out = set(), []
    for x in comps:
        k = re.sub(r"[^a-z0-9]", "", (x.get("name") or "").lower())
        w = urlparse(x.get("website") or "").netloc.replace("www.", "")
        if not k or k in seen or (w and w in seen):
            continue
        seen.add(k)
        if w:
            seen.add(w)
        out.append(x)
    people, tsrc, teamc, comm = team_and_community(fund, lres)
    ok_pages = [p for p in lres.get("list_pages", []) if p.get("ok")]
    status = "ok" if out else ("failed" if not ok_pages else "no_companies_found")
    if out and fund in ("Mercia Ventures", "Foresight Group", "Octopus Ventures", "Livingbridge", "Inflexion"):
        status = "partial"
    rec = {"fund": fund, "website": site,
           "portfolio_urls": [p["final"] for p in lres.get("list_pages", []) if p.get("ok")] or c["list"],
           "scrape_status": status, "scrape_notes": NOTES.get(fund), "list_fetch": lres.get("list_pages"),
           "team_pages_checked": teamc, "team_platform_people": people, "community_signals": comm,
           "company_count": len(out), "companies": out}
    return rec


if STAGE == "build":
    L = json.load(open("lists.json"))
    funds = ONLY or list(C.keys())
    outp = os.path.join(OUT, "funds.jsonl")
    done = {}
    if os.path.exists(outp):
        for line in open(outp):
            r = json.loads(line); done[r["fund"]] = r
    for f in funds:
        try:
            rec = build(f, L)
        except Exception as e:
            import traceback
            rec = {"fund": f, "website": SITES.get(f), "portfolio_urls": C[f]["list"], "scrape_status": "failed",
                   "scrape_notes": "error: " + str(e)[:200], "team_platform_people": [], "community_signals": [], "companies": []}
            traceback.print_exc()
        done[f] = rec
        with open(outp, "w") as fh:
            for k in C:
                if k in done:
                    fh.write(json.dumps(done[k], ensure_ascii=False) + "\n")
        print(f"{f[:32]:32} {rec['scrape_status']:18} companies={len(rec['companies']):4} people={len(rec['team_platform_people'])} comm={len(rec['community_signals'])}", flush=True)
