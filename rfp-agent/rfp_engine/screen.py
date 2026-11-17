"""Intake screens. Detection only: a detection string triggers a screen and never
concludes it. Conclusions need the primary document read (screen 1 passes) and,
for any no-bid, the yes-second-pass. Code strings match the governing gate file.

Order: Screen 0 access, then intake V/P/M and LANGUAGE, then go/no-go 1..12.
One code per row; the earliest screen wins. PRICE is never written on a row
that failed screen 1.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

# Go/no-go screens 1..12 and their codes.
GO_NO_GO = {
    1: "UNREAD", 2: "UNREAD-ADD", 3: "NOFIT", 4: "MINQUAL", 5: "GEO", 6: "STAFFING", 7: "REFERENCES",
    8: "DEADLINE-3P", 9: "QUESTIONS-OPEN", 10: "REGISTRATION", 11: "PRICE", 12: "HUMAN-NOGO",
}
SOFT = {"QUESTIONS-OPEN", "PRICE"}
OTHER_CODES = {"DEADLINE-PASSED", "CONFLICT", "DUPLICATE", "REOPENED", "EXPIRED", "BOND", "LANGUAGE",
               "PAYWALL", "UNREACHABLE", "INELIGIBLE_CONTRACT_VEHICLE", "SCOPE_MISMATCH_PRODUCT_LOWEST_PRICE",
               "SUBMISSION_MECHANICS_LEAD_TIME"}

_VEHICLE = [r"open only to", r"supply arrangement holders", r"standing offer holders", r"qualified suppliers under",
            r"E60ZT-18TSPS", r"selective tendering", r"invited bidders only", r"pre-qualified list", r"closed competition"]
_PRODUCT = [r"software as a service", r"\bsaas\b", r"\blicen[cs]e\b", r"\bsubscription\b", r"provision of a platform", r"81111901"]
_LOWEST = [r"selection criteria:\s*lowest price", r"lowest compliant bid", r"lowest price"]
_LANG = [r"\bbilingual\b", r"\bfrench\b", r"official languages", r"both official languages"]
_TIER3_REGIONS = [r"quebec", r"qu[eé]bec", r"new brunswick"]
_PAY = [r"\$\s?\d+[\d,.]*\s*(?:fee|charge)\s*(?:for|to)\s*(?:plans|documents|specifications)",
        r"non-refundable (?:fee|deposit) for (?:the )?(?:bid )?documents", r"purchase (?:the )?(?:bid )?documents",
        r"documents (?:are|may be) purchased"]
_BOND = [r"bid bond", r"performance bond", r"bid security"]
_REGISTRATION = [r"must be registered", r"registration (?:is )?required", r"vendor registration"]
_PAST_PERF = [r"minimum of (?:\w+ )?\(?\d+\)? (?:years|similar|comparable)", r"at least (?:\w+ )?\(?\d+\)? (?:similar|comparable) (?:projects|contracts|engagements)"]


def _hits(pats, text):
    return [p for p in pats if re.search(p, text, re.IGNORECASE)]


@dataclass
class ScreenResult:
    flags: list[str] = field(default_factory=list)
    code: str = ""  # a conclusion, only when the evidence allows one
    evidence: list[str] = field(default_factory=list)
    coverage: str = "0/0"

    def add(self, flag: str, ev: str = ""):
        if flag not in self.flags:
            self.flags.append(flag)
        if ev:
            self.evidence.append(f"{flag}: {ev}")


def intake(text: str, *, buyer: str = "", region: str = "", is_gc: bool = False, due: datetime | None = None,
           now: datetime | None = None, primary_read: bool = False, addenda_listed: int = 0, addenda_read: int = 0,
           docs_listed: int = 0, docs_read: int = 0) -> ScreenResult:
    """Run every detection screen over the text the worker actually holds.

    primary_read False forces code UNREAD: nothing after screen 1 concludes.
    """
    r = ScreenResult(coverage=f"{docs_read}/{docs_listed}")
    t = text or ""
    if now and due and due < now:
        r.code = "DEADLINE-PASSED"
        return r
    if h := _hits(_PAY, t):
        r.add("ACCESS_PAYMENT_CHECK", h[0])  # Screen 0 detection; PAYWALL only after the recovery ladder
    if h := _hits(_VEHICLE, t):
        r.add("V:INELIGIBLE_CONTRACT_VEHICLE?", h[0])
    if _hits(_PRODUCT, t) and _hits(_LOWEST, t):
        r.add("P:SCOPE_MISMATCH_PRODUCT_LOWEST_PRICE?", "product and lowest-price signals both present")
    lang = _hits(_LANG, t)
    if is_gc or lang or _hits(_TIER3_REGIONS, region + " " + buyer):
        tier = 3 if _hits(_TIER3_REGIONS, region + " " + buyer) else (1 if is_gc else 2)
        r.add(f"LANGUAGE_TIER{tier}", lang[0] if lang else "buyer class")
    if h := _hits(_BOND, t):
        r.add("BOND?", h[0])
    if h := _hits(_REGISTRATION, t):
        r.add("REGISTRATION?", h[0])
    if h := _hits(_PAST_PERF, t):
        r.add("MINQUAL_PAST_PERFORMANCE?", h[0])
    if due and now and due - now < timedelta(hours=72):
        r.add("DEADLINE_SAFETY_72H")
    if not primary_read:
        r.code = "UNREAD"
    elif addenda_listed > addenda_read:
        r.code = "UNREAD-ADD"  # stops submission, never the build
    return r


def normalise_stage(stage: str) -> str:
    """Board stages are spelled several ways. Map case variants to one form for counting only;
    never rewrite the board's own values without a ruling."""
    s = (stage or "").strip()
    table = {"pursue": "Pursue", "no-bid": "No-bid", "watch": "Watch", "no_bid": "No-bid"}
    return table.get(s.lower(), s)


LIVE_EXCLUDED = {"Expired", "No-bid", "Lost", "Won", "Duplicate", "Bad data", "Needs investigation"}


def is_live(stage: str) -> bool:
    return normalise_stage(stage) not in LIVE_EXCLUDED
