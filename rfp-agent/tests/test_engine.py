import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from rfp_engine import keywords
from rfp_engine.dedupe import BoardIndex, norm_title
from rfp_engine.merge import in_board_writer_window, plan_merge, rows_from_values
from rfp_engine.model import BOARD_COLUMNS, Opportunity, fmt_date, paste_blocks, to_tsv
from rfp_engine.pricing import Plan, decide, value_estimate
from rfp_engine.screen import intake, is_live
from rfp_engine.sources import bidnet_email, canadabuys, merx, sam

FX = Path(__file__).parent / "fixtures"
MAD = ZoneInfo("Europe/Madrid")


def test_keywords_strong_and_negative():
    assert keywords.match("Leadership development and executive coaching for county managers").relevant
    assert not keywords.match("Small craft coxswain and rescue training").relevant
    assert not keywords.match("Annual training").strong  # weak term, no org context
    assert keywords.match("Annual training for staff supervisors").strong
    m = keywords.match("Board of Directors governance retreat facilitation")
    assert keywords.primary_lane(m) == "Board"
    assert keywords.primary_lane(keywords.match("Website redesign and CMS migration")) == "Digital"


def test_date_format_requires_tz():
    dt = datetime(2026, 12, 1, 12, 0, tzinfo=ZoneInfo("America/New_York"))
    assert fmt_date(dt, MAD) == "01 Dec 2026 18:00 CET"
    with pytest.raises(ValueError):
        fmt_date(datetime(2026, 12, 1))


def test_board_row_shape_and_cleaning():
    o = Opportunity(title="Culture assessment — phase 1\tx", buyer="City of X", source="SAM.gov",
                    source_url="https://sam.gov/opp/abc/view", number="'123")
    row = o.board_row()
    assert len(row) == 36 == len(BOARD_COLUMNS)
    assert "—" not in row[1] and "\t" not in row[1]
    assert row[2] == "123"
    a, c = paste_blocks(row)
    assert len(a.split("\t")) == 28 and len(c.split("\t")) == 8
    assert to_tsv([row]).count("\t") == 35


def test_dedupe_exact_fuzzy_and_url():
    master = [
        {"opportunity": "RFP 2026-14 Organizational Culture Assessment Services", "number": "2026-14",
         "buyer": "City of Loveland", "source_url": "https://www.bidnetdirect.com/x/123"},
    ]
    idx = BoardIndex(master)
    assert idx.find("2026 14", "Loveland City", "anything")[1] == "exact:number+buyer"
    assert idx.find("BN-998877", "City of Loveland", "Organizational Culture Assessment Services")[0] == 0
    assert idx.find("", "Other", "x", "https://bidnetdirect.com/x/123/")[1] == "exact:source_url"
    assert idx.find("777", "Town of Elsewhere", "Paving")[0] is None
    idx2 = BoardIndex([{"opportunity": "Client facilitation services (NRCan-5000075549/B)", "number": "22785012593",
                        "buyer": "Department of Natural Resources (NRCan)"}])
    assert idx2.find("5000099999", "Department of Natural Resources (NRCan)", "Client facilitation services")[0] == 0
    assert norm_title("RFP 26-1563 Organizational Development") == "organizational development"


def test_merge_window_and_plan():
    assert in_board_writer_window(datetime(2026, 11, 18, 0, 45, tzinfo=MAD))
    assert not in_board_writer_window(datetime(2026, 11, 18, 1, 30, tzinfo=MAD))
    header = BOARD_COLUMNS
    master = rows_from_values([header, ["Pursue", "Board training", "A1", "County of Y"] + [""] * 32])
    staging = [dict(zip(header, ["Discovered", "Board training", "A1", "Y County"] + [""] * 32)),
               dict(zip(header, ["Discovered", "Strategic plan facilitation", "Q-9", "Town Z"] + [""] * 32)),
               dict(zip(header, ["Discovered", "Strategic plan facilitation", "Q-9", "Town Z"] + [""] * 32))]
    res = plan_merge(master, staging, datetime(2026, 11, 18, 3, 0, tzinfo=MAD))
    assert len(res.append) == 1 and len(res.duplicates) == 2
    with pytest.raises(RuntimeError):
        plan_merge(master, staging, datetime(2026, 11, 18, 1, 0, tzinfo=MAD))


def test_sam_fixture_parse():
    d = json.loads((FX / "sam_search.json").read_text())
    o = sam.to_opportunity(d["_embedded"]["results"][0])
    assert o.source_url.startswith("https://sam.gov/opp/") and o.due.tzinfo is not None


def test_canadabuys_csv_multiline_and_bom():
    csv_text = ('﻿"title-titre-eng","referenceNumber-numeroReference","solicitationNumber-numeroSollicitation",'
                '"tenderClosingDate-appelOffresDateCloture","tenderStatus-appelOffresStatut-eng",'
                '"contractingEntityName-nomEntitContractante-eng","tenderDescription-descriptionAppelOffres-eng"\n'
                '"Leadership development coaching","cb-123-456","W1234","2026-12-10T14:00:00","Open",'
                '"Public Services and Procurement Canada","Line one\nline two, ""quoted"" managers"\n'
                '"Asphalt paving","cb-9-9","X","2026-12-10T14:00:00","Open","PSPC","paving"\n')
    opps, h = canadabuys.sweep(now=datetime(2026, 11, 17, tzinfo=MAD), text=csv_text)
    assert h.raw_hits == 2 and len(opps) == 1
    o = opps[0]
    assert o.source_url.endswith("/tender-notice/cb-123-456")
    assert "GC_LANGUAGE_SCREEN_REQUIRED" in o.flags


def test_merx_classes():
    assert merx.classify("4044466903") == "merx-native"
    assert merx.classify("444143152673") == "merx-federal-relay"
    assert merx.candidate_urls("22712345678")[0].startswith("https://www.merx.com/private/supplier/")
    assert merx.gc_reference("ref cb-1234-5678 x") == "cb-1234-5678"


def test_bidnet_email_parse():
    body = ("Title: Board Governance Training and Retreat Facilitation\n"
            "Solicitation Number: RFP 26-031\nAgency: Example School District\n"
            "Closing Date: 12/04/2026 02:00 PM EST\n"
            "URL: https://www.bidnetdirect.com/private/supplier/solicitations/statewide/123/abstract\n"
            "Member Agency bid\n-----\n"
            "Title: Other\nClosing Date: 12/05/2026\n"
            "URL: https://www.bidnetdirect.com/x/9\n")
    opps = bidnet_email.parse(body)
    assert len(opps) == 2
    assert opps[0].due.tzinfo is not None and opps[0].lane == "Board"
    assert opps[1].due is None and any(f.startswith("DEADLINE_UNPARSED") for f in opps[1].flags)


def test_screen_unread_and_flags():
    now = datetime(2026, 11, 17, tzinfo=MAD)
    r = intake("Open only to Supply Arrangement Holders. Bilingual services required. Bid bond.", is_gc=True,
               due=datetime(2026, 12, 1, tzinfo=MAD), now=now)
    assert r.code == "UNREAD"
    assert any(f.startswith("V:") for f in r.flags) and "LANGUAGE_TIER1" in r.flags and "BOND?" in r.flags
    assert intake("x", due=datetime(2026, 11, 1, tzinfo=MAD), now=now).code == "DEADLINE-PASSED"
    assert intake("x", primary_read=True, addenda_listed=3, addenda_read=1).code == "UNREAD-ADD"
    assert is_live("PURSUE") and not is_live("NO-BID")


def test_pricing_floor_minimum_and_walkaway():
    p = Plan(hours={"principal": 20, "senior": 40, "analyst": 20})
    d = decide(p, competitor_benchmark=9000)
    assert d.price >= 95 * 80 and d.price >= 7500
    d2 = decide(p, budget=4000)
    assert d2.code == "PRICE" and d2.scope_cut_needed
    assert value_estimate(budget=50000)[3] == "published budget"
    assert value_estimate()[0] is None
