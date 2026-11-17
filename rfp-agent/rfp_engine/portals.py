"""Portal logins from environment variables. Values are read at run time and never
printed, logged, written to disk or returned.

Variable names, per portal key K (upper case):
  K_USERNAME, K_PASSWORD, and optionally K_TOTP_SECRET (the authenticator setup key,
  base32). Pablo pastes the values into the cloud environment settings himself.

MERX and BidNet Direct run on the same platform (mdf commerce): a form posting
j_username, j_password and a per-session _csrf token to /public/authentication/login.
They log in with a plain HTTP session, no browser. Portals behind JavaScript sign-in
or single sign-on (Login.gov, Bonfire, OpenGov and others) use portals/login.js.

Stop conditions, always: a CAPTCHA, a push or SMS approval, a terms page, or an
account-lockout warning. The run reports and stops; it never works around them.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import struct
import time
from dataclasses import dataclass

import requests

from . import USER_AGENT

# key -> (display name, login style, home or login URL, hosts the environment must allow)
PORTALS = {
    "MERX": ("MERX", "mdf", "https://www.merx.com", ["www.merx.com"]),
    "BIDNET": ("BidNet Direct (also Rocky Mountain E-Purchasing and MITN)", "mdf", "https://www.bidnetdirect.com",
               ["www.bidnetdirect.com"]),
    "LOGINGOV": ("Login.gov (SAM.gov, Grants.gov)", "logingov", "https://secure.login.gov",
                 ["secure.login.gov", "login.gov", "sam.gov"]),
    "CANADABUYS": ("CanadaBuys", "browser", "https://canadabuys.canada.ca", ["canadabuys.canada.ca"]),
    "BONFIRE": ("Bonfire", "browser", "https://bonfirehub.com/login", ["bonfirehub.com"]),
    "OPENGOV": ("OpenGov Procurement", "browser", "https://procurement.opengov.com/login", ["procurement.opengov.com"]),
    "COLORADO_VSS": ("Colorado vendor self service", "browser", "https://osc.colorado.gov/spco", ["osc.colorado.gov"]),
    "NYC_PASSPORT": ("NYC PASSPort", "browser", "https://passport.cityofnewyork.us", ["passport.cityofnewyork.us"]),
    "GOVTRIBE": ("GovTribe", "browser", "https://govtribe.com/login", ["govtribe.com"]),
    "PLANETBIDS": ("PlanetBids", "browser", "https://www.planetbids.com", ["www.planetbids.com", "pbsystem.planetbids.com"]),
    "IONWAVE_WDM": ("Ionwave, West Des Moines", "browser", "https://westdesmoines.ionwave.net", ["westdesmoines.ionwave.net"]),
    "ONTARIO": ("Ontario Tenders Portal", "browser", "https://ontariotenders.app.jaggaer.com", ["ontariotenders.app.jaggaer.com"]),
    "BCBID": ("BC Bid (BCeID)", "browser", "https://bcbid.gov.bc.ca", ["bcbid.gov.bc.ca", "www.bceid.ca", "logon7.gov.bc.ca"]),
    "ALBERTA_APC": ("Alberta Purchasing Connection", "browser", "https://purchasing.alberta.ca", ["purchasing.alberta.ca"]),
    "SASKTENDERS": ("SaskTenders", "browser", "https://sasktenders.ca", ["sasktenders.ca"]),
    "OREGONBUYS": ("OregonBuys", "browser", "https://oregonbuys.gov", ["oregonbuys.gov"]),
    "LABAVN": ("LABAVN (Los Angeles)", "browser", "https://www.labavn.org", ["www.labavn.org"]),
    "CALGARY": ("City of Calgary supplier portal", "browser", "https://www.calgary.ca", ["www.calgary.ca"]),
    "WASHTENAW": ("Washtenaw County bids", "browser", "https://www.washtenaw.org/bids.aspx", ["www.washtenaw.org"]),
    "DEMANDSTAR": ("DemandStar (one free agency)", "browser", "https://www.demandstar.com", ["www.demandstar.com"]),
}

STOP_PATTERNS = re.compile(
    r"captcha|recaptcha|hcaptcha|are you a robot|verify you are human|account (is )?locked|too many (failed )?attempts|"
    r"terms (of use|and conditions).{0,40}(accept|agree)|approve (the )?sign.?in on your (phone|device)|push notification",
    re.I)


def env_names(key: str) -> tuple[str, str, str]:
    return f"{key}_USERNAME", f"{key}_PASSWORD", f"{key}_TOTP_SECRET"


def has_credentials(key: str) -> bool:
    u, p, _ = env_names(key)
    return bool(os.environ.get(u)) and bool(os.environ.get(p))


def totp(secret_b32: str, at: float | None = None, step: int = 30, digits: int = 6) -> str:
    """RFC 6238 one-time code from an authenticator setup key."""
    key = base64.b32decode(re.sub(r"\s+", "", secret_b32).upper() + "=" * (-len(re.sub(r"\s+", "", secret_b32)) % 8))
    counter = int((time.time() if at is None else at) // step)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    off = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[off:off + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(code).zfill(digits)


@dataclass
class LoginResult:
    portal: str
    status: str  # LOGGED_IN, FAILED, STOPPED, MISSING_CREDENTIALS, NEEDS_BROWSER, ERROR
    detail: str = ""

    def __str__(self) -> str:  # never contains a secret
        return f"{self.portal}: {self.status}" + (f" ({self.detail})" if self.detail else "")


def _csrf(html: str) -> str | None:
    m = re.search(r'id="loginWindowForm".*?name="_csrf"\s+value="([0-9A-Fa-f]+)"', html, re.S)
    return m.group(1) if m else None


def login_mdf(key: str, base: str, session: requests.Session | None = None) -> tuple[LoginResult, requests.Session | None]:
    """MERX or BidNet Direct. Returns a logged-in session or a result explaining why not."""
    u, p, _ = env_names(key)
    if not has_credentials(key):
        return LoginResult(key, "MISSING_CREDENTIALS", f"set {u} and {p} in the environment settings"), None
    s = session or requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    try:
        home = s.get(base, timeout=60)
        token = _csrf(home.text)
        if not token:
            return LoginResult(key, "ERROR", "login form not found on the home page; layout may have changed"), None
        r = s.post(f"{base}/public/authentication/login",
                   data={"j_username": os.environ[u], "j_password": os.environ[p], "_csrf": token},
                   timeout=60, allow_redirects=True)
    except requests.RequestException as e:
        return LoginResult(key, "ERROR", type(e).__name__), None
    text = r.text or ""
    if STOP_PATTERNS.search(text):
        return LoginResult(key, "STOPPED", "the site asked for a CAPTCHA, approval, terms or reported a lockout"), None
    if re.search(r"j_password", text) and re.search(r"(invalid|incorrect|error).{0,60}(user|password|credential)", text, re.I):
        return LoginResult(key, "FAILED", "the site rejected the username or password"), None
    # A logged-in page offers logout and no longer shows the login form.
    if re.search(r"logout|log out|sign out|/private/", text, re.I) and "loginBox_j_password" not in text:
        return LoginResult(key, "LOGGED_IN"), s
    return LoginResult(key, "FAILED", f"no logged-in marker after login (landed on {r.url.split('?')[0]})"), None


def check(keys: list[str] | None = None) -> list[LoginResult]:
    out = []
    for key in keys or list(PORTALS):
        name, style, base, _ = PORTALS[key]
        if style == "mdf":
            res, _s = login_mdf(key, base)
            out.append(res)
        elif not has_credentials(key):
            u, p, _ = env_names(key)
            out.append(LoginResult(key, "MISSING_CREDENTIALS", f"set {u} and {p}"))
        else:
            out.append(LoginResult(key, "NEEDS_BROWSER", "run: node portals/login.js " + key))
    return out


def required_hosts() -> list[str]:
    return sorted({h for *_x, hosts in PORTALS.values() for h in hosts})
