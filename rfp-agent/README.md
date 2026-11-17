# RFP agent engine

Mechanics for the Thriving Culture RFP agent (`.claude/agents/rfp-agent.md` and its sub-agents). This folder holds code only. Rules, rulings, team data, client data and private identifiers live in the private system of record and are read at run time; this repository is public, so none of them belong here.

## What works today

| Capability | Module | Status |
|---|---|---|
| SAM.gov search, notice detail, public attachment list and download, no API key | `sources/sam.py` | Live-tested 17 Nov 2026 |
| Grants.gov search2 API | `sources/grants.py` | Live-tested 17 Nov 2026 |
| CanadaBuys open-data CSV (BOM, multiline fields) | `sources/canadabuys.py` | Live-tested 17 Nov 2026 |
| MERX ID classes and URL templates, GC relay routing | `sources/merx.py` | Unit-tested; fetching needs Pablo's session |
| BidNet notification email parser | `sources/bidnet_email.py` | Unit-tested on synthetic bodies; tune on real mail |
| Keyword lanes (core, board, digital) with title-only boilerplate terms and negatives | `keywords.py` | Tuned on 17 Nov live data |
| 36-column board row, cleaning, TSV, 28 + 8 paste blocks | `model.py` | Unit-tested |
| Dedupe: source URL, number plus buyer, number, fuzzy buyer plus title, containment | `dedupe.py` | Unit-tested; run against the live board |
| Merge planner with the 00:30 to 01:30 Madrid refusal and TSV re-parse check | `merge.py` | Unit-tested |
| Intake screens (detections only; UNREAD until the primary is read) | `screen.py` | Unit-tested |
| Price decision (card, benchmark, floor, minimum, walk-away) and value estimate | `pricing.py` | Unit-tested; numbers come from the private rubric |
| Download, hash, count on disk, `00_SOURCE.md` | `acquire.py` | Live-tested on four SAM notices |
| Proposal PDF build with face tokens, header and footer bands, no split tables | `proposal/build_pdf.js` | Smoke-tested |

## Run

```bash
pip install requests pytest
cd rfp-agent
python -m pytest -q
python -m rfp_engine sweep --master master_keys.csv --out runs/$(date +%F)
```

Outputs go to `runs/` (gitignored): `staging_rows.tsv`, `opportunities.json`, `duplicates.json`, `health.json`, `SWEEP.md`.

## Network

The cloud environment must allow: `sam.gov`, `api.grants.gov`, `canadabuys.canada.ca`, plus the portal hosts the sourcer visits. Requests use an honest user agent and no credentials.
