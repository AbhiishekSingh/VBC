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


#: A payload each call can parse, so a test about the REQUEST fails on
#: the request and never on the response. `digital_footprint` needs the
#: real nested envelope; the other four are still flat guesses, which is
#: exactly what the next captured response will correct.
_PARSEABLE = {
    "mobile_prefill": {"data": {"name": "X"}},
    "address_lookup": {"data": {"addresses": ["12 MG Rd"]}},
    "epfo_member": {"data": {"uan": "100123456789"}},
    "digital_footprint": {
        "data": {"code": "1030", "message": "ok", "digital_profile_data": [
            {"data_type": "phone_data",
             "primary_data": {"social_profile_count": 1,
                              "account_details": [
                                  {"platform": "AMAZON", "user_exist": True}]}}]}},
}


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
        provider = _Recorder(_PARSEABLE[call])
        getattr(provider, call)(consent="Y", **kwargs)
        assert provider.sent["url"].endswith(path)
        assert provider.sent["json"][key] == "9876543210"

    def test_employment_history_sends_uan_number(self):
        provider = _Recorder({"data": {"employment_history": [{"x": 1}]}})
        provider.employment_history("100123456789", consent="Y")
        assert provider.sent["url"].endswith(
            "/epfo-api/employment-history/fetch-by-uan")
        assert provider.sent["json"]["uan_number"] == "100123456789"

    # -----------------------------------------------------------------
    # THE OPTIONAL FIELDS, WHICH THIS ADAPTER GOT WRONG
    # -----------------------------------------------------------------
    #
    # Both were INVENTED here rather than copied, and both were sent on
    # ordinary calls rather than rare ones. The only evidence anyone has
    # about what these endpoints accept is the Mobile Intelligence
    # Suite's `third_party.py`, which is live against this same key and
    # these same endpoints — so where this adapter disagrees with it,
    # this adapter is wrong by definition.

    def test_prefill_sends_the_name_FLAT_not_nested(self):
        """Was `{"name": {"first_name": …, "last_name": …}}`.

        `api_mobile_prefill` sends them at the top level.
        """
        provider = _Recorder({"data": {"name": "X"}})
        provider.mobile_prefill("9876543210", consent="Y",
                                first_name="RAJESH", last_name="SHARMA")
        body = provider.sent["json"]
        assert body["first_name"] == "RAJESH"
        assert body["last_name"] == "SHARMA"
        assert "name" not in body, (
            "a nested name object was this adapter's invention and is not "
            "what the live integration sends"
        )

    def test_epfo_member_sends_pan_not_pan_number(self):
        """Was `pan_number`. `api_epfo_member` sends `pan`.

        Not an edge case: the vendor record usually HAS a PAN, so the
        wrong spelling was on almost every real request.
        """
        provider = _Recorder({"data": {"uan": "100123456789"}})
        provider.epfo_member("9876543210", consent="Y", pan="abcde1234f")
        body = provider.sent["json"]
        assert body["pan"] == "ABCDE1234F"
        assert "pan_number" not in body

    def test_the_two_uan_spellings_are_NOT_normalised(self):
        """`epfo_member` takes `pan`; `employment_history` takes
        `uan_number`. The provider is inconsistent, and making the two
        agree with each other would break one of them."""
        one = _Recorder({"data": {"employment_history": [{"x": 1}]}})
        one.employment_history("100123456789", consent="Y")
        assert "uan_number" in one.sent["json"]

    def test_the_body_matches_the_live_integration_field_for_field(self):
        """A bare call — no optional fields — on all four mobile
        endpoints sends EXACTLY what `third_party.py` sends, and nothing
        extra. An unexpected key is how a request starts being rejected
        for a reason the response does not name.
        """
        expected = {
            "mobile_prefill": {"mobile_number": "9876543210", "consent": "Y"},
            "digital_footprint": {"phone": "9876543210", "consent": "Y"},
            "address_lookup": {"mobile_number": "9876543210", "consent": "Y"},
            "epfo_member": {"mobile_number": "9876543210", "consent": "Y"},
        }
        for call, body in expected.items():
            provider = _Recorder(_PARSEABLE[call])
            getattr(provider, call)("9876543210", consent="Y")
            assert provider.sent["json"] == body, call

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
    def test_the_person_checks_exist_and_are_gridlines(self):
        """FOUR, not five. `personaddr` was removed on 7 Nov 2026 —
        Gridlines refuses that product for this account, in the Mobile
        Intelligence Suite as well as here, so it was never a check
        anybody could run; it only reported Unavailable forever."""
        from app.catalog.checks import CHECKS_BY_ID

        for check_id in ("prefill", "footprint", "epfomember",
                         "emphistory"):
            assert CHECKS_BY_ID[check_id].provider.value == "gridlines"

    def test_every_person_check_offers_a_consent_reference(self):
        from app.catalog.checks import CHECKS_BY_ID

        for check_id in ("prefill", "footprint", "epfomember",
                         "emphistory"):
            keys = {p.key for p in CHECKS_BY_ID[check_id].params}
            assert "consentRef" in keys, check_id

    def test_none_of_them_feeds_a_scan_parameter(self):
        """Deliberate, and worth pinning so it cannot drift in by accident.

        No parameter among the eighteen means "the contact person's home
        address". Mapping one is a versioned scoring migration with a
        re-scoring plan, not a catalog edit.
        """
        from app.catalog.checks import CHECKS_BY_ID

        for check_id in ("prefill", "footprint", "epfomember",
                         "emphistory"):
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
        "value", ["5876543210", "987654321", "98765432100", "9876abc210"],
    )
    def test_anything_else_blocks(self, value):
        """BLOCK, not WARN, and the reason is specific to this field: a
        mistyped CIN produces an error from the provider, while a
        mistyped mobile produces a DIFFERENT PERSON'S PAN and home
        address, with nothing in the response to say so."""
        from app.domain.validation import check_value

        problem = check_value("mobile", value)
        assert problem is not None and problem.level == "block"

    @pytest.mark.parametrize(
        "value", ["+919876543210", "98765 43210", "098765 43210",
                  "+91-98765-43210"],
    )
    def test_a_pasted_number_is_cleaned_rather_than_refused(self, value):
        """A `+91`, a leading `0` and spaces off a contact sheet are the
        commonest paste, not a mistake.

        This test REPLACES one that required the analyst to tidy them by
        hand. The reason is not leniency: `runner._subjects` has always
        stripped exactly these, so a field that refused them refused a
        value the runner would have accepted — and both now call ONE
        `clean_subject`, so what the box accepts is what the provider is
        sent. The alternative, a red field over a number the system would
        have handled, is the same screen-says-one-thing defect that had
        SSL being asked about a domain the analyst thought they had
        deleted.
        """
        from app.domain.validation import check_value, clean_subject

        assert check_value("mobile", value) is None
        assert clean_subject(value) == "9876543210"

    def test_several_numbers_in_one_field_do_not_block_the_run(self):
        """The whole feature, at the level of the API's own gate.

        `blocking()` is what `POST /vendors/{id}/run` consults before
        anything is spent. A single-value pattern over a field holding
        five numbers makes it invalid, so the run is refused with a 422 —
        a feature that cannot be used.
        """
        from app.domain.validation import blocking, check_value

        many = "9876543210\n9876543211\n9876543212"
        assert check_value("mobile", many) is None
        assert blocking({"mobile": many}) == []

    def test_one_bad_entry_among_five_names_itself(self):
        """"Ten digits starting 6-9" against a box of five numbers does
        not say which of the five to look at."""
        from app.domain.validation import check_value

        problem = check_value("mobile", "9876543210\n5876543211\n9876543212")
        assert problem is not None and problem.level == "block"
        assert "5876543211" in problem.message

    def test_the_api_refuses_a_bad_mobile_on_a_vendor(self):
        from app.api.routes import VENDOR_ID_FIELDS

        assert VENDOR_ID_FIELDS["contactMobile"] == "mobile"

    def test_the_splitter_is_one_definition_shared_with_the_runner(self):
        """Not two copies that can drift. The field validator, the form
        and the runner all read the same function, so the box cannot
        accept a value the runner would send differently."""
        from app.domain import validation
        from app.services import runner as rn

        assert rn.split_subjects is validation.split_subjects


# =====================================================================
# 6. ONE CHECK, MANY PEOPLE
# =====================================================================
#
# A company with five directors is five lookups. They belong on ONE
# check row, every answer tagged with the number it came from, because
# run as five separate checks the analyst ends up with five rows and no
# way to tell which answer belonged to whom.
#
# Three things have to hold and each is a way this gets quietly wrong:
#
#   1. The subject must travel WITH the answer. A list of five identity
#      records in payload order is unreadable the moment one of them
#      fails and the order shifts.
#   2. A failed lookup must stay VISIBLE. Four successes and a silent
#      omission reads as four people examined and a fifth who came back
#      clean. That person was not examined at all.
#   3. Paying twice for one answer. Two directors sharing a number is a
#      real thing; two calls for it is not.

from app.providers import factsets as fx  # noqa: E402
from app.services.runner import _subjects, _uans_by_mobile  # noqa: E402


class TestOneCheckManyPeople:
    def test_numbers_are_split_on_whatever_the_analyst_typed(self):
        """Commas, semicolons or newlines — whichever the paste produced.

        No schema change behind this: the value lands in the existing
        `vendor_check_inputs` row, which is already Text and already
        unique on (vendor, check, key).
        """
        assert _subjects("9876543210, 9876543211") == ["9876543210", "9876543211"]
        assert _subjects("9876543210;9876543211") == ["9876543210", "9876543211"]
        assert _subjects("9876543210\n9876543211") == ["9876543210", "9876543211"]

    def test_a_pasted_prefix_is_stripped_rather_than_rejected(self):
        """`+91` and a leading `0` are the commonest paste, not an error."""
        assert _subjects("+919876543210\n09876543211\n91 98765 43212") == [
            "9876543210", "9876543211", "9876543212",
        ]

    def test_the_same_number_twice_is_one_call(self):
        """Two directors sharing a number is real. Paying twice is not."""
        assert _subjects("9876543210, 9876543210") == ["9876543210"]

    def test_order_is_preserved(self):
        """The analyst typed them in the order they think about them."""
        assert _subjects("9876543212\n9876543210") == ["9876543212", "9876543210"]

    def test_the_vendor_record_is_the_fallback_not_an_override(self):
        assert _subjects("", "9876543210") == ["9876543210"]
        assert _subjects("9876543211", "9876543210") == ["9876543211"]

    def test_a_single_subject_renders_as_a_record_not_a_one_row_table(self):
        """The ordinary case must look like every other check on the
        screen — a Field/Value panel — or the common path pays for the
        rare one."""
        raw = {"subjects": [{"subject": "9876543210", "ok": True,
                             "data": {"name": "A SHARMA", "dob": "1985-02-03"}}],
               "subject_count": 1}
        blob = fx.person_subjects("prefill", raw)
        labels = [r["field"] for r in blob["table"]["rows"]]
        assert "Name" in labels and "subject" not in labels
        # And it still says whose record it is.
        assert blob["fields"][0]["label"] == "Number"

    def test_five_subjects_render_as_a_table_keyed_on_the_number(self):
        raw = {"subjects": [
            {"subject": f"987654321{i}", "ok": True,
             "data": {"name": f"NAME {i}"}} for i in range(5)
        ], "subject_count": 5}
        blob = fx.person_subjects("prefill", raw)
        assert blob["table"]["columns"][0]["key"] == "subject"
        assert len(blob["table"]["rows"]) == 5
        # Each answer carries its own number. Position in the list is not
        # enough — one failure shifts it.
        assert len({r["subject"] for r in blob["table"]["rows"]}) == 5

    def test_a_failed_subject_is_FLAGGED_not_dropped(self):
        """THE RULE THIS PRODUCT TURNS ON, at the level of one person.

        Four returned and a fifth omitted reads as five people examined.
        The fifth was not examined at all, and the flag says so by name.
        """
        raw = {"subjects": [
            {"subject": "9876543210", "ok": True, "data": {"name": "A"}},
            {"subject": "9876543211", "ok": False, "error": "ProviderError: 500"},
        ], "subject_count": 2}
        blob = fx.person_subjects("prefill", raw)
        assert len(blob["table"]["rows"]) == 1
        flags = [f for f in blob["flags"] if "Not examined" in f["label"]]
        assert len(flags) == 1
        assert "not a clearance" in flags[0]["detail"]
        assert [s for s in blob["stats"] if s["label"] == "Not examined"][0]["value"] == "1"

    def test_the_headline_counts_are_honest_about_the_denominator(self):
        """`subject_count` is how many people were ASKED ABOUT, which is
        not how many rows came back — the loop stops on a 402."""
        raw = {"subjects": [{"subject": "9876543210", "ok": True, "data": {"name": "A"}}],
               "subject_count": 5}
        stats = {s["label"]: s["value"]
                 for s in fx.person_subjects("prefill", raw)["stats"]}
        assert stats["People looked up"] == "5"
        assert stats["Returned"] == "1"

    def test_a_list_valued_answer_gets_one_row_per_item(self):
        """Three addresses for two people is five rows with the number
        repeated, not two rows with the detail collapsed into a cell.
        Collapsing is what made the director profile unreadable."""
        raw = {"subjects": [
            {"subject": "9876543210", "ok": True,
             "data": {"addresses": ["12 MG Rd, Mumbai", "4 Linking Rd"]}},
            {"subject": "9876543211", "ok": True,
             "data": {"addresses": ["7 Hill View"]}},
        ], "subject_count": 2}
        blob = fx.person_subjects("personaddr", raw)
        assert len(blob["table"]["rows"]) == 3
        assert sum(1 for r in blob["table"]["rows"]
                   if r["subject"].startswith("9876")) == 3

    def test_employment_history_says_whose(self):
        """A UAN on its own does not identify one of five directors. The
        row carries the number the UAN was found against."""
        raw = {"subjects": [
            {"subject": "9876543210", "uan": "100123456789", "ok": True,
             "data": {"employments": [{"establishment_name": "ACME",
                                       "date_of_joining": "2019-04-01"}]}},
        ], "subject_count": 2}
        row = fx.person_subjects("emphistory", raw)["table"]["rows"][0]
        assert "100123456789" in row["subject"]
        assert "9876" in row["subject"]
        assert row["from"] == "01 Apr 2019"

    def test_the_uan_map_is_keyed_by_number_so_the_chain_keeps_identity(self):
        """`emphistory` chains from `epfomember`. Taking a LIST of UANs
        off that result would put five employment histories on screen
        with no way to tell which belongs to whom."""
        class _F:
            raw = {"subjects": [
                {"subject": "9876543210", "ok": True, "data": {"uan": "1001"}},
                {"subject": "9876543211", "ok": True, "data": {"uan": "1002"}},
                {"subject": "9876543212", "ok": False, "error": "x"},
            ]}
        assert _uans_by_mobile({"epfomember": _F()}) == {
            "9876543210": "1001", "9876543211": "1002",
        }

    def test_nothing_stored_is_not_an_empty_table(self):
        """"Nothing was parsed" and "nobody has any records" are
        different findings. An empty table states the second."""
        assert fx.person_subjects("prefill", {})["shape"] == "none"
        assert fx.person_subjects("prefill", {"subjects": []})["shape"] == "none"

    def test_one_unmapped_shape_is_one_flag_not_five(self):
        """Five numbers against a response this adapter cannot read is
        ONE defect in the adapter, not five findings about people."""
        raw = {"subjects": [
            {"subject": f"987654321{i}", "ok": True,
             "data": {"_raw_keys": ["memberDetails", "y"]}} for i in range(5)
        ], "subject_count": 5}
        blob = fx.person_subjects("prefill", raw)
        shape = [f for f in blob["flags"] if "shape" in f["label"].lower()]
        assert len(shape) == 1


# =====================================================================
# 7. What is NOT in a fact blob
# =====================================================================

class TestPersonFactsAreSafeToRender:
    """`facts` is the tier a client-facing screen reads. The rule in
    `app/domain/facts.py` is that a PAN or an unmasked contact never
    reaches it, and `test_no_pan_reaches_the_facts` already pins that for
    the director rows. These five checks return a PAN, an email and a
    mobile number, so the same rule has to hold here."""

    def test_the_pan_is_part_masked(self):
        blob = fx.person_identity({"name": "A", "pan": "ABCDE1234F"})
        text = str(blob)
        assert "ABCDE1234F" not in text
        # The last four stay, because the one thing an analyst does with
        # this field is match it against the PAN on the vendor record.
        assert "234F" in text

    def test_the_email_is_part_masked(self):
        blob = fx.person_identity({"email": "amit.sharma@acme.in"})
        assert "amit.sharma@acme.in" not in str(blob)
        assert "a***@acme.in" in str(blob)

    def test_the_number_is_part_masked_but_still_identifies_the_row(self):
        """Full masking would make five directors five identical rows and
        destroy the reason these are on one check."""
        raw = {"subjects": [
            {"subject": "9876543210", "ok": True, "data": {"name": "A"}},
            {"subject": "9876543211", "ok": True, "data": {"name": "B"}},
        ], "subject_count": 2}
        rows = fx.person_subjects("prefill", raw)["table"]["rows"]
        shown = [r["subject"] for r in rows]
        assert "9876543210" not in shown and "9876543211" not in shown
        assert len(set(shown)) == 2

    def test_every_person_blob_says_it_is_personal_data(self):
        """As a `lede`, not a `note` — ABOVE the data, not under it.

        A `note` renders as a footnote. "This is one person's data, not a
        company record" read after a table of PANs, dates of birth and
        home addresses is read too late to be a disclosure.
        """
        for blob in (
            fx.person_identity({"name": "A"}),
            fx.person_footprint({"platforms": ["x"]}),
            fx.person_addresses({"addresses": ["y"]}),
            fx.person_epfo({"uan": "1"}),
            fx.person_employment({"employments": []}),
        ):
            assert "Personal data" in blob["lede"]
            assert "note" not in blob


# =====================================================================
# 8. The delta run — re-selection must not re-bill
# =====================================================================

class TestRunOnlyTheDelta:
    """`run()` does NOT skip a check that already answered, and
    `_persist` increments `attempts`. Correct for a deliberate re-run,
    and catastrophic for a "run more checks" control on the findings
    screen: it would re-call and re-bill the whole selection on every
    click — upwards of ₹40 on a full MCA set, with nothing on screen to
    say it had happened."""

    def test_the_route_accepts_an_optional_body(self):
        """Step 2 posts nothing. That caller must not have to change."""
        import inspect

        from app.api.routes import run_checks

        body = inspect.signature(run_checks).parameters["body"]
        assert body.default is None

    def test_a_partial_run_does_not_move_the_stage_backwards(self):
        """A vendor at `report` whose analyst runs two more checks is
        still at `report`. Setting it back to `manual` would walk them
        through screens they had already finished — and on a `decided`
        vendor it would reopen a closed file."""
        import inspect

        from app.api import routes

        source = inspect.getsource(routes.run_checks)
        assert "if only is None:" in source
        assert source.index("if only is None:") < source.index('stage = "manual"')

    def test_only_narrows_to_the_intersection_with_the_selection(
        self, session, seeded
    ):
        """A check the analyst never selected cannot be run by posting
        its id. The selection is the authority on what this vendor is
        paying for."""
        from app.db.models import Vendor
        from app.services.runner import CheckRunner
        from app.tests.conftest import DEFAULT_CLIENT_ID

        vendor = Vendor(id="GL0001", client_id=DEFAULT_CLIENT_ID,
                        name="Delta Test", selected=["ssl"])
        session.add(vendor)
        session.flush()

        runner = CheckRunner(session)
        try:
            result = runner.run(vendor, only=["reput"])
        finally:
            runner.close()
        assert result.findings == []

    def test_a_prerequisite_already_on_file_is_not_bought_again(
        self, session, seeded
    ):
        """`master` fetched an hour ago is still `master`. Re-expanding
        it on every delta run is the re-billing this guard exists for."""
        from app.db.models import Vendor, VendorCheck
        from app.services.runner import CheckRunner
        from app.tests.conftest import DEFAULT_CLIENT_ID

        vendor = Vendor(id="GL0002", client_id=DEFAULT_CLIENT_ID,
                        name="Delta Test", cin="U72900KA2020PTC131614",
                        selected=["master", "dirs"])
        session.add(vendor)
        session.add(VendorCheck(vendor_id="GL0002", check_id="master",
                                status="pass", value="on file"))
        session.flush()

        runner = CheckRunner(session)
        try:
            result = runner.run(vendor, only=["dirs"])
        finally:
            runner.close()
        assert "master" not in [f.check_id for f in result.findings], (
            "master already answered; a delta run must not call it again"
        )

    def test_the_partial_run_is_audited_with_what_it_skipped(
        self, session, seeded
    ):
        """So the bill can be reconciled against the screen later."""
        from sqlalchemy import select

        from app.db.models import AuditLog, Vendor
        from app.services.runner import CheckRunner
        from app.tests.conftest import DEFAULT_CLIENT_ID

        vendor = Vendor(id="GL0003", client_id=DEFAULT_CLIENT_ID,
                        name="Delta Test", selected=["ssl"])
        session.add(vendor)
        session.flush()

        runner = CheckRunner(session)
        try:
            runner.run(vendor, only=["ssl"])
        finally:
            runner.close()
        actions = session.scalars(
            select(AuditLog.action).where(AuditLog.vendor_id == "GL0003")
        ).all()
        assert "RUN_PARTIAL" in actions


# =====================================================================
# 9. The runner, end to end, with five people on one check
# =====================================================================

class TestPersonCheckRunsEverySubject:
    """What the facts tests above assert about the blob, asserted here
    about the run that produces it — including the one behaviour that
    only shows up in the loop: a 402 on the second of five numbers must
    STOP, not fail three more times."""

    def _runner(self, session, provider):
        from app.services.runner import CheckRunner

        runner = CheckRunner(session)
        runner.gridlines = provider
        return runner

    def _vendor(self, session, vendor_id, mobiles):
        from app.db.models import Vendor, VendorCheckInput
        from app.tests.conftest import DEFAULT_CLIENT_ID

        vendor = Vendor(id=vendor_id, client_id=DEFAULT_CLIENT_ID,
                        name="Person Test", selected=["prefill"])
        session.add(vendor)
        session.add(VendorCheckInput(vendor_id=vendor_id, check_id="prefill",
                                     key="mobile", value=mobiles))
        session.flush()
        return vendor

    class _Fake:
        """Answers per number, or raises what it was told to."""

        def __init__(self, answers=None, raises=None):
            self.answers = answers or {}
            self.raises = raises or {}
            self.calls: list[str] = []

        def mobile_prefill(self, mobile, *, consent, **_):
            self.calls.append(mobile)
            if mobile in self.raises:
                raise self.raises[mobile]
            return self.answers.get(mobile, {"name": f"NAME {mobile[-2:]}"})

        def close(self):
            pass

    def test_every_number_is_called_once(self, session, seeded):
        fake = self._Fake()
        vendor = self._vendor(session, "GL1001",
                              "9876543210\n9876543211\n9876543212")
        runner = self._runner(session, fake)
        try:
            result = runner.run(vendor)
        finally:
            runner.close()

        assert fake.calls == ["9876543210", "9876543211", "9876543212"]
        finding = next(f for f in result.findings if f.check_id == "prefill")
        assert finding.value == "3 of 3 returned"
        assert len(finding.raw["subjects"]) == 3

    def test_each_answer_is_tagged_with_the_number_it_came_from(
        self, session, seeded
    ):
        """Position in a list is not enough. One failure shifts it, and
        then the analyst is reading the wrong person's PAN."""
        fake = self._Fake(answers={
            "9876543210": {"name": "A SHARMA"},
            "9876543211": {"name": "B RAO"},
        })
        vendor = self._vendor(session, "GL1002", "9876543210, 9876543211")
        runner = self._runner(session, fake)
        try:
            result = runner.run(vendor)
        finally:
            runner.close()

        rows = next(f for f in result.findings
                    if f.check_id == "prefill").raw["subjects"]
        assert {r["subject"]: r["data"]["name"] for r in rows} == {
            "9876543210": "A SHARMA", "9876543211": "B RAO",
        }

    def test_one_failure_does_not_lose_the_other_two(self, session, seeded):
        from app.providers.base import ProviderError

        fake = self._Fake(raises={"9876543211": ProviderError("HTTP 500")})
        vendor = self._vendor(session, "GL1003",
                              "9876543210\n9876543211\n9876543212")
        runner = self._runner(session, fake)
        try:
            result = runner.run(vendor)
        finally:
            runner.close()

        finding = next(f for f in result.findings if f.check_id == "prefill")
        assert len(fake.calls) == 3
        assert finding.status.value == "warn"
        assert "2 of 3 returned" == finding.value
        assert "NOT cleared, they were not examined" in finding.detail

    def test_an_account_refusal_STOPS_the_loop(self, session, seeded):
        """A 402 on the second of five means the next three will fail
        identically. Carrying on spends nothing and turns one clear 'top
        the account up' into five confusing failures."""
        from app.providers.base import ProviderOutOfCredits

        fake = self._Fake(raises={
            "9876543211": ProviderOutOfCredits("Insufficient balance", status=402),
        })
        vendor = self._vendor(session, "GL1004",
                              "9876543210\n9876543211\n9876543212\n9876543213")
        runner = self._runner(session, fake)
        try:
            result = runner.run(vendor)
        finally:
            runner.close()

        assert fake.calls == ["9876543210", "9876543211"], (
            "the loop must stop at the account refusal, not call the rest"
        )
        finding = next(f for f in result.findings if f.check_id == "prefill")
        assert finding.status.value == "unavailable"
        # The PROVIDER'S own sentence, not ours.
        assert "Insufficient balance" in finding.detail

    def test_the_same_number_twice_is_one_call(self, session, seeded):
        fake = self._Fake()
        vendor = self._vendor(session, "GL1005", "9876543210, 9876543210")
        runner = self._runner(session, fake)
        try:
            runner.run(vendor)
        finally:
            runner.close()
        assert fake.calls == ["9876543210"]

    def test_a_single_number_still_reads_as_one_record(self, session, seeded):
        """The ordinary case must not be made worse by the rare one: the
        headline is the person's name, not '1 of 1 returned'."""
        fake = self._Fake(answers={"9876543210": {"name": "A SHARMA"}})
        vendor = self._vendor(session, "GL1006", "9876543210")
        runner = self._runner(session, fake)
        try:
            result = runner.run(vendor)
        finally:
            runner.close()

        finding = next(f for f in result.findings if f.check_id == "prefill")
        assert finding.value == "A SHARMA"
        assert finding.facts["fields"][0]["label"] == "Number"

    def test_the_stored_payload_is_what_the_facts_rebuild_from(
        self, session, seeded
    ):
        """THE PROPERTY THE WHOLE ADAPTER RESTS ON.

        Nobody knows what Gridlines returns, so the adapter extracts
        across several spellings and stores the payload whole. That is
        only defensible because the first real response can be parsed
        properly and every row already paid for rebuilt from storage for
        nothing — which requires the facts to be a pure projection of
        `raw_response`, subjects wrapper and all.
        """
        from scripts.backfill_facts import BUILDERS

        full = {"name": "A SHARMA", "pan": "ABCDE1234F", "dob": "1985-02-03",
                "address": "12 MG Rd, Mumbai"}
        fake = self._Fake(answers={"9876543210": full,
                                   "9876543211": dict(full, name="B RAO")})
        vendor = self._vendor(session, "GL1007", "9876543210\n9876543211")
        runner = self._runner(session, fake)
        try:
            result = runner.run(vendor)
        finally:
            runner.close()

        finding = next(f for f in result.findings if f.check_id == "prefill")
        assert BUILDERS["prefill"](finding.raw, vendor) == finding.facts

    def test_every_person_check_has_a_backfill_builder(self):
        """Without one the row is counted `no_builder` and SKIPPED
        SILENTLY, so a corrected parser would leave every person result
        already paid for stuck on the old shape — and these are the five
        checks whose response shape is not known yet, which is to say the
        five most likely to need exactly this."""
        from scripts.backfill_facts import BUILDERS

        for check_id in ("prefill", "footprint", "epfomember",
                         "emphistory"):
            assert check_id in BUILDERS, check_id

    def test_a_rebuild_is_honest_about_a_subject_that_failed(self):
        """A rebuilt blob must keep the gaps. A re-parse that turned two
        failed lookups into a clean table of three would be the original
        defect, reintroduced by the thing meant to fix it."""
        from scripts.backfill_facts import BUILDERS

        raw = {"subjects": [
            {"subject": "9876543210", "ok": True, "data": {"name": "A"}},
            {"subject": "9876543211", "ok": False, "error": "HTTP 500"},
        ], "subject_count": 2}
        blob = BUILDERS["prefill"](raw, None)
        assert any("Not examined" in f["label"] for f in blob["flags"])


# =====================================================================
# 10. The status endpoints must KNOW about this provider
# =====================================================================

class TestGridlinesIsVisibleToTheStatusEndpoints:
    """`/api/providers` is where Step 2 and the Step 3 dialog learn which
    checks a refusal covers. A provider with no row there greys nothing
    and explains nothing: the analyst picks five person checks, waits,
    and gets five unavailable results with no warning beforehand.

    This is the same omission the endpoint's own docstring records for
    ecourts and finagg — two live paid accounts no screen could ask
    about — reintroduced by adding a provider and forgetting one list.
    """

    def _rows(self, **over):
        """The /providers payload, built without standing up the app.

        Same harness as `test_provider_status_endpoint.py`: called
        directly with a session stand-in, because the endpoint makes one
        query and a real database adds nothing to what is being asserted.
        """
        from app.api import routes

        class _NoOutages:
            def scalars(self, *_a, **_k):
                return self

            def all(self):
                return []

        base = {"filesure_api_key": "f", "whoisxml_api_key": "w",
                "ecourts_api_key": "e", "finagg_api_key": "fa",
                "gridlines_api_key": "g"}
        base.update(over)
        import app.api.routes as r
        real = r.get_settings
        r.get_settings = lambda: Settings(**base)
        try:
            rows = routes.provider_status(session=_NoOutages())
        finally:
            r.get_settings = real
        return {row["provider"]: row for row in rows}

    def test_every_provider_with_checks_has_a_status_row(self):
        """Not a list of names kept in step by hand. Anything the catalog
        runs checks against must be reportable, or the next provider
        added repeats this."""
        from app.catalog.checks import CHECKS

        reported = set(self._rows())
        expected = {c.provider.value for c in CHECKS} - {"none", "in_house"}
        assert expected <= reported, f"missing: {expected - reported}"

    def test_gridlines_reports_configured_from_the_key(self):
        assert self._rows()["gridlines"]["configured"] is True
        assert self._rows(gridlines_api_key="")["gridlines"]["configured"] is False

    def test_gridlines_is_in_the_health_payload(self):
        from fastapi.testclient import TestClient

        from app.api.main import app

        body = TestClient(app).get("/health").json()
        assert "gridlines" in body["providers"]

    def test_an_outage_resolves_to_the_person_checks(self):
        """The point of the row. A refused Gridlines account must name
        the checks it covers, so the screen greys exactly those."""
        from app.services.runner import _checks_in_scope

        assert set(_checks_in_scope("gridlines", "")) == {
            "prefill", "footprint", "epfomember", "emphistory",
        }

    def test_the_row_says_these_are_a_person_not_a_company(self):
        """Every other provider reads a registry about a company. This
        one returns a named individual's records, and the one line a
        screen shows has to say so."""
        assert "person" in self._rows()["gridlines"]["note"].lower()

    def test_an_unset_key_does_not_read_as_no_record(self):
        """`not_configured` is a coverage gap. The note must not let it
        pass for a person who came back clean."""
        note = self._rows(gridlines_api_key="")["gridlines"]["note"]
        assert "not the same as a person having no record" in note.lower()


# =====================================================================
# 11. THE FIRST REAL RESPONSE
# =====================================================================
#
# Everything above section 10 was written without ever having seen one.
# On 7 Nov 2026 the live endpoint was called with the production key
# straight from the server, no VBC code in the path, and it returned
# HTTP 200 with a full body. The parser had been looking for `platforms`
# / `accounts` / `services` at the top of `data`; the real payload nests
# the platform list two levels further in, under a key none of those
# guesses matched.
#
# ParseGuard caught it exactly as designed — the check went UNAVAILABLE
# with the payload attached rather than reporting "no online presence"
# for a number with eight profiles. These tests pin the shape so the
# next guess has to be checked against it.

from app.tests.fixtures_gridlines import (  # noqa: E402
    FOOTPRINT_EMPTY,
    FOOTPRINT_LIVE,
)


class TestTheRealFootprintShape:
    def test_the_old_parser_would_have_found_nothing(self):
        """The defect, pinned. `data` is a STATUS envelope — `code` and
        `message` — and the payload is a key further in. Searching the
        envelope for the payload's field names finds nothing at all."""
        data = gl.unwrap(FOOTPRINT_LIVE)
        assert sorted(data) == ["code", "digital_profile_data", "message"]
        for guess in ("platforms", "accounts", "services", "digital_footprint"):
            assert guess not in data

    def test_descend_reaches_the_payload_and_keeps_the_status(self):
        inner, code, message = gl.descend(gl.unwrap(FOOTPRINT_LIVE))
        assert code == "1030"
        assert "Fetched digital footprint" in message
        assert isinstance(inner, list) and len(inner) == 4

    def test_blocks_are_read_by_name_never_by_index(self):
        """`status_code` and `status` blocks are interleaved with the
        real ones, so position is not stable."""
        inner, _, _ = gl.descend(gl.unwrap(FOOTPRINT_LIVE))
        blocks = gl.blocks_by_type(inner)
        assert set(blocks) == {"phone_data", "intelligence_data",
                               "status_code", "status"}

    @pytest.mark.parametrize(
        "account,expected",
        [
            ({"platform": "AMAZON", "user_exist": True}, True),
            ({"platform": "SNAPDEAL", "user_exist": False}, False),
            # THE ONE THAT MATTERS. An error is "we could not check",
            # and collapsing it into "no account" is this product's
            # cardinal sin at the level of a single row.
            ({"platform": "SKYPE", "error": True}, None),
            ({"platform": "UNKNOWN"}, None),
        ],
    )
    def test_a_platform_has_three_states_not_two(self, account, expected):
        assert gl.present_state(account) is expected

    def test_the_live_payload_parses(self):
        provider = _Recorder(FOOTPRINT_LIVE)
        out = provider.digital_footprint("9876543210", consent="Y")

        assert out["verified_name"] == "TEST SUBJECT"
        assert out["profile_count"] == 8
        assert out["risk_score"] == 0.173
        assert out["fintech_count"] == 0
        assert len(out["platforms"]) == 18

    def test_the_populated_digital_age_wins_over_the_errored_copy(self):
        """It appears twice on the real response and the second copy is
        `{"error": true}`. Taking that one yields a blank where a figure
        belongs, which reads as "no footprint" rather than "not
        established"."""
        out = _Recorder(FOOTPRINT_LIVE).digital_footprint("9876543210", consent="Y")
        assert out["digital_age"] == "1+ years (first seen 2025)"

    def test_an_uncomputed_score_is_not_rendered_as_zero(self):
        """`phone_email_linking_score` came back `{}`. Zero is a number
        we would have invented."""
        out = _Recorder(FOOTPRINT_LIVE).digital_footprint("9876543210", consent="Y")
        assert out["scores"]["phone_email_linking_score"] == {}

    def test_an_empty_payload_is_an_ANSWER_not_a_parse_gap(self):
        """`code` and `message` ride on every response including the
        empty ones. Guarding against the envelope would call a clear
        'no record found' a defect in us."""
        out = _Recorder(FOOTPRINT_EMPTY).digital_footprint("9876543210", consent="Y")
        assert out["platforms"] == []
        assert out["message"] == "No digital footprint found."

    def test_a_shape_we_still_cannot_read_RAISES(self):
        """The guard must survive the rewrite. A payload with blocks we
        parse nothing from is still a defect in us, not a person with no
        online presence."""
        mystery = {"data": {"code": "1030", "message": "ok",
                            "digital_profile_data": [
                                {"data_type": "phone_data",
                                 "someNewBlock": {"x": 1}}]}}
        with pytest.raises(ProviderParseGap):
            _Recorder(mystery).digital_footprint("9876543210", consent="Y")


class TestTheRealFootprintRenders:
    def _blob(self, payload=FOOTPRINT_LIVE):
        out = _Recorder(payload).digital_footprint("9876543210", consent="Y")
        return fx.person_footprint(out)

    def test_the_counts_separate_absent_from_unchecked(self):
        """Four silent platforms among eighteen is not the same as four
        absences, and the tiles must not add them together."""
        stats = {s["label"]: s["value"] for s in self._blob()["stats"]}
        # Eighteen platforms: 8 with an account, 5 without, 5 the
        # source could not reach.
        assert stats["Accounts found"] == "8"
        assert stats["Platforms checked"] == "13"
        assert stats["Could not check"] == "5"

    def test_an_unchecked_platform_is_flagged_by_name(self):
        flags = [f for f in self._blob()["flags"]
                 if "could not be checked" in f["label"]]
        assert len(flags) == 1
        assert "Times Prime" in flags[0]["detail"]
        assert "gaps, not absences" in flags[0]["detail"]

    def test_the_table_never_prints_an_error_as_No(self):
        rows = {r["platform"]: r["present"] for r in self._blob()["table"]["rows"]}
        assert rows["Amazon"] == "Yes"
        assert rows["Snapdeal"] == "No"
        assert rows["Skype"] == "Not checked"

    def test_the_name_on_the_number_leads(self):
        """The one field here that corroborates identity rather than
        describing activity."""
        fields = self._blob()["fields"]
        assert fields[0]["label"] == "Name on the number"
        assert fields[0]["value"] == "TEST SUBJECT"

    def test_the_providers_risk_score_is_labelled_as_theirs(self):
        field = next(f for f in self._blob()["fields"]
                     if f["label"] == "Phone risk score")
        assert field["value"] == "0.173 of 1.00"
        assert "feeds no SCAN parameter" in field["note"]

    def test_the_risk_score_feeds_nothing(self):
        """Importing another vendor's model into our score would make
        SCAN stop meaning what the methodology says it means."""
        from app.catalog.checks import CHECKS_BY_ID

        assert not CHECKS_BY_ID["footprint"].feeds

    def test_an_empty_answer_says_what_the_source_said(self):
        blob = self._blob(FOOTPRINT_EMPTY)
        flag = next(f for f in blob["flags"] if "no platform data" in f["label"])
        assert "No digital footprint found." in flag["detail"]
        assert "not a clearance" in flag["detail"]

    def test_no_raw_platform_constants_reach_the_screen(self):
        """`TIMES_PRIME` and `OYOROOMS` are the provider's constants. A
        client reads this."""
        text = str(self._blob())
        assert "TIMES_PRIME" not in text and "NOBROKER" not in text
        assert "Times Prime" in text and "NoBroker" in text


# =====================================================================
# 12. THE OTHER FOUR — READ AT DEPTH, BECAUSE THE ONE WE SAW WAS DEEP
# =====================================================================
#
# These four endpoints have still not been seen. What the footprint
# response settled is that the ENVELOPE is consistent and the content is
# NESTED: the platform list sits four levels down, under
# `digital_profile_data[].primary_data.account_details`. A top-level
# lookup could not have found it with any number of spellings.
#
# So the four unseen ones search the whole payload tree. That is a
# widened net and not a licence to invent — ParseGuard is unchanged, and
# a payload that carries content and yields nothing still raises.

class TestDeepSearchHandlesNesting:
    def _nested(self, inner: dict) -> dict:
        """The real envelope, with an arbitrary payload inside it."""
        return {"request_id": "r", "status": 200,
                "data": {"code": "1030", "message": "ok",
                         "profile_data": [{"data_type": "phone_data",
                                           "primary_data": inner}]}}

    def test_a_field_four_levels_down_is_found(self):
        provider = _Recorder(self._nested(
            {"identity": {"details": {"pan": "ABCDE1234F"}}}))
        out = provider.mobile_prefill("9876543210", consent="Y")
        assert out["pan"] == "ABCDE1234F"

    def test_the_shallowest_match_wins(self):
        """Breadth-first, and it matters: on the real footprint response
        `digital_age` appears at two depths and the shallow copy is the
        populated one. Depth-first returns the errored copy."""
        source = {"name": "SHALLOW", "a": {"b": {"name": "DEEP"}}}
        assert gl.deep_find(source, "name") == "SHALLOW"

    def test_every_list_is_collected_not_just_the_first(self):
        """A provider may return several address blocks. Taking the
        first would silently drop the rest, and a dropped employer or
        address is exactly the gap this product may not create."""
        source = {"one": {"addresses": ["A", "B"]},
                  "two": {"addresses": ["C"]}}
        assert sorted(gl.deep_rows(source, "addresses")) == ["A", "B", "C"]

    def test_the_epfo_status_is_not_the_HTTP_status(self):
        """`"status": 200` sits at the top of every Gridlines response.
        A deep search for "status" would report the HTTP code as the
        member's EPFO status — a number that looks like data."""
        provider = _Recorder({"status": 200,
                              "data": {"code": "1", "message": "ok",
                                       "epfo_data": {"uan": "100123456789"}}})
        out = provider.epfo_member("9876543210", consent="Y")
        assert out["uan"] == "100123456789"
        assert out["status"] != 200

    def test_a_payload_that_still_cannot_be_read_RAISES(self):
        """The widened net must not become a silent pass. Content in,
        nothing out, is still a defect in us."""
        provider = _Recorder(self._nested({"somethingEntirelyNew": {"x": 1}}))
        with pytest.raises(ProviderParseGap):
            provider.mobile_prefill("9876543210", consent="Y")

    def test_an_empty_payload_is_still_an_answer(self):
        provider = _Recorder({"data": {"code": "1031",
                                       "message": "No record found.",
                                       "profile_data": []}})
        out = provider.mobile_prefill("9876543210", consent="Y")
        assert out["pan"] is None
        assert out["message"] == "No record found."

    def test_raw_keys_name_the_payloads_own_keys(self):
        """The field that makes a wrong parser cheap to fix. `[""]` —
        which a blocks-by-type of a flat payload produces — says nothing
        to anybody."""
        provider = _Recorder({"data": {"code": "1", "message": "ok",
                                       "epfo_data": {"uan": "100123456789",
                                                     "odd_field": 1}}})
        out = provider.epfo_member("9876543210", consent="Y")
        assert out["_raw_keys"] == ["odd_field", "uan"]


class TestTheOneLineSummary:
    """The line an analyst reads without opening anything. It is the
    only part of a finding that appears on the report summary, so a
    number that is wrong here is wrong in front of a client."""

    def test_footprint_counts_ACCOUNTS_not_platforms_checked(self):
        """The platform list holds every platform the source looked at,
        including the ones with no account and the ones it could not
        reach. Its length reports "18 accounts" for a number with 8."""
        from app.services.runner import _one_line

        data = _Recorder(FOOTPRINT_LIVE).digital_footprint(
            "9876543210", consent="Y")
        line = _one_line("footprint", data)
        assert line == "8 of 13 platforms, 5 unchecked"
        assert "18" not in line

    def test_an_empty_footprint_does_not_read_as_a_clean_one(self):
        from app.services.runner import _one_line

        data = _Recorder(FOOTPRINT_EMPTY).digital_footprint(
            "9876543210", consent="Y")
        assert _one_line("footprint", data) == "No online presence returned"


# =====================================================================
# 13. THE UAN, FOUND BY SHAPE
# =====================================================================
#
# Live, 7 Nov 2026: `/epfo-api/fetch-uan` returned HTTP 200 and this
# adapter could not read the number out of it — the sixth guessed field
# name in a row. Guessing a seventh is the same mistake with a
# different spelling, so the number is now identified by what it IS.
#
# A UAN is exactly twelve digits. Nothing else in an EPFO response is.
# A key whose name contains "uan" holding a twelve-digit value is
# therefore unambiguous, whatever the provider decided to call it.

class TestTheUanIsFoundByShape:
    @pytest.mark.parametrize(
        "key", ["uan", "uan_number", "uanNumber", "member_uan", "uanNo",
                "UAN", "uan_details"],
    )
    def test_any_uan_ish_key_is_read(self, key):
        assert gl.find_uan({"data": {"block": {key: "100123456789"}}}) \
            == "100123456789"

    def test_it_is_found_at_any_depth(self):
        deep = {"a": {"b": {"c": [{"d": {"member_uan": "100123456789"}}]}}}
        assert gl.find_uan(deep) == "100123456789"

    def test_a_uan_ish_key_that_is_not_a_uan_is_REFUSED(self):
        """`uan_status: "ACTIVE"` is not a UAN, and neither is a
        truncated one. Feeding either to the employment-history call
        would buy an answer about nobody."""
        assert gl.find_uan({"uan_status": "ACTIVE"}) is None
        assert gl.find_uan({"uan": "1234"}) is None
        assert gl.find_uan({"uan_count": 2}) is None

    def test_a_twelve_digit_number_under_an_unrelated_key_is_ignored(self):
        """BOTH conditions, not either. A twelve-digit value that is not
        under a uan-ish key is some other identifier."""
        assert gl.find_uan({"establishment_id": "100123456789"}) is None

    def test_the_named_lookup_still_wins_when_it_hits(self):
        """Cheaper and unambiguous. The shape search is the fallback,
        not the primary."""
        provider = _Recorder({"data": {"code": "1", "message": "ok",
                                       "epfo_data": {"uan": "100123456789"}}})
        assert provider.epfo_member("9876543210", consent="Y")["uan"] \
            == "100123456789"

    def test_an_unguessed_spelling_no_longer_costs_a_round_trip(self):
        """The case that actually happened: 200 from the provider, and
        a ProviderParseGap because the key was not one of three."""
        provider = _Recorder({"data": {"code": "1", "message": "ok",
                                       "epfo_data": {"member_uan": "100123456789",
                                                     "establishment": "ACME"}}})
        out = provider.epfo_member("9876543210", consent="Y")
        assert out["uan"] == "100123456789"


class TestAnUnreadablePayloadIsKept:
    """`ProviderParseGap` carries the response so the runner can persist
    it — "a response we have paid for and cannot read is the one
    artefact needed to fix the adapter".

    The multi-subject loop stored only the error string, so the first
    real EPFO response was bought, found unreadable, and thrown away.
    The stored row had an error and an empty `_raw_keys`, and the only
    way to see the shape was to pay for the call again.
    """

    def test_the_flag_names_the_fields_we_could_not_read(self):
        raw = {"subjects": [{
            "subject": "9876543210", "ok": False,
            "error": "ProviderParseGap: could not read 1 field(s)",
            "unreadable_payload": {
                "status": 200,
                "data": {"code": "1", "message": "ok",
                         "epfo_data": {"member_uan": "100123456789",
                                       "establishment": "ACME"}}},
        }], "subject_count": 1}
        detail = fx.person_subjects("epfomember", raw)["flags"][0]["detail"]
        assert "establishment, member_uan" in detail
        assert "without paying again" in detail

    def test_the_envelope_is_walked_so_the_keys_are_the_PAYLOADS(self):
        """Reporting `["data"]` would tell nobody anything."""
        from app.providers.factsets import _payload_keys

        assert _payload_keys(
            {"data": {"code": "1", "message": "m",
                      "profile_data": {"pan": "X", "dob": "Y"}}}
        ) == ["dob", "pan"]

    def test_a_failure_with_no_payload_still_reads_cleanly(self):
        raw = {"subjects": [{"subject": "9876543210", "ok": False,
                             "error": "HTTP 500"}], "subject_count": 1}
        detail = fx.person_subjects("prefill", raw)["flags"][0]["detail"]
        assert "gap, not a clearance" in detail
        assert "carried these fields" not in detail
