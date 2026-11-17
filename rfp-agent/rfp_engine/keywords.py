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
    # added 17 Nov 2026 (Pablo's pop-up answers)
    "strategic plan", "needs assessment", "organizational assessment", "employee engagement",
    "community engagement",
    # Spanish (matching is accent-insensitive)
    "cultura organizacional", "desarrollo de liderazgo", "liderazgo", "planificacion estrategica",
    "plan estrategico", "capacitacion", "desarrollo organizacional", "gestion del cambio",
    "clima laboral", "diversidad e inclusion",
    # fractional, interim and embedded leadership roles (17 Nov 2026)
    "fractional executive", "fractional CHRO", "fractional COO", "fractional CTO", "fractional CIO",
    "fractional chief", "interim executive director", "interim CEO", "interim chief", "interim director",
    "interim HR director", "interim human resources", "acting executive director", "chief people officer",
    "executive director search", "on-call consultant", "consultant pool", "consultant roster",
    "management consulting", "organizational consulting", "operations assessment", "operational assessment",
    "operational efficiency", "organizational efficiency", "process improvement", "business process improvement",
    "operations review", "efficiency study", "organizational review", "organizational structure",
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
    # added 17 Nov 2026: digital accessibility, and branding and storytelling (not advertising or PR)
    "accessibility", "ADA Title II", "WCAG", "storytelling", "brand strategy", "brand identity",
    "employer brand", "employer branding", "internal communications", "culture storytelling",
    # AI, technology architecture and operations (17 Nov 2026)
    "AI implementation", "AI integration", "AI policy", "AI training", "AI literacy", "AI consulting",
    "AI roadmap", "AI assessment", "AI workforce", "responsible AI", "generative AI", "machine learning",
    "chief AI officer", "AI officer", "technology roadmap", "technology strategy", "IT strategy",
    "IT strategic plan", "technology assessment", "IT assessment", "enterprise architecture",
    "technology architecture", "solution architecture", "data strategy", "data governance",
    "systems integration", "digital strategy", "technology modernization", "IT modernization",
    "process automation", "workflow automation", "intelligent automation", "knowledge management",
    "change management technology", "technology adoption", "digital literacy",
]

# Portal saved-search themes (10 to 12 per portal), short forms that portals match.
PORTAL_THEMES = {
    "culture-od": ["culture", "organizational development", "organizational assessment"],
    "change": ["change management"],
    "leadership": ["leadership development", "leadership training", "executive coaching"],
    "strategy": ["strategic planning", "strategic plan"],
    "espanol": ["liderazgo", "capacitacion", "planificacion estrategica", "cultura organizacional"],
    "people": ["climate survey", "engagement survey", "compensation study", "executive search"],
    "dei-ci": ["DEI", "cultural intelligence", "intercultural"],
    "facilitation": ["facilitation", "retreat", "training"],
    "board": ["board development", "board training", "governance", "trustee"],
    "fractional": ["fractional", "interim", "on-call", "prequalified", "interim executive director",
                   "management consulting"],
    "operations": ["process improvement", "operations assessment", "efficiency study", "organizational review"],
    "digital-web": ["website", "redesign", "intranet", "CMS", "WordPress"],
    "digital-ai": ["AI strategy", "AI adoption", "chatbot", "digital transformation", "generative AI",
                   "AI policy", "AI training", "AI governance"],
    "tech-architecture": ["technology roadmap", "IT strategy", "enterprise architecture", "data governance",
                          "technology assessment", "IT modernization"],
    "brand": ["branding", "storytelling", "brand strategy", "SEO"],
    "accessibility": ["accessibility", "ADA Title II", "WCAG"],
    "assessment": ["needs assessment", "organizational assessment", "employee engagement"],
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
    "media buying", "paid media", "advertising campaign", "ad placement", "intercom", "communications system",
    "marine", "standing offer", "offenders", "building automation", "industrial automation",
    "automated external", "license plate", "airborne", "weapon system", "weapons system", "avionics",
]

# Lanes. Engagement-type words modify a real hit; they never qualify a notice alone.
MODIFIERS = {t.lower() for t in ENGAGEMENT_TYPES}
# Single-word or acronym terms that appear in boilerplate ("see our website"); title-only.
TITLE_ONLY = {"website", "redesign", "intranet", "portal", "seo", "branding", "chatbot", "wordpress",
              "culture", "assessment", "training", "engagement", "workforce", "governance", "retreat", "leadership",
              "coaching", "talent", "organizational", "inclusion", "mediation", "EEO", "accessibility", "storytelling",
              "liderazgo", "capacitacion",
              "facilitation", "dei", "trustee", "artificial intelligence"}
LANES = {"board": BOARD, "core": CORE + ENGAGEMENT_TYPES, "digital": DIGITAL}


def _compile(term: str) -> re.Pattern:
    words = [re.escape(w) for w in term.split()]
    flags = 0 if term.isupper() else re.IGNORECASE  # acronyms (DEI, SEO, CMS) match case-sensitively
    return re.compile(r"(?<![A-Za-z0-9])" + r"[\s\-_]+".join(words) + r"(?![A-Za-z0-9])", flags)


_COMPILED = {lane: [(t, _compile(t)) for t in terms] for lane, terms in LANES.items()}
_NEG = [(t, _compile(t)) for t in NEGATIVE]
# Weak terms count only alongside an organizational context word.
_WEAK = {"training", "assessment", "engagement", "workforce", "portal", "governance", "culture", "talent",
         "organizational", "inclusion", "user experience", "accessibility", "capacitacion", "liderazgo",
         "community engagement"}
_CONTEXT_WORDS = [
    _compile(w) for w in [
        "staff", "employee", "employees", "leadership", "leaders", "managers", "supervisors",
        "organizational", "organization", "team", "teams", "board of directors", "workplace", "personnel",
        "council", "commissioners", "trustees", "empleados", "funcionarios", "directivos",
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


def _fold(s: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c))


def match(title: str, description: str = "") -> Match:
    """Classify a notice. Every term may match the title; only multi-word, non-boilerplate
    terms may match the description. Negatives are read from the title only, so a
    description that mentions a vehicle does not sink a leadership contract."""
    title = _fold(title or "")
    description = _fold(description or "")
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
    """Any board hit makes it Board (governance work is its own lane). Otherwise the lane with the
    most non-modifier, non-weak hits; ties go Core, then Digital."""
    if "board" in m.lanes:
        return "Board"
    score = {}
    for lane in ("core", "digital"):
        if lane not in m.lanes:
            continue
        hits = [t for t in m.terms if t in LANES[lane] and t.lower() not in MODIFIERS]
        strong = [t for t in hits if t.lower() not in _WEAK]
        score[lane] = (len(strong), len(hits))
    if not score:
        return ""
    order = {"board": 2, "core": 1, "digital": 0}
    best = max(score, key=lambda l: (score[l], order[l]))
    return {"board": "Board", "core": "Core", "digital": "Digital"}[best]
