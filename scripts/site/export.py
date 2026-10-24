"""Bundle scored data into site/data.json for the case-study site."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
cfg = json.loads((ROOT / "scripts/scoring/config.json").read_text())
funds = json.loads((ROOT / "data/scored/funds_scored.json").read_text())
brands = json.loads((ROOT / "data/scored/brands_scored.json").read_text())
raw_funds = [json.loads(l) for l in open(ROOT / "data/firecrawl/funds.jsonl")]
cands = json.loads((ROOT / "data/firecrawl/grocery_candidates.json").read_text())


def news_item(n):
    return {"date": n["date_parsed"], "headline": n["headline"], "url": n["url"], "trade": n["trade_press"]}


out_brands = []
for b in brands:
    trig = sorted([n for n in b["funding_news"] + b["listing_news"] if n["trade_press"]],
                  key=lambda n: n["date_parsed"], reverse=True)
    out_brands.append({
        "name": b["brand"], "website": b.get("website"), "description": (b.get("description") or "")[:220],
        "funds": b["funds"], "category": b["category"], "fit": b["fit"], "pain": b["pain"],
        "pain_parts": b["pain_parts"], "size_proxy": b["size_proxy"],
        "retailers": b["retailers"], "ops_roles": b["ops_roles"][:5],
        "triggers": [news_item(n) for n in trig[:3]],
        "news_count": len(b["news"]), "fund_sources": b["fund_sources"][:3],
    })

out_funds = []
for f in funds:
    out_funds.append({
        "name": f["fund"], "type": f["fund_type"], "website": f.get("website"), "scrape": f["scrape_status"],
        "portfolio_urls": f.get("portfolio_urls", [])[:2], "companies": f["company_count"],
        "n": f["normalised"], "raw": f["raw"], "gate": f["gate"], "score": f["score"], "tier": f["tier"],
        "pillars": f["pillars"], "live": f["live_brand_count"], "why": f["why"],
        "brands": f["brands"],
        "people": [{"name": p["name"], "title": p["title"], "url": p["url"]} for p in f["evidence"]["platform_people"][:4]],
        "community": [{"text": c["text"][:60], "url": c["url"]} for c in f["evidence"]["community"][:4]],
        "overlap": sorted(set(f["evidence"]["procuros_overlap"])),
    })

failed = [{"name": f["fund"], "status": f["scrape_status"], "note": (f.get("scrape_notes") or "")[:140]}
          for f in raw_funds if f["scrape_status"] in ("failed", "no_companies_found")]
funnel = [
    {"label": "Funds seeded", "value": len(raw_funds)},
    {"label": "Portfolios scraped", "value": sum(1 for f in raw_funds if f["scrape_status"] in ("ok", "partial"))},
    {"label": "Portfolio companies", "value": sum(len(f.get("companies", [])) for f in raw_funds)},
    {"label": "Food & drink candidates", "value": len(cands)},
    {"label": "UK grocery brands kept", "value": len(brands)},
    {"label": "Funds holding a live brand", "value": sum(1 for f in funds if f["live_brand_count"] > 0)},
    {"label": "Shortlist", "value": 20},
]
data = {"as_of": cfg["as_of"], "config": {k: cfg[k] for k in ("pillars", "fit", "pain", "access", "strategic", "tiers", "gate_brands")},
        "funnel": funnel, "funds": out_funds, "brands": out_brands, "failed": failed,
        "stats": {"brands_with_retailers": sum(1 for b in brands if b["retailers"]),
                  "brands_with_ops": sum(1 for b in brands if b["ops_roles"]),
                  "brands_with_news": sum(1 for b in brands if b["news"])}}
(ROOT / "site/data.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
print({k: v for k, v in data["stats"].items()}, [x["value"] for x in funnel], len(out_funds))
