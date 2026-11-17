"""Opportunity record and the 36-column bid board row format.

Board layout (data tab): 28 original cells (A to X), then the value block
(Y to AB: value_low, value_mid, value_high, value_basis), then the comp block
(AC to AJ). New rows are pasted as tab-separated values: exactly 28 cells for
the original block, then the value block, then the comp block. Cells never
contain tabs or newlines and numbers are never apostrophe-prefixed.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

BOARD_COLUMNS = [
    "stage", "opportunity", "number", "buyer", "due", "questions_due", "value", "lane", "source", "warm",
    "Folder", "v_deadline", "v_docs", "v_addenda", "effort_h", "win_pct", "next_action", "outcome",
    "source_url", "summary", "doc_link", "bid_amount", "bid_date", "price_basis",
    "value_low", "value_mid", "value_high", "value_basis",
    "comp_analog", "comp_bids", "comp_low", "comp_mid", "comp_high", "comp_winner", "comp_winner_amt", "comp_source",
]
assert len(BOARD_COLUMNS) == 36
ORIGINAL_BLOCK = BOARD_COLUMNS[:24]  # A..X
VALUE_BLOCK = BOARD_COLUMNS[24:28]  # Y..AB
COMP_BLOCK = BOARD_COLUMNS[28:]  # AC..AJ

MADRID = ZoneInfo("Europe/Madrid")
UTC = ZoneInfo("UTC")


def fmt_date(dt: datetime | None, tz: ZoneInfo | None = None, with_time: bool = True) -> str:
    """DD Mon YYYY, always with the time zone named when a time is shown."""
    if dt is None:
        return ""
    if dt.tzinfo is None:
        raise ValueError("naive datetime refused: deadlines must be offset-aware")
    if tz is not None:
        dt = dt.astimezone(tz)
    if not with_time:
        return dt.strftime("%d %b %Y")
    return dt.strftime("%d %b %Y %H:%M ") + (dt.tzname() or "")


def deadline_pair(dt: datetime | None, source_tz: ZoneInfo | None = None) -> str:
    """Buyer-local deadline plus the Barcelona equivalent."""
    if dt is None:
        return ""
    local = fmt_date(dt, source_tz) if source_tz else fmt_date(dt)
    return f"{local} ({fmt_date(dt, MADRID)} Barcelona)"


def clean_cell(v) -> str:
    if v is None:
        return ""
    s = str(v).replace("\t", " ").replace("\r", " ").replace("\n", " ").strip()
    s = s.replace("—", ", ").replace("–", "-")  # no em or en dashes on the board
    s = s.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    while s.startswith("'"):
        s = s[1:]
    return s


@dataclass
class Opportunity:
    title: str
    buyer: str
    source: str
    source_url: str
    number: str = ""
    due: datetime | None = None
    due_tz: str = ""
    questions_due: datetime | None = None
    summary: str = ""
    lane: str = ""
    notice_type: str = ""
    region: str = ""
    record_class: str = ""  # e.g. merx-native, merx-federal-relay, gc-canadabuys
    authoritative_url: str = ""  # the buyer's own record when traced
    documents: list[dict] = field(default_factory=list)  # {name, url, size}
    flags: list[str] = field(default_factory=list)  # screen flags, never conclusions
    matched_terms: list[str] = field(default_factory=list)
    raw_id: str = ""
    value_low: float | None = None
    value_mid: float | None = None
    value_high: float | None = None
    value_basis: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        for k in ("due", "questions_due"):
            d[k] = d[k].isoformat() if d[k] else ""
        return d

    def board_row(self, stage: str = "New", warm: str = "cold") -> list[str]:
        tz = ZoneInfo(self.due_tz) if self.due_tz else None
        cells = {
            "stage": stage,
            "opportunity": self.title,
            "number": self.number,
            "buyer": self.buyer,
            "due": deadline_pair(self.due, tz),
            "questions_due": deadline_pair(self.questions_due, tz),
            "value": "not published",
            "lane": self.lane,
            "source": self.source,
            "warm": warm,
            "Folder": "",
            "v_deadline": "y" if self.due else "n",
            "v_docs": "y" if self.documents else "n",
            "v_addenda": "n",
            "effort_h": "",
            "win_pct": "",
            "next_action": "Acquire documents and run the 360 read" if self.documents else "Trace to buyer record and acquire documents",
            "outcome": "",
            "source_url": self.authoritative_url or self.source_url,
            "summary": self.summary[:900],
            "doc_link": "",
            "bid_amount": "",
            "bid_date": "",
            "price_basis": "",
            "value_low": _num(self.value_low),
            "value_mid": _num(self.value_mid),
            "value_high": _num(self.value_high),
            "value_basis": self.value_basis,
        }
        row = [clean_cell(cells.get(c, "")) for c in BOARD_COLUMNS]
        return row


def _num(v) -> str:
    if v is None:
        return ""
    return str(int(round(v)))


def to_tsv(rows: list[list[str]]) -> str:
    out = []
    for r in rows:
        if len(r) != 36:
            raise ValueError(f"row has {len(r)} cells, expected 36")
        if any("\t" in c or "\n" in c for c in r):
            raise ValueError("cell contains a tab or newline")
        out.append("\t".join(r))
    return "\n".join(out) + ("\n" if out else "")


def paste_blocks(row: list[str]) -> tuple[str, str]:
    """The legacy board was 28 columns (A..AB, ending at value_basis, so the value
    block Y..AB sits inside the 28). The comp block AC..AJ was added later.
    Returns (A..AB as 28 cells, AC..AJ as 8 cells)."""
    if len(row) != 36:
        raise ValueError("row must have 36 cells")
    return "\t".join(row[:28]), "\t".join(row[28:])
