import json, re, os
OUT="/Users/lini/Documents/My Claude/procuros-engine/data/firecrawl"
norm=lambda n: re.sub(r"[^a-z0-9]","",(n or "").lower())
PE={"BGF","LDC","Piper","Inflexion","Livingbridge","Palatine","YFM Equity Partners","Mobeus","NorthEdge","Kester Capital","Elaghmore","Silverfleet","Synova","CBPE","Langholm Capital","Exponent","CapVest","L Catterton (Europe)","Lion Capital","Endless","Penta Capital","Rutland Partners","Inverleith","Cairngorm Capital","Phoenix Equity Partners","Primary Capital","ECI Partners","Tenzing","Bridgepoint Development Capital","Literacy Capital","Active Partners","Verlinvest","True (TrueCapital)"}
CVC={"Unilever Ventures","Distill Ventures","SnackFutures (Mondelez)","ZX Ventures"}
ANGEL={"Angel Investment Network","Crowdcube (food & drink raises)","Republic Europe/Seedrs (food & drink raises)"}
def ftype(f): return "PE" if f in PE else "corporate VC" if f in CVC else "angel/crowdfunding listing" if f in ANGEL else "VC"
funds=[json.loads(l) for l in open(OUT+"/funds.jsonl")]
side=open(OUT+"/companies_page_text.jsonl","a") if False else open(os.devnull,"w") if os.path.exists(OUT+"/companies_page_text.jsonl") else open(OUT+"/companies_page_text.jsonl","w")
status={}
for f in funds:
    f["fund_type"]=ftype(f["fund"])
    for c in f["companies"]:
        t=c.pop("_text",None); c.pop("_home",None); c.pop("fetch",None)
        if t: side.write(json.dumps({"fund":f["fund"],"name":c["name"],"profile_url":c.get("profile_url"),"text":t},ensure_ascii=False)+"\n")
        status.setdefault(norm(c["name"]),{})[f["fund"]]=c.get("status")
side.close()
order=["fund","fund_type","website","portfolio_urls","scrape_status","scrape_notes","company_count","team_platform_people","community_signals","team_pages_checked","list_fetch","companies"]
with open(OUT+"/funds.jsonl","w") as fh:
    for f in funds: fh.write(json.dumps({k:f.get(k) for k in order},ensure_ascii=False)+"\n")
C=json.load(open(OUT+"/grocery_candidates.json"))
brands=[json.loads(l) for l in open(OUT+"/brands.jsonl")]
with open(OUT+"/brands.jsonl","w") as fh:
    for b in brands:
        k=norm(b["brand"]); cand=next((v for kk,v in C.items() if norm(v["brand"])==k),{})
        b["backer_types"]=sorted({ftype(x) for x in b["funds"]})
        st={}
        for x in b["funds"]:
            for kk,v in status.items():
                if kk==k or (cand and kk==norm(cand.get("brand"))): 
                    if x in v: st[x]=v[x]
        b["status_by_fund"]=st
        b["description"]=cand.get("description")
        b["selection"]="keyword classifier + manual review of name/description" if not cand.get("added") else "manual review of portfolio names"
        order=["brand","website","funds","backer_types","status_by_fund","fund_sources","description","retailers","ops_roles","news","erp_mentions","pages_checked","notes","selection"]
        fh.write(json.dumps({kk:b.get(kk) for kk in order},ensure_ascii=False)+"\n")
# summary
fs=[f for f in funds]
print("funds",len(fs),{s:sum(1 for f in fs if f["scrape_status"]==s) for s in set(f["scrape_status"] for f in fs)})
print("companies",sum(len(f["companies"]) for f in fs))
bs=[json.loads(l) for l in open(OUT+"/brands.jsonl")]
print("brands",len(bs),"with_retailers",sum(1 for b in bs if b["retailers"]),"with_ops_roles",sum(1 for b in bs if b["ops_roles"]),"with_news",sum(1 for b in bs if b["news"]),"with_erp",sum(1 for b in bs if b["erp_mentions"]),"no_site",sum(1 for b in bs if not b["website"]))
print("people",sum(len(f["team_platform_people"]) for f in fs))
