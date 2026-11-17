"""Standing keyword sets and lane classification.

Single words and short terms match on portals; some multi-word phrases return
nothing there, so portal queries use the short forms and the local matcher
does the precise work on title plus description.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

CORE = [
    "culture", "organizational development", "change management", "leadership development",
    "strategic planning", "executive coaching", "assessment", "cultural intelligence",
    "intercultural", "DEI", "diversity equity", "workforce", "engagement", "climate survey",
    "compensation study", "executive search", "facilitation", "training", "retreat",
    "leadership", "coaching", "human resources", "human capital", "talent", "learning and development",
    "organizational", "organization transformation", "succession planning", "team building", "inclusion",
    "mediation", "conflict resolution", "program evaluation", "psychological safety", "cultural competency",
    "equal employment opportunity", "EEO", "employee experience", "classification and compensation",
]
BOARD = [
    "board development", "board training", "board coaching", "governance", "board of directors",
    "trustee", "board retreat", "board member", "board effectiveness", "school board",
]
ENGAGEMENT_TYPES = ["fractional", "interim", "embedded", "on-call advisory", "roster", "prequalified", "pre-qualified"]
DIGITAL = [
    "website", "redesign", "intranet", "portal", "digital transformation", "SEO", "branding",
    "AI strategy", "AI adoption", "AI governance", "AI readiness", "artificial intelligence", "chatbot",
    "content management", "WordPress", "user experience",
]

# Portal saved-search themes (10 to 12 per portal), short forms that portals match.
PORTAL_THEMES = {
    "culture-od": ["culture", "organizational development", "organizational assessment"],
    "change": ["change management"],
    "leadership": ["leadership development", "leadership training", "executive coaching"],
    "strategy": ["strategic planning", "strategic plan"],
    "people": ["climate survey", "engagement survey", "compensation study", "executive search"],
    "dei-ci": ["DEI", "cultural intelligence", "intercultural"],
    "facilitation": ["facilitation", "retreat", "training"],
    "board": ["board development", "board training", "governance", "trustee"],
    "fractional": ["fractional", "interim", "on-call", "prequalified"],
    "digital-web": ["website", "redesign", "intranet", "CMS", "WordPress"],
    "digital-ai": ["AI strategy", "AI adoption", "chatbot", "digital transformation"],
    "brand": ["branding", "SEO"],
}

NAICS = ["611430", "541612", "541618", "541611"]

# Terms that turn a keyword hit into noise (equipment, construction, clinical, tactical).
NEGATIVE = [
    "construction", "paving", "roofing", "hvac", "janitorial", "vehicle", "vehicles", "ammunition", "firearm",
    "aircraft", "vessel", "dredging", "asphalt", "medical device", "pharmaceutical", "laboratory", "spectrometer",
    "software license", "hardware", "fuel", "uniforms", "food service", "catering", "rescue training", "coxswain",
    "weapons", "simulator", "flight training", "crane", "forklift", "cdl", "marksmanship", "tactics", "explosives",
    "welding", "parachute", "rigger", "blood", "culture media", "nursing", "physician", "dental", "tccc", "jrotc",
    "rotc", "firefighting", "tractor", "mowers", "furniture", "seating", "timber", "grass cutting", "brush clearing",
    "lidar", "geospatial", "bathymetric", "archaeology", "cables", "trucks", "buses", "generator", "watermain",
    "bridge", "surveillance", "printing services", "translation services", "interpreter", "medicare", "medicaid",
    "accountable care", "intelligence surveillance", "c4isr", "uncrewed", "drone", "satellite", "sole source",
    "notice of intent", "audit services", "financial statement", "valuation", "security services",
    "warhead", "payload", "maintenance support", "contractor maintenance", "littoral", "superfund", "logistics",
    "cybersecurity", "data security", "command and control", "telepathology", "trades training", "safety training",
    "combat", "MDB", "APN", "junior reserve", "industry day", "scholarship", "clinical trial", "clinical trials",
    "career award", "research training", "somatic", "boat maintenance", "construction of", "test and measurement",
]

# Lanes. Engagement-type words modify a real hit; they never qualify a notice alone.
MODIFIERS = {t.lower() for t in ENGAGEMENT_TYPES}
# Single-word or acronym terms that appear in boilerplate ("see our website"); title-only.
TITLE_ONLY = {"website", "redesign", "intranet", "portal", "seo", "branding", "chatbot", "wordpress",
              "culture", "assessment", "training", "engagement", "workforce", "governance", "retreat", "leadership",
              "coaching", "talent", "organizational", "inclusion", "mediation", "EEO",
              "facilitation", "dei", "trustee", "artificial intelligence"}
LANES = {"board": BOARD, "core": CORE + ENGAGEMENT_TYPES, "digital": DIGITAL}


def _compile(term: str) -> re.Pattern:
    words = [re.escape(w) for w in term.split()]
    flags = 0 if term.isupper() else re.IGNORECASE  # acronyms (DEI, SEO, CMS) match case-sensitively
    return re.compile(r"\b" + r"[\s\-]+".join(words) + r"\b", flags)


_COMPILED = {lane: [(t, _compile(t)) for t in terms] for lane, terms in LANES.items()}
_NEG = [(t, _compile(t)) for t in NEGATIVE]
# Weak terms count only alongside an organizational context word.
_WEAK = {"training", "assessment", "engagement", "workforce", "portal", "governance", "culture", "talent",
         "organizational", "inclusion", "user experience"}
_CONTEXT_WORDS = [
    _compile(w) for w in [
        "staff", "employee", "employees", "leadership", "leaders", "managers", "supervisors",
        "organizational", "organization", "team", "teams", "board of directors", "workplace", "personnel",
        "council", "commissioners", "trustees",
    ]
]


@dataclass
class Match:
    lanes: list[str]
    terms: list[str]
    negative: list[str]
    strong: bool

    @property
    def relevant(self) -> bool:
        return self.strong and not self.negative


def match(title: str, description: str = "") -> Match:
    """Classify a notice. Every term may match the title; only multi-word, non-boilerplate
    terms may match the description. Negatives are read from the title only, so a
    description that mentions a vehicle does not sink a leadership contract."""
    title = title or ""
    description = description or ""
    lanes, terms = [], []
    for lane, pats in _COMPILED.items():
        hit = []
        for t, p in pats:
            if p.search(title):
                hit.append(t)
            elif description and " " in t and t.lower() not in TITLE_ONLY and t.lower() not in MODIFIERS and p.search(description):
                hit.append(t)
        if hit:
            lanes.append(lane)
            terms.extend(hit)
    negative = [t for t, p in _NEG if p.search(title)]
    real = [t for t in terms if t.lower() not in MODIFIERS]
    strong_terms = [t for t in real if t.lower() not in _WEAK]
    blob = f"{title} {description}"
    has_context = any(p.search(blob) for p in _CONTEXT_WORDS)
    strong = bool(strong_terms) or (bool(real) and has_context)
    lanes = [l for l in lanes if any(t in LANES[l] and t.lower() not in MODIFIERS for t in terms)]
    return Match(lanes=lanes, terms=sorted(set(terms)), negative=negative, strong=strong)


def primary_lane(m: Match) -> str:
    if "board" in m.lanes:
        return "Board"
    if "core" in m.lanes:
        return "Core"
    if "digital" in m.lanes:
        return "Digital"
    return ""
