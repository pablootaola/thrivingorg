"""Fit and win-likelihood scoring with reasons.

Two separate scores, each 0 to 100, because a bid can fit perfectly and still be
unwinnable (an incumbent, a closed vehicle), or be winnable and off-strategy.

  FIT   how well the work matches what the firm sells and can deliver
  WIN   how likely the firm is to win if it bids, given what the notice reveals

Every point added or removed carries a one-line reason, so the score is an
argument, not a verdict. Weights below are a first proposal (17 Nov 2026), not
calibrated: the Weekly outcome loop should refit them from Won, Lost and
Submitted rows once there are enough of them. Detection flags inform the
score; they never conclude a no-bid on their own.

Tiers: A (fit >= 70 and win >= 50) build now; B (fit >= 55 and win >= 35) read
and decide; C everything else, screened only if capacity allows.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from .keywords import MODIFIERS, _WEAK, match

# FIT weights
LANE_STRENGTH = {"Board": 30, "Core": 30, "Digital": 22}
PER_STRONG_TERM = 8  # up to 3 terms
BUYER_TYPES = [  # (pattern, points, reason)
    (r"school district|union free school|unified|community college|college|university|board of education", 8, "education buyer, a core market"),
    (r"county|city of|town of|village of|township|municipal", 6, "local government buyer"),
    (r"nonprofit|foundation|association|alliance|council|society", 8, "nonprofit or association buyer"),
    (r"tribe|tribal|nation\b|band of|first nation|indigenous", 6, "tribal or Indigenous buyer"),
    (r"department of|agency|administration|office of|state of", 3, "state or federal agency"),
]
PRODUCT_SIGNALS = r"\b(software|saas|licen[cs]e|subscription|platform purchase|equipment|hardware|supply and delivery)\b"

# WIN weights
WIN_BASE = 40


@dataclass
class Score:
    fit: int
    win: int
    tier: str
    fit_reasons: list[str] = field(default_factory=list)
    win_reasons: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (f"FIT {self.fit} | WIN {self.win} | tier {self.tier}. Fit: " + "; ".join(self.fit_reasons)
                + ". Win: " + "; ".join(self.win_reasons) + ".")


def _clamp(x: float) -> int:
    return int(max(0, min(100, round(x))))


def score(*, title: str, summary: str = "", buyer: str = "", lane: str = "", notice_type: str = "",
          flags: list[str] | None = None, due: datetime | None = None, now: datetime | None = None,
          value_mid: float | None = None, board_history: list[dict] | None = None,
          min_engagement: float = 7500.0) -> Score:
    flags = flags or []
    text = f"{title} {summary}"
    low = text.lower()
    fr: list[str] = []
    wr: list[str] = []

    # ---------------- FIT ----------------
    fit = 0.0
    m = match(title, summary)
    strong = [t for t in m.terms if t.lower() not in _WEAK and t.lower() not in MODIFIERS]
    if lane in LANE_STRENGTH and m.relevant:
        fit += LANE_STRENGTH[lane]
        fr.append(f"+{LANE_STRENGTH[lane]} {lane} lane")
    pts = min(3, len(strong)) * PER_STRONG_TERM
    if pts:
        fit += pts
        fr.append(f"+{pts} specific terms ({', '.join(strong[:3])})")
    title_hits = match(title).terms
    if any(t.lower() not in _WEAK and t.lower() not in MODIFIERS for t in title_hits):
        fit += 15
        fr.append("+15 the title itself names the service")
    for pat, p, why in BUYER_TYPES:
        if re.search(pat, buyer, re.I):
            fit += p
            fr.append(f"+{p} {why}")
            break
    if any(t.lower() in MODIFIERS for t in m.terms):
        fit += 4
        fr.append("+4 fractional, interim or roster engagement")
    if re.search(PRODUCT_SIGNALS, low):
        fit -= 20
        fr.append("-20 reads as a product or licence purchase")
    if any(f.startswith("LANGUAGE_TIER3") for f in flags):
        fit -= 25
        fr.append("-25 French-language buyer (firm delivers English and Spanish)")
    elif any(f.startswith("LANGUAGE_TIER1") for f in flags):
        fit -= 8
        fr.append("-8 federal Canadian buyer, bilingual criteria likely")
    if any(f.startswith("V:") or f == "CONTRACT_VEHICLE_CHECK" for f in flags):
        fit -= 10
        fr.append("-10 may be limited to holders of a supply arrangement or standing offer")
    if value_mid is not None and value_mid < min_engagement:
        fit -= 10
        fr.append(f"-10 estimated value under the {min_engagement:,.0f} minimum engagement")
    fit = _clamp(fit + 10)  # small floor so a lone strong hit is not scored as zero
    fr.insert(0, "+10 base")

    # ---------------- WIN ----------------
    win = float(WIN_BASE)
    wr.append(f"{WIN_BASE} base")
    nt = (notice_type or "").lower()
    if "sources sought" in nt or "request for information" in low or "rfi" in nt or "PRE_SOLICITATION_NOTICE" in flags:
        win += 10
        wr.append("+10 pre-solicitation: a response shapes the requirement and the buyer list")
    if re.search(r"small business set-aside|total small business|set aside.*small business|52\.219-6", low):
        win += 10
        wr.append("+10 small-business set-aside narrows the field")
    if re.search(r"new requirement|not a follow-on|no incumbent", low):
        win += 8
        wr.append("+8 new requirement, no incumbent")
    if re.search(r"incumbent|follow-on|recompete|re-compete", low) and "no incumbent" not in low:
        win -= 10
        wr.append("-10 incumbent or follow-on")
    if re.search(r"lowest price technically acceptable|\blpta\b|lowest compliant", low):
        win -= 8
        wr.append("-8 lowest-price award; firm prices to value, not to the floor")
    if re.search(r"best value|tradeoff|trade-off", low):
        win += 5
        wr.append("+5 best-value award rewards a differentiated approach")
    if re.search(r"minimum of (\w+ )?\(?\d+\)? (years|similar)|at least (\w+ )?\(?\d+\)? (similar|comparable)", low) \
            or "MINQUAL_PAST_PERFORMANCE?" in flags:
        win -= 8
        wr.append("-8 minimum past-performance requirement to verify")
    if re.search(r"local (vendor|preference|presence)|located within|in-state preference", low):
        win -= 8
        wr.append("-8 local presence or preference")
    if "BOND?" in flags:
        win -= 5
        wr.append("-5 bid or performance bond")
    if now and due:
        days = (due - now).total_seconds() / 86400
        if days < 3:
            win -= 25
            wr.append(f"-25 closes in {days:.1f} days")
        elif days < 10:
            win -= 10
            wr.append(f"-10 closes in {days:.0f} days")
        elif days >= 21:
            win += 5
            wr.append(f"+5 {days:.0f} days to prepare")
    elif not due:
        win -= 5
        wr.append("-5 deadline not established")
    for h in board_history or []:
        st = (h.get("stage") or "").lower()
        if st in ("won",):
            win += 12
            wr.append(f"+12 won before with this buyer ({h.get('opportunity', '')[:40]})")
            break
        if st in ("submitted",):
            win += 5
            wr.append("+5 has bid this buyer before")
            break
        if st in ("lost",):
            win -= 3
            wr.append("-3 lost a previous bid with this buyer; ask for the debrief")
            break
    win = _clamp(win)

    tier = "A" if fit >= 70 and win >= 50 else "B" if fit >= 55 and win >= 35 else "C"
    return Score(fit=fit, win=win, tier=tier, fit_reasons=fr, win_reasons=wr)
