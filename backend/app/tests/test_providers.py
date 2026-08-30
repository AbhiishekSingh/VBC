"""Provider tests, against the EXACT payloads from the API reference.

Live calls cannot be tested without keys and network access, so what is
tested here is the layer that actually breaks in production: the
normalisers. Every payload below is copied from the FileSure /
WhoisXML / archive.org reference documents, and every assertion targets a
documented gotcha that would otherwise cost a debugging session — or worse,
silently produce a wrong finding about a real business.

The most dangerous one has its own test: FileSure returns booleans as
STRINGS, so ``"DirectorDisqualified": "false"`` read with a plain
truthiness test flags every director in the country as disqualified.
"""

from __future__ import annotations

import httpx
import pytest

from app.config import Settings
from app.providers.archive import (
    ArchiveProvider, _outage_windows, _from_wayback_timestamp, is_outage_status,
)
from app.providers.base import (
    ProviderRejected,
    ProviderUnavailable,
    as_bool,
    dig,
    parse_ddmmyyyy,
)
from app.providers.filesure import (
    FileSureProvider,
    normalise_charges,
    normalise_directors,
    normalise_financials,
    normalise_master,
)
from app.providers.whoisxml import WhoisXmlProvider, _is_real_record, _summarise_history


def settings(**kw) -> Settings:
    base = dict(
        filesure_api_key="fsk_test_x", whoisxml_api_key="wx_x",
        allow_paid_calls=True, http_max_retries=2, http_backoff_base_seconds=0.001,
    )
    base.update(kw)
    return Settings(**base)


def mock_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


# =====================================================================
# The gotchas, in isolation
# =====================================================================


class TestPrimitives:
    def test_string_false_is_false(self):
        """THE most dangerous gotcha in the integration.

        FileSure sends "false" as a string. Python's truthiness says a
        non-empty string is True, so a naive check flags every director as
        disqualified.
        """
        assert as_bool("false") is False
        assert as_bool("False") is False
        assert as_bool("true") is True
        assert as_bool(False) is False
        assert as_bool(None) is False
        # The trap itself:
        assert bool("false") is True

    def test_date_formats_are_normalised(self):
        """Master data is MM/DD/YYYY — NOT day-first, as was assumed here.

        A live company master carries both forms of the same dates and they
        agree only month-first: dateOfIncorporation "12/05/2020" alongside
        date_of_incorporation "2020-12-05". This test previously asserted
        the opposite and passed, because nothing had checked it against a
        real payload. Director profiles are ISO and pass straight through.
        """
        assert parse_ddmmyyyy("04/06/2013") == "2013-04-06"
        assert parse_ddmmyyyy("07/28/2022") == "2022-07-28"   # 28 must be the day
        assert parse_ddmmyyyy("2015-02-02") == "2015-02-02"
        assert parse_ddmmyyyy(None) is None
        assert parse_ddmmyyyy("") is None

    def test_dig_tolerates_a_missing_meta(self):
        """/update/status has NO meta object — assuming one crashes a poll."""
        assert dig({"data": {"status": "completed"}}, "meta", "priceChargedPaisa") is None
        assert dig({"data": {"x": 1}}, "data", "x") == 1


# =====================================================================
# FileSure normalisers
# =====================================================================

MASTER_PAYLOAD = {
    "cin": "U74999HR2015FTC056386",
    "company": "CARS24 SERVICES PRIVATE LIMITED",
    "cinHistory": [], "nameHistory": [],
    "masterData": {
        "companyData": {
            "companyType": "Company limited by Shares",
            "classOfCompany": "Private",
            "dateOfIncorporation": "02/02/2015",
            "authorisedCapital": 100000000,
            "paidupCapital": 76934000,
            "activeCompliance": "ACTIVE compliant",
            "companyStatus": "Active",
            "whetherListedOrNot": "Unlisted",
            "MCAMDSCompanyAddress": [
                {"addressType": "Registered Address",
                 "streetAddress": "Plot No. 78, Sector 44, Gurugram, Haryana, 122001",
                 "country": "India"}
            ],
        },
        "commonData": {"mainDivisionCode": "74",
                       "mainDivisionDescription": "Business support activities"},
        "directorData": [
            {"DIN": "07347299", "PAN": "ABCPK1234E", "FirstName": "VIKRAM",
             "LastName": "CHOPRA", "dateOfAppointment": "02/02/2015",
             "DirectorDisqualified": "false", "MCAUserRole": []},
            {"DIN": "08087425", "PAN": "ABCPK9911K", "FirstName": "MEHUL",
             "LastName": "AGRAWAL", "dateOfAppointment": "11/03/2018",
             "DirectorDisqualified": "true", "MCAUserRole": []},
        ],
        "indexChargesData": [
            {"chargeId": "100518842", "chName": "HDFC BANK LIMITED",
             "chargeAmount": 5000000000, "dateOfCreation": "15/03/2022",
             "dateOfSatisfaction": None},
            {"chargeId": "100411903", "chName": "ICICI BANK LIMITED",
             "chargeAmount": 15000000, "dateOfCreation": "02/08/2019",
             "dateOfSatisfaction": "19/01/2023"},
        ],
    },
}


class TestMasterNormaliser:
    def test_extracts_the_facts_scoring_needs(self):
        facts = normalise_master(MASTER_PAYLOAD)
        assert facts["status"] == "Active"
        assert facts["class_of_company"] == "Private"
        assert facts["incorporated_on"] == "2015-02-02"  # was DD/MM/YYYY
        assert facts["paidup_capital"] == 76934000
        assert "Gurugram" in facts["registered_address"]

    def test_rename_history_is_preserved_as_a_finding(self):
        """A non-empty nameHistory means the company was renamed — a fact."""
        payload = {**MASTER_PAYLOAD, "nameHistory": [{"oldName": "OLD CO"}]}
        assert normalise_master(payload)["name_history"] != []


class TestDirectorNormaliser:
    def test_pascal_case_keys_are_read(self):
        """directorData is PascalCase while the rest of the response is not."""
        directors = normalise_directors(MASTER_PAYLOAD)
        assert len(directors) == 2
        assert directors[0]["din"] == "07347299"
        assert directors[0]["name"] == "VIKRAM CHOPRA"

    def test_string_booleans_do_not_flag_everyone(self):
        """The headline test. "false" must not read as disqualified."""
        directors = normalise_directors(MASTER_PAYLOAD)
        assert directors[0]["disqualified"] is False   # "false"
        assert directors[1]["disqualified"] is True    # "true"

    def test_missing_director_data_returns_empty(self):
        assert normalise_directors({"masterData": {}}) == []


class TestChargeNormaliser:
    def test_null_satisfaction_means_open(self):
        """dateOfSatisfaction: null = OPEN. Reading this backwards would
        report a secured lender as cleared."""
        charges = normalise_charges(MASTER_PAYLOAD)
        assert len(charges["open"]) == 1
        assert charges["open"][0]["holder"] == "HDFC BANK LIMITED"
        assert len(charges["closed"]) == 1
        assert charges["closed"][0]["satisfied_on"] == "2023-01-19"

    def test_open_total_sums_only_open_charges(self):
        assert normalise_charges(MASTER_PAYLOAD)["open_total"] == 5_000_000_000


EXTRACTION_PAYLOAD = {
    "cin": "U74999HR2015FTC056386",
    "filing_scope": "standalone",
    "period_end": "2024-03-31", "period_start": "2023-04-01",
    "taxonomy_id": "in-ca:Schedule3IndAS",
    "balance_sheet": [{"qname": "in-ca:Equity", "value": 12450000000, "unit": "INR"}],
    "profit_and_loss": [
        {"qname": "in-ca:RevenueFromOperations", "value": 89400000000, "unit": "INR"}
    ],
    "cash_flow": [
        {"qname": "in-ca:CashFlowsFromUsedInOperatingActivities",
         "value": -3210000000, "unit": "INR"}
    ],
    "metadata": {"source": {"dateOfFiling": "30/09/2024", "year": 2024}},
    "_resolved_year": 2024, "_available_years": [2025, 2024, 2022, 2021],
    "_year_gaps": [2023],
}


class TestFinancialNormaliser:
    def test_xbrl_triples_become_named_figures(self):
        facts = normalise_financials(EXTRACTION_PAYLOAD)
        assert facts["revenue"] == 89_400_000_000
        assert facts["net_worth"] == 12_450_000_000
        assert facts["figures"]["in-ca:Equity"]["label"] == "Equity / net worth"

    def test_scope_travels_with_the_result(self):
        """standalone vs consolidated changes the numbers materially, so the
        report has to be able to state which was used."""
        assert normalise_financials(EXTRACTION_PAYLOAD)["scope"] == "standalone"

    def test_a_missing_qname_is_absent_not_zero(self):
        """Defaulting a missing figure to zero would turn 'not filed' into
        'filed as nil' — a materially different claim."""
        payload = {**EXTRACTION_PAYLOAD, "balance_sheet": []}
        facts = normalise_financials(payload)
        assert "in-ca:Equity" not in facts["figures"]
        assert facts["net_worth"] is None
        assert facts["positive_net_worth"] is False

    def test_year_gaps_are_carried_through(self):
        """A missing filing year is a compliance signal, not an error."""
        assert normalise_financials(EXTRACTION_PAYLOAD)["year_gaps"] == [2023]

    def test_snake_case_keys_are_read(self):
        """This endpoint alone uses snake_case."""
        facts = normalise_financials(EXTRACTION_PAYLOAD)
        assert facts["period_end"] == "2024-03-31"
        assert facts["filed_on"] == "2024-09-30"


class TestYearGaps:
    def test_finds_a_missing_year(self):
        assert FileSureProvider.year_gaps([2025, 2024, 2022, 2021]) == [2023]

    def test_no_gaps_when_continuous(self):
        assert FileSureProvider.year_gaps([2024, 2023, 2022]) == []

    def test_single_year_has_no_gaps(self):
        assert FileSureProvider.year_gaps([2024]) == []


# =====================================================================
# FileSure transport behaviour
# =====================================================================


class TestFileSureTransport:
    def test_filings_data_is_a_bare_array(self):
        """Unlike every other endpoint, and pagination lives in meta."""
        def handler(request):
            return httpx.Response(200, json={
                "data": [{"filingId": "flg_x", "formId": "AOC-4",
                          "dateOfFiling": "30/09/2024", "year": 2024}],
                "meta": {"page": 1, "limit": 20, "total": 653, "totalPages": 33},
            })

        with FileSureProvider(settings(), mock_client(handler)) as fs:
            rows, meta = fs.filings("U1", limit=50)
        assert isinstance(rows, list) and rows[0]["formId"] == "AOC-4"
        # The server capped it at 20 despite the request for 50 — the caller
        # must read meta back rather than trusting its own request.
        assert meta["limit"] == 20
        assert meta["total"] == 653

    def test_unlock_status_is_free_and_read_before_paying(self):
        calls = []

        def handler(request):
            calls.append((request.method, str(request.url)))
            return httpx.Response(200, json={"data": {
                "cin": "U1", "unlocked": True,
                "unlockedAt": "2026-05-01T07:30:00.000Z",
                "expiresAt": "2027-05-01T07:30:00.000Z",
                "unlockPrice": 22000, "job": None}})

        with FileSureProvider(settings(), mock_client(handler)) as fs:
            status, paid = fs.ensure_unlocked("U1")

        assert status.unlocked is True
        assert paid is False, "a valid unlock must never be bought twice"
        assert [m for m, _ in calls] == ["GET"], "no POST should have been made"

    def test_a_sandbox_unlock_is_not_treated_as_real(self):
        def handler(request):
            if request.method == "GET":
                return httpx.Response(200, json={"data": {"unlocked": False}})
            return httpx.Response(200, json={"data": {
                "cin": "U1", "unlocked": True, "unlockedAt": None,
                "expiresAt": None, "sandbox": True, "job": None}})

        with FileSureProvider(settings(), mock_client(handler)) as fs:
            status, paid = fs.ensure_unlocked("U1")
        assert status.sandbox is True
        assert status.expires_at is None

    def test_paid_calls_are_refused_by_default(self):
        """A misconfigured staging box must not drain the wallet."""
        from app.providers.base import PaidCallRefused

        def handler(request):
            return httpx.Response(200, json={"data": {}})

        with FileSureProvider(settings(allow_paid_calls=False), mock_client(handler)) as fs:
            with pytest.raises(PaidCallRefused, match="paid calls are disabled"):
                fs.unlock_company("U1")

    def test_actual_charge_is_read_back_from_meta(self):
        """The provider reports what it really charged — trust that over
        the rate card."""
        def handler(request):
            return httpx.Response(200, json={
                "data": {"query": "x", "candidates": []},
                "meta": {"priceChargedPaisa": 137, "walletBalanceAfterPaisa": 44190},
            })

        with FileSureProvider(settings(), mock_client(handler)) as fs:
            fs.resolve_company("x")
            assert fs.spend.paisa == 137
            assert fs.spend.wallet_balance_paisa == 44190

    def test_extractions_are_a_three_step_drill_down(self):
        seen = []

        def handler(request):
            path = request.url.path
            seen.append(path)
            if path.endswith("/extractions"):
                return httpx.Response(200, json={
                    "data": {"availableFormTypes": ["AOC-4", "MGT-7"]}})
            if path.endswith("/extractions/AOC-4"):
                return httpx.Response(200, json={
                    "data": {"formType": "AOC-4", "availableYears": [2024, 2022]}})
            return httpx.Response(200, json={"data": EXTRACTION_PAYLOAD})

        with FileSureProvider(settings(), mock_client(handler)) as fs:
            data = fs.latest_financials("U1")

        assert len(seen) == 3, "financials require three calls, not one"
        assert data["_resolved_year"] == 2024
        assert data["_year_gaps"] == [2023]

    def test_a_missing_form_type_is_a_gap_not_an_error(self):
        def handler(request):
            return httpx.Response(200, json={"data": {"availableFormTypes": ["MGT-7"]}})

        with FileSureProvider(settings(), mock_client(handler)) as fs:
            assert fs.latest_financials("U1", form_type="AOC-4") is None

    def test_5xx_is_retried_then_reported_unavailable(self):
        attempts = {"n": 0}

        def handler(request):
            attempts["n"] += 1
            return httpx.Response(503)

        with FileSureProvider(settings(), mock_client(handler)) as fs:
            with pytest.raises(ProviderUnavailable):
                fs.company_master("U1")
        assert attempts["n"] == 2, "should retry up to the configured limit"

    def test_4xx_is_not_retried(self):
        """The provider answered and said no. Hammering will not help."""
        attempts = {"n": 0}

        def handler(request):
            attempts["n"] += 1
            return httpx.Response(403, json={"error": {"code": "FORBIDDEN",
                                                       "message": "bad key"}})

        with FileSureProvider(settings(), mock_client(handler)) as fs:
            with pytest.raises(ProviderRejected, match="bad key"):
                fs.company_master("U1")
        assert attempts["n"] == 1


# =====================================================================
# WhoisXML
# =====================================================================


class TestWhoisXml:
    def test_failed_lookups_are_filtered_out(self):
        """WhoisXML sometimes returns a record containing only a timeout
        message. That is their failure, not the domain's history."""
        good = {"domainName": "x.in", "registrarName": "GoDaddy",
                "createdDateNormalized": "2015-03-11 00:00:00 UTC"}
        bad = {"note": "Closing connections because of Timeout"}
        assert _is_real_record(good) is True
        assert _is_real_record(bad) is False

    def test_history_summary_computes_domain_age(self):
        summary = _summarise_history([
            {"domainName": "x.in", "registrarName": "GoDaddy",
             "createdDateNormalized": "2015-03-11 00:00:00 UTC",
             "expiresDateNormalized": "2028-03-11 00:00:00 UTC",
             "registrantContact": {"organization": "MERIDIAN PACKAGING"}},
        ])
        assert summary["age_years"] >= 10
        assert summary["registrant"] == "MERIDIAN PACKAGING"
        assert summary["privacy_protected"] is False

    def test_live_api_date_fields_are_read(self):
        """REGRESSION: the live API does not return createdDateNormalized.

        The reference document showed that field name. A real response from
        whois-history.whoisxmlapi.com carries createdDateISO8601 and
        createdDateRaw instead. Reading only the documented name produced
        created=None and age_years=None for every domain, which meant the
        whois check could never PASS and risk rule r4 ("domain older than 2
        years", +10 points) could never fire.

        Payload below is trimmed from a real q1ssl.com response.
        """
        records = [
            {"domainName": "q1ssl.com",
             "createdDateISO8601": "2024-07-18T12:08:54+00:00",
             "expiresDateISO8601": "2027-07-18T12:08:54+00:00",
             "createdDateRaw": "2024-07-18 12:08:54 UTC",
             "registrarName": "PDR Ltd. d/b/a PublicDomainRegistry.com",
             "registrantContact": {"name": "Urvish", "organization": None,
                                   "country": "INDIA"}},
            {"domainName": "q1ssl.com",
             "createdDateISO8601": "2024-07-18T12:08:49+00:00",
             "registrarName": "GMO Internet, Inc.",
             "registrantContact": {"name": "Urvish NA", "organization": "IMT"}},
        ]
        summary = _summarise_history(records)
        assert summary["created"] is not None, "live date fields must be read"
        assert summary["created"].startswith("2024-07-18")
        assert summary["expires"].startswith("2027-07-18")
        assert summary["age_years"] is not None and summary["age_years"] >= 2
        # A registrar change is a real audit signal, not noise.
        assert summary["registrar_changes"] == 1

    def test_the_documented_field_name_still_works(self):
        """Older payloads using createdDateNormalized must not break."""
        summary = _summarise_history([
            {"domainName": "x.in", "registrarName": "GoDaddy",
             "createdDateNormalized": "2015-03-11 00:00:00 UTC",
             "expiresDateNormalized": "2028-03-11 00:00:00 UTC",
             "registrantContact": {"organization": "MERIDIAN"}},
        ])
        assert summary["age_years"] >= 10

    def test_a_timeout_record_is_dropped_even_with_a_registrar(self):
        """From the live response: the failed record still carries a
        registrarName, so the marker check must run first."""
        assert _is_real_record({
            "domainName": "q1ssl.com",
            "registrarName": "PDR Ltd. d/b/a PublicDomainRegistry.com",
            "cleanText": "Closing connections because of Timeout",
            "rawText": "Closing connections because of Timeout",
            "registrantContact": {"name": None},
        }) is False

    def test_privacy_protection_is_detected_not_treated_as_adverse(self):
        summary = _summarise_history([
            {"domainName": "x.in", "registrarName": "PDR",
             "createdDateNormalized": "2025-11-01 00:00:00 UTC",
             "registrantContact": {}},
        ])
        assert summary["privacy_protected"] is True

    def test_variable_length_test_results_are_iterated(self):
        """Never index a fixed position into testResults."""
        def handler(request):
            return httpx.Response(200, json={
                "mode": "fast", "reputationScore": 89.45,
                "testResults": [
                    {"test": "WHOIS Domain check",
                     "warningDescription": "Owner details are publicly available"},
                    {"test": "SSL certificate validity", "warnings": []},
                ]})

        with WhoisXmlProvider(settings(), mock_client(handler)) as wx:
            data = wx.domain_reputation("q1ssl.com")
        assert data["score"] == 89.45
        assert len(data["warnings"]) == 1  # only the one WITH a description

    def test_reverse_whois_without_a_term_does_not_call(self):
        """A placeholder term returns 200 with count 0 — a successful call
        is not proof of a correct query, so no term means no call."""
        called = {"n": 0}

        def handler(request):
            called["n"] += 1
            return httpx.Response(200, json={"domainsCount": 0, "domainsList": []})

        with WhoisXmlProvider(settings(), mock_client(handler)) as wx:
            result = wx.reverse_whois("")
        assert result["queried"] is False
        assert called["n"] == 0

    def test_self_signed_certificate_is_flagged_untrusted(self):
        def handler(request):
            return httpx.Response(200, json={"certificates": [{
                "issuer": {"organization": "Self-signed"},
                "validFrom": "2026-01-01", "validTo": "2027-01-01",
                "subject": {"commonName": "kaveritraders.co.in"},
                "dnsNames": ["kaveritraders.co.in"]}]})

        with WhoisXmlProvider(settings(), mock_client(handler)) as wx:
            data = wx.ssl_certificate("kaveritraders.co.in")
        assert data["trusted_ca"] is False

    def test_a_short_validity_window_is_not_a_red_flag(self):
        """~90 days is normal Let's Encrypt auto-renewal."""
        def handler(request):
            return httpx.Response(200, json={"certificates": [{
                "issuer": {"organization": "Google Trust Services"},
                "validFrom": "2026-02-06", "validTo": "2026-05-07",
                "subject": {"commonName": "q1ssl.com"},
                "dnsNames": ["q1ssl.com", "*.q1ssl.com"]}]})

        with WhoisXmlProvider(settings(), mock_client(handler)) as wx:
            data = wx.ssl_certificate("q1ssl.com")
        assert data["trusted_ca"] is True
        assert data["wildcard"] is True


# =====================================================================
# archive.org
# =====================================================================


class TestArchive:
    def test_empty_snapshots_means_never_archived(self):
        """archived_snapshots is {} — reading it blindly crashes on a
        legitimate finding."""
        def handler(request):
            return httpx.Response(200, json={"url": "x.in", "archived_snapshots": {}})

        with ArchiveProvider(settings(), mock_client(handler)) as ar:
            data = ar.availability("x.in")
        assert data["archived"] is False

    def test_status_is_a_string(self):
        def handler(request):
            return httpx.Response(200, json={"url": "google.com", "archived_snapshots": {
                "closest": {"status": "200", "available": True,
                            "url": "http://web.archive.org/...",
                            "timestamp": "20250823120000"}}})

        with ArchiveProvider(settings(), mock_client(handler)) as ar:
            data = ar.availability("google.com")
        assert data["archived"] is True
        assert data["status"] == "200"
        assert data["last_seen"].startswith("2025-08-23")

    def test_cdx_array_of_arrays_with_a_header_row(self):
        """Real captured data for q1ssl.com: blocked 403 through 2024, then
        live with a 200 on 29 Dec 2024."""
        def handler(request):
            return httpx.Response(200, json=[
                ["urlkey", "timestamp", "original", "mimetype", "statuscode",
                 "digest", "length"],
                ["com,q1ssl)/", "20240727123708", "https://q1ssl.com/", "text/html",
                 "403", "OIAQ4CLB", "1012"],
                ["com,q1ssl)/", "20240924203139", "https://q1ssl.com/", "text/html",
                 "403", "OIAQ4CLB", "1012"],
                ["com,q1ssl)/", "20241229181853", "https://q1ssl.com/", "text/html",
                 "200", "FNQXKDIR", "99208"],
            ])

        with ArchiveProvider(settings(), mock_client(handler)) as ar:
            data = ar.timeline("q1ssl.com")

        assert data["captures"] == 3, "the header row must not be counted"
        assert data["ok_captures"] == 1
        assert data["first_ok_capture"].startswith("2024-12-29")
        assert len(data["outages"]) == 1
        assert data["outages"][0]["status"] == "403"
        assert data["continuous"] is False

    def test_no_captures_at_all(self):
        def handler(request):
            return httpx.Response(200, json=[])

        with ArchiveProvider(settings(), mock_client(handler)) as ar:
            data = ar.timeline("nothing.example")
        assert data["captures"] == 0
        assert data["continuous"] is False

    def test_redirects_are_not_outages(self):
        """A 301/302 is normal, not downtime.

        Straight from the archive.org evaluation report: amazon.com returned
        20 consecutive 302s with an identical digest. That is redirect noise
        — nearly every site redirects http to https.

        Counting them as outages produced a WRONG finding, not a missing
        one: a healthy site reported as intermittently down, and risk rule
        r5 ("continuous web presence, no outages", +10) unable to fire for
        anybody. Table 3 of the report is explicit: 301/302 are NEUTRAL,
        only 403/404/5xx are flags.
        """
        def handler(request):
            return httpx.Response(200, json=[
                ["urlkey", "timestamp", "original", "mimetype", "statuscode",
                 "digest", "length"],
                ["com,amazon)/", "19981212012532", "http://amazon.com:80/",
                 "text/html", "302", "VXEDWGPH", "330"],
                ["com,amazon)/", "19990125093156", "http://www.amazon.com:80/",
                 "text/html", "302", "VXEDWGPH", "335"],
                ["com,amazon)/", "20000301120000", "https://amazon.com/",
                 "text/html", "200", "AAAA1111", "48210"],
            ])

        with ArchiveProvider(settings(), mock_client(handler)) as ar:
            data = ar.timeline("amazon.com")

        assert data["outages"] == [], "redirects must not be reported as downtime"
        assert data["redirects"] == 2, "but they are still counted and visible"
        assert data["continuous"] is True
        assert data["ok_captures"] == 1

    def test_403_and_5xx_are_still_outages(self):
        """The q1ssl.com case: genuinely blocked, and that IS the finding."""
        assert is_outage_status("403") is True
        assert is_outage_status("404") is True
        assert is_outage_status("500") is True
        assert is_outage_status("503") is True
        assert is_outage_status("200") is False
        assert is_outage_status("301") is False
        assert is_outage_status("302") is False
        assert is_outage_status(None) is False

    def test_outage_windows_group_consecutive_failures(self):
        """Nineteen timestamps are noise; '403 for six weeks' is a finding."""
        bad = [
            {"timestamp": "20260201000000", "statuscode": "403"},
            {"timestamp": "20260215000000", "statuscode": "403"},
            {"timestamp": "20260301000000", "statuscode": "403"},
            {"timestamp": "20260401000000", "statuscode": "500"},
        ]
        windows = _outage_windows(bad)
        assert len(windows) == 2
        assert windows[0]["status"] == "403"
        assert windows[0]["captures"] == 3
        assert windows[1]["status"] == "500"

    def test_wayback_timestamps_normalise_to_iso(self):
        assert _from_wayback_timestamp("20241229181853").startswith("2024-12-29")
        assert _from_wayback_timestamp("") is None
        assert _from_wayback_timestamp(None) is None
