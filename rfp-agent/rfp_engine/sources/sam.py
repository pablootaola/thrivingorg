"""SAM.gov through its public, keyless endpoints (the same ones sam.gov's own pages call).

Search:      /api/prod/sgs/v1/search/?index=opp&q=...&is_active=true
Notice:      /api/prod/opps/v2/opportunities/{noticeId}
Attachments: /api/prod/opps/v3/opportunities/{noticeId}/resources
Download:    /api/prod/opps/v3/opportunities/resources/files/{resourceId}/download
Human page:  https://sam.gov/opp/{noticeId}/view

No API key is needed for public notices. Following a notice (the SAM follow
rule) still needs Pablo's logged-in session; this adapter only builds the
follow-link queue and never claims a notice as Followed.
"""
from __future__ import annotations

import re
from datetime import datetime

from .. import http
from ..keywords import NAICS, PORTAL_THEMES, match, primary_lane
from ..model import Opportunity
from . import SourceHealth

BASE = "https://sam.gov/api/prod"
SKIP_TYPES = {"Award Notice", "Justification", "Sale of Surplus Property", "Intent to Bundle Requirements (DoD-Funded)"}


def notice_url(notice_id: str) -> str:
    return f"https://sam.gov/opp/{notice_id}/view"


def _strip_html(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or "")).strip()


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def to_opportunity(r: dict) -> Opportunity:
    org = r.get("organizationHierarchy") or []
    buyer = " / ".join(o.get("name", "") for o in org[:3] if o.get("name")) or "Federal agency"
    desc = " ".join(_strip_html(d.get("content", "")) for d in (r.get("descriptions") or []))
    opp = Opportunity(
        title=(r.get("title") or "").strip(),
        buyer=buyer,
        source="SAM.gov",
        source_url=notice_url(r["_id"]),
        authoritative_url=notice_url(r["_id"]),
        number=r.get("solicitationNumber") or "",
        due=_parse_dt(r.get("responseDate")),
        due_tz=r.get("responseTimeZone") or "",
        summary=desc[:900],
        notice_type=(r.get("type") or {}).get("value", ""),
        raw_id=r["_id"],
        record_class="sam-public",
    )
    m = match(opp.title, desc)
    opp.lane = primary_lane(m)
    opp.matched_terms = m.terms
    if opp.notice_type in ("Sources Sought", "Special Notice", "Presolicitation"):
        opp.flags.append("PRE_SOLICITATION_NOTICE")
    return opp


def search(q: str | None = None, naics: str | None = None, size: int = 100, max_pages: int = 3) -> list[dict]:
    out = []
    for page in range(max_pages):
        params = {"index": "opp", "page": page, "size": size, "mode": "search",
                  "sort": "-modifiedDate", "is_active": "true"}
        if q:
            params["q"] = q
        if naics:
            params["naics"] = naics
        r = http.get(f"{BASE}/sgs/v1/search/", params=params)
        r.raise_for_status()
        d = r.json()
        res = (d.get("_embedded") or {}).get("results") or []
        out.extend(res)
        pg = d.get("page") or {}
        if page + 1 >= min(pg.get("totalPages", 0), max_pages) or not res:
            break
    return out


def attachments(notice_id: str) -> list[dict]:
    r = http.get(f"{BASE}/opps/v3/opportunities/{notice_id}/resources",
                 params={"excludeDeleted": "true", "withScanResult": "false"})
    r.raise_for_status()
    lists = ((r.json().get("_embedded") or {}).get("opportunityAttachmentList") or [])
    docs = []
    for l in lists:
        for a in l.get("attachments") or []:
            if a.get("deletedFlag") == "1":
                continue
            if a.get("type") == "link":
                docs.append({"name": a.get("name") or a.get("uri", ""), "url": a.get("uri", ""),
                             "size": None, "access": a.get("accessLevel", ""), "kind": "link"})
                continue
            docs.append({
                "name": a.get("name", ""),
                "url": f"{BASE}/opps/v3/opportunities/resources/files/{a['resourceId']}/download",
                "size": a.get("size"),
                "access": a.get("accessLevel", ""),
                "posted": a.get("postedDate", ""),
                "kind": "file",
            })
    return docs


def sweep(themes: dict | None = None, naics_codes: list[str] | None = None,
          now: datetime | None = None) -> tuple[list[Opportunity], SourceHealth]:
    themes = themes or PORTAL_THEMES
    naics_codes = naics_codes if naics_codes is not None else NAICS
    health = SourceHealth("SAM.gov")
    seen: dict[str, Opportunity] = {}
    queries = [("q", t) for terms in themes.values() for t in terms] + [("naics", n) for n in naics_codes]
    for kind, val in queries:
        health.queries += 1
        try:
            results = search(q=val if kind == "q" else None, naics=val if kind == "naics" else None)
        except Exception as e:  # network or schema change
            health.fail(f"{kind}={val}: {e}")
            continue
        health.raw_hits += len(results)
        for r in results:
            if r.get("isCanceled") or not r.get("isActive", True):
                continue
            if (r.get("type") or {}).get("value") in SKIP_TYPES:
                continue
            if r["_id"] in seen:
                continue
            opp = to_opportunity(r)
            if now and opp.due and opp.due < now:
                continue
            pub = _parse_dt(r.get("publishDate"))
            if now and not opp.due and pub and (now - pub).days > 365:
                continue  # stale notice still flagged active, no response date
            if not opp.due:
                opp.flags.append("NO_RESPONSE_DATE")
            m = match(opp.title, opp.summary)
            if m.relevant:
                if kind == "naics":
                    opp.flags.append(f"NAICS_{val}")
                seen[r["_id"]] = opp
    health.relevant = len(seen)
    return list(seen.values()), health
