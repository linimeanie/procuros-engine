import json, re
from concurrent.futures import ThreadPoolExecutor
from fx import *
funds=[json.loads(l) for l in open(OUT+"/funds.jsonl")]
urls=set()
for f in funds:
    for c in f["companies"]:
        if c.get("website") and not c.get("_text"):
            p=urlparse(c["website"]); urls.add(f"{p.scheme}://{p.netloc}")
print(len(urls))
def g(u):
    d=http_get(u, timeout=15)
    h=d.get("html") or ""
    s=BeautifulSoup(h[:400000],"lxml") if h else None
    t=(s.title.get_text(" ",strip=True) if s and s.title else "")
    m=s.find("meta",attrs={"name":"description"}) or s.find("meta",property="og:description") if s else None
    return u,{"title":t[:200],"desc":((m.get("content") or "") if m else "")[:400],"status":d["status"],"final":d["final_url"]}
with ThreadPoolExecutor(16) as ex: R=dict(ex.map(g,sorted(urls)))
json.dump(R,open("homes.json","w"),indent=0)
print(sum(1 for v in R.values() if v["status"]==200))
