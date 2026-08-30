/* eslint-disable */
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

export const SEED_VENDORS: Vendor[] = [
  {
    "id": "234478",
    "clientId": "CL000001",
    "clientName": "Reliance Industries",
    "name": "Azahan Advertising",
    "legalName": "AZAHAN ADVERTISING",
    "address": "Bajirao Hule Chawl, Sainath Nagar Road, Shanti Nagar,\nGhatkopar West, Mumbai 400086, Maharashtra",
    "pan": "FNNPM0105B",
    "gst": "27FNNPM0105B1ZE",
    "cin": null,
    "domain": null,
    "website": null,
    "material": "Services",
    "spoc": "Mohd. Azahan",
    "designation": "Proprietor",
    "submitted": "2026-07-24 11:20",
    "stage": "decided",
    "decision": "Rejected",
    "decisionRemarks": "Unincorporated, no premises, no web presence. Recommendation overridden.",
    "decidedBy": "r.iyer",
    "unlocked": false,
    "selected": [
      "ustatus",
      "master",
      "resolve",
      "dirs",
      "whois",
      "avail",
      "cdx",
      "dup",
      "conflict"
    ],
    "inputs": {},
    "checks": {
      "resolve": {
        "checkId": "resolve",
        "status": "warn",
        "value": "No CIN found",
        "detail": "No MCA registration traced for this name — consistent with a sole proprietorship"
      },
      "master": {
        "checkId": "master",
        "status": "fail",
        "value": "Not a registered company",
        "detail": "No CIN — entity is unincorporated, MCA holds no record"
      },
      "dirs": {
        "checkId": "dirs",
        "status": "skip",
        "value": "N/A",
        "detail": "No directors — proprietorship"
      },
      "whois": {
        "checkId": "whois",
        "status": "fail",
        "value": "No domain",
        "detail": "No registered domain traced to this entity"
      },
      "avail": {
        "checkId": "avail",
        "status": "fail",
        "value": "Never archived",
        "detail": "archived_snapshots empty — no web presence on record"
      },
      "cdx": {
        "checkId": "cdx",
        "status": "skip",
        "value": "N/A",
        "detail": "No domain to build a timeline from"
      },
      "dup": {
        "checkId": "dup",
        "status": "pass",
        "value": "No duplicate",
        "detail": "No matching GST/PAN in the vendor master"
      },
      "conflict": {
        "checkId": "conflict",
        "status": "pass",
        "value": "No conflict",
        "detail": "No overlap with employee records"
      }
    },
    "scan": {
      "S1": "Individual/ Proprietorship",
      "S2": "< 3 Years",
      "S3": "No",
      "S4": "Manufacturer/ Services",
      "S5": null,
      "C1": null,
      "C2": null,
      "C3": null,
      "C4": "No",
      "C5": null,
      "A1": null,
      "A2": null,
      "A3": "Positive",
      "A4": null,
      "N1": null,
      "N2": null,
      "N3": null,
      "N4": null
    },
    "manual": [
      {
        "id": "e0",
        "key": "Physical availability of office",
        "value": "No",
        "type": "Yes / No",
        "templateId": "m1",
        "note": "Address is a residential chawl; no commercial signage or office found.",
        "enteredBy": "r.iyer",
        "enteredAt": "2026-07-24 13:40"
      },
      {
        "id": "e1",
        "key": "GST status (checked manually on the portal)",
        "value": "Active",
        "type": "Choice",
        "templateId": "m6",
        "note": "Verified on the GST portal by hand — API not configured.",
        "enteredBy": "r.iyer",
        "enteredAt": "2026-07-24 13:42"
      },
      {
        "id": "e2",
        "key": "Years trading before application",
        "value": "2",
        "type": "Number",
        "templateId": null,
        "note": "Custom field. Stated by the vendor, not independently confirmed.",
        "enteredBy": "r.iyer",
        "enteredAt": "2026-07-24 13:45"
      }
    ],
    "surveillance": {},
    "surveillanceDone": false
  },
  {
    "id": "234479",
    "clientId": "CL000001",
    "clientName": "Reliance Industries",
    "name": "Meridian Packaging Pvt Ltd",
    "legalName": "MERIDIAN PACKAGING PRIVATE LIMITED",
    "address": "Plot 44, MIDC Industrial Area, Andheri East,\nMumbai 400093, Maharashtra",
    "pan": "AAGCM4821K",
    "gst": "27AAGCM4821K1Z9",
    "cin": "U21029MH2013PTC245119",
    "domain": "meridianpack.in",
    "website": "https://meridianpack.in",
    "material": "Goods — Corrugated packaging",
    "spoc": "Priya Deshmukh",
    "designation": "Head — Procurement",
    "submitted": "2026-07-28 09:05",
    "stage": "review",
    "decision": null,
    "unlocked": true,
    "selected": [
      "ustatus",
      "master",
      "dirs",
      "dprof",
      "charges",
      "filings",
      "fin",
      "whois",
      "reput",
      "ssl",
      "rwhois",
      "avail",
      "cdx",
      "dup",
      "rp",
      "conflict"
    ],
    "inputs": {},
    "checks": {
      "master": {
        "checkId": "master",
        "status": "pass",
        "value": "ACTIVE · U21029MH2013PTC245119",
        "detail": "Incorporated 04-Jun-2013 · Private Limited · paid-up ₹1.2 Cr"
      },
      "dirs": {
        "checkId": "dirs",
        "status": "pass",
        "value": "2 directors",
        "detail": "R. Deshmukh (DIN 03412887), S. Deshmukh (DIN 03412901) — both active"
      },
      "dprof": {
        "checkId": "dprof",
        "status": "pass",
        "value": "Profiles retrieved",
        "detail": "S. Deshmukh holds 3 other directorships, all active"
      },
      "charges": {
        "checkId": "charges",
        "status": "warn",
        "value": "1 open charge ₹2.4 Cr",
        "detail": "HDFC Bank, created 15-Mar-2022, not satisfied. 4 earlier charges closed."
      },
      "filings": {
        "checkId": "filings",
        "status": "pass",
        "value": "Filings current",
        "detail": "AOC-4 and MGT-7 filed for FY2024 on 30-Sep-2024"
      },
      "fin": {
        "checkId": "fin",
        "status": "pass",
        "value": "Revenue ₹41.2 Cr · PAT ₹1.8 Cr",
        "detail": "AOC-4 FY2023-24 standalone · net worth ₹8.9 Cr"
      },
      "whois": {
        "checkId": "whois",
        "status": "pass",
        "value": "Domain age 11 yrs",
        "detail": "meridianpack.in registered 2015, renewed to 2028"
      },
      "reput": {
        "checkId": "reput",
        "status": "pass",
        "value": "Trust score 91.2",
        "detail": "No blacklist, phishing or malware flags"
      },
      "ssl": {
        "checkId": "ssl",
        "status": "pass",
        "value": "Valid SSL",
        "detail": "Let's Encrypt · valid chain · HTTPS enforced"
      },
      "rwhois": {
        "checkId": "rwhois",
        "status": "pass",
        "value": "3 domains, same owner",
        "detail": "All three are Meridian group brands"
      },
      "avail": {
        "checkId": "avail",
        "status": "pass",
        "value": "Archived since 2015",
        "detail": "First capture 12-Aug-2015 · last capture 03-Aug-2026"
      },
      "cdx": {
        "checkId": "cdx",
        "status": "pass",
        "value": "412 captures, no outages",
        "detail": "Continuous presence since 2015"
      },
      "dup": {
        "checkId": "dup",
        "status": "pass",
        "value": "No duplicate",
        "detail": "No matching GST/PAN in the vendor master"
      },
      "rp": {
        "checkId": "rp",
        "status": "warn",
        "value": "Possible related party",
        "detail": "Director S. Deshmukh is also a director at vendor Meridian Logistics"
      },
      "conflict": {
        "checkId": "conflict",
        "status": "pass",
        "value": "No conflict",
        "detail": "No overlap with employee records"
      }
    },
    "scan": {
      "S1": "Private Ltd",
      "S2": "> 10 Years",
      "S3": "Yes",
      "S4": "Manufacturer/ Services",
      "S5": "Owned",
      "C1": null,
      "C2": null,
      "C3": null,
      "C4": "No",
      "C5": null,
      "A1": "On-board",
      "A2": "Positive",
      "A3": "Positive",
      "A4": "Good",
      "N1": "Industry",
      "N2": "More than 5",
      "N3": "2 Cr / 1 Cr",
      "N4": "State"
    },
    "manual": [
      {
        "id": "e0",
        "key": "Physical availability of office",
        "value": "Yes",
        "type": "Yes / No",
        "templateId": "m1",
        "note": "MIDC unit confirmed on site visit. Nameboard present, production running.",
        "enteredBy": "s.nair",
        "enteredAt": "2026-07-28 15:20"
      },
      {
        "id": "e1",
        "key": "Office ownership",
        "value": "Owned",
        "type": "Choice",
        "templateId": "m2",
        "note": "",
        "enteredBy": "s.nair",
        "enteredAt": "2026-07-28 15:21"
      },
      {
        "id": "e2",
        "key": "Staff present at time of visit",
        "value": "34",
        "type": "Number",
        "templateId": "m4",
        "note": "",
        "enteredBy": "s.nair",
        "enteredAt": "2026-07-28 15:22"
      },
      {
        "id": "e3",
        "key": "GST status (checked manually on the portal)",
        "value": "Active",
        "type": "Choice",
        "templateId": "m6",
        "note": "",
        "enteredBy": "a.mehta",
        "enteredAt": "2026-07-28 09:30"
      },
      {
        "id": "e4",
        "key": "Reference feedback",
        "value": "Good",
        "type": "Choice",
        "templateId": "m15",
        "note": "Two references contacted, both positive on quality and delivery.",
        "enteredBy": "a.mehta",
        "enteredAt": "2026-07-28 11:05"
      },
      {
        "id": "e5",
        "key": "Certifications held (ISO / FSSAI / other)",
        "value": "ISO 9001:2015",
        "type": "Text",
        "templateId": "m16",
        "note": "Certificate seen on site, copy collected.",
        "enteredBy": "s.nair",
        "enteredAt": "2026-07-28 15:25"
      },
      {
        "id": "e6",
        "key": "Machine capacity (sheets/hour)",
        "value": "8500",
        "type": "Number",
        "templateId": null,
        "note": "Custom field added for packaging vendors — capacity stated by plant manager.",
        "enteredBy": "s.nair",
        "enteredAt": "2026-07-28 15:30"
      }
    ],
    "surveillance": {
      "V1": "Yes",
      "V2": "High",
      "V3": "Yes",
      "V4": "Yes",
      "V5": "Strong",
      "V6": "At Par",
      "V7": "At Par",
      "V8": "Satisfactory",
      "V9": "NA",
      "V10": "Strong",
      "V11": "Yes",
      "V12": "Yes",
      "V13": "State"
    },
    "surveillanceDone": true
  },
  {
    "id": "234480",
    "clientId": "CL000002",
    "clientName": "Tata Steel",
    "name": "Kaveri Traders",
    "legalName": "KAVERI TRADERS",
    "address": "18/B Gandhi Market, Pune 411002, Maharashtra",
    "pan": "BXKPK9021J",
    "gst": "27BXKPK9021J1ZR",
    "cin": null,
    "domain": "kaveritraders.co.in",
    "website": "http://kaveritraders.co.in",
    "material": "Goods — Stationery",
    "spoc": "Nilesh Kulkarni",
    "designation": "Partner",
    "submitted": "2026-07-29 16:40",
    "stage": "scoring",
    "decision": null,
    "unlocked": false,
    "selected": [
      "ustatus",
      "master",
      "resolve",
      "whois",
      "reput",
      "ssl",
      "avail",
      "cdx",
      "dup"
    ],
    "inputs": {},
    "checks": {
      "resolve": {
        "checkId": "resolve",
        "status": "warn",
        "value": "No CIN found",
        "detail": "Partnership firm — not registered with MCA"
      },
      "master": {
        "checkId": "master",
        "status": "fail",
        "value": "Not a registered company",
        "detail": "No CIN — MCA holds no record for a partnership firm"
      },
      "whois": {
        "checkId": "whois",
        "status": "warn",
        "value": "Domain age 8 months",
        "detail": "kaveritraders.co.in registered Nov-2025 · registrant privacy-protected"
      },
      "reput": {
        "checkId": "reput",
        "status": "warn",
        "value": "Trust score 54.8",
        "detail": "Recently registered domain · registrant details redacted"
      },
      "ssl": {
        "checkId": "ssl",
        "status": "fail",
        "value": "Self-signed certificate",
        "detail": "Certificate not issued by a trusted CA"
      },
      "avail": {
        "checkId": "avail",
        "status": "warn",
        "value": "Archived since Dec-2025",
        "detail": "First capture 14-Dec-2025"
      },
      "cdx": {
        "checkId": "cdx",
        "status": "warn",
        "value": "19 captures, 1 outage",
        "detail": "Site returned 403 for a 6-week period, Feb–Mar 2026"
      },
      "dup": {
        "checkId": "dup",
        "status": "warn",
        "value": "Possible duplicate",
        "detail": "Similar name and same PIN code as existing vendor #231902"
      }
    },
    "scan": {
      "S1": "Partnership/LLP",
      "S2": "< 3 Years",
      "S3": "Yes",
      "S4": "Retailer/ Trader",
      "S5": "Rented",
      "C1": null,
      "C2": null,
      "C3": null,
      "C4": "Yes",
      "C5": null,
      "A1": null,
      "A2": null,
      "A3": null,
      "A4": null,
      "N1": null,
      "N2": null,
      "N3": null,
      "N4": null
    },
    "manual": [
      {
        "id": "e0",
        "key": "GST status (checked manually on the portal)",
        "value": "Suspended",
        "type": "Choice",
        "templateId": "m6",
        "note": "GSTIN shows SUSPENDED since 11-Feb-2026 for non-filing. Checked by hand on the GST portal — the API is not configured, so this would otherwise have been missed entirely.",
        "enteredBy": "a.mehta",
        "enteredAt": "2026-07-29 16:55"
      },
      {
        "id": "e1",
        "key": "Physical availability of office",
        "value": "Yes",
        "type": "Yes / No",
        "templateId": "m1",
        "note": "Shop exists at the market address, but it is a small retail counter, not a warehouse.",
        "enteredBy": "a.mehta",
        "enteredAt": "2026-07-29 17:02"
      },
      {
        "id": "e2",
        "key": "Office ownership",
        "value": "Rented",
        "type": "Choice",
        "templateId": "m2",
        "note": "",
        "enteredBy": "a.mehta",
        "enteredAt": "2026-07-29 17:03"
      },
      {
        "id": "e3",
        "key": "Partner named on RBI defaulter list?",
        "value": "Possible match — unconfirmed",
        "type": "Text",
        "templateId": null,
        "note": "Custom field. A name match was spotted manually; sanctions screening is not configured, so this cannot be confirmed by the system and must be verified before any decision.",
        "enteredBy": "a.mehta",
        "enteredAt": "2026-07-29 17:15"
      }
    ],
    "surveillance": {},
    "surveillanceDone": false
  }
]

export const SEED_AUDIT: AuditEntry[] = [
  {
    "ts": "2026-07-24 11:20:04",
    "vendorId": "234478",
    "actor": "a.mehta",
    "action": "VENDOR_SUBMITTED",
    "detail": "Azahan Advertising submitted via intake form"
  },
  {
    "ts": "2026-07-24 11:20:20",
    "vendorId": "234478",
    "actor": "a.mehta",
    "action": "CHECKS_SELECTED",
    "detail": "8 checks selected · est. ₹3 + 50 credits"
  },
  {
    "ts": "2026-07-24 11:20:31",
    "vendorId": "234478",
    "actor": "system",
    "action": "CHECKS_COMPLETE",
    "detail": "8 checks settled · 2 pass · 1 warn · 3 fail · 2 skipped"
  },
  {
    "ts": "2026-07-24 11:21:02",
    "vendorId": "234478",
    "actor": "system",
    "action": "SCAN_SCORED",
    "detail": "Weighted 0.90 / best 1.50 · 60.0% · gated by coverage policy 1.0"
  },
  {
    "ts": "2026-07-24 13:45:10",
    "vendorId": "234478",
    "actor": "r.iyer",
    "action": "MANUAL_FIELD_ADDED",
    "detail": "Physical availability of office = No"
  },
  {
    "ts": "2026-07-24 14:02:47",
    "vendorId": "234478",
    "actor": "r.iyer",
    "action": "DECISION_RECORDED",
    "detail": "REJECTED — unincorporated, no premises, no web presence"
  },
  {
    "ts": "2026-07-28 09:05:12",
    "vendorId": "234479",
    "actor": "a.mehta",
    "action": "VENDOR_SUBMITTED",
    "detail": "Meridian Packaging Pvt Ltd submitted via intake form"
  },
  {
    "ts": "2026-07-28 09:05:30",
    "vendorId": "234479",
    "actor": "a.mehta",
    "action": "CHECKS_SELECTED",
    "detail": "16 checks selected · company already unlocked"
  },
  {
    "ts": "2026-07-28 09:05:41",
    "vendorId": "234479",
    "actor": "system",
    "action": "CHECKS_COMPLETE",
    "detail": "16 checks settled · 13 pass · 2 warn · 0 fail"
  },
  {
    "ts": "2026-07-28 15:30:08",
    "vendorId": "234479",
    "actor": "s.nair",
    "action": "SURVEILLANCE_FILED",
    "detail": "Site surveillance completed · result Positive"
  },
  {
    "ts": "2026-07-29 16:40:55",
    "vendorId": "234480",
    "actor": "a.mehta",
    "action": "VENDOR_SUBMITTED",
    "detail": "Kaveri Traders submitted via intake form"
  },
  {
    "ts": "2026-07-29 16:55:12",
    "vendorId": "234480",
    "actor": "a.mehta",
    "action": "MANUAL_FIELD_ADDED",
    "detail": "GST status (manual) = Suspended — API not configured"
  }
]

export const COST_REFERENCE = [
  {
    "group": "FileSure",
    "item": "Company master / directors / filings / extractions",
    "unit": "₹1 per read",
    "source": "derived from /v1/account/usage"
  },
  {
    "group": "FileSure",
    "item": "Company unlock (once per company per year)",
    "unit": "₹220",
    "source": "unlockPrice 22000 paisa"
  },
  {
    "group": "FileSure",
    "item": "Director unlock",
    "unit": "₹10",
    "source": "unlockPrice 1000 paisa"
  },
  {
    "group": "FileSure",
    "item": "Filing document download",
    "unit": "₹0.10",
    "source": "19250 paisa / 1925 calls"
  },
  {
    "group": "FileSure",
    "item": "Full company refresh (async)",
    "unit": "₹150",
    "source": "priceChargedPaisa 15000"
  },
  {
    "group": "FileSure",
    "item": "Filings-only refresh",
    "unit": "₹5",
    "source": "priceChargedPaisa 500"
  },
  {
    "group": "FileSure",
    "item": "Unlock status check",
    "unit": "FREE",
    "source": "GET on the unlock path"
  },
  {
    "group": "WhoisXML",
    "item": "WHOIS History (purchase mode)",
    "unit": "50 credits",
    "source": "500-credit shared pool"
  },
  {
    "group": "WhoisXML",
    "item": "Domain Reputation",
    "unit": "1 credit",
    "source": "50 trial credits"
  },
  {
    "group": "WhoisXML",
    "item": "SSL Certificates",
    "unit": "1 credit",
    "source": "100 trial credits"
  },
  {
    "group": "WhoisXML",
    "item": "Reverse WHOIS",
    "unit": "1 credit",
    "source": "shares the 500-credit pool"
  },
  {
    "group": "WhoisXML",
    "item": "Screenshot",
    "unit": "1 of only 10",
    "source": "tightest limit on the platform"
  },
  {
    "group": "archive.org",
    "item": "Availability, CDX, Advanced Search",
    "unit": "FREE",
    "source": "no key required"
  },
  {
    "group": "In-house",
    "item": "Duplicate, related party, director conflict",
    "unit": "FREE",
    "source": "computed over stored data"
  }
] as const
