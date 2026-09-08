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
        finagg_version="v1",
        finagg_gsp_version="v1.2",
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
        assert request.url.params["action"] == "SEARCHGSTIN"
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
