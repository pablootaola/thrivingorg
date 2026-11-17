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

from .dedupe import BoardIndex, norm_buyer, similarity
from .scoring import score
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
    state_path = Path(a.state)
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    since = None
    if a.since_last and state.get("sam_last_run"):
        since = datetime.fromisoformat(state["sam_last_run"])
    adapters = {"sam": lambda: sam.sweep(now=now, since=since), "grants": grants.sweep,
                "canadabuys": lambda: canadabuys.sweep(now=now)}
    opps, health = [], []
    for name in a.sources.split(","):
        found, h = adapters[name.strip()]()
        opps.extend(found)
        health.append(h)
        print(f"{h.source}: {h.status} queries={h.queries} raw={h.raw_hits} relevant={h.relevant}", file=sys.stderr)
    alerts = source_alerts(health, state, {"SAM.gov"} if since else set())
    for al in alerts:
        print("ALERT " + al, file=sys.stderr)
    state.setdefault("history", {})
    for h in health:
        hist = state["history"].setdefault(h.source, [])
        hist.append({"at": now.isoformat(), "status": h.status, "raw": h.raw_hits, "relevant": h.relevant})
        del hist[:-14]
    if all(h.status == "HEALTHY" for h in health if h.source == "SAM.gov"):
        state["sam_last_run"] = now.isoformat()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=1))
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
        nb = norm_buyer(o.buyer)
        hist = [r for r in master if nb and similarity(nb, norm_buyer(r.get("buyer", ""))) >= 0.85]
        sc = score(title=o.title, summary=o.summary, buyer=o.buyer, lane=o.lane, notice_type=o.notice_type,
                   flags=o.flags, due=o.due, now=now, value_mid=o.value_mid, board_history=hist)
        o.fit, o.win, o.tier, o.score_summary = sc.fit, sc.win, sc.tier, sc.summary()
        new.append(o)
    new.sort(key=lambda o: (o.tier or "Z", -(o.fit or 0) - (o.win or 0), o.due is None, o.due or now))
    rows = [o.board_row(stage=a.stage or "Verify") for o in new]
    (out / "staging_rows.tsv").write_text(to_tsv(rows), encoding="utf-8")
    (out / "opportunities.json").write_text(json.dumps([o.to_dict() for o in new], indent=1), encoding="utf-8")
    (out / "duplicates.json").write_text(json.dumps(dup, indent=1), encoding="utf-8")
    (out / "health.json").write_text(json.dumps([h.__dict__ for h in health], indent=1), encoding="utf-8")
    lines = [f"# Sweep {now.astimezone(MADRID):%d %b %Y %H:%M %Z}", "",
             f"Master rows compared: {len(master)}. New: {len(new)}. Already on board: {len(dup)}.", "",
             "| Source | Status | Queries | Raw hits | Relevant |", "|---|---|---|---|---|"]
    lines += [f"| {h.source} | {h.status} | {h.queries} | {h.raw_hits} | {h.relevant} |" for h in health]
    lines += ["", "## Alerts", ""] + ([f"- {al}" for al in alerts] or ["- none"])
    if since:
        lines += ["", f"SAM.gov fetched incrementally: notices modified since {since.isoformat()}."]
    lines += ["", "## New rows, by tier (A build now, B read and decide, C screen if capacity allows)", "",
              "| Tier | Fit | Win | Deadline | Lane | Buyer | Number | Title |", "|---|---|---|---|---|---|---|---|"]
    for o in new:
        lines.append(f"| {o.tier} | {o.fit} | {o.win} | {deadline_pair(o.due) or 'not established'} | {o.lane or '?'} | "
                     f"{o.buyer} | {o.number} | [{o.title}]({o.source_url}) |")
    lines += ["", "## Why each score", ""]
    for o in new:
        lines.append(f"- **{o.title}** ({o.buyer}): {o.score_summary} Flags: {', '.join(o.flags) or 'none'}")
    (out / "SWEEP.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(out)
    return 0


def source_alerts(health, state, incremental: set[str] | None = None) -> list[str]:
    """A source that errors, returns nothing, or yields zero relevant rows twice running is an alert.
    Quiet and broken must never look the same."""
    out = []
    hist = state.get("history", {})
    for h in health:
        if h.status != "HEALTHY":
            out.append(f"{h.source} {h.status}: {'; '.join(h.errors[:3])}")
        elif h.raw_hits == 0 and h.source not in (incremental or set()):
            out.append(f"{h.source} returned 0 raw hits: check the endpoint before trusting silence")
        prev = (hist.get(h.source) or [])[-1:] or [None]
        if h.source not in (incremental or set()) and h.relevant == 0 and prev[0] and prev[0].get("relevant") == 0:
            out.append(f"{h.source} has yielded 0 relevant rows two runs in a row: retune or retire")
    return out


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
    from dataclasses import asdict

    from .sources import bidnet_email
    body = Path(a.body).read_text(encoding="utf-8")
    if a.subject or body.lstrip().lower().startswith(("<!doctype", "<html")):
        n = bidnet_email.parse_message(a.subject or "", body_html=body)
        d = asdict(n)
        d["opportunity"] = n.opportunity.to_dict() if n.opportunity else None
        print(json.dumps(d, indent=1))
        return 0
    opps = bidnet_email.parse(body)
    print(json.dumps([o.to_dict() for o in opps], indent=1))
    return 0


def cmd_portal_check(a) -> int:
    from .portals import PORTALS, check, env_names, required_hosts
    if a.list:
        for k, (name, style, base, hosts) in PORTALS.items():
            u, p, t = env_names(k)
            print(f"{k:14} {name} | {u}, {p}, {t} (optional) | {base}")
        print("hosts the environment must allow: " + ", ".join(required_hosts()))
        return 0
    results = check([k.upper() for k in a.keys] or None)
    for r in results:
        print(r)
    return 0 if all(r.status in ("LOGGED_IN", "NEEDS_BROWSER", "MISSING_CREDENTIALS") for r in results) else 1


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="rfp_engine")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sweep")
    s.add_argument("--sources", default="sam,grants,canadabuys")
    s.add_argument("--out")
    s.add_argument("--master", help="CSV export of the master data tab (header row first)")
    s.add_argument("--stage", default="")
    s.add_argument("--since-last", action="store_true", help="SAM.gov: only notices modified since the last healthy run")
    s.add_argument("--state", default="runs/state.json")
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
    b.add_argument("--subject", default="", help="email subject; needed to classify HTML notices")
    b.set_defaults(fn=cmd_bidnet)
    pc = sub.add_parser("portal-check", help="test portal logins from environment variables; prints status only")
    pc.add_argument("keys", nargs="*")
    pc.add_argument("--list", action="store_true", help="list portal keys, variable names and required hosts")
    pc.set_defaults(fn=cmd_portal_check)
    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
