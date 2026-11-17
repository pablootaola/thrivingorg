"""Command line.

  python -m rfp_engine sweep [--sources sam,grants,canadabuys] [--out DIR] [--master master.csv]
  python -m rfp_engine merge --master master.csv --staging staging.csv [--out append.tsv]
  python -m rfp_engine acquire-sam NOTICE_ID --dest DIR --title T --buyer B --number N --due D
  python -m rfp_engine bidnet-email BODY.txt

Outputs land in --out (default: a dated folder under ./runs, which is gitignored).
Nothing here writes to the master board, Dropbox or Notion; the agent does that with
its connectors after reading these outputs.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from .dedupe import BoardIndex
from .merge import plan_merge, rows_from_csv
from .model import MADRID, UTC, deadline_pair, to_tsv
from .screen import intake


def _now():
    return datetime.now(UTC)


def cmd_sweep(a) -> int:
    from .sources import canadabuys, grants, sam
    now = _now()
    out = Path(a.out or f"runs/{now.astimezone(MADRID):%Y-%m-%d_%H%M}")
    out.mkdir(parents=True, exist_ok=True)
    adapters = {"sam": lambda: sam.sweep(now=now), "grants": grants.sweep,
                "canadabuys": lambda: canadabuys.sweep(now=now)}
    opps, health = [], []
    for name in a.sources.split(","):
        found, h = adapters[name.strip()]()
        opps.extend(found)
        health.append(h)
        print(f"{h.source}: {h.status} queries={h.queries} raw={h.raw_hits} relevant={h.relevant}", file=sys.stderr)
    master = rows_from_csv(Path(a.master).read_text(encoding="utf-8")) if a.master else []
    idx = BoardIndex(master)
    new, dup = [], []
    for o in opps:
        i, how = idx.find(o.number, o.buyer, o.title, o.source_url)
        if i is not None:
            dup.append({"title": o.title, "buyer": o.buyer, "master_row": i + 2, "match": how})
            continue
        sr = intake(f"{o.title} {o.summary}", buyer=o.buyer, region=o.region,
                    is_gc=o.record_class == "gc-canadabuys", due=o.due, now=now)
        o.flags = sorted(set(o.flags + sr.flags))
        new.append(o)
    new.sort(key=lambda o: (o.due is None, o.due or now))
    rows = [o.board_row(stage=a.stage or "Verify") for o in new]
    (out / "staging_rows.tsv").write_text(to_tsv(rows), encoding="utf-8")
    (out / "opportunities.json").write_text(json.dumps([o.to_dict() for o in new], indent=1), encoding="utf-8")
    (out / "duplicates.json").write_text(json.dumps(dup, indent=1), encoding="utf-8")
    (out / "health.json").write_text(json.dumps([h.__dict__ for h in health], indent=1), encoding="utf-8")
    lines = [f"# Sweep {now.astimezone(MADRID):%d %b %Y %H:%M %Z}", "",
             f"Master rows compared: {len(master)}. New: {len(new)}. Already on board: {len(dup)}.", "",
             "| Source | Status | Queries | Raw hits | Relevant |", "|---|---|---|---|---|"]
    lines += [f"| {h.source} | {h.status} | {h.queries} | {h.raw_hits} | {h.relevant} |" for h in health]
    lines += ["", "## New rows, soonest deadline first", ""]
    for o in new:
        tz = None
        lines.append(f"- {deadline_pair(o.due) or 'deadline not established'} | {o.lane or 'lane?'} | "
                     f"{o.buyer} | {o.number} | {o.title} | {o.source_url} | flags: {', '.join(o.flags) or 'none'}")
    (out / "SWEEP.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(out)
    return 0


def cmd_merge(a) -> int:
    master = rows_from_csv(Path(a.master).read_text(encoding="utf-8"))
    staging = rows_from_csv(Path(a.staging).read_text(encoding="utf-8"))
    res = plan_merge(master, staging, _now())
    Path(a.out).write_text(res.tsv(), encoding="utf-8")
    print(json.dumps({"append": len(res.append), "duplicates": res.duplicates, "rejected": len(res.rejected)}, indent=1))
    return 0


def cmd_acquire_sam(a) -> int:
    from .acquire import download_all, write_source_md
    from .sources import sam
    docs = sam.attachments(a.notice_id)
    dest = Path(a.dest)
    rec = download_all(docs, dest, "SAM.gov", sam.notice_url(a.notice_id))
    write_source_md(rec, dest, title=a.title, buyer=a.buyer, number=a.number, due=a.due)
    print(json.dumps({"fraction": rec.fraction, "missing": rec.missing}, indent=1))
    return 0 if len(rec.on_disk) == len(rec.listed) else 3


def cmd_bidnet(a) -> int:
    from .sources import bidnet_email
    opps = bidnet_email.parse(Path(a.body).read_text(encoding="utf-8"))
    print(json.dumps([o.to_dict() for o in opps], indent=1))
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="rfp_engine")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sweep")
    s.add_argument("--sources", default="sam,grants,canadabuys")
    s.add_argument("--out")
    s.add_argument("--master", help="CSV export of the master data tab (header row first)")
    s.add_argument("--stage", default="")
    s.set_defaults(fn=cmd_sweep)
    m = sub.add_parser("merge")
    m.add_argument("--master", required=True)
    m.add_argument("--staging", required=True)
    m.add_argument("--out", default="append.tsv")
    m.set_defaults(fn=cmd_merge)
    q = sub.add_parser("acquire-sam")
    q.add_argument("notice_id")
    q.add_argument("--dest", required=True)
    for f in ("title", "buyer", "number", "due"):
        q.add_argument(f"--{f}", default="")
    q.set_defaults(fn=cmd_acquire_sam)
    b = sub.add_parser("bidnet-email")
    b.add_argument("body")
    b.set_defaults(fn=cmd_bidnet)
    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
