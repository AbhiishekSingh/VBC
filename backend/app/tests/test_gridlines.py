"""The five person-level checks — and the one thing they must never do.

These differ in kind from every other adapter in this package. The rest
read a REGISTRY about a company: MCA, GSTN, the courts, the DNS. Public
records, nobody's permission needed.

These take a mobile number and return a named individual's PAN, date of
birth, home address, digital footprint and EPFO employment history. Even
a company's own switchboard number belongs to whoever holds the SIM.

So the tests below are in two halves. The first half is ordinary adapter
testing. The second half guards the thing that makes this adapter
defensible rather than merely functional — that consent is carried from
a recorded human decision, never asserted by a constant.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from app.config import Settings
from app.providers import gridlines as gl
from app.providers.base import NotConfigured, ProviderParseGap


SOURCE = pathlib.Path(gl.__file__)


def _settings(**over) -> Settings:
    base = {"gridlines_api_key": "test-key", "allow_paid_calls": True}
    base.update(over)
    return Settings(**base)


class _FakeResponse:
    def __init__(self, payload):
        self.payload = payload


class _Recorder(gl.GridlinesProvider):
    """Captures the request instead of sending it."""

    def __init__(self, payload, **over):
        super().__init__(_settings(**over))
        self._payload = payload
        self.sent: dict = {}

    def request(self, method, url, **kwargs):  # type: ignore[override]
        self.sent = {"method": method, "url": url, **kwargs}
        return _FakeResponse(self._payload)


# =====================================================================
# 1. CONSENT — the half that matters
# =====================================================================

class TestConsentIsCarriedNotAsserted:
    """The Mobile Intelligence Suite hardcodes `"consent": "Y"` in all
    twenty-five of its calls. This adapter must not, and the guard is
    structural rather than a convention somebody has to remember."""

    def test_the_literal_appears_nowhere_in_executable_code(self):
        """Parses the AST, so a comment or docstring mentioning it is
        fine and an actual assignment is not.

        Same shape as `test_no_otp_surface`, which keeps FinAGG's
        consent-gated endpoints out of the codebase entirely.
        """
        tree = ast.parse(SOURCE.read_text())
        offenders = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and node.value == "Y":
                offenders.append(getattr(node, "lineno", "?"))
        assert not offenders, (
            f"the string \"Y\" is assigned in executable code at line(s) "
            f"{offenders}. Consent must arrive as an argument from a "
            f"recorded human decision, never as a constant here."
        )

    @pytest.mark.parametrize(
        "call,kwargs",
        [
            ("mobile_prefill", {"mobile": "9876543210"}),
            ("digital_footprint", {"mobile": "9876543210"}),
            ("address_lookup", {"mobile": "9876543210"}),
            ("epfo_member", {"mobile": "9876543210"}),
            ("employment_history", {"uan": "100123456789"}),
        ],
    )
    def test_every_call_requires_consent_as_a_keyword(self, call, kwargs):
        """Not a default, not optional. Omitting it is a TypeError, so a
        future caller cannot forget it by accident."""
        provider = _Recorder({"data": {"name": "X"}})
        with pytest.raises(TypeError):
            getattr(provider, call)(**kwargs)

    def test_the_consent_value_sent_is_the_one_passed_in(self):
        provider = _Recorder({"data": {"name": "A SHARMA"}})
        provider.mobile_prefill("9876543210", consent="RECORDED-REF-42")
        assert provider.sent["json"]["consent"] == "RECORDED-REF-42"


# =====================================================================
# 2. The request, which the Mobile Intelligence Suite settles exactly
# =====================================================================

class TestRequestShape:
    def test_both_auth_headers_are_sent(self):
        """Sending only the key returns 401 — X-Auth-Type names the scheme."""
        provider = _Recorder({"data": {"name": "X"}})
        provider.mobile_prefill("9876543210", consent="Y")
        headers = provider.sent["headers"]
        assert headers["X-API-Key"] == "test-key"
        assert headers["X-Auth-Type"] == "API-Key"

    @pytest.mark.parametrize(
        "call,kwargs,path,key",
        [
            ("mobile_prefill", {"mobile": "9876543210"},
             "/profile-api/mobile/prefill", "mobile_number"),
            ("digital_footprint", {"mobile": "9876543210"},
             "/profile-api/mobile/digital-footprint", "phone"),
            ("address_lookup", {"mobile": "9876543210"},
             "/profile-api/mobile/address-lookup", "mobile_number"),
            ("epfo_member", {"mobile": "9876543210"},
             "/epfo-api/fetch-uan", "mobile_number"),
        ],
    )
    def test_endpoint_and_body_key(self, call, kwargs, path, key):
        """`digital_footprint` sends `phone`, the others `mobile_number`.

        Not a tidy-up opportunity — it is what the live integration does,
        and normalising it here would break the call.
        """
        provider = _Recorder({"data": {"uan": "1", "name": "X"}})
        getattr(provider, call)(consent="Y", **kwargs)
        assert provider.sent["url"].endswith(path)
        assert provider.sent["json"][key] == "9876543210"

    def test_employment_history_sends_uan_number(self):
        provider = _Recorder({"data": {"employment_history": [{"x": 1}]}})
        provider.employment_history("100123456789", consent="Y")
        assert provider.sent["url"].endswith(
            "/epfo-api/employment-history/fetch-by-uan")
        assert provider.sent["json"]["uan_number"] == "100123456789"

    def test_no_key_is_not_configured_rather_than_an_error(self):
        """A coverage gap, not a failure. `not_configured` is NOT the same
        as a person having no record, and the screen says so."""
        provider = _Recorder({}, gridlines_api_key="")
        with pytest.raises(NotConfigured):
            provider.mobile_prefill("9876543210", consent="Y")


# =====================================================================
# 3. Reading a shape nobody has seen yet
# =====================================================================

class TestUnknownResponseShape:
    """The Mobile Intelligence Suite calls these endpoints but never
    parses them — its UI walks whatever JSON arrives — so the project
    records no response field anywhere. Documentation has been wrong
    about this project's providers three times. The adapter therefore
    reads across spellings and fails loudly rather than quietly."""

    @pytest.mark.parametrize("envelope", ["data", "result", "response"])
    def test_any_of_the_common_envelopes_is_unwrapped(self, envelope):
        provider = _Recorder({envelope: {"pan": "ABCDE1234F"}})
        assert provider.mobile_prefill("9876543210", consent="Y")["pan"] == "ABCDE1234F"

    def test_a_bare_payload_with_no_envelope_still_reads(self):
        provider = _Recorder({"pan": "ABCDE1234F"})
        assert provider.mobile_prefill("9876543210", consent="Y")["pan"] == "ABCDE1234F"

    @pytest.mark.parametrize("spelling", ["pan", "pan_number", "panNumber"])
    def test_pan_is_found_under_any_of_its_spellings(self, spelling):
        provider = _Recorder({"data": {spelling: "ABCDE1234F"}})
        assert provider.mobile_prefill("9876543210", consent="Y")["pan"] == "ABCDE1234F"

    def test_a_payload_we_cannot_read_RAISES_rather_than_reads_empty(self):
        """THE RULE THIS WHOLE PRODUCT TURNS ON.

        A response full of content that this adapter extracts nothing
        from must never be reported as a person with no records. It is a
        defect in us, and `ProviderParseGap` makes the check
        `unavailable` with the payload attached.
        """
        provider = _Recorder({"data": {"memberDetails": {"x": 1}, "y": 2}})
        with pytest.raises(ProviderParseGap):
            provider.mobile_prefill("9876543210", consent="Y")

    def test_a_genuinely_empty_response_does_not_raise(self):
        """No content in, nothing extracted out — that is a real answer,
        not a parse gap, and ParseGuard knows the difference."""
        provider = _Recorder({"data": {}})
        assert provider.mobile_prefill("9876543210", consent="Y")["pan"] is None

    def test_raw_keys_are_kept_so_the_shape_can_be_mapped_later(self):
        """`facts` is a projection of `raw_response` and backfill_facts
        rebuilds it for nothing — so the first real response can be
        parsed properly and every historical row corrected without
        re-paying for a single call."""
        provider = _Recorder({"data": {"pan": "ABCDE1234F", "odd_field": 1}})
        out = provider.mobile_prefill("9876543210", consent="Y")
        assert out["_raw_keys"] == ["odd_field", "pan"]

    def test_employment_history_accepts_a_single_record_or_a_list(self):
        one = _Recorder({"data": {"employment_history": {"employer_name": "ACME"}}})
        assert len(one.employment_history("1", consent="Y")["employments"]) == 1
        many = _Recorder({"data": {"history": [{"a": 1}, {"b": 2}]}})
        assert len(many.employment_history("1", consent="Y")["employments"]) == 2


# =====================================================================
# 4. The catalog
# =====================================================================

class TestCatalog:
    def test_the_five_checks_exist_and_are_gridlines(self):
        from app.catalog.checks import CHECKS_BY_ID

        for check_id in ("prefill", "footprint", "personaddr",
                         "epfomember", "emphistory"):
            assert CHECKS_BY_ID[check_id].provider.value == "gridlines"

    def test_every_person_check_offers_a_consent_reference(self):
        from app.catalog.checks import CHECKS_BY_ID

        for check_id in ("prefill", "footprint", "personaddr",
                         "epfomember", "emphistory"):
            keys = {p.key for p in CHECKS_BY_ID[check_id].params}
            assert "consentRef" in keys, check_id

    def test_none_of_them_feeds_a_scan_parameter(self):
        """Deliberate, and worth pinning so it cannot drift in by accident.

        No parameter among the eighteen means "the contact person's home
        address". Mapping one is a versioned scoring migration with a
        re-scoring plan, not a catalog edit.
        """
        from app.catalog.checks import CHECKS_BY_ID

        for check_id in ("prefill", "footprint", "personaddr",
                         "epfomember", "emphistory"):
            assert not CHECKS_BY_ID[check_id].feeds, check_id

    def test_employment_history_chains_from_epfo_membership(self):
        from app.catalog.checks import CHECKS_BY_ID

        assert CHECKS_BY_ID["emphistory"].requires == ("epfomember",)
        uan = next(p for p in CHECKS_BY_ID["emphistory"].params
                   if p.key == "uan")
        assert uan.from_result == "epfomember"

    def test_the_mobile_comes_from_the_vendor_record(self):
        from app.catalog.checks import CHECKS_BY_ID

        mobile = next(p for p in CHECKS_BY_ID["prefill"].params
                      if p.key == "mobile")
        assert mobile.from_vendor == "contact_mobile"
        assert mobile.required


# =====================================================================
# 5. Validation — where a typo is worse than an error
# =====================================================================

class TestMobileValidation:
    @pytest.mark.parametrize("value", ["9876543210", "6000000000"])
    def test_a_real_indian_mobile_passes(self, value):
        from app.domain.validation import check_value

        assert check_value("mobile", value) is None

    @pytest.mark.parametrize(
        "value", ["5876543210", "987654321", "98765432100",
                  "+919876543210", "98765 43210"],
    )
    def test_anything_else_blocks(self, value):
        """BLOCK, not WARN, and the reason is specific to this field: a
        mistyped CIN produces an error from the provider, while a
        mistyped mobile produces a DIFFERENT PERSON'S PAN and home
        address, with nothing in the response to say so."""
        from app.domain.validation import check_value

        problem = check_value("mobile", value)
        assert problem is not None and problem.level == "block"

    def test_the_api_refuses_a_bad_mobile_on_a_vendor(self):
        from app.api.routes import VENDOR_ID_FIELDS

        assert VENDOR_ID_FIELDS["contactMobile"] == "mobile"
