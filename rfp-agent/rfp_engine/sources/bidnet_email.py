"""Parse BidNet Direct notification emails.

Real BidNet mail (checked 17 Nov 2026) is HTML only. Three kinds arrive:

  new       subject "<Buyer> Has Published a New Solicitation Matching Your Profile";
            body has label/value cell pairs: Solicitation Number, Solicitation Title,
            Buying Organization, Description (truncated), Closing date
            ("01/11/2027 02:00 PM EST"), and an anchor "Link to Solicitation Page".
  addendum  subject "Addendum from BidNet Direct for <Title> solicitation for <Buyer>";
            body "an addendum has been published for the <NUM> - <TITLE> solicitation".
  award     subject "Award(s) Published for <NUM> - <TITLE>";
            body "Award(s) for <NUM> - <TITLE> have been published by <Buyer>".

Every link is a SendGrid click-tracking redirect, not a bidnetdirect.com URL.
The redirect is kept as source_url (it resolves to the solicitation page) and the
row is flagged TRACKING_LINK so the acquirer resolves it before dedupe by URL.

The mailbox is read by an agent with Gmail access (label:RFPs---Thriving-Culture);
this module only parses the subject and HTML (or plain text) it is handed.
"""
from __future__ import annotations

import html as htmllib
import re
from dataclasses import dataclass, field
from datetime import datetime
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

from ..keywords import match, primary_lane
from ..model import Opportunity

_TZ = {"EST": "America/New_York", "EDT": "America/New_York", "ET": "America/New_York",
       "CST": "America/Chicago", "CDT": "America/Chicago", "CT": "America/Chicago",
       "MST": "America/Denver", "MDT": "America/Denver", "MT": "America/Denver",
       "PST": "America/Los_Angeles", "PDT": "America/Los_Angeles", "PT": "America/Los_Angeles",
       "AKST": "America/Anchorage", "HST": "Pacific/Honolulu"}

LABELS = {
    "number": ["solicitation number", "reference number", "bid number"],
    "title": ["solicitation title", "title", "bid title"],
    "buyer": ["buying organization", "agency", "organization", "purchasing agency"],
    "description": ["description"],
    "due": ["closing date", "bid closing date", "due date", "close date"],
    "questions": ["question deadline", "questions due", "question due date"],
}
_LABEL_INDEX = {v: k for k, vs in LABELS.items() for v in vs}


class _Cells(HTMLParser):
    """Collect table cell texts in order and anchors (text, href)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.cells: list[str] = []
        self.anchors: list[tuple[str, str]] = []
        self._buf: list[str] | None = None
        self._a_href: str | None = None
        self._a_text: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("style", "script", "head"):
            self._skip += 1
        if tag == "td":
            self._buf = []
        if tag == "br" and self._buf is not None:
            self._buf.append(" ")
        if tag == "a":
            self._a_href = dict(attrs).get("href", "")
            self._a_text = []

    def handle_endtag(self, tag):
        if tag in ("style", "script", "head") and self._skip:
            self._skip -= 1
        if tag == "td" and self._buf is not None:
            self.cells.append(_clean(" ".join(self._buf)))
            self._buf = None
        if tag == "a" and self._a_href is not None:
            self.anchors.append((_clean(" ".join(self._a_text)), self._a_href))
            self._a_href = None

    def handle_data(self, data):
        if self._skip:
            return
        if self._buf is not None:
            self._buf.append(data)
        if self._a_href is not None:
            self._a_text.append(data)


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", htmllib.unescape(s or "").replace("\xa0", " ")).strip()


def parse_due(s: str) -> tuple[datetime | None, str]:
    s = _clean(s)
    tzname = ""
    m = re.search(r"\b(AKST|HST|[ECMP][SD]?T)\b", s)
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


@dataclass
class Notice:
    kind: str  # new | addendum | award | unknown
    number: str = ""
    title: str = ""
    buyer: str = ""
    link: str = ""
    link_text: str = ""
    opportunity: Opportunity | None = None
    flags: list[str] = field(default_factory=list)


def classify(subject: str) -> str:
    s = (subject or "").lower()
    if "published a new solicitation" in s:
        return "new"
    if s.startswith("addendum") or "addendum" in s:
        return "addendum"
    if "award" in s:
        return "award"
    return "unknown"


def parse_message(subject: str, body_html: str = "", body_text: str = "") -> Notice:
    kind = classify(subject)
    cells, anchors = [], []
    if body_html:
        p = _Cells()
        p.feed(body_html)
        cells, anchors = p.cells, p.anchors
    text = " ".join(cells) if cells else _clean(body_text)
    n = Notice(kind=kind)

    if kind == "new":
        fields: dict[str, str] = {}
        if cells:
            for i, c in enumerate(cells[:-1]):
                key = _LABEL_INDEX.get(c.rstrip(":").strip().lower())
                if key and key not in fields:
                    fields[key] = cells[i + 1]
        else:  # plain-text fallback: "Label: value" lines
            for line in (body_text or "").splitlines():
                m = re.match(r"\s*([A-Za-z ]{3,40}):\s*(.+)$", line)
                if m and m.group(1).strip().lower() in _LABEL_INDEX:
                    fields.setdefault(_LABEL_INDEX[m.group(1).strip().lower()], m.group(2).strip())
        n.number, n.title, n.buyer = fields.get("number", ""), fields.get("title", ""), fields.get("buyer", "")
        if not n.buyer:
            m = re.match(r"(.+?) Has Published a New Solicitation", subject or "")
            n.buyer = m.group(1).strip() if m else ""
        link = next((h for t, h in anchors if "solicitation" in t.lower()), "")
        n.link, n.link_text = link, "Link to Solicitation Page" if link else ""
        due, tz = parse_due(fields.get("due", ""))
        opp = Opportunity(title=n.title, buyer=n.buyer, source="BidNet", source_url=link, number=n.number,
                          due=due, due_tz=tz, summary=fields.get("description", "")[:900], record_class="bidnet-email")
        if fields.get("due") and not due:
            opp.flags.append("DEADLINE_UNPARSED:" + fields["due"])
        if "sendgrid.net" in link:
            opp.flags.append("TRACKING_LINK")
        m = match(opp.title, opp.summary)
        opp.lane, opp.matched_terms = primary_lane(m), m.terms
        if not m.relevant:
            opp.flags.append("OFF_LANE_BY_KEYWORDS")
        n.opportunity = opp
        if not (n.title and link):
            n.flags.append("INCOMPLETE")
    elif kind == "addendum":
        m = re.search(r"addendum has been published for the (.+?) - (.+?) solicitation", text, re.I)
        if m:
            n.number, n.title = m.group(1).strip(), m.group(2).strip()
        m = re.search(r" solicitation for (.+)$", subject or "")
        n.buyer = m.group(1).strip() if m else ""
        a = next(((t, h) for t, h in anchors if "addendum" in t.lower()), None)
        if a:
            n.link_text, n.link = a
        n.flags.append("ADDENDUM_UNREAD")  # an unread addendum stops submission
    elif kind == "award":
        m = re.search(r"Award\(s\) for (.+?) - (.+?) have been published by (.+?)\.?$", text, re.I | re.M)
        if not m:
            m = re.search(r"Award\(s\) for (.+?) - (.+?) have been published by (.+?)\.", text, re.I)
        if m:
            n.number, n.title, n.buyer = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
        a = next(((t, h) for t, h in anchors if "award" in t.lower()), None)
        if a:
            n.link_text, n.link = a
        n.flags.append("AWARD_CHECK_COMPETITOR_PRICES")
    return n


def parse(body: str, received: datetime | None = None) -> list[Opportunity]:
    """Back-compatible entry point for plain-text bodies: returns new-solicitation rows only."""
    out = []
    for chunk in re.split(r"\n\s*(?:-{5,}|={5,}|_{5,})\s*\n", body):
        if not chunk.strip():
            continue
        fields: dict[str, str] = {}
        leftovers = []
        for line in chunk.splitlines():
            m = re.match(r"\s*([A-Za-z][A-Za-z #/]{1,40}?)\s*:\s*(.+?)\s*$", line)
            key = _LABEL_INDEX.get(m.group(1).strip().lower().rstrip("#").strip()) if m else None
            if m and m.group(1).strip().lower() in ("url", "link"):
                key = "url"
            if key and key not in fields:
                fields[key] = m.group(2)
            elif line.strip():
                leftovers.append(line.strip())
        url = fields.get("url") or next(iter(re.findall(r"https?://\S+", chunk)), "")
        if not fields.get("title") or not url:
            continue
        due, tz = parse_due(fields.get("due", ""))
        opp = Opportunity(title=fields["title"], buyer=fields.get("buyer", ""), source="BidNet", source_url=url,
                          number=fields.get("number", ""), due=due, due_tz=tz,
                          summary=" ".join(leftovers)[:900], record_class="bidnet-email")
        if fields.get("due") and not due:
            opp.flags.append("DEADLINE_UNPARSED:" + fields["due"])
        m = match(opp.title, opp.summary)
        opp.lane, opp.matched_terms = primary_lane(m), m.terms
        out.append(opp)
    return out
