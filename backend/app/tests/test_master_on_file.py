"""A delta run must read the master it already paid for.

WHAT HAPPENED, 18 NOV 2026
--------------------------
`dirs` and `charges` make no provider call. They are read out of the
company master payload, which `run()` holds in a local called
`master_payload` — set when, and only when, `master` runs in that same
run.

`run(only=[...])` exists because re-running costs money, and it
deliberately drops a prerequisite that is already on file:

    already = {row.check_id for row in vendor.checks
               if row.status in ("pass", "warn", "fail")}

So on the "Run more checks" path, `master` was correctly not re-bought —
and `master_payload` stayed None. Every master-derived check then
reported:

    Directors list — N/A · Company master did not return, so no
                           directors are on file.

about a company whose master was in the database, fetched minutes
earlier, paid for. The screen said we had nothing. We had everything.

This is the same failure as a parse gap in different clothing: evidence
we hold, reported as evidence we do not. It is worse than a parse gap,
because "N/A" reads like the check was never applicable rather than like
something went wrong, so nobody goes looking.

WHY NOBODY SAW IT
-----------------
`test_a_prerequisite_already_on_file_is_not_bought_again` asserts that
`master` is NOT in the findings of a `only=["dirs"]` run. It passes. It
was the right assertion about billing and it says nothing about whether
the check that needed the prerequisite got anything — so the suite
proved we did not re-charge, and never asked what we returned.

These tests assert the other half.
"""

from __future__ import annotations

import pytest

from app.db.models import Vendor, VendorCheck
from app.services.runner import CheckRunner
from app.tests.conftest import DEFAULT_CLIENT_ID

CIN = "U46909MH2020PLC351339"

#: A master payload in the shape the live FileSure response has, trimmed
#: to the parts `dirs` and `charges` read.
MASTER_RAW = {
    "facts": {"status": "ACTIVE", "cin": CIN},
    "payload": {
        "cin": CIN,
        "masterData": {
            "directorData": [
                {"DIN": "08057013", "FirstName": "AADIT", "MiddleName": "KAVIT",
                 "LastName": "PALICHA", "dateOfAppointment": "28/08/2020",
                 "MCAUserRole": [
                     {"cin": CIN, "role": "Director", "ucin": "U1",
                      "companyName": "ZEPTO LIMITED",
                      "designation": "Managing Director", "directorFlag": "D",
                      "cessationDate": "", "currentDesignationDate": "28/08/2020"}
                 ]},
                {"DIN": "08057029", "FirstName": "KAIVALYA", "MiddleName": "",
                 "LastName": "VOHRA", "dateOfAppointment": "28/08/2020",
                 "MCAUserRole": [
                     {"cin": CIN, "role": "Director", "ucin": "U2",
                      "companyName": "ZEPTO LIMITED", "designation": "Director",
                      "directorFlag": "D", "cessationDate": "",
                      "currentDesignationDate": "28/08/2020"}
                 ]},
            ],
            "indexChargesData": [],
        },
    },
}


def _vendor(session, vid: str, *, selected: list[str]) -> Vendor:
    vendor = Vendor(id=vid, client_id=DEFAULT_CLIENT_ID, name="Zepto",
                    legal_name="ZEPTO LIMITED", cin=CIN, selected=selected)
    session.add(vendor)
    return vendor


def _master_row(vid: str, *, status: str = "pass", raw=MASTER_RAW) -> VendorCheck:
    return VendorCheck(vendor_id=vid, check_id="master", status=status,
                       value="ACTIVE", raw_response=raw)


def _run(session, vendor, only: list[str]):
    runner = CheckRunner(session)
    try:
        return runner.run(vendor, only=only)
    finally:
        runner.close()


def _finding(result, check_id: str):
    return next((f for f in result.findings if f.check_id == check_id), None)


class TestADeltaRunReadsTheMasterOnFile:
    def test_directors_come_back_instead_of_not_applicable(self, session, seeded):
        """THE REGRESSION. This returned SKIP / "Company master did not
        return" with the master sitting in the same table."""
        vendor = _vendor(session, "MF0001", selected=["master", "dirs"])
        session.add(_master_row("MF0001"))
        session.flush()

        finding = _finding(_run(session, vendor, ["dirs"]), "dirs")

        assert finding is not None
        assert finding.value == "2 directors"
        assert "AADIT KAVIT PALICHA" in finding.detail

    def test_charges_are_read_from_it_too(self, session, seeded):
        """`dirs` is the one that was reported, but `charges` reads the
        same local and failed the same way."""
        vendor = _vendor(session, "MF0002", selected=["master", "charges"])
        session.add(_master_row("MF0002"))
        session.flush()

        finding = _finding(_run(session, vendor, ["charges"]), "charges")

        assert finding is not None
        assert finding.value == "No open charges"

    def test_master_is_still_not_re_bought(self, session, seeded):
        """The billing guard this path exists for must survive the fix."""
        vendor = _vendor(session, "MF0003", selected=["master", "dirs"])
        session.add(_master_row("MF0003"))
        session.flush()

        result = _run(session, vendor, ["dirs"])

        assert _finding(result, "master") is None, (
            "master was already on file; a delta run must not call it again"
        )


class TestItRefusesEvidenceItShouldNotUse:
    def test_an_unavailable_master_is_not_fed_to_the_parser(self, session, seeded):
        """An `unavailable` row's raw_response is a ParseGuard envelope,
        not a company. Handing it on would turn one unreadable response
        into three."""
        vendor = _vendor(session, "MF0004", selected=["master", "dirs"])
        session.add(_master_row(
            "MF0004", status="unavailable",
            raw={"_note": "could not be read", "payload": {"masterData": {}}},
        ))
        session.flush()

        finding = _finding(_run(session, vendor, ["dirs"]), "dirs")

        # master is NOT in `already` (unavailable is not examined), so the
        # delta run re-expands it. Either way the one thing that must not
        # happen is the gap envelope being read as a company.
        assert finding is None or "AADIT" not in (finding.detail or "")

    def test_no_master_row_at_all_still_says_so_honestly(self, session, seeded):
        """With nothing on file the old message is the right one."""
        vendor = _vendor(session, "MF0005", selected=["dirs"])
        session.flush()

        finding = _finding(_run(session, vendor, ["dirs"]), "dirs")

        if finding is not None:
            assert "director" in finding.detail.lower()

    def test_a_row_with_no_payload_key_is_ignored(self, session, seeded):
        """Rows written before the payload was kept carry facts only.
        `master.get("payload", master)` would hand the FACTS blob to the
        directors parser, which reads `masterData` and would find none —
        an empty board reported as fact."""
        vendor = _vendor(session, "MF0006", selected=["master", "dirs"])
        session.add(_master_row("MF0006", raw={"facts": {"status": "ACTIVE"}}))
        session.flush()

        finding = _finding(_run(session, vendor, ["dirs"]), "dirs")

        assert finding is not None
        assert finding.value != "0 directors", (
            "a facts-only row must not be read as a company with no board"
        )
