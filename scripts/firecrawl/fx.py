"""Fetch helpers: free HTTP first, Firecrawl CLI fallback. Everything cached on disk."""
import hashlib, json, os, re, subprocess, sys, time, warnings
warnings.filterwarnings("ignore")
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

OUT = "/Users/lini/Documents/My Claude/procuros-engine/data/firecrawl"
CACHE = os.path.join(OUT, "raw")
os.makedirs(CACHE, exist_ok=True)
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/129.0 Safari/537.36")
LOG = os.path.join(OUT, "fetch_log.jsonl")
FC_BIN = "/Users/lini/.local/node-v22.12.0-darwin-arm64/bin/firecrawl"
import threading
_FCLOCK = threading.Lock()
_FCLAST = [0.0]


def _fc_run(cmd, timeout=180):
    """Serialise Firecrawl calls at ~8/min; retry on rate limit."""
    for attempt in range(4):
        with _FCLOCK:
            gap = time.time() - _FCLAST[0]
            if gap < 7.5:
                time.sleep(7.5 - gap)
            _FCLAST[0] = time.time()
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if "Rate limit" in (r.stderr + r.stdout)[:2000]:
            time.sleep(30 * (attempt + 1))
            continue
        return r
    return r


def _key(url, kind):
    return os.path.join(CACHE, kind + "_" + hashlib.md5(url.encode()).hexdigest() + ".json")


def log(rec):
    rec["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    with open(LOG, "a") as f:
        f.write(json.dumps(rec) + "\n")


def http_get(url, timeout=25):
    """Free fetch. Returns dict(url, final_url, status, html) or None. Cached."""
    p = _key(url, "http")
    if os.path.exists(p):
        return json.load(open(p))
    try:
        r = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "en-GB,en"},
                         timeout=timeout, allow_redirects=True)
        d = {"url": url, "final_url": r.url, "status": r.status_code,
             "html": r.text if "html" in r.headers.get("content-type", "") or "xml" in r.headers.get("content-type", "") else r.text[:200000]}
    except Exception as e:
        d = {"url": url, "final_url": url, "status": 0, "html": "", "error": str(e)[:300]}
    json.dump(d, open(p, "w"))
    log({"method": "http", "url": url, "status": d["status"], "err": d.get("error")})
    return d


def fc_scrape(url, wait_ms=None):
    """Firecrawl scrape (1 credit). Returns dict(url, html, markdown, links) or None. Cached."""
    p = _key(url, "fc")
    if os.path.exists(p):
        return json.load(open(p))
    cmd = [FC_BIN, "scrape", url, "--format", "markdown,rawHtml,links", "--json"]
    if wait_ms:
        cmd += ["--wait-for", str(wait_ms)]
    try:
        r = _fc_run(cmd)
        j = json.loads(r.stdout) if r.stdout.strip().startswith("{") else None
    except Exception as e:
        j = None
        r = None
    if not j:
        d = {"url": url, "error": (r.stderr[:300] if r else "timeout"), "html": "", "markdown": "", "links": []}
        log({"method": "firecrawl_scrape", "url": url, "err": d["error"]})
        return d
    else:
        dd = j.get("data", j)
        d = {"url": url, "final_url": (dd.get("metadata") or {}).get("url", url),
             "html": dd.get("rawHtml") or dd.get("html") or "", "markdown": dd.get("markdown") or "",
             "links": dd.get("links") or [], "status": (dd.get("metadata") or {}).get("statusCode")}
    json.dump(d, open(p, "w"))
    log({"method": "firecrawl_scrape", "url": url, "status": d.get("status"), "err": d.get("error")})
    return d


def fc_map(url, search=None, limit=500):
    p = _key(url + "|" + str(search), "fcmap")
    if os.path.exists(p):
        return json.load(open(p))
    cmd = [FC_BIN, "map", url, "--json", "--limit", str(limit), "--wait"]
    if search:
        cmd += ["--search", search]
    try:
        r = _fc_run(cmd)
        j = json.loads(r.stdout)
        links = j.get("links") or (j.get("data") or {}).get("links") or []
        links = [l["url"] if isinstance(l, dict) else l for l in links]
    except Exception as e:
        links = []
    json.dump(links, open(p, "w"))
    log({"method": "firecrawl_map", "url": url, "search": search, "n": len(links)})
    return links


def fc_search(query, limit=5, tbs=None, sources=None):
    p = _key(query + "|" + str(limit) + str(tbs) + str(sources), "fcsearch")
    if os.path.exists(p):
        return json.load(open(p))
    cmd = [FC_BIN, "search", query, "--limit", str(limit), "--json", "--country", "GB"]
    if tbs:
        cmd += ["--tbs", tbs]
    if sources:
        cmd += ["--sources", sources]
    try:
        r = _fc_run(cmd, 120)
        j = json.loads(r.stdout)
    except Exception as e:
        log({"method": "firecrawl_search", "query": query, "err": str(e)[:200]})
        return {"error": str(e)[:300]}
    json.dump(j, open(p, "w"))
    log({"method": "firecrawl_search", "query": query})
    return j


def visible_text(html):
    s = BeautifulSoup(html, "lxml")
    for t in s(["script", "style", "noscript", "svg"]):
        t.decompose()
    return re.sub(r"\n\s*\n+", "\n", s.get_text("\n")).strip()


def links_of(html, base):
    s = BeautifulSoup(html, "lxml")
    out = []
    for a in s.find_all("a", href=True):
        href = urljoin(base, a["href"].strip())
        if href.startswith("http"):
            out.append((href.split("#")[0], re.sub(r"\s+", " ", a.get_text(" ")).strip()))
    return out


def get(url, need_text_len=1500, allow_fc=True, wait_ms=None):
    """HTTP first; Firecrawl if blocked/JS-empty. Returns (html, final_url, method) or (None, url, err)."""
    d = http_get(url)
    if d["status"] == 200 and d["html"]:
        txt = visible_text(d["html"])
        if len(txt) >= need_text_len:
            return d["html"], d["final_url"], "http"
    if not allow_fc:
        return (d["html"] or None), d["final_url"], "http_thin"
    f = fc_scrape(url, wait_ms)
    if f.get("html"):
        return f["html"], f.get("final_url") or url, "firecrawl"
    return None, url, "failed:" + str(d.get("status")) + "/" + str(f.get("error", ""))[:120]
