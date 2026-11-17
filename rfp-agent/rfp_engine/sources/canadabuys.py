"""CanadaBuys open data: the authoritative free source for every Government of Canada tender.

The HTML search needs JavaScript; the open-data CSV does not. It is UTF-8 with a
byte-order mark, bilingual column names ("title-titre-eng"), and description
fields that contain embedded newlines and quotes, so it must be read with a real
CSV parser over the whole file, never line by line.

Routing rule (control plane 2026-09-17.3): for a GC solicitation CanadaBuys is
the source and MERX or BidNet is only a distributor. Notice pages are
canadabuys.canada.ca/en/tender-opportunities/tender-notice/{reference}.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime
from zoneinfo import ZoneInfo

from .. import http
from ..keywords import match, primary_lane
from ..model import Opportunity
from . import SourceHealth

OPEN_CSV = "https://canadabuys.canada.ca/opendata/pub/openTenderNotice-ouvertAvisAppelOffres.csv"
NOTICE = "https://canadabuys.canada.ca/en/tender-opportunities/tender-notice/{ref}"
ET = ZoneInfo("America/Toronto")


def _col(row: dict, prefix: str) -> str:
    for k, v in row.items():
        if k and k.lstrip("﻿").startswith(prefix):
            return (v or "").strip()
    return ""


def _parse_closing(s: str) -> datetime | None:
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s[:19], fmt)
            # CanadaBuys publishes closing times in Eastern time.
            return dt.replace(tzinfo=ET)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def parse_csv(text: str) -> list[dict]:
    text = text.lstrip("﻿")
    return list(csv.DictReader(io.StringIO(text, newline="")))


def to_opportunity(row: dict) -> Opportunity:
    ref = _col(row, "referenceNumber")
    title = _col(row, "title-titre-eng")
    desc = _col(row, "tenderDescription-descriptionAppelOffres-eng")
    entity = _col(row, "contractingEntityName-nomEntitContractante-eng")
    end_user = _col(row, "endUserEntitiesName-nomEntitesUtilisateurFinal-eng")
    opp = Opportunity(
        title=title,
        buyer=end_user or entity or "Government of Canada",
        source="CanadaBuys",
        source_url=NOTICE.format(ref=ref),
        authoritative_url=NOTICE.format(ref=ref),
        number=_col(row, "solicitationNumber") or ref,
        due=_parse_closing(_col(row, "tenderClosingDate")),
        due_tz="America/Toronto",
        summary=desc[:900],
        notice_type=_col(row, "noticeType-avisType-eng"),
        region=_col(row, "regionsOfDelivery-regionsLivraison-eng"),
        raw_id=ref,
        record_class="gc-canadabuys",
    )
    # Federal Crown buyer: bilingual criteria are usual and not waived. A flag, not a no-bid.
    opp.flags.append("GC_LANGUAGE_SCREEN_REQUIRED")
    if _col(row, "procurementMethod-methodeApprovisionnement-eng").lower().startswith("limited"):
        opp.flags.append("LIMITED_TENDERING")
    if "supply arrangement" in (title + " " + desc).lower() or "standing offer" in (title + " " + desc).lower():
        opp.flags.append("CONTRACT_VEHICLE_CHECK")
    m = match(title, desc)
    opp.lane, opp.matched_terms = primary_lane(m), m.terms
    return opp


def sweep(now: datetime | None = None, text: str | None = None) -> tuple[list[Opportunity], SourceHealth]:
    health = SourceHealth("CanadaBuys")
    if text is None:
        health.queries += 1
        try:
            r = http.get(OPEN_CSV, timeout=180)
            r.raise_for_status()
            r.encoding = "utf-8-sig"
            text = r.text
        except Exception as e:
            health.fail(str(e))
            return [], health
    rows = parse_csv(text)
    health.raw_hits = len(rows)
    out = []
    for row in rows:
        status = _col(row, "tenderStatus-appelOffresStatut-eng").lower()
        if status and status not in ("open", "active"):
            continue
        m = match(_col(row, "title-titre-eng"), _col(row, "tenderDescription-descriptionAppelOffres-eng"))
        if not m.relevant:
            continue
        opp = to_opportunity(row)
        if now and opp.due and opp.due < now:
            continue
        out.append(opp)
    health.relevant = len(out)
    return out, health
