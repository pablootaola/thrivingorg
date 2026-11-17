"""Grants.gov search2 API (public, keyless).

Grants are a separate lane from contracts; rows carry notice_type "Grant" so
the screen can treat eligibility (often nonprofit or government applicants
only) before anything is built.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from .. import http
from ..keywords import PORTAL_THEMES, match, primary_lane
from ..model import Opportunity
from . import SourceHealth

URL = "https://api.grants.gov/v1/api/search2"
ET = ZoneInfo("America/New_York")


def _parse_date(s: str | None) -> datetime | None:
    if not s:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            # Grants.gov close dates are dates; treat as 23:59 Eastern, flagged as unknown time.
            return datetime.strptime(s, fmt).replace(hour=23, minute=59, tzinfo=ET)
        except ValueError:
            pass
    return None


def to_opportunity(h: dict) -> Opportunity:
    opp = Opportunity(
        title=h.get("title", ""),
        buyer=h.get("agency") or h.get("agencyCode", ""),
        source="Grants.gov",
        source_url=f"https://www.grants.gov/search-results-detail/{h.get('id')}",
        number=h.get("number", ""),
        due=_parse_date(h.get("closeDate")),
        due_tz="America/New_York",
        notice_type="Grant " + (h.get("oppStatus") or ""),
        raw_id=str(h.get("id", "")),
        record_class="grant",
    )
    opp.authoritative_url = opp.source_url
    if opp.due:
        opp.flags.append("DEADLINE_TIME_UNKNOWN")
    m = match(opp.title)
    opp.lane, opp.matched_terms = primary_lane(m), m.terms
    return opp


def sweep(themes: dict | None = None, rows: int = 100) -> tuple[list[Opportunity], SourceHealth]:
    themes = themes or PORTAL_THEMES
    health = SourceHealth("Grants.gov")
    seen: dict[str, Opportunity] = {}
    for terms in themes.values():
        for t in terms:
            health.queries += 1
            try:
                d = post_search(t, rows)
            except Exception as e:
                health.fail(f"{t}: {e}")
                continue
            hits = (d.get("data") or {}).get("oppHits") or []
            health.raw_hits += len(hits)
            for h in hits:
                key = str(h.get("id"))
                if key in seen:
                    continue
                m = match(h.get("title", ""))
                if m.relevant:
                    seen[key] = to_opportunity(h)
    health.relevant = len(seen)
    return list(seen.values()), health


def post_search(keyword: str, rows: int = 100) -> dict:
    return http.post_json(URL, {"keyword": keyword, "oppStatuses": "forecasted|posted", "rows": rows})
