"""Staging to master merge, the single writer's logic.

The writer (an agent with Sheets access) does the I/O; this module decides.
Contract:
  1. Refuse to run inside the Board Writer window (00:30 to 01:30 Europe/Madrid).
  2. Re-export the master data tab immediately before computing (caller passes it).
  3. Dedupe every staging row (exact then fuzzy) against master AND against
     rows already accepted in this batch.
  4. Emit the append block as 36-cell rows; verify by re-parsing the TSV.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import datetime, time

from .dedupe import BoardIndex
from .model import BOARD_COLUMNS, MADRID, clean_cell, to_tsv

WINDOW_START = time(0, 30)
WINDOW_END = time(1, 30)


def in_board_writer_window(now: datetime) -> bool:
    if now.tzinfo is None:
        raise ValueError("naive datetime refused")
    t = now.astimezone(MADRID).time()
    return WINDOW_START <= t < WINDOW_END


def rows_from_values(values: list[list[str]]) -> list[dict]:
    """values as returned by Sheets get_values (first row is the header)."""
    if not values:
        return []
    header = [h.strip() for h in values[0]]
    out = []
    for r in values[1:]:
        r = list(r) + [""] * (len(header) - len(r))
        d = dict(zip(header, r))
        if any(v.strip() for v in r[:4]):
            out.append(d)
    return out


def rows_from_csv(text: str) -> list[dict]:
    return rows_from_values(list(csv.reader(io.StringIO(text))))


@dataclass
class MergeResult:
    append: list[list[str]] = field(default_factory=list)
    duplicates: list[dict] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)

    def tsv(self) -> str:
        return to_tsv(self.append)


def plan_merge(master: list[dict], staging: list[dict], now: datetime) -> MergeResult:
    if in_board_writer_window(now):
        raise RuntimeError("Merge refused: 00:30 to 01:30 Europe/Madrid is the Board Writer window")
    idx = BoardIndex(master)
    res = MergeResult()
    accepted: list[dict] = []
    for s in staging:
        title, buyer, number = s.get("opportunity", ""), s.get("buyer", ""), s.get("number", "")
        if not title.strip() or not buyer.strip():
            res.rejected.append({"row": s, "reason": "missing opportunity or buyer"})
            continue
        i, how = idx.find(number, buyer, title, s.get("source_url", ""))
        if i is not None:
            res.duplicates.append({"staging": title, "buyer": buyer, "master_row": i + 2, "match": how})
            continue
        batch = BoardIndex(accepted)
        j, how = batch.find(number, buyer, title, s.get("source_url", ""))
        if j is not None:
            res.duplicates.append({"staging": title, "buyer": buyer, "batch_row": j, "match": "in-batch " + how})
            continue
        row = [clean_cell(s.get(c, "")) for c in BOARD_COLUMNS]
        res.append.append(row)
        accepted.append(s)
    verify_tsv(res.tsv(), len(res.append))
    return res


def verify_tsv(tsv: str, expected_rows: int) -> None:
    rows = [l.split("\t") for l in tsv.splitlines() if l]
    if len(rows) != expected_rows:
        raise AssertionError(f"TSV has {len(rows)} rows, expected {expected_rows}")
    for n, r in enumerate(rows, 1):
        if len(r) != 36:
            raise AssertionError(f"TSV row {n} has {len(r)} cells")
        if any(c.startswith("'") for c in r):
            raise AssertionError(f"TSV row {n} has an apostrophe-prefixed cell")
