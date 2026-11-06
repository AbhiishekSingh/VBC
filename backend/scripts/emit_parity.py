#!/usr/bin/env python3
"""Emit expected scoring outputs from the PYTHON engine, for the TS parity test.

The frontend mirrors the scoring engines so the SCAN page can recalculate
without a round-trip. That mirror is only safe if something proves the two
implementations agree. This script runs the authoritative Python engine over
the shared fixtures and writes its answers to JSON; the Vitest parity suite
runs the TypeScript engine over the same inputs and asserts equality.

If this file and the TS output disagree, the frontend is scoring vendors
differently from the backend and the build must fail.
"""
from __future__ import annotations
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.domain.scoring import score_scan, score_risk, score_surveillance   # noqa: E402
from app.domain.policy import apply_policy, DEFAULT_POLICY, PROTOTYPE_POLICY  # noqa: E402
from app.domain.validation import check_value, split_subjects  # noqa: E402
from app.catalog.scan import SCAN_PARAMETERS  # noqa: E402
from app.tests import fixtures as fx  # noqa: E402

OUT = ROOT.parent / "frontend" / "src" / "scoring" / "parity-expected.json"


def scan_payload(ratings):
    s = score_scan(ratings)
    return {
        "weighted": s.weighted, "best": s.best, "pct": s.pct,
        "applicable": s.applicable, "passed": s.passed, "verdict": s.verdict,
        "tolerance60": s.tolerance_60, "assessmentEvaluated": s.assessment_evaluated,
        "coverageNote": s.coverage_note,
        "pillars": {k.value: {"applicable": p.applicable, "G": p.G, "Y": p.Y,
                              "R": p.R, "positives": p.positives,
                              "weighted": p.weighted, "max": p.max}
                    for k, p in s.pillars.items()},
    }


def risk_payload(checks, selected):
    r = score_risk(checks, selected)
    return {"score": r.score, "raw": r.raw, "band": r.band.label, "dead": r.dead,
            "gained": r.gained, "lost": r.lost,
            "ledger": [{"id": l.id, "state": l.state.value, "applied": l.applied,
                        "contribution": l.contribution,
                        "explanation": l.explanation} for l in r.ledger]}


def sv_payload(values, done=True):
    s = score_surveillance(values, done=done)
    return {"done": s.done, "applicable": s.applicable, "positives": s.positives,
            "pct": s.pct, "gateFailed": s.gate_failed, "passed": s.passed,
            "verdict": s.verdict, "scanValue": s.scan_value}


def policy_payload(ratings, policy):
    g = apply_policy(score_scan(ratings), policy=policy)
    return {"verdict": g.verdict.value, "rawVerdict": g.raw_verdict.value,
            "gated": g.gated, "policyVersion": g.policy_version,
            "reasonCount": len(g.reasons), "headline": g.headline}


# --- validation ------------------------------------------------------
#
# The format rules are mirrored by hand in `frontend/src/lib/validate.ts`,
# and until now nothing proved the two agreed. Scoring has had a parity
# test since the engines were written, for the obvious reason; validation
# earned one the moment a field stopped being a single regex test.
#
# `mobile` and `uan` hold a LIST, and their normalisation — a pasted +91,
# a leading 0, spaces — is procedural rather than expressible in the
# pattern the two languages share. So the mirror can now be wrong in a way
# a shared regex could not be, and the failure mode is a field that
# accepts a value the runner would send differently.
VALIDATION_CASES: list[tuple[str, str]] = [
    ("mobile", "9876543210"),
    ("mobile", "+919876543210"),
    ("mobile", "09876543210"),
    ("mobile", "98765 43210"),
    ("mobile", "+91-98765-43210"),
    ("mobile", "5876543210"),
    ("mobile", "987654321"),
    ("mobile", ""),
    ("mobile", "9876543210\n9876543211\n9876543212"),
    ("mobile", "9876543210, 9876543211; 9876543212"),
    ("mobile", "9876543210\n5876543211"),
    ("mobile", "9876543210\n\n9876543210"),
    ("uan", "100123456789"),
    ("uan", "100123456789\n100123456780"),
    ("uan", "10012345678"),
    ("gstin", "27AANCB8469J1ZS"),
    ("gstin", "29AANCB8469J1ZS"),
    ("cin", "U93090MH2011PTC215361"),
    ("cin", "AAA-1234"),
    ("cin", "NOT-A-CIN"),
    ("pan", "ABCDE1234F"),
    ("din", "09054126"),
    ("cnr", "MHAU010012342024"),
    ("domainName", "https://example.com"),
]

SUBJECT_CASES = [
    "9876543210",
    "+919876543210\n09876543211\n91 98765 43212",
    "9876543210, 9876543210",
    "9876543212\n9876543210",
    "",
    "   ",
    "abc",
]

all_first = {p.id: p.options[0][0] for p in SCAN_PARAMETERS}
all_worst = {p.id: p.options[-1][0] for p in SCAN_PARAMETERS}

data = {
  "scan": {
    "azahan": {"input": fx.AZAHAN_SCAN, "expected": scan_payload(fx.AZAHAN_SCAN)},
    "meridian": {"input": fx.MERIDIAN_SCAN, "expected": scan_payload(fx.MERIDIAN_SCAN)},
    "kaveri": {"input": fx.KAVERI_SCAN, "expected": scan_payload(fx.KAVERI_SCAN)},
    "kaveriNoManualGst": {"input": fx.KAVERI_SCAN_WITHOUT_MANUAL_GST,
                          "expected": scan_payload(fx.KAVERI_SCAN_WITHOUT_MANUAL_GST)},
    "empty": {"input": {}, "expected": scan_payload({})},
    "allBestOption": {"input": all_first, "expected": scan_payload(all_first)},
    "allWorstOption": {"input": all_worst, "expected": scan_payload(all_worst)},
    "oddYellow": {"input": {"N1": "Industry"}, "expected": scan_payload({"N1": "Industry"})},
    "twoYellows": {"input": {"N1": "Industry", "N2": "1 to 5"},
                   "expected": scan_payload({"N1": "Industry", "N2": "1 to 5"})},
    "unknownValue": {"input": {"S1": "not a real option"},
                     "expected": scan_payload({"S1": "not a real option"})},
  },
  "risk": {
    "azahan": {"selected": fx.AZAHAN_SELECTED,
               "checks": {k: {"status": v.status.value, "value": v.value}
                          for k, v in fx.AZAHAN_CHECKS.items()},
               "expected": risk_payload(fx.AZAHAN_CHECKS, fx.AZAHAN_SELECTED)},
    "meridian": {"selected": fx.MERIDIAN_SELECTED,
                 "checks": {k: {"status": v.status.value, "value": v.value}
                            for k, v in fx.MERIDIAN_CHECKS.items()},
                 "expected": risk_payload(fx.MERIDIAN_CHECKS, fx.MERIDIAN_SELECTED)},
    "kaveri": {"selected": fx.KAVERI_SELECTED,
               "checks": {k: {"status": v.status.value, "value": v.value}
                          for k, v in fx.KAVERI_CHECKS.items()},
               "expected": risk_payload(fx.KAVERI_CHECKS, fx.KAVERI_SELECTED)},
    "nothing": {"selected": [], "checks": {}, "expected": risk_payload({}, [])},
  },
  "surveillance": {
    "meridian": {"input": fx.MERIDIAN_SURVEILLANCE, "done": True,
                 "expected": sv_payload(fx.MERIDIAN_SURVEILLANCE)},
    "hardGateFails": {"input": {**fx.MERIDIAN_SURVEILLANCE, "V1": "No"}, "done": True,
                      "expected": sv_payload({**fx.MERIDIAN_SURVEILLANCE, "V1": "No"})},
    "notConducted": {"input": {}, "done": False, "expected": sv_payload({}, done=False)},
  },
  "validation": {
    "checkValue": [
      {"key": key, "value": value,
       "expected": (None if (p := check_value(key, value)) is None
                    else {"level": p.level, "message": p.message})}
      for key, value in VALIDATION_CASES
    ],
    "splitSubjects": [
      {"value": value, "expected": split_subjects(value)}
      for value in SUBJECT_CASES
    ],
  },
  "policy": {
    "azahanDefault": {"input": fx.AZAHAN_SCAN, "policy": "default",
                      "expected": policy_payload(fx.AZAHAN_SCAN, DEFAULT_POLICY)},
    "azahanPrototype": {"input": fx.AZAHAN_SCAN, "policy": "prototype",
                        "expected": policy_payload(fx.AZAHAN_SCAN, PROTOTYPE_POLICY)},
    "meridianDefault": {"input": fx.MERIDIAN_SCAN, "policy": "default",
                        "expected": policy_payload(fx.MERIDIAN_SCAN, DEFAULT_POLICY)},
    "kaveriDefault": {"input": fx.KAVERI_SCAN, "policy": "default",
                      "expected": policy_payload(fx.KAVERI_SCAN, DEFAULT_POLICY)},
  },
}

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(data, indent=2, ensure_ascii=False))
cases = sum(len(v) for v in data.values())
print(f"OK   wrote {OUT.name} — {cases} parity cases from the Python engine")
