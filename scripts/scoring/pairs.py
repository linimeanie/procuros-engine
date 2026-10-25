"""Rank intro opportunities (fund x brand pairs), then roll them up into the fund shortlist.

python scripts/scoring/pairs.py   (after score.py) -> data/scored/opportunities.json, data/scored/shortlist.csv

A pair is worth pursuing when the brand needs Procuros (brand fit, built only from observed evidence)
AND the fund can actually make the introduction (intro path). The pair score is the product, so either
side at zero sinks it. A fund's score is a decaying sum of its three best pairs: depth helps, but only
on top of quality.
"""
import json, re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CFG = json.loads((ROOT / "scripts/scoring/config.json").read_text())
P = CFG["pairs"]
AS_OF = date.fromisoformat(CFG["as_of"])
FUNDS = json.loads((ROOT / "data/scored/funds_scored.json").read_text())
BRANDS = {b["brand"]: b for b in json.loads((ROOT / "data/scored/brands_scored.json").read_text())}
_ip = ROOT / "data/firecrawl/intro_paths.jsonl"
PATHS = {(r["fund"], r["brand"]): r for r in map(json.loads, open(_ip))} if _ip.exists() else {}
# The fund itself on a brand's register (PSC or corporate director), found by step5 even before step6 runs
CH_LINKS = {}
for r in map(json.loads, open(ROOT / "data/firecrawl/companies_house.jsonl")):
    for l in r.get("fund_links") or []:
        CH_LINKS.setdefault((l["fund"], r["brand"]), []).append(
            {"name": l["name"], "role": l["role"], "since": l.get("since"), "ceased": l.get("ceased"), "ch_url": l["url"]})


def age_months(d):
    return max((AS_OF - date.fromisoformat(d[:10])).days / 30.4, 0)


def decayed(news):
    return sum(0.5 ** (age_months(n["date_parsed"]) / CFG["recency_half_life_months"]) for n in news)


def size_fit(b):
    """Companies House accounts type is evidence; without it, retail reach is the stand-in and says so."""
    band = ((b.get("companies_house") or {}).get("size_band") or "")
    if band.startswith(("medium", "full accounts", "group accounts")):
        return 1.0, "confirmed", "files full or group accounts (usually £10m+ turnover)"
    if band.startswith("small"):
        return 0.7, "confirmed", "files small-company accounts (up to £15m turnover)"
    if band.startswith("micro"):
        return 0.2, "confirmed", "files micro-entity accounts, likely under the £3m floor"
    n = len(b["retailers"])
    return (0.6 if n >= 2 else 0.3), "assumed", ("no accounts matched; sized from retail reach" if n else "no accounts matched and no retailer found")


def uk_fit(b):
    ch = b.get("companies_house") or {}
    if ch.get("company_number") and not (ch.get("size_band") or "").startswith("dormant"):
        return 1.0, "confirmed", f"UK company {ch['company_name']} ({ch['company_number']})"
    if b["retailers"]:
        return 0.5, "assumed", "sold by UK retailers, UK entity not matched"
    return 0.2, "unknown", "no UK entity or UK retailer found"


def why_now(b):
    """Recent change, not current state: new listings, money in, ops hiring, new markets. Volume of news is left out
    because it re-counts the same events."""
    w = P["why_now"]
    parts = {"listings": min(decayed(b["listing_news"]) / 2, 1), "funding": min(decayed(b["funding_news"]) / 2, 1),
             "ops_hiring": min(len(b["ops_roles"]) / 3, 1), "expansion": min(decayed(b["export_news"]), 1)}
    base = sum(w[k] * v for k, v in parts.items())
    st = CFG["stack"]
    mult = min(1 + st["bonus_per_extra_signal"] * max(len(b["stack"]) - 1, 0), st["max_multiplier"])
    return round(min(base * mult, 1), 3), parts, mult


def brand_fit(b):
    w = P["brand_fit"]
    reach = min(len(b["retailers"]) / 4, 1)
    now, parts, mult = why_now(b)
    size, size_ev, size_note = size_fit(b)
    uk, uk_ev, uk_note = uk_fit(b)
    fit = w["reach"] * reach + w["why_now"] * now + w["size"] * size + w["uk"] * uk
    trig = sorted([n for n in b["listing_news"] + b["funding_news"] + b["export_news"] if n["trade_press"]],
                  key=lambda n: n["date_parsed"], reverse=True)
    trig = list({n["date_parsed"][:7]: n for n in reversed(trig)}.values())[::-1]  # one story per month: outlets re-run the same news
    return {
        "fit": round(fit, 3),
        "parts": {"reach": round(reach, 3), "why_now": now, "size": size, "uk": uk},
        "why_now_parts": {k: round(v, 3) for k, v in parts.items()}, "stack_mult": mult, "stack": b["stack"],
        "evidence": {
            "reach": {"state": "confirmed" if b["retailers"] else "checked, none found",
                      "items": [{"name": r["name"], "url": r["source_url"]} for r in b["retailers"]]},
            "why_now": {"state": "confirmed" if trig or b["ops_roles"] else "checked, none found",
                        "items": [{"date": n["date_parsed"][:10], "text": n["headline"], "url": n["url"]} for n in trig[:3]]
                                 + [{"date": None, "text": f"Hiring: {r['title']}", "url": r.get("url")} for r in b["ops_roles"][:2]]},
            "size": {"state": size_ev, "note": size_note, "url": (b.get("companies_house") or {}).get("url")},
            "uk": {"state": uk_ev, "note": uk_note, "url": (b.get("companies_house") or {}).get("url")},
            "manual_process": {"state": "not observable", "note": "No public source shows how orders and invoices are handled; ask on the call."},
        },
    }


def intro_path(fund, fb):
    w = P["intro_path"]
    ip = PATHS.get((fund["fund"], fb["brand"])) or {}
    board = [p for p in ip.get("board_people", []) if not p.get("resigned")]
    entity = [e for e in ip.get("fund_entity") or CH_LINKS.get((fund["fund"], fb["brand"]), []) if not e.get("ceased")]
    entity = list({e["role"] + e["name"]: e for e in entity}.values())
    people = fund["evidence"]["platform_people"]
    support = fund["evidence"]["community"] + fund["evidence"]["vendor"]
    held = fb["status"] == "current"
    parts = {
        "listed": w["listed"],
        "board": w["board"] if board else w["board"] * 0.5 if entity else 0.0,
        "ops_person": w["ops_person"] if people else 0.0,
        "support": w["support"] if support else 0.0,
        "held": w["held"] if held else 0.0,
    }
    score = round(sum(parts.values()), 3)
    strength = "Strong" if score >= P["strong_path"] else "Good" if score >= P["good_path"] else "Weak"
    return {"path": score, "strength": strength, "parts": parts,
            "board_people": [{"name": pretty_person(p["name"]), "role": p.get("role"), "since": p.get("appointed"), "url": p["ch_url"],
                              "team_page": p.get("team_page")} for p in board],
            "fund_entity": [{"name": e["name"], "role": e["role"], "url": e["ch_url"]} for e in entity],
            "ops_people": [{"name": p["name"], "title": p["title"], "url": p["url"]} for p in people[:2]],
            "support": [{"text": c["text"][:70], "url": c["url"]} for c in support[:2]],
            "held": {"state": "confirmed" if held else "unconfirmed", "source": fb["status_source"]}}


def pretty_person(ch_name):
    if "," not in ch_name:
        return ch_name.title()
    last, rest = ch_name.split(",", 1)
    return f"{rest.split()[0].title()} {last.strip().title()}" if rest.split() else ch_name.title()


def confidence(fit, path):
    ev = fit["evidence"]
    hits = sum([ev["reach"]["state"] == "confirmed", ev["uk"]["state"] == "confirmed", ev["size"]["state"] == "confirmed",
                path["held"]["state"] == "confirmed", bool(path["board_people"] or path["fund_entity"])])
    return "High" if hits >= 4 else "Medium" if hits >= 2 else "Low"


def route_phrase(p, brand):
    if p["board_people"]:
        x = p["board_people"][0]
        return f"{x['name']} sits on {brand}'s board"
    if p["ops_people"]:
        x = p["ops_people"][0]
        return f"{x['name']} ({x['title']}) runs portfolio support"
    if p["fund_entity"]:
        return f"the fund is on {brand}'s Companies House register"
    return None


def next_step(f, best):
    b, p = best["brand"], best["intro"]
    steps = []
    if p["held"]["state"] != "confirmed":
        steps.append(f"Confirm {f['fund']} still holds {b}.")
    if best["fit"]["evidence"]["uk"]["state"] != "confirmed":
        steps.append(f"Check {b} trades through a UK company.")
    if p["board_people"]:
        steps.append(f"Ask {p['board_people'][0]['name']}, on {b}'s board, for an intro to the founder.")
    elif p["ops_people"]:
        x = p["ops_people"][0]
        steps.append(f"Ask {x['name']} ({x['title']}) for an intro to {b}.")
    elif p["fund_entity"]:
        steps.append(f"Find which {f['fund']} partner holds the board seat at {b}, then ask them.")
    else:
        steps.append(f"Find the deal partner for {b} and look for a mutual connection.")
    trig = best["fit"]["evidence"]["why_now"]["items"]
    if trig and trig[0]["date"]:
        steps.append(f"Lead with: {trig[0]['text'][:80]} ({trig[0]['date'][:7]}).")
    return steps


def rationale(f, pairs):
    good = [x for x in pairs if x["score"] >= P["qualified_pair"]][:3] or pairs[:1]
    names = []
    for x in good:
        r = [i["name"] for i in x["fit"]["evidence"]["reach"]["items"]][:2]
        names.append(f"{x['brand']} ({', '.join(r)})" if r else x["brand"])
    lead = " and ".join([", ".join(names[:-1]), names[-1]] if len(names) > 1 else names)
    route = route_phrase(pairs[0]["intro"], pairs[0]["brand"])
    return f"Backs {lead}" + (f"; {route}." if route else "; no named route yet, so the first job is finding the deal partner.")


def rank(fund_rows, fit_w=None, path_w=None, decay=None):
    """Pure re-score used by the sensitivity test; returns fund names in rank order."""
    decay = decay or P["aggregate_decay"]
    scored = []
    for f in fund_rows:
        ps = []
        for x in f["pairs"]:
            fit = sum((fit_w or P["brand_fit"])[k] * v for k, v in x["fit"]["parts"].items())
            pw = path_w or P["intro_path"]
            path = sum(pw[k] / P["intro_path"][k] * v if P["intro_path"][k] else 0 for k, v in x["intro"]["parts"].items())
            ps.append(fit * path)
        ps.sort(reverse=True)
        scored.append((sum(d * s for d, s in zip(decay, ps)) / sum(decay), f["fund"]))
    return [n for _, n in sorted(scored, reverse=True)]


def main():
    rows = []
    for f in FUNDS:
        if not f["brands"]:
            continue
        pairs = []
        for fb in f["brands"]:
            b = BRANDS[fb["brand"]]
            fit, path = brand_fit(b), intro_path(f, fb)
            pairs.append({"brand": fb["brand"], "score": round(100 * fit["fit"] * path["path"], 1), "fit": fit, "intro": path,
                          "confidence": confidence(fit, path), "fund_source": (b.get("fund_sources") or [None])[0]})
        pairs.sort(key=lambda x: -x["score"])
        d = P["aggregate_decay"]
        score = round(sum(w * x["score"] for w, x in zip(d, pairs)) / sum(d), 1)
        rows.append({"fund": f["fund"], "fund_type": f["fund_type"], "score": score, "pairs": pairs,
                     "qualified": sum(1 for x in pairs if x["score"] >= P["qualified_pair"]),
                     "set_aside": f.get("set_aside", []), "procuros_overlap": sorted(set(f["evidence"]["procuros_overlap"])),
                     "ops_people": f["evidence"]["platform_people"][:3], "support": (f["evidence"]["community"] + f["evidence"]["vendor"])[:3]})
    rows.sort(key=lambda r: -r["score"])
    n = CFG["shortlist_size"]
    for i, r in enumerate(rows, 1):
        r["rank"] = i
        r["selected"] = i <= n
        best = r["pairs"][0]
        t = P["tiers"]
        r["tier"] = ("A" if r["score"] >= t["A"] and r["qualified"] >= 2 else "B" if r["score"] >= t["B"] else "C") if r["selected"] else "-"
        r["rationale"] = rationale(r, r["pairs"])
        r["next_steps"] = next_step(r, best)

    # Sensitivity: does the 20 (and the call-first group) survive other reasonable weightings?
    scen = {
        "As built": {},
        "Fit matters more": {"fit_w": {"reach": .45, "why_now": .35, "size": .1, "uk": .1}},
        "Why-now matters more": {"fit_w": {"reach": .25, "why_now": .55, "size": .1, "uk": .1}},
        "Size and UK matter more": {"fit_w": {"reach": .3, "why_now": .3, "size": .2, "uk": .2}},
        "Board seat matters more": {"path_w": {"listed": .1, "board": .5, "ops_person": .15, "support": .05, "held": .2}},
        "Ops contact matters more": {"path_w": {"listed": .1, "board": .3, "ops_person": .35, "support": .1, "held": .15}},
        "Best pair only": {"decay": [1]},
        "All pairs count equally": {"decay": [1] * 30},
    }
    base_top = [r["fund"] for r in rows[:n]]
    k = sum(1 for r in rows if r["tier"] == "A") or 5
    sens = []
    for name, kw in scen.items():
        order = rank(rows, **kw)
        sens.append({"scenario": name, "top": order[:n], "same_in_top": len(set(order[:n]) & set(base_top)),
                     "same_in_first": len(set(order[:k]) & set(base_top[:k]))})
    for r in rows:
        ranks = [rank(rows, **kw).index(r["fund"]) + 1 for kw in scen.values()]
        r["rank_range"] = [min(ranks), max(ranks)]
    out = {"as_of": CFG["as_of"], "shortlist_size": n, "first_group": k, "funds": rows, "sensitivity": sens,
           "dropped": [{"fund": r["fund"], "score": r["score"], "why": r["rationale"]} for r in rows[n:]]}
    (ROOT / "data/scored/opportunities.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    with open(ROOT / "data/scored/shortlist.csv", "w") as fh:
        fh.write("rank,fund,type,tier,score,best_brand,best_pair,path,confidence,rationale,next_step\n")
        for r in rows[:n]:
            b = r["pairs"][0]
            q = lambda s: '"' + s.replace('"', "'") + '"'
            fh.write(f"{r['rank']},{q(r['fund'])},{r['fund_type']},{r['tier']},{r['score']},{q(b['brand'])},{b['score']},"
                     f"{b['intro']['strength']},{b['confidence']},{q(r['rationale'])},{q(' '.join(r['next_steps']))}\n")
    for r in rows:
        b = r["pairs"][0]
        print(r["rank"], r["tier"], r["fund"], r["score"], "q", r["qualified"], "|", b["brand"], b["score"], b["intro"]["strength"], b["confidence"], r["rank_range"])
    for s in sens:
        print(s["scenario"], s["same_in_top"], s["same_in_first"])


if __name__ == "__main__":
    main()
