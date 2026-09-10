"""FinAGG GSP adapter — the parts that would silently produce a wrong score.

Two things are being defended here.

First, that only the consent-free endpoints exist. An OTP-gated call cannot
be made against a vendor who has not agreed to be audited, so an adapter
that grows one later would be shipping a check that can never run in the
flow it was written for. ``test_no_otp_surface`` fails if one appears.

Second, that an unreadable or unrecognised answer never reports as clean.
Every one of these cases produces a 200 from the provider, which is exactly
how a scoring bug gets past a green test suite.
"""

from __future__ import annotations

import httpx
import pytest

from app.config import Settings
from app.providers import finagg as fa
from app.providers.base import NotConfigured, ProviderParseGap


def _settings(**kw) -> Settings:
    base = dict(
        finagg_api_key="test-key",
        finagg_base_url="https://sandbox-gsp.finagg.in/basic/gstn",
        finagg_version="fin-v1",
        finagg_gsp_version="v1.3",
    )
    base.update(kw)
    return Settings(**base)


def _provider(handler, **kw) -> fa.FinaggProvider:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return fa.FinaggProvider(_settings(**kw), client=client)


def _code_strings(path: str) -> list[str]:
    """Every string literal in the module except docstrings."""
    import ast

    tree = ast.parse(open(path).read())
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if body and isinstance(body[0], ast.Expr) \
                    and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                docstrings.add(id(body[0].value))
    return [
        n.value for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
        and id(n) not in docstrings
    ]


GSTIN = "27AAACX1234C1ZV"

ACTIVE_SEARCH = {
    "data": {
        "gstin": GSTIN,
        "lgnm": "MERIDIAN PACKAGING PRIVATE LIMITED",
        "tradeNam": "Meridian Packaging",
        "sts": "Active",
        "dty": "Regular",
        "ctb": "Private Limited Company",
        "rgdt": "04/06/2013",
        "cxdt": "",
        "pradr": {
            "addr": {
                "bnm": "Sunrise Industrial Estate",
                "st": "MIDC Road",
                "loc": "Andheri East",
                "city": "Mumbai",
                "stcd": "Maharashtra",
                "pncd": "400093",
                "ntr": "Factory / Manufacturing, Warehouse/Depot",
            }
        },
        "stj": "Mumbai Ward 402",
    }
}


# ---------------------------------------------------------------------
# The structural guarantee
# ---------------------------------------------------------------------


def test_no_otp_surface():
    """No OTP-gated endpoint may be reachable from this adapter.

    FinAGG's Taxpayer APIs and File Download calls all require an auth
    token obtained by sending an OTP to the TAXPAYER's registered mobile.
    A vendor under assessment does not forward one, so a method that
    needed a token would be dead code that looked like coverage.
    """
    # Docstrings are excluded deliberately: the module SHOULD explain why
    # those endpoints are absent. What must not exist is a string the code
    # could actually put in a URL or a request body.
    for literal in _code_strings(fa.__file__):
        for forbidden in ("taxpayerapi", "OTPREQUEST", "AUTHTOKEN", "app_key",
                          "DOCDOWNLOAD", "FILEDET", "authenticate"):
            assert forbidden.lower() not in literal.lower(), (
                f"{forbidden!r} appears in executable code as {literal!r} — an "
                f"OTP-gated endpoint cannot be used against a non-consenting "
                f"vendor."
            )

    public = {n for n in dir(fa.FinaggProvider) if not n.startswith("_")}
    assert "search_gstin" in public and "returns_metadata" in public
    assert not {"authenticate", "auth_token", "otp"} & public


# ---------------------------------------------------------------------
# search — C1, C3, C4, C5
# ---------------------------------------------------------------------


def test_search_active_company():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-api-key"] == "test-key"
        assert request.url.params["action"] == "TP"
        assert request.url.params["gstin"] == GSTIN
        assert "/commonapi/" in str(request.url)
        return httpx.Response(200, json=ACTIVE_SEARCH)

    data = _provider(handler).search_gstin(GSTIN)

    assert data["is_active"] is True
    assert data["is_suspended"] is False
    assert data["is_composition"] is False
    assert data["legal_name"] == "MERIDIAN PACKAGING PRIVATE LIMITED"
    # GSTN dates really are day-first, unlike FileSure's company master.
    assert data["registered_on"] == "2013-06-04"
    assert data["premises_kind"] == "commercial"
    assert "Mumbai" in data["address"]


def test_suspended_is_detected():
    """The Kaveri case. A suspended GSTIN found here is the finding that
    flips a vendor from pass to fail, and it was previously reachable only
    through a manual entry."""
    payload = {"data": {**ACTIVE_SEARCH["data"], "sts": "Suspended"}}
    data = _provider(lambda r: httpx.Response(200, json=payload)).search_gstin(GSTIN)
    assert data["is_suspended"] is True
    assert data["is_active"] is False


def test_composition_read_from_dty_not_from_otp_endpoint():
    payload = {"data": {**ACTIVE_SEARCH["data"], "dty": "Composition"}}
    data = _provider(lambda r: httpx.Response(200, json=payload)).search_gstin(GSTIN)
    assert data["is_composition"] is True


@pytest.mark.parametrize("envelope", [
    lambda d: d,                       # bare
    lambda d: {"data": d},             # wrapped
    lambda d: {"data": {"data": d}},   # double-wrapped
])
def test_envelope_variations(envelope):
    """FinAGG's docs do not describe the envelope. Each shape a GSP might
    use has to reach the same fields, or C1–C5 silently go unwritten."""
    payload = envelope(ACTIVE_SEARCH["data"])
    data = _provider(lambda r: httpx.Response(200, json=payload)).search_gstin(GSTIN)
    assert data["is_active"] is True


def test_missing_status_is_a_parse_gap_not_a_pass():
    """A 200 whose status field is absent must not read as 'not suspended'."""
    payload = {"data": {"gstin": GSTIN, "lgnm": "SOMETHING LIMITED"}}
    with pytest.raises(ProviderParseGap) as exc:
        _provider(lambda r: httpx.Response(200, json=payload)).search_gstin(GSTIN)
    assert exc.value.payload is not None    # the response is kept for diagnosis


def test_no_residential_inference():
    """No nature-of-business declared means nothing was declared. It does
    NOT mean the premises are residential, and C5 must stay unset."""
    stripped = {"data": {**ACTIVE_SEARCH["data"],
                         "pradr": {"addr": {"city": "Mumbai", "pncd": "400093"}}}}
    data = _provider(lambda r: httpx.Response(200, json=stripped)).search_gstin(GSTIN)
    assert data["premises_kind"] is None


def test_malformed_gstin_rejected_before_any_call():
    called = []

    def handler(request):
        called.append(1)
        return httpx.Response(200, json=ACTIVE_SEARCH)

    with pytest.raises(ValueError):
        _provider(handler).search_gstin("NOT-A-GSTIN")
    assert not called, "a malformed GSTIN must not reach the provider"


def test_no_key_is_not_configured_not_failure():
    provider = fa.FinaggProvider(Settings(finagg_api_key=""))
    with pytest.raises(NotConfigured):
        provider.search_gstin(GSTIN)


# ---------------------------------------------------------------------
# returns metadata — C2
# ---------------------------------------------------------------------


RETURNS = {
    "data": {
        "EFiledlist": [
            {"rtntype": "GSTR1", "ret_prd": "072026", "dof": "11/08/2026", "arn": "AA27..."},
            {"rtntype": "GSTR3B", "ret_prd": "072026", "dof": "20/08/2026", "arn": "AB27..."},
            {"rtntype": "GSTR1", "ret_prd": "122025", "dof": "11/01/2026", "arn": "AC27..."},
        ]
    }
}


def test_returns_sorted_by_real_period_not_text():
    """``ret_prd`` is MMYYYY. Sorted as text, 12/2025 beats 07/2026 and the
    'months since last filing' figure that decides C2 comes out wrong."""
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["action"] == "RETTRACK"
        assert request.url.params["fy"]
        return httpx.Response(200, json=RETURNS)

    data = _provider(handler).returns_metadata(GSTIN)
    assert data["latest_period"] == "072026"
    assert data["filing_count"] == 3
    assert data["return_types"] == ["GSTR1", "GSTR3B"]


def test_empty_filing_list_is_a_parse_gap():
    """A taxpayer with no filings and an adapter that cannot read the list
    look identical from here — so the safe reading is 'could not examine'."""
    with pytest.raises(ProviderParseGap):
        _provider(lambda r: httpx.Response(200, json={"data": {"gstin": GSTIN}})) \
            .returns_metadata(GSTIN)


def test_financial_year_is_april_to_march():
    import datetime as dt
    assert fa._current_fy(dt.date(2026, 3, 31)) == "2025-26"
    assert fa._current_fy(dt.date(2026, 4, 1)) == "2026-27"


def test_gstn_dates_are_day_first():
    # 11/08/2026 is 11 August, not 8 November. Read the other way, a return
    # filed on time reads as three months late and C2 drops two grades.
    assert fa._iso("11/08/2026") == "2026-08-11"
    assert fa._iso("") is None
    assert fa._iso("garbage") is None


# ---------------------------------------------------------------------
# The real envelope — captured from a live 200, 2026-09-09
# ---------------------------------------------------------------------
#
# Everything above this line was written against an ASSUMED response shape,
# and none of it would have caught the defect these tests exist for: FinAGG
# returns the GSTN body as a BASE64 STRING under `data`, not as a nested
# object. `_unwrap` tested `isinstance(inner, dict)`, fell through to the
# outer envelope, and every lookup came back empty — turning every GST check
# into a ParseGuard `unavailable` while the provider was answering correctly.
#
# The payload below is the verbatim decoded body for GSTIN 29AANCB8469J1ZS
# (BLINKIT FOODS LIMITED), trimmed to the fields the adapter reads plus the
# ones it newly captures. Sandbox serves live GSTN data, so this is a real
# registration, not a fixture the provider invented.

import base64 as _b64
import json as _json

LIVE_GSTIN = "29AANCB8469J1ZS"

LIVE_BODY = {
    "stjCd": "KA004",
    "lgnm": "BLINKIT FOODS LIMITED",
    "stj": "LGSTO 016- Bengaluru",
    "dty": "Regular",
    "adadr": [
        {
            "addr": {
                "bnm": "", "loc": "Bengaluru",
                "st": "Nada Prabhu Kempegowda Main Road, Mariyannapalya,",
                "bno": "FJ Complex, #202", "dst": "Bengaluru Urban",
                "pncd": "560024", "stcd": "Karnataka", "flno": "Ground Floor",
            },
            "ntr": "Wholesale Business, Recipient of Goods or Services, "
                   "Supplier of Services, Retail Business",
        },
        {
            "addr": {
                "bnm": "", "loc": "Bengaluru", "st": "Outer Ring Road, Bellandur,",
                "bno": "No. 78/11", "dst": "Bengaluru Urban",
                "pncd": "560103", "stcd": "Karnataka", "flno": "Ground Floor",
            },
            "ntr": "Wholesale Business, Recipient of Goods or Services, "
                   "Supplier of Services, Warehouse / Depot, Retail Business",
        },
    ],
    "cxdt": "",
    "gstin": LIVE_GSTIN,
    "nba": ["Wholesale Business", "Recipient of Goods or Services",
            "Supplier of Services", "Warehouse / Depot", "Retail Business"],
    "lstupdt": "11/11/2025",
    "rgdt": "24/12/2019",
    "ctb": "Private Limited Company",
    "pradr": {
        "addr": {
            "bnm": "", "st": "Outer Ring Road", "loc": "Bengaluru",
            "bno": "No. 78/11", "dst": "Bengaluru Urban",
            "pncd": "560103", "stcd": "Karnataka", "flno": "",
        },
        "ntr": "Wholesale Business, Supplier of Services",
    },
    "tradeNam": "BLINKIT FOODS LIMITED",
    "sts": "Active",
    "ctjCd": "ZK0405",
    "ctj": "RANGE - 155",
    "einvoiceStatus": "Yes",
}


def _live_envelope(body=None, **over):
    """The real wire format: base64 JSON under `data`."""
    payload = {
        "status_cd": "1",
        "data": _b64.b64encode(
            _json.dumps(body if body is not None else LIVE_BODY).encode()
        ).decode(),
        "rek": "",
        "hmac": "",
    }
    payload.update(over)
    return payload


def _live_provider(payload=None, capture=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if capture is not None:
            capture.append(request)
        return httpx.Response(
            200, json=payload if payload is not None else _live_envelope()
        )
    return _provider(handler)


def test_base64_envelope_is_decoded():
    """The defect that made every GST check unavailable.

    A dict-shaped `data` was all the adapter had ever been tested against.
    The provider sends a string.
    """
    facts = _live_provider().search_gstin(LIVE_GSTIN)

    assert facts["legal_name"] == "BLINKIT FOODS LIMITED"
    assert facts["is_active"] is True
    assert facts["taxpayer_type"] == "Regular"
    assert facts["constitution"] == "Private Limited Company"
    assert facts["registered_on"] == "2019-12-24"   # 24/12/2019, day-first
    assert facts["cancelled_on"] is None            # "" is not a date
    assert facts["state_jurisdiction"] == "LGSTO 016- Bengaluru"
    assert "Bengaluru" in facts["address"]


def test_correct_path_and_action_are_sent():
    """`fin-v1` / `v1.3` / `TP`, not the values the GSTN contract implies.

    Getting any of the three wrong produced a 500 with an empty
    `{"status_cd": "0"}` body and no error object — a failure that looks
    like a provider outage rather than a bad request, which is why it cost
    a day to find.
    """
    seen = []
    _live_provider(capture=seen).search_gstin(LIVE_GSTIN)

    url = str(seen[0].url)
    assert "/fin-v1/commonapi/v1.3/search" in url
    assert seen[0].url.params["action"] == "TP"


def test_nba_array_preferred_over_splitting_ntr():
    """`nba` is a real array; `ntr` is a comma-joined string.

    "Office / Sale Office" survives as one entry from `nba` and would be
    correct either way here — but a value containing a comma would be torn
    in half by the fallback, so the array must win when it is present.
    """
    facts = _live_provider().search_gstin(LIVE_GSTIN)
    assert facts["nature_of_business"] == LIVE_BODY["nba"]
    assert "Warehouse / Depot" in facts["nature_of_business"]


def test_additional_places_are_captured():
    """A vendor with depots is not the same as one with a single office."""
    facts = _live_provider().search_gstin(LIVE_GSTIN)

    assert facts["additional_place_count"] == 2
    natures = facts["additional_places"][1]["nature_of_business"]
    assert "Warehouse / Depot" in natures
    assert "560103" in facts["additional_places"][1]["address"]


def test_new_evidence_fields_are_recorded():
    facts = _live_provider().search_gstin(LIVE_GSTIN)
    assert facts["einvoice_status"] == "Yes"
    assert facts["record_last_updated"] == "2025-11-11"
    assert facts["state_jurisdiction_code"] == "KA004"
    assert facts["centre_jurisdiction_code"] == "ZK0405"


def test_failure_status_cd_is_a_parse_gap_not_an_empty_result():
    """`status_cd: "0"` is the shape a wrong action/version produced.

    It must never read as "we looked and the vendor has no registration".
    """
    with pytest.raises(ProviderParseGap):
        _live_provider(payload={"status_cd": "0"}).search_gstin(LIVE_GSTIN)


def test_encrypted_body_is_not_reported_as_empty():
    """`rek`/`hmac` populated means the body is encrypted, not absent."""
    payload = _live_envelope(rek="sOmEkEy==", hmac="abc123")
    with pytest.raises(ProviderParseGap):
        _live_provider(payload=payload).search_gstin(LIVE_GSTIN)


def test_undecodable_base64_is_a_parse_gap():
    payload = {"status_cd": "1", "data": "!!!not base64!!!", "rek": "", "hmac": ""}
    with pytest.raises(ProviderParseGap):
        _live_provider(payload=payload).search_gstin(LIVE_GSTIN)


def test_dict_shaped_data_still_works():
    """Backwards compatibility: the older assumed envelope must not break."""
    facts = _live_provider(payload={"data": LIVE_BODY}).search_gstin(LIVE_GSTIN)
    assert facts["legal_name"] == "BLINKIT FOODS LIMITED"


# ---------------------------------------------------------------------
# Financial-year rollover
# ---------------------------------------------------------------------


def test_previous_fy():
    assert fa._previous_fy("2026-27") == "2025-26"
    assert fa._previous_fy("2019-20") == "2018-19"


def test_early_in_fy_window():
    from datetime import date as _date
    assert fa._early_in_fy(_date(2026, 4, 10)) is True
    assert fa._early_in_fy(_date(2026, 6, 30)) is True
    assert fa._early_in_fy(_date(2026, 7, 1)) is False
    assert fa._early_in_fy(_date(2026, 1, 15)) is False


def test_empty_current_year_falls_back_to_prior_fy(monkeypatch):
    """In April a compliant vendor has nothing due yet.

    Without the fallback, `filing_count == 0` makes C2 red — recording a
    fully compliant vendor as a current defaulter on the strength of a
    financial year that is two weeks old.
    """
    from datetime import date as _date
    monkeypatch.setattr(fa, "_early_in_fy", lambda today=None: True)
    monkeypatch.setattr(fa, "_current_fy", lambda today=None: "2026-27")

    asked = []
    prior_rows = [
        {"rtntype": "GSTR3B", "ret_prd": "032026", "dof": "18/04/2026",
         "arn": "AA2903", "status": "Filed", "mof": "ONLINE"},
        {"rtntype": "GSTR1", "ret_prd": "022026", "dof": "11/03/2026",
         "arn": "AA2902", "status": "Filed", "mof": "ONLINE"},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        fy = request.url.params["fy"]
        asked.append(fy)
        rows = prior_rows if fy == "2025-26" else []
        return httpx.Response(200, json=_live_envelope({"EFiledlist": rows}))

    data = _provider(handler).returns_metadata(LIVE_GSTIN)

    assert asked == ["2026-27", "2025-26"], "current year must be tried first"
    assert data["financial_year"] == "2025-26"
    assert data["fell_back_to_prior_fy"] is True
    assert data["filing_count"] == 2
    assert data["latest_period"] == "032026"


def test_caller_supplied_fy_is_never_silently_changed(monkeypatch):
    """A named year gets an answer about THAT year, empty or not."""
    monkeypatch.setattr(fa, "_early_in_fy", lambda today=None: True)

    asked = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(request.url.params["fy"])
        return httpx.Response(200, json=_live_envelope({"EFiledlist": []}))

    with pytest.raises(ProviderParseGap):
        _provider(handler).returns_metadata(LIVE_GSTIN, fy="2024-25")

    assert asked == ["2024-25"], "must not fall back on an explicit year"
