"""The LegalCheck submit body — six failed attempts, one wrong field.

`POST /legal-check` returned `400 VALIDATION_ERROR` with an EMPTY
`details[]` on six structurally different bodies, and the check has sat as
a hook ever since. The catalog note blamed the submit endpoint being absent
from the published docs.

It is in the docs now, and the body was almost right. One field:

    individual  ->  subject.name
    company     ->  subject.company_name

Every attempt sent `subject.name`, for a company. Not a field the API
recognises on that subject type, so it read as a company with no name. The
empty `details[]` is why this cost six attempts instead of one.

These tests pin the shape against the documented schema so the next
provider-side change fails here, loudly, rather than as another silent 400.

NOTE: the fix is verified against the DOCUMENTATION, not against a live
submit. That call costs ₹99 and this codebase's record on documentation is
five adapters written from a reference document and five of them wrong.
Treat a green suite here as "the body now matches what is published", not
as "the check works".
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.config import Settings
from app.providers.ecourts import EcourtsProvider

ACCEPTED = {"data": {"code": "LC-A1B2C3D", "status": "queued",
                     "model": "eCI-1.2"}}


def provider(**settings_kwargs):
    sent: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        sent["body"] = json.loads(request.content)
        sent["headers"] = dict(request.headers)
        return httpx.Response(200, json=ACCEPTED)

    settings = Settings(ecourts_api_key="eci_live_test", allow_paid_calls=True,
                        http_max_retries=1, **settings_kwargs)
    p = EcourtsProvider(settings, client=httpx.Client(
        transport=httpx.MockTransport(handler)))
    p.sent = sent                       # type: ignore[attr-defined]
    return p


def submit(p, **kwargs):
    defaults = dict(subject_name="RELIANCE INDUSTRIES LIMITED",
                    idempotency_key="vbc-V1-court", client_ref_no="V1")
    return p.submit_legal_check(**{**defaults, **kwargs})


# =====================================================================
# 1 · The field that broke it
# =====================================================================

class TestTheNameField:
    def test_a_company_is_sent_as_company_name(self):
        """The whole defect, in one assertion."""
        p = provider()
        submit(p, subject_type="company")
        assert p.sent["body"]["subject"]["company_name"] == "RELIANCE INDUSTRIES LIMITED"

    def test_a_company_does_not_carry_a_plain_name(self):
        """`name` is individual-only. Sending both would be sending one
        field the API does not expect on this subject type — which is how
        the original 400 happened."""
        p = provider()
        submit(p, subject_type="company")
        assert "name" not in p.sent["body"]["subject"]

    def test_an_individual_is_sent_as_name(self):
        p = provider()
        submit(p, subject_type="individual", subject_name="Amit Kumar")
        assert p.sent["body"]["subject"]["name"] == "Amit Kumar"
        assert "company_name" not in p.sent["body"]["subject"]

    @pytest.mark.parametrize("given", ["Company", "COMPANY", " company "])
    def test_the_subject_type_is_matched_case_and_space_insensitively(self, given):
        """A select box value that arrives capitalised must not silently
        route a company down the individual branch."""
        p = provider()
        submit(p, subject_type=given)
        assert "company_name" in p.sent["body"]["subject"]


# =====================================================================
# 2 · Identity is the point of this check
#
# The report returns `identity_confidence` beside the risk band, and below
# `ecourts_min_score` a match is shown but never scored. Every identifier
# sent raises the chance the result can actually be used.
# =====================================================================

class TestIdentifiersAreSent:
    def test_the_cin_goes_with_the_submit(self):
        """Unique, where a company name is not."""
        p = provider()
        submit(p, subject_type="company", cin="L17110MH1973PLC019786")
        assert p.sent["body"]["subject"]["cin"] == "L17110MH1973PLC019786"

    def test_the_cin_is_normalised_to_upper_case(self):
        p = provider()
        submit(p, subject_type="company", cin=" l17110mh1973plc019786 ")
        assert p.sent["body"]["subject"]["cin"] == "L17110MH1973PLC019786"

    def test_the_board_goes_too(self):
        """Two companies of the same name are told apart by who runs them."""
        p = provider()
        submit(p, subject_type="company",
               directors=["MUKESH DHIRUBHAI AMBANI", "NIKHIL R MESWANI"])
        assert p.sent["body"]["subject"]["directors"] == [
            "MUKESH DHIRUBHAI AMBANI", "NIKHIL R MESWANI"]

    def test_company_addresses_use_the_registered_key(self):
        """The API separates where a person has lived from where a company
        is registered. Same list, different field."""
        p = provider()
        submit(p, subject_type="company", addresses=["Maker Chambers IV, Mumbai"])
        subject = p.sent["body"]["subject"]
        assert subject["registered_addresses"] == ["Maker Chambers IV, Mumbai"]
        assert "addresses" not in subject

    def test_individual_addresses_use_the_plain_key(self):
        p = provider()
        submit(p, subject_type="individual", addresses=["Patna, Bihar"])
        assert p.sent["body"]["subject"]["addresses"] == ["Patna, Bihar"]

    def test_individual_only_fields_never_reach_a_company_submit(self):
        """`father_name` on a company is meaningless and is exactly the kind
        of stray field that earns an empty-details 400."""
        p = provider()
        submit(p, subject_type="company", father_name="Ramesh Kumar",
               date_of_birth="1988-04-12")
        subject = p.sent["body"]["subject"]
        assert "father_name" not in subject
        assert "date_of_birth" not in subject

    def test_company_only_fields_never_reach_an_individual_submit(self):
        p = provider()
        submit(p, subject_type="individual", cin="L17110MH1973PLC019786",
               directors=["Someone"])
        subject = p.sent["body"]["subject"]
        assert "cin" not in subject
        assert "directors" not in subject

    def test_blank_identifiers_are_omitted_not_sent_empty(self):
        """An empty string is a value; a missing key is not. Sending
        `"cin": ""` invites the validator to reject it."""
        p = provider()
        submit(p, subject_type="company", cin="  ", pan="", directors=[])
        subject = p.sent["body"]["subject"]
        assert not {"cin", "pan", "directors"} & set(subject)


# =====================================================================
# 3 · The rest of the envelope
# =====================================================================

class TestTheEnvelope:
    def test_the_documented_top_level_keys_are_present(self):
        p = provider()
        submit(p)
        assert set(p.sent["body"]) == {"subject_type", "subject", "config"}

    def test_the_idempotency_key_is_a_header_not_a_body_field(self):
        """It costs ₹99 a submit. A retry must collect the existing job
        rather than start a second paid one."""
        p = provider()
        submit(p, idempotency_key="vbc-V1-court")
        assert p.sent["headers"]["idempotency-key"] == "vbc-V1-court"
        assert "Idempotency-Key" not in p.sent["body"]

    def test_the_purpose_is_declared(self):
        p = provider()
        submit(p)
        assert p.sent["body"]["config"]["purpose"] == "vendor_onboarding"

    def test_the_client_reference_is_the_vendor_id(self):
        """So a report collected days later can be reconciled."""
        p = provider()
        submit(p, client_ref_no="V1")
        assert p.sent["body"]["config"]["client_ref_no"] == "V1"

    def test_a_blank_subject_name_never_reaches_the_provider(self):
        """₹99 is not the right price for discovering the field was empty."""
        p = provider()
        with pytest.raises(ValueError, match="needs a subject name"):
            submit(p, subject_name="   ")
        assert p.sent == {}