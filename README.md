# procuros-engine

This repo holds the data and scripts behind the Procuros UK GTM case study, which plans warm intros via VCs/PEs to UK grocery/FMCG brands.
All of it was scraped on 2026-10-24. Every record includes the URL it came from, and nothing was typed in by hand without a source.

## Files: `data/firecrawl/`

| File | What it is |
|---|---|
| `funds.jsonl` | One line per fund (66 total). Fields: `fund`, `fund_type` (PE / VC / corporate VC / angel-crowdfunding listing), `website`, `portfolio_urls`, `scrape_status` (ok / partial / no_companies_found / failed), `scrape_notes`, `team_platform_people` [{name, title, url}], `community_signals` [{text, url}], `companies` [{name, website, description, sector_tag_on_site, status, investment_year, profile_url, source_url, name_source?}] |
| `brands.jsonl` | 118 UK grocery/FMCG brands taken from those portfolios. Fields: `brand`, `website`, `funds`, `backer_types`, `status_by_fund`, `fund_sources` (the portfolio URLs the brand was found on), `retailers` [{name, source_url}], `ops_roles` [{title, url}], `news` [{date, headline, url, type}], `erp_mentions` [{text, url}], `pages_checked`, `notes` |
| `grocery_candidates.json` | All 390 food/drink candidates the keyword classifier flagged. The 118 in `brands.jsonl` are a manually reviewed subset of these. |
| `companies_page_text.jsonl` | The first ~2.5k characters of each scraped portfolio profile page (useful for re-classifying later) |
| `fetch_log.jsonl` | Every HTTP / Firecrawl request, with its status or error |
| `raw/` | Cached raw responses. Kept local only and gitignored (~800MB). |

## Method

1. **Fund sites.** I started from the official domain and checked it resolves. Several funds have moved: Hambro Perks is now salicainvestments.com, Primary Capital is at primary.pe, NorthEdge at northedge.com, The Craftory at thecraftory.io, and Gresham House Ventures at greshamhouseventures.com.
2. **Portfolio discovery.** I used sitemaps, the portfolio list pages (following pagination) and Firecrawl `map`. Company profile URLs were matched with a pattern set per fund (`scripts/firecrawl/config.py`). For funds that only list logos with links out, companies come from those outbound links.
3. **Profiles.** Each profile page gives the name (h1/title), description (meta or first paragraph), website (a "visit website" style link), sector/status/year (when labelled on the page) and the page text. If a value repeats across most of a fund's profile pages, it's page chrome, so it's dropped. In that case the name falls back to the anchor text or the URL slug, and `name_source` records which.
4. **Fetching.** Static pages were fetched directly over HTTP. Firecrawl (`scrape` with JS render, `map`, `search`) was used only when a page was JS-rendered or behind Cloudflare. The account had about 1,000 credits; about 425 were used.
5. **Brand selection.** A keyword classifier ran over name, description, homepage meta and profile text. Words that appear on most of one fund's pages were ignored, and exclusion terms (restaurant, SaaS, ag-tech, cultivated meat, B2B ingredients) pushed a company down. I then reviewed the candidates by hand and kept UK packaged food, drinks, snacks, chilled/frozen, pet food and health-food brands. I dropped restaurants, meal kits that are D2C only, tech and non-UK HQs.
6. **Enrichment** (per brand):
   - Homepage, plus up to 2 stockist and 2 careers links, plus one level of ATS links. These pages are checked for the 14 named retailers, ops/supply-chain/customer-service role titles, and ERP/EDI terms.
   - A Firecrawl news search covering the last 24 months, typed as funding / acquisition / retailer_listing / export / erp / other.
   - When a portfolio page gave no brand website, I looked for it with a Firecrawl search and then reviewed the result by hand. 11 wrong matches were rejected (noted in `notes`).

## Known gaps

- **Failed or empty:** CPT Capital (cptcapital.com is parked), Distill Ventures (TLS errors), ZX Ventures (DNS doesn't resolve), SnackFutures (site in maintenance), L Catterton (JS image grid), Cairngorm (renders empty), Crowdcube and Republic/Seedrs (Cloudflare/JS, no campaign list).
- **Partial:** Inflexion (built from the current-portfolio PDF plus profile pages), Livingbridge (the first 12 tiles load before a JS "load more"), Mercia (first page only), Foresight (FCA disclaimer gate), Octopus (only the rendered set).
- **Angel Investment Network** entries are open fundraising listings, not completed deals. They're tagged `backer_types: ["angel/crowdfunding listing"]`.
- **Retailer detection** only finds retailers named on the brand's own site. A missing retailer doesn't mean the brand isn't stocked there. Store-locator widgets that load by JS are often missed.
- **Ops roles** only cover careers pages that can be reached from the homepage. Many ATSs render with JS.
- **Team people** are found by heuristics on the team page (a name line followed by a title such as portfolio / platform / value creation / talent / community). JS-rendered team pages return nothing.

## Re-running

From `scripts/firecrawl/`, set up a Python 3.9 venv with requests, beautifulsoup4, lxml and pypdf, and log the Firecrawl CLI in. Then run:

```
python step1.py list && python step1.py build      # funds.jsonl
python homes.py && python step2.py classify          # candidates
python step2.py enrich selected.json && python finalize.py
```

The cache lives in `data/firecrawl/raw/`, so a re-run only spends credits on pages that aren't cached yet.

## Scoring: `scripts/scoring/`

Run `python3 scripts/scoring/score.py`. It reads `data/firecrawl/`, applies `overrides.json`, and writes `data/scored/`:

- `funds_scored.json`: for each fund, its rank, score (0–100), tier, the four pillar scores, raw and normalised signals, its brands, the evidence behind them, and a generated `why`.
- `brands_scored.json`: for each brand, fit, pain, the retailer list (from its site plus news headlines), filtered news, and its size proxy.
- `shortlist.csv`: the ranking as a flat table.

**Model** (weights are in `config.json`):
- Score = 100 × (0.4 fit + 0.3 pain + 0.2 access + 0.1 strategic).
- **Fit** (portfolio fit): the fund's brand count weighted by how well each brand fits (log-scaled), FMCG share of the portfolio, average brand fit, and recent deals.
- **Pain** (brand pain): the mean pain of the fund's top 5 brands, built from listings, funding/M&A, ops hiring, news momentum and export.
- **Access** (accessibility): platform or portfolio-ops people, community programmes, fund size/stage, and openness to vendors.
- **Strategic**: overlap with Procuros customers, brand halo, and ecosystem programmes.
- Access and strategic are multiplied by `min(live brands / 3, 1)`, because reach is worth nothing without brands to reach.

**Brand status weights:**

| Status | Weight |
|---|---|
| Current | 1 |
| Unknown | 0.85 |
| Exited within 24 months | 0.5 |
| Exited earlier | 0.15 |

**Curation** (`overrides.json`): Angel Investment Network listings and 3 non-ICP brands are dropped. Exit statuses come from the profile pages where they say so; a few come from desk knowledge and are labelled that way. 7 brands found in the earlier web pass were added, each with its source. Fund size/stage values are desk knowledge, so treat their confidence as low.

**Limits:**
- No revenue data was available, so the £3m–£100m size band is approximated by retail reach and trade-press coverage.
- News only counts if the headline names the brand and the article is from the last 24 months. Ambiguous names (THIS, Sneak, STOCKED…) also need a trade-press domain.
- Tier cut-offs (A ≥ 38 with 3+ live brands, B ≥ 30) are set to the observed score range, because sparse signals keep the top score near 45.

## Case-study site: `site/`

The site is static (D3 from cdnjs, no build step). It covers the thesis, the pipeline funnel, the signal table with live pillar-weight sliders, the ranking, the fund↔brand network map, fund dossiers, and limits.

- `python3 scripts/site/export.py` rebuilds `site/data.json` from `data/scored/`.
- `python3 scripts/site/build.py` wraps `site/page.html` into the standalone `site/index.html`.
- Vercel: import the repo. `vercel.json` serves `site/` as-is.
