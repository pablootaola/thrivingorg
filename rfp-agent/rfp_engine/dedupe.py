"""Dedupe against the master board.

Pass 1: exact key on normalised solicitation number plus normalised buyer.
Pass 2: fuzzy buyer plus normalised title. This catches the case where an
aggregator carries its own ID and the buyer carries a different reference
number for the same solicitation.
"""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

_STOP_BUYER = {
    "the", "of", "city", "county", "town", "village", "department", "dept", "inc", "llc", "corp",
    "corporation", "district", "office", "state", "government", "board", "and", "for",
}
_STOP_TITLE = {
    "rfp", "rfq", "rfi", "request", "for", "proposal", "proposals", "quote", "quotes", "qualifications",
    "information", "the", "of", "and", "a", "an", "to", "services", "service", "solicitation", "notice",
    "sources", "sought", "invitation", "bid", "itb", "ifb", "soq", "re", "issue", "amended", "amendment",
}


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9 ]+", " ", s.lower())


def norm_number(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def norm_buyer(s: str) -> str:
    toks = [t for t in _fold(s).split() if t not in _STOP_BUYER]
    return " ".join(toks)


def norm_title(s: str) -> str:
    s = re.sub(r"\b\d{2,}[-/]\d+[-/\w]*\b", " ", s or "")  # strip embedded reference numbers
    toks = [t for t in _fold(s).split() if t not in _STOP_TITLE and len(t) > 1]
    return " ".join(toks)


def norm_url(u: str) -> str:
    u = (u or "").strip().lower()
    if not u.startswith("http"):
        return ""
    u = re.sub(r"^https?://(www\.)?", "", u).rstrip("/")
    u = re.sub(r"[?#].*$", "", u)
    # bare portal homepages identify nothing
    return u if "/" in u else ""


def exact_key(number: str, buyer: str) -> str | None:
    n = norm_number(number)
    if not n or len(n) < 3:
        return None
    return f"{n}|{norm_buyer(buyer)}"


def similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    ta, tb = set(a.split()), set(b.split())
    jac = len(ta & tb) / len(ta | tb) if ta | tb else 0.0
    seq = SequenceMatcher(None, a, b).ratio()
    return max(jac, seq)


def containment(a: str, b: str) -> float:
    """1.0 when every token of the shorter title appears in the longer one (min 2 tokens).
    Catches board titles that append a reference, e.g. 'X services (ORG-123/B)'."""
    ta, tb = set(a.split()), set(b.split())
    small, big = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    if len(small) < 2:
        return 0.0
    return 1.0 if small <= big else 0.0


class BoardIndex:
    def __init__(self, rows: list[dict]):
        self.rows = rows
        self.exact: dict[str, int] = {}
        self.fuzzy: list[tuple[str, str, int]] = []
        self.numbers: dict[str, int] = {}
        self.urls: dict[str, int] = {}
        for i, r in enumerate(rows):
            u = norm_url(r.get("source_url", ""))
            if u:
                self.urls.setdefault(u, i)
            k = exact_key(r.get("number", ""), r.get("buyer", ""))
            if k:
                self.exact.setdefault(k, i)
            n = norm_number(r.get("number", ""))
            if len(n) >= 6:
                self.numbers.setdefault(n, i)
            self.fuzzy.append((norm_buyer(r.get("buyer", "")), norm_title(r.get("opportunity", "")), i))

    def find(self, number: str, buyer: str, title: str, source_url: str = "",
             buyer_threshold: float = 0.72, title_threshold: float = 0.80) -> tuple[int | None, str]:
        u = norm_url(source_url)
        if u and u in self.urls:
            return self.urls[u], "exact:source_url"
        k = exact_key(number, buyer)
        if k and k in self.exact:
            return self.exact[k], "exact:number+buyer"
        n = norm_number(number)
        if len(n) >= 6 and n in self.numbers:
            return self.numbers[n], "exact:number"
        nb, nt = norm_buyer(buyer), norm_title(title)
        best, best_i = 0.0, None
        for b, t, i in self.fuzzy:
            bs = similarity(nb, b)
            if bs < buyer_threshold:
                continue
            s = similarity(nt, t)
            if bs >= 0.85:
                s = max(s, containment(nt, t))
            if s > best:
                best, best_i = s, i
        if best_i is not None and best >= title_threshold:
            return best_i, f"fuzzy:buyer+title:{best:.2f}"
        return None, ""
