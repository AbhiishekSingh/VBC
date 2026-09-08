/* eslint-disable */
/**
 * GENERATED FILE — DO NOT EDIT BY HAND.
 *
 * Produced by backend/scripts/emit_catalog.py from the Python catalog,
 * which is the single source of truth for every parameter, option string,
 * rating and weight in this system.
 *
 * If you need to change a check or a SCAN option, change it in
 * backend/app/catalog/ and re-run:
 *
 *     npm run codegen
 *
 * CI regenerates this file and fails the build if the result differs from
 * what is committed, so a hand-edit here will be caught rather than
 * silently shipping a frontend that scores differently from the backend.
 */

export const PILLARS = [
  {
    "key": "S",
    "name": "Stature",
    "subtitle": "Capability",
    "weight": 0.2
  },
  {
    "key": "C",
    "name": "Compliance",
    "subtitle": "Statutory",
    "weight": 0.1
  },
  {
    "key": "A",
    "name": "Assessment",
    "subtitle": "Diligence",
    "weight": 0.6
  },
  {
    "key": "N",
    "name": "Numbers",
    "subtitle": "Financial",
    "weight": 0.1
  }
] as const;

export const SCAN_PARAMETERS = [
  {
    "id": "S1",
    "pillar": "S",
    "label": "Constitution",
    "source": "AUTO",
    "feed": "MCA company status",
    "fedBy": "master",
    "options": [
      {
        "value": "Listed/Public",
        "rating": "G"
      },
      {
        "value": "Private Ltd",
        "rating": "G"
      },
      {
        "value": "Partnership/LLP",
        "rating": "Y"
      },
      {
        "value": "Individual/ Proprietorship",
        "rating": "R"
      }
    ]
  },
  {
    "id": "S2",
    "pillar": "S",
    "label": "Vintage",
    "source": "AUTO",
    "feed": "MCA incorporation date",
    "fedBy": "master",
    "options": [
      {
        "value": "> 10 Years",
        "rating": "G"
      },
      {
        "value": "3 - 10 Years",
        "rating": "Y"
      },
      {
        "value": "< 3 Years",
        "rating": "R"
      }
    ]
  },
  {
    "id": "S3",
    "pillar": "S",
    "label": "Social Profiling (website, catalogue, directories)",
    "source": "AUTO",
    "feed": "Domain + archive evidence",
    "fedBy": "cdx",
    "options": [
      {
        "value": "Yes",
        "rating": "G"
      },
      {
        "value": "No",
        "rating": "R"
      }
    ]
  },
  {
    "id": "S4",
    "pillar": "S",
    "label": "Type of Business",
    "source": "HUMAN",
    "feed": "Analyst classification",
    "fedBy": null,
    "options": [
      {
        "value": "Manufacturer/ Services",
        "rating": "G"
      },
      {
        "value": "Wholesaler",
        "rating": "Y"
      },
      {
        "value": "Retailer/ Trader",
        "rating": "R"
      }
    ]
  },
  {
    "id": "S5",
    "pillar": "S",
    "label": "Infrastructure",
    "source": "HUMAN",
    "feed": "Site surveillance",
    "fedBy": null,
    "options": [
      {
        "value": "Owned",
        "rating": "G"
      },
      {
        "value": "Rented",
        "rating": "Y"
      }
    ]
  },
  {
    "id": "C1",
    "pillar": "C",
    "label": "GST Registration",
    "source": "AUTO",
    "feed": "FinAGG GSP — common search",
    "fedBy": "gst",
    "options": [
      {
        "value": "Registered",
        "rating": "G"
      },
      {
        "value": "Not Applicable",
        "rating": "Y"
      },
      {
        "value": "Unregistered",
        "rating": "R"
      }
    ]
  },
  {
    "id": "C2",
    "pillar": "C",
    "label": "Filing Status",
    "source": "AUTO",
    "feed": "FinAGG GSP — returns metadata",
    "fedBy": "gstret",
    "options": [
      {
        "value": "Regular",
        "rating": "G"
      },
      {
        "value": "History of Default",
        "rating": "Y"
      },
      {
        "value": "Current Default (0-3 months)",
        "rating": "R"
      }
    ]
  },
  {
    "id": "C3",
    "pillar": "C",
    "label": "Registration Type",
    "source": "AUTO",
    "feed": "FinAGG GSP — common search",
    "fedBy": "gst",
    "options": [
      {
        "value": "Regular",
        "rating": "G"
      },
      {
        "value": "Composite",
        "rating": "Y"
      }
    ]
  },
  {
    "id": "C4",
    "pillar": "C",
    "label": "Suspension (if any)",
    "source": "AUTO",
    "feed": "FinAGG GSP — common search",
    "fedBy": "gst",
    "options": [
      {
        "value": "No",
        "rating": "G"
      },
      {
        "value": "Yes",
        "rating": "R"
      }
    ]
  },
  {
    "id": "C5",
    "pillar": "C",
    "label": "GST Address",
    "source": "AUTO",
    "feed": "FinAGG GSP — common search",
    "fedBy": "gst",
    "options": [
      {
        "value": "Commercial",
        "rating": "G"
      },
      {
        "value": "Residential",
        "rating": "Y"
      }
    ]
  },
  {
    "id": "A1",
    "pillar": "A",
    "label": "Psychometric Test Result",
    "source": "HUMAN",
    "feed": "External assessment",
    "fedBy": null,
    "options": [
      {
        "value": "On-board",
        "rating": "G"
      },
      {
        "value": "Reject",
        "rating": "R"
      }
    ]
  },
  {
    "id": "A2",
    "pillar": "A",
    "label": "Site Surveillance",
    "source": "HUMAN",
    "feed": "Site Surveillance module",
    "fedBy": null,
    "options": [
      {
        "value": "Positive",
        "rating": "G"
      },
      {
        "value": "Negative",
        "rating": "R"
      }
    ]
  },
  {
    "id": "A3",
    "pillar": "A",
    "label": "Conflict of Interest (Employees)",
    "source": "AUTO",
    "feed": "Internal check over MCA director data",
    "fedBy": "conflict",
    "options": [
      {
        "value": "Positive",
        "rating": "G"
      },
      {
        "value": "Negative",
        "rating": "R"
      }
    ]
  },
  {
    "id": "A4",
    "pillar": "A",
    "label": "Market References",
    "source": "HUMAN",
    "feed": "Analyst reference calls",
    "fedBy": null,
    "options": [
      {
        "value": "Good",
        "rating": "G"
      },
      {
        "value": "Average",
        "rating": "Y"
      },
      {
        "value": "Poor",
        "rating": "R"
      }
    ]
  },
  {
    "id": "N1",
    "pillar": "N",
    "label": "Credit Period Offered",
    "source": "HUMAN",
    "feed": "Commercial terms",
    "fedBy": null,
    "options": [
      {
        "value": "Better than Industry",
        "rating": "G"
      },
      {
        "value": "Industry",
        "rating": "Y"
      },
      {
        "value": "Lower than Industry",
        "rating": "R"
      }
    ]
  },
  {
    "id": "N2",
    "pillar": "N",
    "label": "Big Players in Clientele",
    "source": "HUMAN",
    "feed": "Reference check",
    "fedBy": null,
    "options": [
      {
        "value": "More than 5",
        "rating": "G"
      },
      {
        "value": "1 to 5",
        "rating": "Y"
      },
      {
        "value": "Zero",
        "rating": "R"
      }
    ]
  },
  {
    "id": "N3",
    "pillar": "N",
    "label": "Turnover of the Vendor",
    "source": "AUTO",
    "feed": "MCA filed financials (AOC-4)",
    "fedBy": "fin",
    "options": [
      {
        "value": "2 Cr / 1 Cr",
        "rating": "G"
      },
      {
        "value": "> 50 Lac / 25 Lac",
        "rating": "Y"
      },
      {
        "value": "< 50 Lac / 25 Lac",
        "rating": "R"
      }
    ]
  },
  {
    "id": "N4",
    "pillar": "N",
    "label": "Reach",
    "source": "HUMAN",
    "feed": "Analyst assessment",
    "fedBy": null,
    "options": [
      {
        "value": "Pan India",
        "rating": "G"
      },
      {
        "value": "State",
        "rating": "Y"
      },
      {
        "value": "Local",
        "rating": "R"
      }
    ]
  }
] as const;

export const SURVEILLANCE_PARAMETERS = [
  {
    "id": "V1",
    "label": "Existence of Premises",
    "hardGate": true,
    "options": [
      {
        "value": "Yes",
        "rating": "G"
      },
      {
        "value": "No",
        "rating": "R"
      }
    ]
  },
  {
    "id": "V2",
    "label": "Traceability",
    "hardGate": false,
    "options": [
      {
        "value": "High",
        "rating": "G"
      },
      {
        "value": "Low",
        "rating": "R"
      }
    ]
  },
  {
    "id": "V3",
    "label": "Genuinity — deals in the same materials",
    "hardGate": false,
    "options": [
      {
        "value": "Yes",
        "rating": "G"
      },
      {
        "value": "No",
        "rating": "R"
      }
    ]
  },
  {
    "id": "V4",
    "label": "Capability",
    "hardGate": false,
    "options": [
      {
        "value": "Yes",
        "rating": "G"
      },
      {
        "value": "No",
        "rating": "R"
      }
    ]
  },
  {
    "id": "V5",
    "label": "Market Position",
    "hardGate": false,
    "options": [
      {
        "value": "Strong",
        "rating": "G"
      },
      {
        "value": "Average",
        "rating": "Y"
      },
      {
        "value": "Weak",
        "rating": "R"
      }
    ]
  },
  {
    "id": "V6",
    "label": "Sample vs Quality Standards",
    "hardGate": false,
    "options": [
      {
        "value": "Above Par",
        "rating": "G"
      },
      {
        "value": "At Par",
        "rating": "Y"
      },
      {
        "value": "Below Par",
        "rating": "R"
      }
    ]
  },
  {
    "id": "V7",
    "label": "Rate of the Product",
    "hardGate": false,
    "options": [
      {
        "value": "Positive",
        "rating": "G"
      },
      {
        "value": "At Par",
        "rating": "Y"
      },
      {
        "value": "Negative",
        "rating": "R"
      }
    ]
  },
  {
    "id": "V8",
    "label": "Infrastructure",
    "hardGate": false,
    "options": [
      {
        "value": "Satisfactory",
        "rating": "G"
      },
      {
        "value": "Dis-satisfactory",
        "rating": "R"
      }
    ]
  },
  {
    "id": "V9",
    "label": "Political Connection",
    "hardGate": false,
    "options": [
      {
        "value": "Yes",
        "rating": "G"
      },
      {
        "value": "NA",
        "rating": "Y"
      },
      {
        "value": "No",
        "rating": "R"
      }
    ]
  },
  {
    "id": "V10",
    "label": "Staff Strength",
    "hardGate": false,
    "options": [
      {
        "value": "Strong",
        "rating": "G"
      },
      {
        "value": "Average",
        "rating": "Y"
      },
      {
        "value": "Weak",
        "rating": "R"
      }
    ]
  },
  {
    "id": "V11",
    "label": "Certifications (ISO, FSSAI etc.)",
    "hardGate": false,
    "options": [
      {
        "value": "Yes",
        "rating": "G"
      },
      {
        "value": "NA",
        "rating": "Y"
      },
      {
        "value": "No",
        "rating": "R"
      }
    ]
  },
  {
    "id": "V12",
    "label": "Clientele (Competitor)",
    "hardGate": false,
    "options": [
      {
        "value": "Yes",
        "rating": "G"
      },
      {
        "value": "No",
        "rating": "R"
      }
    ]
  },
  {
    "id": "V13",
    "label": "Reach (Branches)",
    "hardGate": false,
    "options": [
      {
        "value": "Pan India",
        "rating": "G"
      },
      {
        "value": "State",
        "rating": "Y"
      },
      {
        "value": "Local",
        "rating": "R"
      }
    ]
  }
] as const;

export const SURVEILLANCE_THRESHOLD_PCT = 60.0 as const;

export const CHECK_GROUPS = [
  {
    "id": "mca",
    "name": "Company Registry — MCA",
    "source": "FileSure",
    "mark": "M",
    "configured": true
  },
  {
    "id": "domain",
    "name": "Website & Domain Ownership",
    "source": "WhoisXML",
    "mark": "D",
    "configured": true
  },
  {
    "id": "web",
    "name": "Web Presence History",
    "source": "archive.org · free",
    "mark": "W",
    "configured": true
  },
  {
    "id": "internal",
    "name": "Internal Checks",
    "source": "our database · free",
    "mark": "I",
    "configured": true
  },
  {
    "id": "admin",
    "name": "Account & Data Freshness",
    "source": "FileSure · admin",
    "mark": "A",
    "configured": true
  },
  {
    "id": "tax",
    "name": "Identity & Tax",
    "source": "FinAGG GSP · GST",
    "mark": "G",
    "configured": true
  },
  {
    "id": "sanctions",
    "name": "Sanctions & Watchlists",
    "source": "not configured",
    "mark": "—",
    "configured": false
  },
  {
    "id": "rep",
    "name": "Litigation & Reputation",
    "source": "eCourtsIndia · LegalCheck",
    "mark": "L",
    "configured": true
  }
] as const;

export const CHECKS = [
  {
    "id": "master",
    "group": "mca",
    "name": "Company master",
    "endpoint": "GET /v1/companies/{cin}?idType=cin",
    "provider": "filesure",
    "note": "Status, incorporation date, capital, registered address",
    "state": "active",
    "requires": [],
    "feeds": [
      "S1",
      "S2"
    ],
    "costPaisa": 500,
    "credits": 0,
    "screenshots": 0,
    "needsCompanyUnlock": false,
    "needsDirectorUnlock": false,
    "always": false,
    "admin": false,
    "params": [
      {
        "key": "cin",
        "label": "CIN",
        "required": true,
        "fromVendor": "cin",
        "fromResult": null,
        "type": "text",
        "options": [],
        "default": "",
        "placeholder": "U21029MH2013PTC245119"
      },
      {
        "key": "idType",
        "label": "Look up by",
        "required": false,
        "fromVendor": null,
        "fromResult": null,
        "type": "select",
        "options": [
          "cin",
          "name"
        ],
        "default": "cin",
        "placeholder": ""
      }
    ]
  },
  {
    "id": "resolve",
    "group": "mca",
    "name": "Resolve company name → CIN",
    "endpoint": "GET /v1/companies/resolve?q={name}",
    "provider": "filesure",
    "note": "Only needed when the client submits a name rather than a CIN",
    "state": "active",
    "requires": [],
    "feeds": [],
    "costPaisa": 500,
    "credits": 0,
    "screenshots": 0,
    "needsCompanyUnlock": false,
    "needsDirectorUnlock": false,
    "always": false,
    "admin": false,
    "params": [
      {
        "key": "q",
        "label": "Company name to search",
        "required": true,
        "fromVendor": "name",
        "fromResult": null,
        "type": "text",
        "options": [],
        "default": "",
        "placeholder": "e.g. Meridian Packaging"
      },
      {
        "key": "state",
        "label": "State",
        "required": false,
        "fromVendor": null,
        "fromResult": null,
        "type": "text",
        "options": [],
        "default": "",
        "placeholder": "Maharashtra"
      },
      {
        "key": "city",
        "label": "City",
        "required": false,
        "fromVendor": null,
        "fromResult": null,
        "type": "text",
        "options": [],
        "default": "",
        "placeholder": "Mumbai"
      },
      {
        "key": "limit",
        "label": "Max results",
        "required": false,
        "fromVendor": null,
        "fromResult": null,
        "type": "number",
        "options": [],
        "default": "10",
        "placeholder": ""
      }
    ]
  },
  {
    "id": "dirs",
    "group": "mca",
    "name": "Directors list",
    "endpoint": "included in company master",
    "provider": "filesure",
    "note": "DIN, name, appointment date, other directorships",
    "state": "active",
    "requires": [
      "master"
    ],
    "feeds": [],
    "costPaisa": 0,
    "credits": 0,
    "screenshots": 0,
    "needsCompanyUnlock": false,
    "needsDirectorUnlock": false,
    "always": false,
    "admin": false,
    "params": []
  },
  {
    "id": "dresolve",
    "group": "mca",
    "name": "Resolve director name → DIN",
    "endpoint": "GET /v1/directors/resolve?q={name}",
    "provider": "filesure",
    "note": "Needed when a client gives a director's name rather than a DIN. totalDirectorshipCount is a free red-flag metric — an unusually high count is the classic mass-director pattern.",
    "state": "active",
    "requires": [],
    "feeds": [],
    "costPaisa": 500,
    "credits": 0,
    "screenshots": 0,
    "needsCompanyUnlock": false,
    "needsDirectorUnlock": false,
    "always": false,
    "admin": false,
    "params": [
      {
        "key": "q",
        "label": "Director name to search",
        "required": true,
        "fromVendor": null,
        "fromResult": null,
        "type": "text",
        "options": [],
        "default": "",
        "placeholder": "e.g. Amit Sharma"
      },
      {
        "key": "limit",
        "label": "Max results",
        "required": false,
        "fromVendor": null,
        "fromResult": null,
        "type": "number",
        "options": [],
        "default": "10",
        "placeholder": ""
      }
    ]
  },
  {
    "id": "dprof",
    "group": "mca",
    "name": "Director full profile",
    "endpoint": "GET /v1/directors/{din}",
    "provider": "filesure",
    "note": "Full directorship history including cessation dates",
    "state": "active",
    "requires": [
      "dirs"
    ],
    "feeds": [],
    "costPaisa": 500,
    "credits": 0,
    "screenshots": 0,
    "needsCompanyUnlock": false,
    "needsDirectorUnlock": false,
    "always": false,
    "admin": false,
    "params": [
      {
        "key": "din",
        "label": "DIN",
        "required": false,
        "fromVendor": null,
        "fromResult": "dirs",
        "type": "text",
        "options": [],
        "default": "",
        "placeholder": "blank = every director found on the company"
      }
    ]
  },
  {
    "id": "dcontact",
    "group": "mca",
    "name": "Director contact details",
    "endpoint": "GET /v1/directors/{din}/contact",
    "provider": "filesure",
    "note": "Mobile and email as filed with MCA — number is returned masked",
    "state": "active",
    "requires": [
      "dirs"
    ],
    "feeds": [],
    "costPaisa": 5,
    "credits": 0,
    "screenshots": 0,
    "needsCompanyUnlock": false,
    "needsDirectorUnlock": true,
    "always": false,
    "admin": false,
    "params": [
      {
        "key": "din",
        "label": "DIN",
        "required": false,
        "fromVendor": null,
        "fromResult": "dirs",
        "type": "text",
        "options": [],
        "default": "",
        "placeholder": "blank = every director found on the company"
      }
    ]
  },
  {
    "id": "charges",
    "group": "mca",
    "name": "Charges and secured loans",
    "endpoint": "included in company master",
    "provider": "filesure",
    "note": "Open and satisfied charges, lender, amount",
    "state": "active",
    "requires": [
      "master"
    ],
    "feeds": [],
    "costPaisa": 0,
    "credits": 0,
    "screenshots": 0,
    "needsCompanyUnlock": false,
    "needsDirectorUnlock": false,
    "always": false,
    "admin": false,
    "params": []
  },
  {
    "id": "filings",
    "group": "mca",
    "name": "Filing history",
    "endpoint": "GET /v1/companies/{cin}/filings",
    "provider": "filesure",
    "note": "Filtered to AOC-4, MGT-7, CHG and ADT-1 forms",
    "state": "active",
    "requires": [
      "master"
    ],
    "feeds": [],
    "costPaisa": 500,
    "credits": 0,
    "screenshots": 0,
    "needsCompanyUnlock": false,
    "needsDirectorUnlock": false,
    "always": false,
    "admin": false,
    "params": [
      {
        "key": "formId",
        "label": "Form type",
        "required": false,
        "fromVendor": null,
        "fromResult": null,
        "type": "select",
        "options": [
          "All forms",
          "AOC-4",
          "MGT-7",
          "CHG-9",
          "CHG-4",
          "ADT-1"
        ],
        "default": "All forms",
        "placeholder": ""
      },
      {
        "key": "year",
        "label": "Year",
        "required": false,
        "fromVendor": null,
        "fromResult": null,
        "type": "number",
        "options": [],
        "default": "",
        "placeholder": "2024"
      },
      {
        "key": "limit",
        "label": "Results per page",
        "required": false,
        "fromVendor": null,
        "fromResult": null,
        "type": "number",
        "options": [],
        "default": "50",
        "placeholder": ""
      }
    ]
  },
  {
    "id": "download",
    "group": "mca",
    "name": "Filing document download",
    "endpoint": "GET /v1/companies/{cin}/filings/{filingId}/download",
    "provider": "filesure",
    "note": "Source PDFs attached to the report as evidence",
    "state": "active",
    "requires": [
      "filings"
    ],
    "feeds": [],
    "costPaisa": 5,
    "credits": 0,
    "screenshots": 0,
    "needsCompanyUnlock": true,
    "needsDirectorUnlock": false,
    "always": false,
    "admin": false,
    "params": [
      {
        "key": "filingId",
        "label": "Filing ID",
        "required": true,
        "fromVendor": null,
        "fromResult": "filings",
        "type": "text",
        "options": [],
        "default": "",
        "placeholder": "flg_Ui2a1vIty…"
      }
    ]
  },
  {
    "id": "frefresh",
    "group": "mca",
    "name": "Refresh filings from MCA",
    "endpoint": "POST /v1/companies/{cin}/filings/refresh",
    "provider": "filesure",
    "note": "₹5 filings-only refresh, distinct from the ₹150 full update. Has its own ~6h cooldown and can return fromCache:true — billing you for cached data with no fresh MCA pull. Check cooldownUntil first.",
    "state": "active",
    "requires": [
      "master"
    ],
    "feeds": [],
    "costPaisa": 500,
    "credits": 0,
    "screenshots": 0,
    "needsCompanyUnlock": false,
    "needsDirectorUnlock": false,
    "always": false,
    "admin": false,
    "params": [
      {
        "key": "cin",
        "label": "CIN",
        "required": true,
        "fromVendor": "cin",
        "fromResult": null,
        "type": "text",
        "options": [],
        "default": "",
        "placeholder": "U21029MH2013PTC245119"
      }
    ]
  },
  {
    "id": "fin",
    "group": "mca",
    "name": "Filed financial statements",
    "endpoint": "GET /v1/companies/{cin}/extractions/{form}/{year}",
    "provider": "filesure",
    "note": "Government-filed XBRL — revenue, profit, net worth, cash flow. Reaching it is a THREE-step drill-down: available form types, then available years, then the filing itself. Year gaps in step 2 are a compliance signal, not an error.",
    "state": "active",
    "requires": [
      "master"
    ],
    "feeds": [
      "N3"
    ],
    "costPaisa": 5,
    "credits": 0,
    "screenshots": 0,
    "needsCompanyUnlock": true,
    "needsDirectorUnlock": false,
    "always": false,
    "admin": false,
    "params": [
      {
        "key": "formType",
        "label": "Form",
        "required": false,
        "fromVendor": null,
        "fromResult": null,
        "type": "select",
        "options": [
          "AOC-4",
          "MGT-7",
          "PAS-3",
          "CHARGES"
        ],
        "default": "AOC-4",
        "placeholder": ""
      },
      {
        "key": "year",
        "label": "Year",
        "required": false,
        "fromVendor": null,
        "fromResult": null,
        "type": "number",
        "options": [],
        "default": "",
        "placeholder": "blank = latest filed"
      },
      {
        "key": "scope",
        "label": "Scope",
        "required": false,
        "fromVendor": null,
        "fromResult": null,
        "type": "select",
        "options": [
          "standalone",
          "consolidated"
        ],
        "default": "standalone",
        "placeholder": ""
      }
    ]
  },
  {
    "id": "whois",
    "group": "domain",
    "name": "Domain ownership history",
    "endpoint": "GET /whois-history/api/v1",
    "provider": "whoisxml",
    "note": "Registrant, registrar and nameserver changes over time",
    "state": "active",
    "requires": [],
    "feeds": [
      "S3"
    ],
    "costPaisa": 0,
    "credits": 50,
    "screenshots": 0,
    "needsCompanyUnlock": false,
    "needsDirectorUnlock": false,
    "always": false,
    "admin": false,
    "params": [
      {
        "key": "domainName",
        "label": "Domain",
        "required": true,
        "fromVendor": "domain",
        "fromResult": null,
        "type": "text",
        "options": [],
        "default": "",
        "placeholder": "example.com"
      },
      {
        "key": "mode",
        "label": "Mode",
        "required": false,
        "fromVendor": null,
        "fromResult": null,
        "type": "select",
        "options": [
          "purchase — full records (50 credits)",
          "preview — count only"
        ],
        "default": "purchase — full records (50 credits)",
        "placeholder": ""
      }
    ]
  },
  {
    "id": "reput",
    "group": "domain",
    "name": "Domain trust score",
    "endpoint": "GET /domain-reputation/api/v2",
    "provider": "whoisxml",
    "note": "0–100 reputation with WHOIS and SSL sanity checks",
    "state": "active",
    "requires": [],
    "feeds": [],
    "costPaisa": 0,
    "credits": 1,
    "screenshots": 0,
    "needsCompanyUnlock": false,
    "needsDirectorUnlock": false,
    "always": false,
    "admin": false,
    "params": [
      {
        "key": "domainName",
        "label": "Domain",
        "required": true,
        "fromVendor": "domain",
        "fromResult": null,
        "type": "text",
        "options": [],
        "default": "",
        "placeholder": "example.com"
      },
      {
        "key": "mode",
        "label": "Depth",
        "required": false,
        "fromVendor": null,
        "fromResult": null,
        "type": "select",
        "options": [
          "fast",
          "full"
        ],
        "default": "fast",
        "placeholder": ""
      }
    ]
  },
  {
    "id": "ssl",
    "group": "domain",
    "name": "SSL certificate",
    "endpoint": "GET /ssl-certificates/api/v1",
    "provider": "whoisxml",
    "note": "Issuer, validity window, wildcard coverage — current certificate only",
    "state": "active",
    "requires": [],
    "feeds": [],
    "costPaisa": 0,
    "credits": 1,
    "screenshots": 0,
    "needsCompanyUnlock": false,
    "needsDirectorUnlock": false,
    "always": false,
    "admin": false,
    "params": [
      {
        "key": "domainName",
        "label": "Domain",
        "required": true,
        "fromVendor": "domain",
        "fromResult": null,
        "type": "text",
        "options": [],
        "default": "",
        "placeholder": "example.com"
      }
    ]
  },
  {
    "id": "rwhois",
    "group": "domain",
    "name": "Other domains by the same owner",
    "endpoint": "POST /reverse-whois/api/v2",
    "provider": "whoisxml",
    "note": "Portfolio check — needs a registrant value from ownership history",
    "state": "active",
    "requires": [
      "whois"
    ],
    "feeds": [],
    "costPaisa": 0,
    "credits": 1,
    "screenshots": 0,
    "needsCompanyUnlock": false,
    "needsDirectorUnlock": false,
    "always": false,
    "admin": false,
    "params": [
      {
        "key": "searchTerm",
        "label": "Registrant email / name / organisation",
        "required": false,
        "fromVendor": null,
        "fromResult": "whois",
        "type": "text",
        "options": [],
        "default": "",
        "placeholder": "blank = taken from the ownership history result"
      },
      {
        "key": "searchType",
        "label": "Search",
        "required": false,
        "fromVendor": null,
        "fromResult": null,
        "type": "select",
        "options": [
          "current",
          "historic"
        ],
        "default": "current",
        "placeholder": ""
      }
    ]
  },
  {
    "id": "shot",
    "group": "domain",
    "name": "Website screenshot",
    "endpoint": "GET /website-screenshot/api/v1",
    "provider": "whoisxml",
    "note": "Live dated image embedded in the report",
    "state": "active",
    "requires": [],
    "feeds": [],
    "costPaisa": 0,
    "credits": 0,
    "screenshots": 1,
    "needsCompanyUnlock": false,
    "needsDirectorUnlock": false,
    "always": false,
    "admin": false,
    "params": [
      {
        "key": "url",
        "label": "Full website URL",
        "required": true,
        "fromVendor": "website",
        "fromResult": null,
        "type": "text",
        "options": [],
        "default": "",
        "placeholder": "https://example.com"
      },
      {
        "key": "imageOutputFormat",
        "label": "Image format",
        "required": false,
        "fromVendor": null,
        "fromResult": null,
        "type": "select",
        "options": [
          "JPG",
          "PNG"
        ],
        "default": "JPG",
        "placeholder": ""
      }
    ]
  },
  {
    "id": "avail",
    "group": "web",
    "name": "Website existence check",
    "endpoint": "GET /wayback/available?url={domain}",
    "provider": "archive",
    "note": "Has the site ever been archived, and when was it last captured",
    "state": "active",
    "requires": [],
    "feeds": [],
    "costPaisa": 0,
    "credits": 0,
    "screenshots": 0,
    "needsCompanyUnlock": false,
    "needsDirectorUnlock": false,
    "always": false,
    "admin": false,
    "params": [
      {
        "key": "url",
        "label": "Domain",
        "required": true,
        "fromVendor": "domain",
        "fromResult": null,
        "type": "text",
        "options": [],
        "default": "",
        "placeholder": "example.com"
      },
      {
        "key": "timestamp",
        "label": "Closest to date",
        "required": false,
        "fromVendor": null,
        "fromResult": null,
        "type": "date",
        "options": [],
        "default": "",
        "placeholder": ""
      }
    ]
  },
  {
    "id": "cdx",
    "group": "web",
    "name": "Full web presence timeline",
    "endpoint": "GET /cdx/search/cdx",
    "provider": "archive",
    "note": "When the site went live, outage periods, content-change events",
    "state": "active",
    "requires": [],
    "feeds": [
      "S3"
    ],
    "costPaisa": 0,
    "credits": 0,
    "screenshots": 0,
    "needsCompanyUnlock": false,
    "needsDirectorUnlock": false,
    "always": false,
    "admin": false,
    "params": [
      {
        "key": "url",
        "label": "Domain",
        "required": true,
        "fromVendor": "domain",
        "fromResult": null,
        "type": "text",
        "options": [],
        "default": "",
        "placeholder": "example.com"
      },
      {
        "key": "matchType",
        "label": "Scope",
        "required": false,
        "fromVendor": null,
        "fromResult": null,
        "type": "select",
        "options": [
          "domain — all pages",
          "prefix",
          "exact — homepage only"
        ],
        "default": "domain — all pages",
        "placeholder": ""
      },
      {
        "key": "limit",
        "label": "Max snapshots",
        "required": false,
        "fromVendor": null,
        "fromResult": null,
        "type": "number",
        "options": [],
        "default": "50",
        "placeholder": ""
      },
      {
        "key": "from",
        "label": "From date",
        "required": false,
        "fromVendor": null,
        "fromResult": null,
        "type": "date",
        "options": [],
        "default": "",
        "placeholder": ""
      },
      {
        "key": "to",
        "label": "To date",
        "required": false,
        "fromVendor": null,
        "fromResult": null,
        "type": "date",
        "options": [],
        "default": "",
        "placeholder": ""
      }
    ]
  },
  {
    "id": "mentions",
    "group": "web",
    "name": "Additional archive mentions",
    "endpoint": "GET /advancedsearch.php",
    "provider": "archive",
    "note": "Usually empty for smaller companies — every hit needs relevance review",
    "state": "active",
    "requires": [],
    "feeds": [],
    "costPaisa": 0,
    "credits": 0,
    "screenshots": 0,
    "needsCompanyUnlock": false,
    "needsDirectorUnlock": false,
    "always": false,
    "admin": false,
    "params": [
      {
        "key": "q",
        "label": "Search term",
        "required": true,
        "fromVendor": "name",
        "fromResult": null,
        "type": "text",
        "options": [],
        "default": "",
        "placeholder": "company name"
      },
      {
        "key": "rows",
        "label": "Max results",
        "required": false,
        "fromVendor": null,
        "fromResult": null,
        "type": "number",
        "options": [],
        "default": "50",
        "placeholder": ""
      }
    ]
  },
  {
    "id": "dup",
    "group": "internal",
    "name": "Duplicate vendor",
    "endpoint": "in-house",
    "provider": "in_house",
    "note": "Matching GST, PAN or address already in the vendor master",
    "state": "active",
    "requires": [],
    "feeds": [],
    "costPaisa": 0,
    "credits": 0,
    "screenshots": 0,
    "needsCompanyUnlock": false,
    "needsDirectorUnlock": false,
    "always": false,
    "admin": false,
    "params": []
  },
  {
    "id": "rp",
    "group": "internal",
    "name": "Related party",
    "endpoint": "in-house, over MCA director data",
    "provider": "in_house",
    "note": "Shared directors or addresses with an existing vendor",
    "state": "active",
    "requires": [
      "dirs"
    ],
    "feeds": [],
    "costPaisa": 0,
    "credits": 0,
    "screenshots": 0,
    "needsCompanyUnlock": false,
    "needsDirectorUnlock": false,
    "always": false,
    "admin": false,
    "params": []
  },
  {
    "id": "conflict",
    "group": "internal",
    "name": "Director conflict of interest",
    "endpoint": "in-house, over MCA director data",
    "provider": "in_house",
    "note": "Overlap between vendor directors and employee records",
    "state": "active",
    "requires": [
      "dirs"
    ],
    "feeds": [
      "A3"
    ],
    "costPaisa": 0,
    "credits": 0,
    "screenshots": 0,
    "needsCompanyUnlock": false,
    "needsDirectorUnlock": false,
    "always": false,
    "admin": false,
    "params": []
  },
  {
    "id": "ustatus",
    "group": "admin",
    "name": "Unlock status check",
    "endpoint": "GET /v1/companies/{cin}/unlock",
    "provider": "filesure",
    "note": "Free. The unlock lifecycle runs this before any paid unlock whether or not it is ticked; tick it to see the result on the findings page",
    "state": "active",
    "requires": [],
    "feeds": [],
    "costPaisa": 0,
    "credits": 0,
    "screenshots": 0,
    "needsCompanyUnlock": false,
    "needsDirectorUnlock": false,
    "always": false,
    "admin": true,
    "params": [
      {
        "key": "cin",
        "label": "CIN",
        "required": true,
        "fromVendor": "cin",
        "fromResult": null,
        "type": "text",
        "options": [],
        "default": "",
        "placeholder": "U21029MH2013PTC245119"
      }
    ]
  },
  {
    "id": "refresh",
    "group": "admin",
    "name": "Refresh company data from MCA",
    "endpoint": "POST /v1/companies/{cin}/update",
    "provider": "filesure",
    "note": "Async job, ~15 seconds. 48-hour cooldown before it can run again",
    "state": "active",
    "requires": [],
    "feeds": [],
    "costPaisa": 15000,
    "credits": 0,
    "screenshots": 0,
    "needsCompanyUnlock": false,
    "needsDirectorUnlock": false,
    "always": false,
    "admin": true,
    "params": [
      {
        "key": "cin",
        "label": "CIN",
        "required": true,
        "fromVendor": "cin",
        "fromResult": null,
        "type": "text",
        "options": [],
        "default": "",
        "placeholder": "U21029MH2013PTC245119"
      }
    ]
  },
  {
    "id": "usage",
    "group": "admin",
    "name": "Wallet balance and usage",
    "endpoint": "GET /v1/account/usage",
    "provider": "filesure",
    "note": "Spend by endpoint over the last 30 days",
    "state": "active",
    "requires": [],
    "feeds": [],
    "costPaisa": 0,
    "credits": 0,
    "screenshots": 0,
    "needsCompanyUnlock": false,
    "needsDirectorUnlock": false,
    "always": false,
    "admin": true,
    "params": []
  },
  {
    "id": "gst",
    "group": "tax",
    "name": "GST registration and status",
    "endpoint": "GET /commonapi/{v}/search?action=SEARCHGSTIN",
    "provider": "finagg",
    "note": "Registration status, taxpayer type, constitution, principal address",
    "state": "active",
    "requires": [],
    "feeds": [
      "C1",
      "C3",
      "C4",
      "C5"
    ],
    "costPaisa": 0,
    "credits": 0,
    "screenshots": 0,
    "needsCompanyUnlock": false,
    "needsDirectorUnlock": false,
    "always": false,
    "admin": false,
    "params": [
      {
        "key": "gstin",
        "label": "GSTIN",
        "required": true,
        "fromVendor": "gst",
        "fromResult": null,
        "type": "text",
        "options": [],
        "default": "",
        "placeholder": "27AAACX1234C1ZV"
      }
    ]
  },
  {
    "id": "gstret",
    "group": "tax",
    "name": "GST return filing history",
    "endpoint": "GET /commonapi/{v}/returns?action=RETTRACK",
    "provider": "finagg",
    "note": "Filed periods and dates — no invoice data, no consent needed",
    "state": "active",
    "requires": [
      "gst"
    ],
    "feeds": [
      "C2"
    ],
    "costPaisa": 0,
    "credits": 0,
    "screenshots": 0,
    "needsCompanyUnlock": false,
    "needsDirectorUnlock": false,
    "always": false,
    "admin": false,
    "params": [
      {
        "key": "gstin",
        "label": "GSTIN",
        "required": true,
        "fromVendor": "gst",
        "fromResult": null,
        "type": "text",
        "options": [],
        "default": "",
        "placeholder": "27AAACX1234C1ZV"
      },
      {
        "key": "fy",
        "label": "Financial year",
        "required": false,
        "fromVendor": null,
        "fromResult": null,
        "type": "text",
        "options": [],
        "default": "",
        "placeholder": "2025-26"
      }
    ]
  },
  {
    "id": "courtsearch",
    "group": "rep",
    "name": "Court case search",
    "endpoint": "GET /search",
    "provider": "ecourts",
    "note": "Cases naming this party, with petitioner/respondent so the side is visible",
    "state": "active",
    "requires": [],
    "feeds": [],
    "costPaisa": 0,
    "credits": 0,
    "screenshots": 0,
    "needsCompanyUnlock": false,
    "needsDirectorUnlock": false,
    "always": false,
    "admin": false,
    "params": [
      {
        "key": "parties",
        "label": "Party name",
        "required": true,
        "fromVendor": "legal_name",
        "fromResult": null,
        "type": "text",
        "options": [],
        "default": "",
        "placeholder": "MERIDIAN PACKAGING PRIVATE LIMITED"
      },
      {
        "key": "courtCodes",
        "label": "Court codes",
        "required": false,
        "fromVendor": null,
        "fromResult": null,
        "type": "text",
        "options": [],
        "default": "",
        "placeholder": "DLHC01"
      },
      {
        "key": "filingDateFrom",
        "label": "Filed since",
        "required": false,
        "fromVendor": null,
        "fromResult": null,
        "type": "date",
        "options": [],
        "default": "",
        "placeholder": ""
      }
    ]
  },
  {
    "id": "courthearing",
    "group": "rep",
    "name": "Upcoming hearings",
    "endpoint": "POST /causelist/cnr/batch",
    "provider": "ecourts",
    "note": "Which matched cases are listed for hearing — active, not merely historical",
    "state": "active",
    "requires": [
      "courtsearch"
    ],
    "feeds": [],
    "costPaisa": 0,
    "credits": 0,
    "screenshots": 0,
    "needsCompanyUnlock": false,
    "needsDirectorUnlock": false,
    "always": false,
    "admin": false,
    "params": []
  },
  {
    "id": "casedetail",
    "group": "rep",
    "name": "Case detail",
    "endpoint": "GET /case/{cnr}",
    "provider": "ecourts",
    "note": "Full record for one case, including its order list",
    "state": "active",
    "requires": [],
    "feeds": [],
    "costPaisa": 0,
    "credits": 0,
    "screenshots": 0,
    "needsCompanyUnlock": false,
    "needsDirectorUnlock": false,
    "always": false,
    "admin": false,
    "params": [
      {
        "key": "cnr",
        "label": "CNR",
        "required": true,
        "fromVendor": null,
        "fromResult": "courtsearch",
        "type": "text",
        "options": [],
        "default": "",
        "placeholder": "DLHC010001232024"
      }
    ]
  },
  {
    "id": "courtorders",
    "group": "rep",
    "name": "Order text",
    "endpoint": "GET /case/{cnr}/order-md/{file}",
    "provider": "ecourts",
    "note": "What the orders actually say — capped by VBC_ECOURTS_MAX_ORDERS",
    "state": "active",
    "requires": [
      "casedetail"
    ],
    "feeds": [],
    "costPaisa": 0,
    "credits": 0,
    "screenshots": 0,
    "needsCompanyUnlock": false,
    "needsDirectorUnlock": false,
    "always": false,
    "admin": false,
    "params": []
  },
  {
    "id": "courtorderai",
    "group": "rep",
    "name": "Order analysis (provider model)",
    "endpoint": "GET /case/{cnr}/order-ai/{file}",
    "provider": "ecourts",
    "note": "PROVIDER-GENERATED analysis, not registry fact. See scope decision 1.",
    "state": "active",
    "requires": [
      "casedetail"
    ],
    "feeds": [],
    "costPaisa": 0,
    "credits": 0,
    "screenshots": 0,
    "needsCompanyUnlock": false,
    "needsDirectorUnlock": false,
    "always": false,
    "admin": false,
    "params": []
  },
  {
    "id": "causelist",
    "group": "rep",
    "name": "Cause list search",
    "endpoint": "GET /causelist/search",
    "provider": "ecourts",
    "note": "Scheduled hearings naming this party — fuzzy match, analyst confirms identity",
    "state": "active",
    "requires": [],
    "feeds": [],
    "costPaisa": 0,
    "credits": 0,
    "screenshots": 0,
    "needsCompanyUnlock": false,
    "needsDirectorUnlock": false,
    "always": false,
    "admin": false,
    "params": [
      {
        "key": "litigant",
        "label": "Party name",
        "required": true,
        "fromVendor": "legal_name",
        "fromResult": null,
        "type": "text",
        "options": [],
        "default": "",
        "placeholder": ""
      },
      {
        "key": "state",
        "label": "State code",
        "required": false,
        "fromVendor": null,
        "fromResult": null,
        "type": "text",
        "options": [],
        "default": "",
        "placeholder": "MH"
      },
      {
        "key": "limit",
        "label": "Max rows",
        "required": false,
        "fromVendor": null,
        "fromResult": null,
        "type": "number",
        "options": [],
        "default": "100",
        "placeholder": ""
      },
      {
        "key": "offset",
        "label": "Skip rows",
        "required": false,
        "fromVendor": null,
        "fromResult": null,
        "type": "number",
        "options": [],
        "default": "0",
        "placeholder": ""
      }
    ]
  },
  {
    "id": "courtcaps",
    "group": "admin",
    "name": "Court search capabilities",
    "endpoint": "GET /search/capabilities",
    "provider": "ecourts",
    "note": "Which filters and name-match modes Case Search supports. Free.",
    "state": "active",
    "requires": [],
    "feeds": [],
    "costPaisa": 0,
    "credits": 0,
    "screenshots": 0,
    "needsCompanyUnlock": false,
    "needsDirectorUnlock": false,
    "always": false,
    "admin": true,
    "params": []
  },
  {
    "id": "courtenums",
    "group": "admin",
    "name": "Court enum reference",
    "endpoint": "GET /enums",
    "provider": "ecourts",
    "note": "Live case-status and bench-type codes. Free of charge, authenticated.",
    "state": "active",
    "requires": [],
    "feeds": [],
    "costPaisa": 0,
    "credits": 0,
    "screenshots": 0,
    "needsCompanyUnlock": false,
    "needsDirectorUnlock": false,
    "always": false,
    "admin": true,
    "params": [
      {
        "key": "types",
        "label": "Enum types",
        "required": false,
        "fromVendor": null,
        "fromResult": null,
        "type": "text",
        "options": [],
        "default": "caseStatus,benchType",
        "placeholder": ""
      }
    ]
  },
  {
    "id": "courtstructure",
    "group": "admin",
    "name": "Court structure",
    "endpoint": "GET /causelist/court-structure/…",
    "provider": "ecourts",
    "note": "States, districts and complexes. High courts appear as districts.",
    "state": "active",
    "requires": [],
    "feeds": [],
    "costPaisa": 0,
    "credits": 0,
    "screenshots": 0,
    "needsCompanyUnlock": false,
    "needsDirectorUnlock": false,
    "always": false,
    "admin": true,
    "params": [
      {
        "key": "state",
        "label": "State code",
        "required": false,
        "fromVendor": null,
        "fromResult": null,
        "type": "text",
        "options": [],
        "default": "",
        "placeholder": "DL"
      },
      {
        "key": "districtCode",
        "label": "District code",
        "required": false,
        "fromVendor": null,
        "fromResult": null,
        "type": "text",
        "options": [],
        "default": "",
        "placeholder": "1"
      }
    ]
  },
  {
    "id": "courtdates",
    "group": "admin",
    "name": "Cause list available dates",
    "endpoint": "GET /causelist/available-dates",
    "provider": "ecourts",
    "note": "Which dates hold cause-list data. Free with auth.",
    "state": "active",
    "requires": [],
    "feeds": [],
    "costPaisa": 0,
    "credits": 0,
    "screenshots": 0,
    "needsCompanyUnlock": false,
    "needsDirectorUnlock": false,
    "always": false,
    "admin": true,
    "params": [
      {
        "key": "state",
        "label": "State code",
        "required": false,
        "fromVendor": null,
        "fromResult": null,
        "type": "text",
        "options": [],
        "default": "",
        "placeholder": "DL"
      },
      {
        "key": "districtCode",
        "label": "District code",
        "required": false,
        "fromVendor": null,
        "fromResult": null,
        "type": "text",
        "options": [],
        "default": "",
        "placeholder": ""
      },
      {
        "key": "courtComplexCode",
        "label": "Complex code",
        "required": false,
        "fromVendor": null,
        "fromResult": null,
        "type": "text",
        "options": [],
        "default": "",
        "placeholder": ""
      },
      {
        "key": "courtNo",
        "label": "Court room",
        "required": false,
        "fromVendor": null,
        "fromResult": null,
        "type": "text",
        "options": [],
        "default": "",
        "placeholder": ""
      },
      {
        "key": "court",
        "label": "Court identifier",
        "required": false,
        "fromVendor": null,
        "fromResult": null,
        "type": "text",
        "options": [],
        "default": "",
        "placeholder": ""
      }
    ]
  },
  {
    "id": "caserefresh",
    "group": "admin",
    "name": "Refresh a case from source",
    "endpoint": "POST /case/{cnr}/refresh",
    "provider": "ecourts",
    "note": "Async — queues a re-pull; the provider quotes 5-10 minutes",
    "state": "active",
    "requires": [],
    "feeds": [],
    "costPaisa": 0,
    "credits": 0,
    "screenshots": 0,
    "needsCompanyUnlock": false,
    "needsDirectorUnlock": false,
    "always": false,
    "admin": true,
    "params": [
      {
        "key": "cnr",
        "label": "CNR",
        "required": true,
        "fromVendor": null,
        "fromResult": "courtsearch",
        "type": "text",
        "options": [],
        "default": "",
        "placeholder": ""
      }
    ]
  },
  {
    "id": "courtchecks",
    "group": "admin",
    "name": "Legal checks on this account",
    "endpoint": "GET /legal-check",
    "provider": "ecourts",
    "note": "Every legal check submitted, with its risk band. Free.",
    "state": "active",
    "requires": [],
    "feeds": [],
    "costPaisa": 0,
    "credits": 0,
    "screenshots": 0,
    "needsCompanyUnlock": false,
    "needsDirectorUnlock": false,
    "always": false,
    "admin": true,
    "params": [
      {
        "key": "status",
        "label": "Status",
        "required": false,
        "fromVendor": null,
        "fromResult": null,
        "type": "select",
        "options": [
          "",
          "completed",
          "running",
          "failed"
        ],
        "default": "completed",
        "placeholder": ""
      },
      {
        "key": "page_size",
        "label": "Rows",
        "required": false,
        "fromVendor": null,
        "fromResult": null,
        "type": "number",
        "options": [],
        "default": "20",
        "placeholder": ""
      }
    ]
  },
  {
    "id": "pan",
    "group": "tax",
    "name": "PAN verification",
    "endpoint": "provider not selected",
    "provider": "none",
    "note": "Identity substantiation",
    "state": "not_configured",
    "requires": [],
    "feeds": [],
    "costPaisa": 0,
    "credits": 0,
    "screenshots": 0,
    "needsCompanyUnlock": false,
    "needsDirectorUnlock": false,
    "always": false,
    "admin": false,
    "params": []
  },
  {
    "id": "ofac",
    "group": "sanctions",
    "name": "OFAC / UN consolidated lists",
    "endpoint": "provider not selected",
    "provider": "none",
    "note": "",
    "state": "not_configured",
    "requires": [],
    "feeds": [],
    "costPaisa": 0,
    "credits": 0,
    "screenshots": 0,
    "needsCompanyUnlock": false,
    "needsDirectorUnlock": false,
    "always": false,
    "admin": false,
    "params": []
  },
  {
    "id": "eusanc",
    "group": "sanctions",
    "name": "EU consolidated sanctions",
    "endpoint": "provider not selected",
    "provider": "none",
    "note": "",
    "state": "not_configured",
    "requires": [],
    "feeds": [],
    "costPaisa": 0,
    "credits": 0,
    "screenshots": 0,
    "needsCompanyUnlock": false,
    "needsDirectorUnlock": false,
    "always": false,
    "admin": false,
    "params": []
  },
  {
    "id": "rbi",
    "group": "sanctions",
    "name": "RBI defaulter list",
    "endpoint": "provider not selected",
    "provider": "none",
    "note": "",
    "state": "not_configured",
    "requires": [],
    "feeds": [],
    "costPaisa": 0,
    "credits": 0,
    "screenshots": 0,
    "needsCompanyUnlock": false,
    "needsDirectorUnlock": false,
    "always": false,
    "admin": false,
    "params": []
  },
  {
    "id": "news",
    "group": "rep",
    "name": "Adverse news scan",
    "endpoint": "provider not selected",
    "provider": "none",
    "note": "",
    "state": "not_configured",
    "requires": [],
    "feeds": [],
    "costPaisa": 0,
    "credits": 0,
    "screenshots": 0,
    "needsCompanyUnlock": false,
    "needsDirectorUnlock": false,
    "always": false,
    "admin": false,
    "params": []
  },
  {
    "id": "court",
    "group": "rep",
    "name": "Litigation exposure",
    "endpoint": "POST /legal-check → GET /legal-check/{code}/report",
    "provider": "ecourts",
    "note": "Risk band with an identity-confidence score. NOT CONFIGURED: POST /legal-check returns 400 VALIDATION_ERROR with an empty details[] on every documented body shape, and the submit endpoint is absent from the published API docs. Awaiting the schema from eCourts. /legal-check/models confirms the account has model eCI-1.2 with company support, so this is a contract gap, not an entitlement one.",
    "state": "not_configured",
    "requires": [],
    "feeds": [],
    "costPaisa": 0,
    "credits": 0,
    "screenshots": 0,
    "needsCompanyUnlock": false,
    "needsDirectorUnlock": false,
    "always": false,
    "admin": false,
    "params": [
      {
        "key": "subjectName",
        "label": "Legal name to search",
        "required": true,
        "fromVendor": "legal_name",
        "fromResult": null,
        "type": "text",
        "options": [],
        "default": "",
        "placeholder": "MERIDIAN PACKAGING PRIVATE LIMITED"
      },
      {
        "key": "subjectType",
        "label": "Subject",
        "required": false,
        "fromVendor": null,
        "fromResult": null,
        "type": "select",
        "options": [
          "company",
          "individual"
        ],
        "default": "company",
        "placeholder": ""
      }
    ]
  },
  {
    "id": "reviews",
    "group": "rep",
    "name": "Online reviews",
    "endpoint": "provider not selected",
    "provider": "none",
    "note": "",
    "state": "not_configured",
    "requires": [],
    "feeds": [],
    "costPaisa": 0,
    "credits": 0,
    "screenshots": 0,
    "needsCompanyUnlock": false,
    "needsDirectorUnlock": false,
    "always": false,
    "admin": false,
    "params": []
  },
  {
    "id": "dirlist",
    "group": "rep",
    "name": "Business directory presence",
    "endpoint": "provider not selected",
    "provider": "none",
    "note": "",
    "state": "not_configured",
    "requires": [],
    "feeds": [],
    "costPaisa": 0,
    "credits": 0,
    "screenshots": 0,
    "needsCompanyUnlock": false,
    "needsDirectorUnlock": false,
    "always": false,
    "admin": false,
    "params": []
  }
] as const;

export const COMPANY_UNLOCK_PAISA = 33000 as const;

export const DIRECTOR_UNLOCK_PAISA = 5000 as const;

export const RISK_BASELINE = 50 as const;

export const RISK_RULES = [
  {
    "id": "r1",
    "points": 20,
    "label": "MCA registered and active",
    "needs": [
      "master"
    ]
  },
  {
    "id": "r2",
    "points": 10,
    "label": "Filings current",
    "needs": [
      "filings"
    ]
  },
  {
    "id": "r3",
    "points": 15,
    "label": "Filed financials show positive net worth",
    "needs": [
      "fin"
    ]
  },
  {
    "id": "r4",
    "points": 10,
    "label": "Domain older than 2 years",
    "needs": [
      "whois"
    ]
  },
  {
    "id": "r5",
    "points": 10,
    "label": "Continuous web presence, no outages",
    "needs": [
      "cdx"
    ]
  },
  {
    "id": "r6",
    "points": 5,
    "label": "Valid SSL from a trusted CA",
    "needs": [
      "ssl"
    ]
  },
  {
    "id": "r7",
    "points": -15,
    "label": "Open charge against the company",
    "needs": [
      "charges"
    ]
  },
  {
    "id": "r8",
    "points": -20,
    "label": "Duplicate vendor detected",
    "needs": [
      "dup"
    ]
  },
  {
    "id": "r9",
    "points": -10,
    "label": "Related party overlap",
    "needs": [
      "rp"
    ]
  },
  {
    "id": "r10",
    "points": 40,
    "label": "GST active",
    "needs": [
      "gst"
    ]
  },
  {
    "id": "r11",
    "points": -25,
    "label": "GST suspended",
    "needs": [
      "gst"
    ]
  },
  {
    "id": "r12",
    "points": -50,
    "label": "Sanctions / defaulter match",
    "needs": [
      "ofac",
      "rbi",
      "eusanc"
    ]
  },
  {
    "id": "r13",
    "points": -15,
    "label": "Adverse news or court records",
    "needs": [
      "news",
      "court"
    ]
  }
] as const;

export const RISK_BANDS = [
  {
    "key": "approve",
    "label": "APPROVE",
    "note": "Low risk. Standard onboarding.",
    "min": 80,
    "max": 100
  },
  {
    "key": "conditional",
    "label": "CONDITIONAL",
    "note": "Medium risk. Verify specific concerns with the vendor.",
    "min": 60,
    "max": 79
  },
  {
    "key": "deep",
    "label": "DEEP REVIEW",
    "note": "Significant risks. Senior analyst review required.",
    "min": 40,
    "max": 59
  },
  {
    "key": "reject",
    "label": "REJECT",
    "note": "High risk profile. Decline or escalate.",
    "min": 0,
    "max": 39
  }
] as const;

export const FIELD_CATEGORIES = [
  "Premises",
  "Compliance",
  "Commercial",
  "Custom"
] as const;

export const MANUAL_TEMPLATES = [
  {
    "id": "m1",
    "label": "Physical availability of office",
    "type": "Yes / No",
    "category": "Premises",
    "options": [
      "Yes",
      "No"
    ],
    "mapsTo": null,
    "mapWhen": {},
    "hint": ""
  },
  {
    "id": "m2",
    "label": "Office ownership",
    "type": "Choice",
    "category": "Premises",
    "options": [
      "Owned",
      "Rented",
      "Shared",
      "Not verified"
    ],
    "mapsTo": "S5",
    "mapWhen": {
      "Owned": "Owned",
      "Rented": "Rented"
    },
    "hint": ""
  },
  {
    "id": "m3",
    "label": "Signage / nameboard present at premises",
    "type": "Yes / No",
    "category": "Premises",
    "options": [
      "Yes",
      "No"
    ],
    "mapsTo": null,
    "mapWhen": {},
    "hint": ""
  },
  {
    "id": "m4",
    "label": "Staff present at time of visit",
    "type": "Number",
    "category": "Premises",
    "options": [],
    "mapsTo": null,
    "mapWhen": {},
    "hint": ""
  },
  {
    "id": "m5",
    "label": "Site visit date",
    "type": "Date",
    "category": "Premises",
    "options": [],
    "mapsTo": null,
    "mapWhen": {},
    "hint": ""
  },
  {
    "id": "m6",
    "label": "GST status (checked manually on the portal)",
    "type": "Choice",
    "category": "Compliance",
    "options": [
      "Active",
      "Suspended",
      "Cancelled",
      "Not registered"
    ],
    "mapsTo": "C4",
    "mapWhen": {
      "Active": "No",
      "Suspended": "Yes",
      "Cancelled": "Yes"
    },
    "hint": "Stopgap until the GST API is configured"
  },
  {
    "id": "m7",
    "label": "GST certificate collected",
    "type": "Yes / No",
    "category": "Compliance",
    "options": [
      "Yes",
      "No"
    ],
    "mapsTo": null,
    "mapWhen": {},
    "hint": ""
  },
  {
    "id": "m8",
    "label": "PAN card copy collected",
    "type": "Yes / No",
    "category": "Compliance",
    "options": [
      "Yes",
      "No"
    ],
    "mapsTo": null,
    "mapWhen": {},
    "hint": ""
  },
  {
    "id": "m9",
    "label": "Cancelled cheque / bank proof collected",
    "type": "Yes / No",
    "category": "Compliance",
    "options": [
      "Yes",
      "No"
    ],
    "mapsTo": null,
    "mapWhen": {},
    "hint": ""
  },
  {
    "id": "m10",
    "label": "Self-declaration signed by vendor",
    "type": "Yes / No",
    "category": "Compliance",
    "options": [
      "Yes",
      "No"
    ],
    "mapsTo": null,
    "mapWhen": {},
    "hint": ""
  },
  {
    "id": "m11",
    "label": "Principal authorisation letter (dealers only)",
    "type": "Yes / No",
    "category": "Compliance",
    "options": [
      "Yes",
      "No",
      "Not applicable"
    ],
    "mapsTo": null,
    "mapWhen": {},
    "hint": ""
  },
  {
    "id": "m12",
    "label": "Type of business",
    "type": "Choice",
    "category": "Commercial",
    "options": [
      "Manufacturer/ Services",
      "Wholesaler",
      "Retailer/ Trader"
    ],
    "mapsTo": "S4",
    "mapWhen": {
      "Manufacturer/ Services": "Manufacturer/ Services",
      "Wholesaler": "Wholesaler",
      "Retailer/ Trader": "Retailer/ Trader"
    },
    "hint": ""
  },
  {
    "id": "m13",
    "label": "Credit period offered (days)",
    "type": "Number",
    "category": "Commercial",
    "options": [],
    "mapsTo": null,
    "mapWhen": {},
    "hint": ""
  },
  {
    "id": "m14",
    "label": "Named reference — company",
    "type": "Text",
    "category": "Commercial",
    "options": [],
    "mapsTo": null,
    "mapWhen": {},
    "hint": ""
  },
  {
    "id": "m15",
    "label": "Reference feedback",
    "type": "Choice",
    "category": "Commercial",
    "options": [
      "Good",
      "Average",
      "Poor"
    ],
    "mapsTo": "A4",
    "mapWhen": {
      "Good": "Good",
      "Average": "Average",
      "Poor": "Poor"
    },
    "hint": ""
  },
  {
    "id": "m16",
    "label": "Certifications held (ISO / FSSAI / other)",
    "type": "Text",
    "category": "Commercial",
    "options": [],
    "mapsTo": null,
    "mapWhen": {},
    "hint": ""
  },
  {
    "id": "m17",
    "label": "Years of dealing with us",
    "type": "Number",
    "category": "Commercial",
    "options": [],
    "mapsTo": null,
    "mapWhen": {},
    "hint": ""
  }
] as const;

