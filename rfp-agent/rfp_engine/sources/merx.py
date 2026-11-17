"""MERX record classes and URL templates.

MERX needs Pablo's authenticated session, so this module does no fetching. It
classifies an ID, builds both URL candidates, and routes a GC relay record to
CanadaBuys, which is authoritative and free.

Class A, MERX-native:  10-digit IDs starting 40
   https://www.merx.com/private/solicitations/{id}/abstract
Class B, federal relay: 11 to 12 digit IDs starting 227, 444, 443, 430
   https://www.merx.com/private/supplier/solicitations/notice/{id}/abstract
Try both templates; the class is a prior, not a certainty.
"""
from __future__ import annotations

import re

NATIVE = "https://www.merx.com/private/solicitations/{id}/abstract"
RELAY = "https://www.merx.com/private/supplier/solicitations/notice/{id}/abstract"
RELAY_PREFIXES = ("227", "444", "443", "430")


def classify(merx_id: str) -> str:
    i = re.sub(r"\D", "", merx_id or "")
    if len(i) == 10 and i.startswith("40"):
        return "merx-native"
    if 11 <= len(i) <= 12 and i.startswith(RELAY_PREFIXES):
        return "merx-federal-relay"
    return "unknown"


def candidate_urls(merx_id: str) -> list[str]:
    i = re.sub(r"\D", "", merx_id or "")
    cls = classify(i)
    first, second = (RELAY, NATIVE) if cls == "merx-federal-relay" else (NATIVE, RELAY)
    return [first.format(id=i), second.format(id=i)]


def gc_reference(text: str) -> str | None:
    """A cb-{n}-{n} reference or a PWGSC-sourced number routes to CanadaBuys."""
    m = re.search(r"\bcb-\d+-\d+\b", text or "", re.IGNORECASE)
    return m.group(0).lower() if m else None
