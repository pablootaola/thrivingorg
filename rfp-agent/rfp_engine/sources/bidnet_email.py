"""Parse BidNet Direct notification emails into opportunities.

BidNet notices carry the full solicitation record in the email body. The
mailbox is read by an agent with Gmail access (search label:RFPs---Thriving-Culture,
hyphen form); this module only parses the plain-text body it is handed.

The parser is tolerant: it reads "Label: value" pairs, accepts the common label
variants BidNet has used, and splits digest emails that hold several notices.
Anything it cannot place is kept in summary for the human or agent reader.
"""
from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from ..keywords import match, primary_lane
from ..model import Opportunity

LABELS = {
    "title": ["title", "solicitation title", "bid title", "opportunity title", "name"],
    "number": ["solicitation number", "reference number", "bid number", "solicitation #", "reference #", "number"],
    "buyer": ["agency", "organization", "purchasing agency", "issuing organization", "buyer"],
    "due": ["closing date", "bid closing date", "due date", "closing", "close date"],
    "questions": ["question deadline", "questions due", "question due date"],
    "url": ["url", "link", "view solicitation", "view bid"],
    "location": ["location", "state", "region"],
    "category": ["category", "categories"],
}
_LABEL_RE = re.compile(r"^\s*([A-Za-z][A-Za-z #/]{1,40}?)\s*:\s*(.+?)\s*$")
_URL_RE = re.compile(r"https?://[^\s<>\"]*bidnetdirect\.com[^\s<>\"]*", re.IGNORECASE)
_TZ = {"EST": "America/New_York", "EDT": "America/New_York", "ET": "America/New_York",
       "CST": "America/Chicago", "CDT": "America/Chicago", "CT": "America/Chicago",
       "MST": "America/Denver", "MDT": "America/Denver", "MT": "America/Denver",
       "PST": "America/Los_Angeles", "PDT": "America/Los_Angeles", "PT": "America/Los_Angeles"}


def _canon(label: str) -> str | None:
    l = label.strip().lower().rstrip("#").strip()
    for k, variants in LABELS.items():
        if l in variants:
            return k
    return None


def parse_due(s: str) -> tuple[datetime | None, str]:
    s = s.strip()
    tzname = ""
    m = re.search(r"\b([ECMP][SD]?T)\b", s)
    if m:
        tzname = _TZ.get(m.group(1), "")
        s = s.replace(m.group(0), "").strip()
    for fmt in ("%m/%d/%Y %I:%M %p", "%m/%d/%Y %I:%M%p", "%m/%d/%Y %H:%M", "%b %d, %Y %I:%M %p",
                "%B %d, %Y %I:%M %p", "%m/%d/%Y", "%b %d, %Y", "%B %d, %Y", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s, fmt)
        except ValueError:
            continue
        if tzname:
            return dt.replace(tzinfo=ZoneInfo(tzname)), tzname
        return None, ""  # time zone unknown: refuse to invent one
    return None, tzname


def split_notices(body: str) -> list[str]:
    parts = re.split(r"\n\s*(?:-{5,}|={5,}|_{5,})\s*\n", body)
    return [p for p in parts if p.strip()]


def parse(body: str, received: datetime | None = None) -> list[Opportunity]:
    out = []
    for chunk in split_notices(body):
        fields: dict[str, str] = {}
        leftovers = []
        for line in chunk.splitlines():
            m = _LABEL_RE.match(line)
            key = _canon(m.group(1)) if m else None
            if key and key not in fields:
                fields[key] = m.group(2)
            elif line.strip():
                leftovers.append(line.strip())
        url = fields.get("url") or next(iter(_URL_RE.findall(chunk)), "")
        if not fields.get("title") or not url:
            continue
        due, tz = parse_due(fields.get("due", ""))
        opp = Opportunity(
            title=fields["title"],
            buyer=fields.get("buyer", ""),
            source="BidNet",
            source_url=url,
            number=fields.get("number", ""),
            due=due,
            due_tz=tz,
            summary=" ".join(leftovers)[:900],
            region=fields.get("location", ""),
            record_class="bidnet-email",
        )
        if fields.get("due") and not due:
            opp.flags.append("DEADLINE_UNPARSED:" + fields["due"])
        if "member agency" not in chunk.lower():
            opp.flags.append("BIDNET_TIER_CHECK")  # State and Local rows may be paywalled
        m = match(opp.title, f"{opp.summary} {fields.get('category', '')}")
        opp.lane, opp.matched_terms = primary_lane(m), m.terms
        out.append(opp)
    return out
