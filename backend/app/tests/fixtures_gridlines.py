"""A REAL Gridlines response shape, with the person removed.

Captured 7 Nov 2026 from `/profile-api/mobile/digital-footprint`, by
calling the live endpoint with the production key straight from the
server — no VBC code in the path. It is the first response anybody on
this project has seen from this provider, and it settled a week of
guessing in one command.

THE VALUES ARE SYNTHETIC. The real response carried a named
individual's mobile number, the name his bank holds against it, and
which twenty-six consumer platforms he has accounts on. This repository
is public. The SHAPE is what has evidential value here; the person does
not belong in it, and a fixture is not a reason to put him there.

What the shape proved, and the first parser got wrong:

  * `data` is a STATUS envelope — `code`, `message` — not the payload.
    The payload is one key further in, ending in `_data`.
  * That payload is a LIST OF BLOCKS keyed by `data_type`, interleaved
    with empty `status` and `status_code` blocks, so blocks must be read
    by name and never by index.
  * A platform has THREE states: `user_exist: true`, `user_exist:
    false`, and `error: true`. The third means "could not check".
  * `digital_age` appears twice, and the second copy came back
    `{"error": true}`.
  * A score can come back `{}` — computed for some numbers, not others.
"""

from __future__ import annotations

FOOTPRINT_LIVE = {
    "request_id": "00000000-0000-0000-0000-000000000000",
    "transaction_id": "00000000-0000-0000-0000-000000000001",
    "status": 200,
    "data": {
        "code": "1030",
        "message": "Fetched digital footprint data.",
        "digital_profile_data": [
            {
                "data_type": "phone_data",
                "primary_data": {
                    "key": "+919876543210",
                    "type": "phone",
                    "social_profile_count": 8,
                    "account_details": [
                        {"platform": "TIMES_PRIME", "error": True},
                        {"platform": "SHAADI", "error": True},
                        {"platform": "AMAZON", "user_exist": True},
                        {"platform": "FLIPKART", "user_exist": True},
                        {"platform": "SNAPDEAL", "user_exist": False},
                        {"platform": "HOUSING", "user_exist": False},
                        {"platform": "FACEBOOK", "user_exist": True},
                        {"platform": "INSTAGRAM", "user_exist": False},
                        {"platform": "SKYPE", "error": True},
                        {"platform": "MICROSOFT", "user_exist": True},
                        {"platform": "TWITTER", "user_exist": False},
                        {"platform": "WHATSAPP", "user_exist": True},
                        {"platform": "DIGILOCKER", "user_exist": True},
                        {"platform": "POLICYBAZAR", "error": True},
                        {"platform": "NOBROKER", "user_exist": True},
                        {"platform": "IRCTC", "user_exist": True},
                        {"platform": "SWIGGY", "user_exist": False},
                        {"platform": "PHONEPE", "error": True},
                    ],
                },
                "intelligence_data": {
                    "bank_verified_name": "TEST SUBJECT",
                    "verified_names_status": "found",
                    "associated_names": [
                        {"name": "TEST SUBJECT", "source": "s17",
                         "confidence_score": "high"},
                        {"name": "T SUBJECT", "source": "s04",
                         "confidence_score": "medium"},
                    ],
                    "verified_names": [{"name": "TEST SUBJECT", "source": "a4"}],
                    "digital_age": {"age": "1+", "year": 2025},
                },
            },
            {
                "data_type": "intelligence_data",
                # The SECOND copy, which came back errored on the real
                # response. The populated one above must win.
                "digital_age": {"error": True},
                "scores": [
                    # Empty on the real response — computed for some
                    # numbers and not others. Must not render as 0.
                    {"score_type": "phone_email_linking_score", "score_data": {}},
                    {"score_type": "finance_presence_score",
                     "score_data": {"checked": 0, "user_exist": 0}},
                    {"score_type": "ecommerce_presence_score",
                     "score_data": {"checked": 3, "user_exist": 1}},
                    {"score_type": "social_media_presence_score",
                     "score_data": {"checked": 3, "user_exist": 1}},
                    {"score_type": "onboarding_phone_risk_score",
                     "score_data": {"max_score_value": 1, "min_score_value": 0,
                                    "score_value": 0.173}},
                ],
                "fintech_count": 0,
            },
            {"data_type": "status_code"},
            {"data_type": "status"},
        ],
    },
    "timestamp": 1794015498228,
    "path": "/profile-api/mobile/digital-footprint",
}

#: The same envelope with nothing found. Not invented: `code` and
#: `message` ride on every response, so this is what an empty one has to
#: look like — and it must read as "no record", never as a parse gap.
FOOTPRINT_EMPTY = {
    "request_id": "00000000-0000-0000-0000-000000000002",
    "status": 200,
    "data": {"code": "1031", "message": "No digital footprint found.",
             "digital_profile_data": []},
    "timestamp": 1794015498229,
    "path": "/profile-api/mobile/digital-footprint",
}


#: The real `/profile-api/mobile/prefill` shape, captured 7 Nov 2026.
#: Values synthetic — the real one carried a named individual's PAN,
#: date of birth, email, two home addresses and an income band, and
#: this repository is public.
#:
#: What it settled, and what the first parser got wrong:
#:   * the payload is `data.personal_data`, and identity sits one level
#:     further in under `personal_information`;
#:   * `pan`, `email` and `alternate_phone` are SERIAL-WRAPPED —
#:     `[{"serial_number": "1", "value": …}]` — so a key lookup returns
#:     a LIST where a string was expected, and the PAN mask then ran
#:     over a stringified dict;
#:   * `address` is a list of records, each with its own
#:     `date_of_reporting`;
#:   * the response carries an INCOME BAND for the individual.
PREFILL_LIVE = {
    "request_id": "00000000-0000-0000-0000-000000000010",
    "transaction_id": "00000000-0000-0000-0000-000000000011",
    "status": 200,
    "data": {
        "code": "1015",
        "message": "Details retrieved successfully.",
        "personal_data": {
            "personal_information": {
                "full_name": "TEST SUBJECT",
                "gender": "MALE",
                "age": "41",
                "date_of_birth": "1985-02-03",
                "income": "3,00,001 - 4,00,000",
            },
            "alternate_phone": [
                {"serial_number": "2", "value": "9820011223"},
                {"serial_number": "1", "value": "9876543210"},
            ],
            "email": [{"serial_number": "1", "value": "TEST@EXAMPLE.COM"}],
            "address": [
                {"detailed_address": "ROOM NO 1 BLD 2 SAMPLE NAGAR",
                 "state": "MH", "pincode": "401501",
                 "date_of_reporting": "2026-11-03"},
                {"detailed_address": "FLAT 9 EXAMPLE SOCIETY",
                 "state": "MH", "pincode": "400068",
                 "date_of_reporting": "2024-10-31"},
            ],
            "document_data": {
                "pan": [{"serial_number": "1", "value": "ABCDE1234F"}],
            },
        },
    },
    "timestamp": 1794016702258,
    "path": "/profile-api/mobile/prefill",
}
