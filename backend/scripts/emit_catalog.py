#!/usr/bin/env python3
"""Emit the catalog and fixtures as TypeScript.

WHY THIS EXISTS
---------------
The frontend needs the same 18 SCAN parameters, 13 surveillance parameters,
32 checks, 13 risk rules and 17 field templates that the backend has — with
identical option strings, identical ratings, identical weights. Maintaining
that by hand in two languages guarantees drift, and drift in an audit
product means two parts of the same system disagreeing about the same
vendor's score.

So the Python catalog is the single source of truth and this script
projects it into TypeScript. The generated file is checked in (so the
frontend builds without a Python toolchain) but must never be hand-edited:
CI regenerates it and fails if the output differs from what is committed.

Usage:  python3 backend/scripts/emit_catalog.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.catalog.checks import (  # noqa: E402
    CHECK_GROUPS,
    CHECKS,
    COMPANY_UNLOCK_PAISA,
    DIRECTOR_UNLOCK_PAISA,
)
from app.catalog.manual_fields import FIELD_CATEGORIES, MANUAL_TEMPLATES  # noqa: E402
from app.catalog.risk import RISK_BANDS, RISK_BASELINE, RISK_RULES  # noqa: E402
from app.catalog.scan import SCAN_PARAMETERS  # noqa: E402
from app.catalog.surveillance import (  # noqa: E402
    SURVEILLANCE_PARAMETERS,
    SURVEILLANCE_THRESHOLD_PCT,
)
from app.domain.types import PILLAR_NAMES, PILLAR_WEIGHTS  # noqa: E402

OUT = ROOT.parent / "frontend" / "src" / "catalog" / "generated.ts"

HEADER = """/* eslint-disable */
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

"""


def emit(name: str, value: object, type_annotation: str = "") -> str:
    payload = json.dumps(value, indent=2, ensure_ascii=False)
    suffix = f": {type_annotation}" if type_annotation else ""
    return f"export const {name}{suffix} = {payload} as const;\n\n"


def build() -> str:
    out = [HEADER]

    out.append(
        emit(
            "PILLARS",
            [
                {
                    "key": pillar.value,
                    "name": PILLAR_NAMES[pillar][0],
                    "subtitle": PILLAR_NAMES[pillar][1],
                    "weight": weight,
                }
                for pillar, weight in PILLAR_WEIGHTS.items()
            ],
        )
    )

    out.append(
        emit(
            "SCAN_PARAMETERS",
            [
                {
                    "id": p.id,
                    "pillar": p.pillar.value,
                    "label": p.label,
                    "source": p.source.value,
                    "feed": p.feed,
                    "fedBy": p.fed_by,
                    "options": [{"value": v, "rating": r.value} for v, r in p.options],
                }
                for p in SCAN_PARAMETERS
            ],
        )
    )

    out.append(
        emit(
            "SURVEILLANCE_PARAMETERS",
            [
                {
                    "id": p.id,
                    "label": p.label,
                    "hardGate": p.hard_gate,
                    "options": [{"value": v, "rating": r.value} for v, r in p.options],
                }
                for p in SURVEILLANCE_PARAMETERS
            ],
        )
    )

    out.append(emit("SURVEILLANCE_THRESHOLD_PCT", SURVEILLANCE_THRESHOLD_PCT))
    out.append(emit("CHECK_GROUPS", list(CHECK_GROUPS)))

    out.append(
        emit(
            "CHECKS",
            [
                {
                    "id": c.id,
                    "group": c.group,
                    "name": c.name,
                    "endpoint": c.endpoint,
                    "provider": c.provider.value,
                    "note": c.note,
                    "state": c.state.value,
                    "requires": list(c.requires),
                    "feeds": list(c.feeds),
                    "costPaisa": c.cost_paisa,
                    "credits": c.credits,
                    "screenshots": c.screenshots,
                    "needsCompanyUnlock": c.needs_company_unlock,
                    "needsDirectorUnlock": c.needs_director_unlock,
                    "always": c.always,
                    "admin": c.admin,
                    "params": [
                        {
                            "key": p.key,
                            "label": p.label,
                            "required": p.required,
                            "fromVendor": p.from_vendor,
                            "fromResult": p.from_result,
                            "type": p.type,
                            "options": list(p.options),
                            "default": p.default,
                            "placeholder": p.placeholder,
                        }
                        for p in c.params
                    ],
                }
                for c in CHECKS
            ],
        )
    )

    out.append(emit("COMPANY_UNLOCK_PAISA", COMPANY_UNLOCK_PAISA))
    out.append(emit("DIRECTOR_UNLOCK_PAISA", DIRECTOR_UNLOCK_PAISA))
    out.append(emit("RISK_BASELINE", RISK_BASELINE))

    out.append(
        emit(
            "RISK_RULES",
            [
                {
                    "id": r.id,
                    "points": r.points,
                    "label": r.label,
                    "needs": list(r.needs),
                }
                for r in RISK_RULES
            ],
        )
    )

    out.append(
        emit(
            "RISK_BANDS",
            [
                {
                    "key": b.key,
                    "label": b.label,
                    "note": b.note,
                    "min": b.min,
                    "max": b.max,
                }
                for b in RISK_BANDS
            ],
        )
    )

    out.append(emit("FIELD_CATEGORIES", list(FIELD_CATEGORIES)))

    out.append(
        emit(
            "MANUAL_TEMPLATES",
            [
                {
                    "id": t.id,
                    "label": t.label,
                    "type": t.type.value,
                    "category": t.category,
                    "options": list(t.options),
                    "mapsTo": t.maps_to,
                    "mapWhen": t.map_when,
                    "hint": t.hint,
                }
                for t in MANUAL_TEMPLATES
            ],
        )
    )

    return "".join(out)


def main() -> int:
    content = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)

    check_only = "--check" in sys.argv
    if check_only:
        if not OUT.exists():
            print(f"FAIL {OUT} does not exist. Run: npm run codegen", file=sys.stderr)
            return 1
        if OUT.read_text() != content:
            print(
                "FAIL The generated catalog is stale or was hand-edited.\n"
                "     The backend catalog and the frontend copy disagree, which\n"
                "     means the two would score the same vendor differently.\n"
                "     Fix with: npm run codegen",
                file=sys.stderr,
            )
            return 1
        print("OK   generated catalog matches the Python source")
        return 0

    OUT.write_text(content, encoding="utf-8")
    print(f"OK   wrote {OUT.relative_to(ROOT.parent)}")
    print(
        f"     {len(SCAN_PARAMETERS)} SCAN · {len(SURVEILLANCE_PARAMETERS)} field · "
        f"{len(CHECKS)} checks · {len(RISK_RULES)} rules · "
        f"{len(MANUAL_TEMPLATES)} templates"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
