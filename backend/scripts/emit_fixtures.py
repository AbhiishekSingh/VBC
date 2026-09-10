#!/usr/bin/env python3
"""Emit the three seeded vendors as TypeScript, for the mock API adapter.

Same reasoning as emit_catalog.py: the fixtures are regression data the
client signed off on, and hand-copying them into the frontend would let the
two drift. Generated, checked in, never hand-edited.
"""
from __future__ import annotations
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.tests import fixtures as fx  # noqa: E402

OUT = ROOT.parent / "frontend" / "src" / "api" / "fixtures.ts"

#: The client the three seeded vendors belong to. The Vendor type gained
#: clientId/clientName with the multi-client work and these fixtures predate
#: it, so the values are supplied here rather than added to each literal
#: below. They MUST match the client seeded in backend/app/db/seed.py — if
#: they drift, the mock adapter and the backend disagree about who owns
#: these vendors, which is exactly what generating this file prevents.
SEED_CLIENT_ID = "c1"
SEED_CLIENT_NAME = "Q1 Software Solutions LLP"


def checks(d):
    return {k: {"checkId": k, "status": v.status.value, "value": v.value,
                "detail": v.detail} for k, v in d.items()}

def manual(entries):
    return [{"id": f"e{i}", "key": e.key, "value": e.value, "type": e.type.value,
             "templateId": e.template_id, "note": e.note,
             "enteredBy": e.entered_by, "enteredAt": e.entered_at}
            for i, e in enumerate(entries)]

VENDORS = [
  {"id": "234478", "name": "Azahan Advertising", "legalName": "AZAHAN ADVERTISING",
   "address": "Bajirao Hule Chawl, Sainath Nagar Road, Shanti Nagar,\nGhatkopar West, Mumbai 400086, Maharashtra",
   "pan": "FNNPM0105B", "gst": "27FNNPM0105B1ZE", "cin": None, "domain": None, "website": None,
   "material": "Services", "spoc": "Mohd. Azahan", "designation": "Proprietor",
   "submitted": "2026-07-24 11:20", "stage": "decided", "decision": "Rejected",
   "decisionRemarks": "Unincorporated, no premises, no web presence. Recommendation overridden.",
   "decidedBy": "r.iyer", "unlocked": False,
   "selected": fx.AZAHAN_SELECTED, "inputs": {}, "checks": checks(fx.AZAHAN_CHECKS),
   "scan": fx.AZAHAN_SCAN, "manual": manual(fx.AZAHAN_MANUAL),
   "surveillance": {}, "surveillanceDone": False},

  {"id": "234479", "name": "Meridian Packaging Pvt Ltd",
   "legalName": "MERIDIAN PACKAGING PRIVATE LIMITED",
   "address": "Plot 44, MIDC Industrial Area, Andheri East,\nMumbai 400093, Maharashtra",
   "pan": "AAGCM4821K", "gst": "27AAGCM4821K1Z9", "cin": "U21029MH2013PTC245119",
   "domain": "meridianpack.in", "website": "https://meridianpack.in",
   "material": "Goods — Corrugated packaging", "spoc": "Priya Deshmukh",
   "designation": "Head — Procurement", "submitted": "2026-07-28 09:05",
   "stage": "review", "decision": None, "unlocked": True,
   "selected": fx.MERIDIAN_SELECTED, "inputs": {}, "checks": checks(fx.MERIDIAN_CHECKS),
   "scan": fx.MERIDIAN_SCAN,
   "manual": manual([
     type("E", (), {"key": "Physical availability of office", "value": "Yes",
       "type": type("T", (), {"value": "Yes / No"})(), "template_id": "m1",
       "entered_by": "s.nair", "entered_at": "2026-07-28 15:20",
       "note": "MIDC unit confirmed on site visit. Nameboard present, production running."})(),
     type("E", (), {"key": "Office ownership", "value": "Owned",
       "type": type("T", (), {"value": "Choice"})(), "template_id": "m2",
       "entered_by": "s.nair", "entered_at": "2026-07-28 15:21", "note": ""})(),
     type("E", (), {"key": "Staff present at time of visit", "value": "34",
       "type": type("T", (), {"value": "Number"})(), "template_id": "m4",
       "entered_by": "s.nair", "entered_at": "2026-07-28 15:22", "note": ""})(),
     type("E", (), {"key": "GST status (checked manually on the portal)", "value": "Active",
       "type": type("T", (), {"value": "Choice"})(), "template_id": "m6",
       "entered_by": "a.mehta", "entered_at": "2026-07-28 09:30", "note": ""})(),
     type("E", (), {"key": "Reference feedback", "value": "Good",
       "type": type("T", (), {"value": "Choice"})(), "template_id": "m15",
       "entered_by": "a.mehta", "entered_at": "2026-07-28 11:05",
       "note": "Two references contacted, both positive on quality and delivery."})(),
     type("E", (), {"key": "Certifications held (ISO / FSSAI / other)", "value": "ISO 9001:2015",
       "type": type("T", (), {"value": "Text"})(), "template_id": "m16",
       "entered_by": "s.nair", "entered_at": "2026-07-28 15:25",
       "note": "Certificate seen on site, copy collected."})(),
     type("E", (), {"key": "Machine capacity (sheets/hour)", "value": "8500",
       "type": type("T", (), {"value": "Number"})(), "template_id": None,
       "entered_by": "s.nair", "entered_at": "2026-07-28 15:30",
       "note": "Custom field added for packaging vendors — capacity stated by plant manager."})(),
   ]),
   "surveillance": fx.MERIDIAN_SURVEILLANCE, "surveillanceDone": True},

  {"id": "234480", "name": "Kaveri Traders", "legalName": "KAVERI TRADERS",
   "address": "18/B Gandhi Market, Pune 411002, Maharashtra",
   "pan": "BXKPK9021J", "gst": "27BXKPK9021J1ZR", "cin": None,
   "domain": "kaveritraders.co.in", "website": "http://kaveritraders.co.in",
   "material": "Goods — Stationery", "spoc": "Nilesh Kulkarni", "designation": "Partner",
   "submitted": "2026-07-29 16:40", "stage": "scoring", "decision": None, "unlocked": False,
   "selected": fx.KAVERI_SELECTED, "inputs": {}, "checks": checks(fx.KAVERI_CHECKS),
   "scan": fx.KAVERI_SCAN,
   "manual": manual([
     type("E", (), {"key": "GST status (checked manually on the portal)", "value": "Suspended",
       "type": type("T", (), {"value": "Choice"})(), "template_id": "m6",
       "entered_by": "a.mehta", "entered_at": "2026-07-29 16:55",
       "note": "GSTIN shows SUSPENDED since 11-Feb-2026 for non-filing. Checked by hand on the GST portal — the API is not configured, so this would otherwise have been missed entirely."})(),
     type("E", (), {"key": "Physical availability of office", "value": "Yes",
       "type": type("T", (), {"value": "Yes / No"})(), "template_id": "m1",
       "entered_by": "a.mehta", "entered_at": "2026-07-29 17:02",
       "note": "Shop exists at the market address, but it is a small retail counter, not a warehouse."})(),
     type("E", (), {"key": "Office ownership", "value": "Rented",
       "type": type("T", (), {"value": "Choice"})(), "template_id": "m2",
       "entered_by": "a.mehta", "entered_at": "2026-07-29 17:03", "note": ""})(),
     type("E", (), {"key": "Partner named on RBI defaulter list?", "value": "Possible match — unconfirmed",
       "type": type("T", (), {"value": "Text"})(), "template_id": None,
       "entered_by": "a.mehta", "entered_at": "2026-07-29 17:15",
       "note": "Custom field. A name match was spotted manually; sanctions screening is not configured, so this cannot be confirmed by the system and must be verified before any decision."})(),
   ]),
   "surveillance": {}, "surveillanceDone": False},
]

# Every vendor carries its client. setdefault rather than assignment so a
# fixture that names its own client above is never silently overwritten.
for _vendor in VENDORS:
    _vendor.setdefault("clientId", SEED_CLIENT_ID)
    _vendor.setdefault("clientName", SEED_CLIENT_NAME)

AUDIT = [
  {"ts": "2026-07-24 11:20:04", "vendorId": "234478", "actor": "a.mehta", "action": "VENDOR_SUBMITTED", "detail": "Azahan Advertising submitted via intake form"},
  {"ts": "2026-07-24 11:20:20", "vendorId": "234478", "actor": "a.mehta", "action": "CHECKS_SELECTED", "detail": "8 checks selected · est. ₹3 + 50 credits"},
  {"ts": "2026-07-24 11:20:31", "vendorId": "234478", "actor": "system", "action": "CHECKS_COMPLETE", "detail": "8 checks settled · 2 pass · 1 warn · 3 fail · 2 skipped"},
  {"ts": "2026-07-24 11:21:02", "vendorId": "234478", "actor": "system", "action": "SCAN_SCORED", "detail": "Weighted 0.90 / best 1.50 · 60.0% · gated by coverage policy 1.0"},
  {"ts": "2026-07-24 13:45:10", "vendorId": "234478", "actor": "r.iyer", "action": "MANUAL_FIELD_ADDED", "detail": "Physical availability of office = No"},
  {"ts": "2026-07-24 14:02:47", "vendorId": "234478", "actor": "r.iyer", "action": "DECISION_RECORDED", "detail": "REJECTED — unincorporated, no premises, no web presence"},
  {"ts": "2026-07-28 09:05:12", "vendorId": "234479", "actor": "a.mehta", "action": "VENDOR_SUBMITTED", "detail": "Meridian Packaging Pvt Ltd submitted via intake form"},
  {"ts": "2026-07-28 09:05:30", "vendorId": "234479", "actor": "a.mehta", "action": "CHECKS_SELECTED", "detail": "16 checks selected · company already unlocked"},
  {"ts": "2026-07-28 09:05:41", "vendorId": "234479", "actor": "system", "action": "CHECKS_COMPLETE", "detail": "16 checks settled · 13 pass · 2 warn · 0 fail"},
  {"ts": "2026-07-28 15:30:08", "vendorId": "234479", "actor": "s.nair", "action": "SURVEILLANCE_FILED", "detail": "Site surveillance completed · result Positive"},
  {"ts": "2026-07-29 16:40:55", "vendorId": "234480", "actor": "a.mehta", "action": "VENDOR_SUBMITTED", "detail": "Kaveri Traders submitted via intake form"},
  {"ts": "2026-07-29 16:55:12", "vendorId": "234480", "actor": "a.mehta", "action": "MANUAL_FIELD_ADDED", "detail": "GST status (manual) = Suspended — API not configured"},
]

COST_REF = [
  {"group": "FileSure", "item": "Company master / directors / filings / extractions", "unit": "₹1 per read", "source": "derived from /v1/account/usage"},
  {"group": "FileSure", "item": "Company unlock (once per company per year)", "unit": "₹330", "source": "filesure.COMPANY_UNLOCK_PAISA = 33000"},
  {"group": "FileSure", "item": "Director unlock", "unit": "₹50", "source": "filesure.DIRECTOR_UNLOCK_PAISA = 5000"},
  {"group": "FileSure", "item": "Filing document download", "unit": "₹0.10", "source": "19250 paisa / 1925 calls"},
  {"group": "FileSure", "item": "Full company refresh (async)", "unit": "₹150", "source": "priceChargedPaisa 15000"},
  {"group": "FileSure", "item": "Filings-only refresh", "unit": "₹5", "source": "priceChargedPaisa 500"},
  {"group": "FileSure", "item": "Unlock status check", "unit": "FREE", "source": "GET on the unlock path"},
  {"group": "WhoisXML", "item": "WHOIS History (purchase mode)", "unit": "50 credits", "source": "500-credit shared pool"},
  {"group": "WhoisXML", "item": "Domain Reputation", "unit": "1 credit", "source": "50 trial credits"},
  {"group": "WhoisXML", "item": "SSL Certificates", "unit": "1 credit", "source": "100 trial credits"},
  {"group": "WhoisXML", "item": "Reverse WHOIS", "unit": "1 credit", "source": "shares the 500-credit pool"},
  {"group": "WhoisXML", "item": "Screenshot", "unit": "1 of only 10", "source": "tightest limit on the platform"},
  {"group": "archive.org", "item": "Availability, CDX, Advanced Search", "unit": "FREE", "source": "no key required"},
  {"group": "eCourtsIndia", "item": "Case search, case detail, cause lists, LegalCheck", "unit": "not yet quoted", "source": "VBC_ECOURTS_*_PAISA unset — a run under-reports its court spend until the provider quotes prices"},
  {"group": "In-house", "item": "Duplicate, related party, director conflict", "unit": "FREE", "source": "computed over stored data"},
]

header = '''/* eslint-disable */
/**
 * GENERATED FILE — DO NOT EDIT BY HAND.
 * Produced by backend/scripts/emit_fixtures.py.
 *
 * The three seeded vendors are regression data the client signed off on.
 * They live in Python (backend/app/tests/fixtures.py) and are projected
 * here so the mock adapter and the backend cannot disagree about them.
 *
 * Regenerate with: npm run codegen
 */

import type { Vendor, AuditEntry } from '@/types/domain'

'''

body = header
body += "export const SEED_VENDORS: Vendor[] = " + json.dumps(VENDORS, indent=2, ensure_ascii=False) + "\n\n"
body += "export const SEED_AUDIT: AuditEntry[] = " + json.dumps(AUDIT, indent=2, ensure_ascii=False) + "\n\n"
body += "export const COST_REFERENCE = " + json.dumps(COST_REF, indent=2, ensure_ascii=False) + " as const\n"

OUT.parent.mkdir(parents=True, exist_ok=True)
# encoding is explicit: Windows defaults to cp1252, which cannot encode the
# rupee sign and made this script fail there while passing on CI.
OUT.write_text(body, encoding="utf-8")
print(f"OK   wrote {OUT.name} — {len(VENDORS)} vendors, {len(AUDIT)} audit entries")