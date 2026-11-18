"""A board of 11 directors, thrown away over a field MCA never sent.

WHAT HAPPENED, 18 NOV 2026
--------------------------
A ZEPTO LIMITED run (CIN U46909MH2020PLC351339) showed the Directors
list check as:

    Unavailable — Response not understood

The payload was fine. ``masterData.directorData[]`` held 11 directors,
each with a DIN, a full name, an appointment date and an
``MCAUserRole[]`` array of directorships. What it did not hold, under
any name anywhere, was a disqualification field: MCA's company master
does not always report s.164 standing, which lives in a separate
register.

``normalise_directors`` had a ParseGuard that fired whenever neither
``DirectorDisqualified`` nor ``isDisqualified`` appeared. On that
payload it fired, and the guard's remedy is to void the whole check. So
eleven directors' worth of real, paid-for evidence was discarded, and
the screen said the response could not be read.

THE GUARD WAS RIGHT ABOUT THE DANGER AND WRONG ABOUT THIS PAYLOAD
-----------------------------------------------------------------
It was written for the opposite failure, which is worse: if
``isDisqualified`` is ever RENAMED, reading no flag and reporting "no
directors disqualified" hides an adverse finding behind a green check,
and nobody investigates a green check.

Both failures come from the same mistake — only two answers were
available, ``False`` and "void the check" — and the fix is a third:

    True   this director is disqualified
    False  this response says they are not
    None   this response did not say

``None`` renders as blank, not "No", and the tile shows "—", not a
green zero. The guard survives in narrowed form: a gap is now raised
only when the PAYLOAD ITSELF names a disqualification under a field
this adapter does not read — which is proof the fact is there and we
are missing it, and is exactly the rename case.

WHAT THIS FILE ASSERTS
----------------------
That the board parses, and that nothing downstream turns "unreported"
into a clearance — not the stat tile, not the table cell, not the
summary line a reader actually reads.
"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.domain.types import CheckStatus
from app.providers import factsets
from app.providers.base import ProviderParseGap
from app.providers.filesure import normalise_directors
from app.services.runner import CheckRunner, Finding

CIN = "U46909MH2020PLC351339"


def _role(**over) -> dict:
    """An MCAUserRole entry in the shape the live payload actually sends.

    Every key here was in the ZEPTO response. Note what is NOT: no
    ``isDisqualified``. ``directorFlag`` is present and is NOT the
    disqualification flag — guessing that it was is the mistake this
    whole file exists to avoid.
    """
    return {
        "cin": CIN,
        "role": "Director",
        "ucin": "U1",
        "companyName": "ZEPTO LIMITED",
        "designation": "Managing Director",
        "directorFlag": "D",
        "cessationDate": "",
        "currentDesignationDate": "28/08/2020",
        **over,
    }


def _payload(*rows: dict) -> dict:
    return {"cin": CIN, "masterData": {"directorData": list(rows)}}


ZEPTO = _payload(
    {"DIN": "08057013", "FirstName": "AADIT", "MiddleName": "KAVIT",
     "LastName": "PALICHA", "dateOfAppointment": "28/08/2020",
     "MCAUserRole": [_role()]},
    {"DIN": "08057029", "FirstName": "KAIVALYA", "MiddleName": "VOHRA",
     "LastName": "VOHRA", "dateOfAppointment": "28/08/2020",
     "MCAUserRole": [_role(designation="Director")]},
)


class TestTheBoardParses:
    def test_the_directors_are_not_thrown_away(self):
        """THE REGRESSION. This raised ProviderParseGap."""
        directors = normalise_directors(ZEPTO)
        assert len(directors) == 2
        assert [d["din"] for d in directors] == ["08057013", "08057029"]

    def test_the_names_survive(self):
        names = [d["name"] for d in normalise_directors(ZEPTO)]
        assert names == ["AADIT KAVIT PALICHA", "KAIVALYA VOHRA VOHRA"]

    def test_the_directorships_survive(self):
        director = normalise_directors(ZEPTO)[0]
        assert director["designations"] == ["Managing Director"]
        assert director["still_serving"] is True


class TestUnreportedIsNotFalse:
    def test_the_flag_is_none_not_false(self):
        """``False`` puts "No" against a director's name on a
        client-facing screen, on the strength of a field nobody read."""
        assert all(d["disqualified"] is None for d in normalise_directors(ZEPTO))

    def test_a_reported_flag_still_reads_as_a_bool(self):
        """The tri-state must not cost the two states that worked."""
        payload = _payload(
            {"DIN": "08057013", "FirstName": "A", "LastName": "B",
             "MCAUserRole": [_role(isDisqualified="N")]},
            {"DIN": "08057029", "FirstName": "C", "LastName": "D",
             "MCAUserRole": [_role(isDisqualified="Y")]},
        )
        directors = normalise_directors(payload)
        assert directors[0]["disqualified"] is False
        assert directors[1]["disqualified"] is True

    def test_the_string_false_is_still_not_truthy(self):
        """The oldest bug in this adapter. ``"false"`` is a truthy string."""
        payload = _payload(
            {"DIN": "08057013", "FirstName": "A", "LastName": "B",
             "DirectorDisqualified": "false", "MCAUserRole": [_role()]},
        )
        assert normalise_directors(payload)[0]["disqualified"] is False

    def test_an_empty_string_counts_as_unsaid(self):
        """The API sends ``""`` as freely as it sends ``"N"``, and an
        empty string is not an assertion that nobody is disqualified."""
        payload = _payload(
            {"DIN": "08057013", "FirstName": "A", "LastName": "B",
             "MCAUserRole": [_role(isDisqualified="")]},
        )
        assert normalise_directors(payload)[0]["disqualified"] is None

    def test_one_bad_seat_still_disqualifies_the_person(self):
        """Unchanged behaviour: the flag is read across every role before
        the row, because a disqualification is not seat-specific."""
        payload = _payload(
            {"DIN": "08057013", "FirstName": "A", "LastName": "B",
             "MCAUserRole": [_role(isDisqualified="N"),
                             _role(cin="U1", isDisqualified="Y")]},
        )
        assert normalise_directors(payload)[0]["disqualified"] is True


class TestTheRenameGuardStillWorks:
    """The narrowing must not reopen the dangerous direction."""

    def test_a_renamed_row_field_is_still_a_gap(self):
        payload = _payload(
            {"DIN": "08057013", "FirstName": "A", "LastName": "B",
             "disqualificationStatus": "Y", "MCAUserRole": [_role()]},
        )
        with pytest.raises(ProviderParseGap, match="disqualification flag"):
            normalise_directors(payload)

    def test_a_renamed_role_field_is_still_a_gap(self):
        payload = _payload(
            {"DIN": "08057013", "FirstName": "A", "LastName": "B",
             "MCAUserRole": [_role(isDisqualifiedUnderS164="Y")]},
        )
        with pytest.raises(ProviderParseGap, match="disqualification flag"):
            normalise_directors(payload)

    def test_the_gap_names_the_field_it_found(self):
        """So whoever fixes the adapter is told the new name rather than
        asked to go and find the payload."""
        payload = _payload(
            {"DIN": "08057013", "FirstName": "A", "LastName": "B",
             "s164DisqualificationFlag": "Y", "MCAUserRole": [_role()]},
        )
        with pytest.raises(ProviderParseGap) as excinfo:
            normalise_directors(payload)
        assert "s164DisqualificationFlag" in str(excinfo.value)

    def test_the_gap_still_carries_the_payload(self):
        payload = _payload(
            {"DIN": "08057013", "FirstName": "A", "LastName": "B",
             "disqualifiedFlag": "Y", "MCAUserRole": [_role()]},
        )
        with pytest.raises(ProviderParseGap) as excinfo:
            normalise_directors(payload)
        assert excinfo.value.payload == payload

    def test_the_known_names_are_not_mistaken_for_a_rename(self):
        """``isDisqualified`` contains "disqualif" too. A guard that did
        not exclude the names it reads would fire on every payload."""
        payload = _payload(
            {"DIN": "08057013", "FirstName": "A", "LastName": "B",
             "DirectorDisqualified": "N",
             "MCAUserRole": [_role(isDisqualified="N")]},
        )
        assert normalise_directors(payload)[0]["disqualified"] is False


class TestNothingOnScreenReadsAsAClearance:
    """The facts blob is what a client-facing screen renders."""

    @staticmethod
    def _blob(payload: dict) -> dict:
        return factsets.directors(normalise_directors(payload))

    @staticmethod
    def _stat(blob: dict, label: str) -> dict:
        return next(s for s in blob["stats"] if s["label"] == label)

    def test_the_tile_is_a_dash_not_a_green_zero(self):
        """A tile reading "0" in green is a clearance assembled out of a
        field nobody read — the cardinal failure, in one number."""
        stat = self._stat(self._blob(ZEPTO), "Disqualified")
        assert stat["value"] == "—"
        assert stat["tone"] == "neutral"

    def test_the_table_cell_is_blank_not_no(self):
        cells = [r["disqualified"] for r in self._blob(ZEPTO)["table"]["rows"]]
        assert cells == [None, None]

    def test_the_blob_says_what_is_not_covered(self):
        flags = self._blob(ZEPTO)["flags"]
        flag = next(f for f in flags if "not reported" in f["label"].lower())
        assert flag["level"] == "info"
        assert "not covered by this check" in flag["detail"].lower()

    def test_the_directors_still_reach_the_table(self):
        """The point of the fix: the evidence is on the screen."""
        rows = self._blob(ZEPTO)["table"]["rows"]
        assert [r["name"] for r in rows] == [
            "AADIT KAVIT PALICHA", "KAIVALYA VOHRA VOHRA",
        ]

    def test_a_reported_clean_board_still_gets_its_green_zero(self):
        """When the source DOES say, the tile says so. "Nobody read it"
        and "the registry says nobody" are different findings and both
        have to be visible as themselves."""
        payload = _payload(
            {"DIN": "08057013", "FirstName": "A", "LastName": "B",
             "MCAUserRole": [_role(isDisqualified="N")]},
        )
        stat = self._stat(self._blob(payload), "Disqualified")
        assert stat["value"] == "0"
        assert stat["tone"] == "good"
        assert not any("not reported" in f["label"].lower()
                       for f in self._blob(payload).get("flags", []))

    def test_a_disqualified_director_still_gets_the_bad_tile_and_flag(self):
        payload = _payload(
            {"DIN": "08057013", "FirstName": "A", "LastName": "B",
             "MCAUserRole": [_role(isDisqualified="Y")]},
        )
        blob = self._blob(payload)
        assert self._stat(blob, "Disqualified")["tone"] == "bad"
        assert any(f["level"] == "bad" for f in blob["flags"])

    def test_a_mixed_board_counts_what_was_reported_and_says_so(self):
        """One director's flag read, one not. The count is of the ones
        actually reported, and the shortfall is stated rather than
        folded into the number."""
        payload = _payload(
            {"DIN": "08057013", "FirstName": "A", "LastName": "B",
             "MCAUserRole": [_role(isDisqualified="N")]},
            {"DIN": "08057029", "FirstName": "C", "LastName": "D",
             "MCAUserRole": [_role()]},
        )
        blob = self._blob(payload)
        assert self._stat(blob, "Disqualified")["value"] == "—"
        flag = next(f for f in blob["flags"] if "not reported" in f["label"].lower())
        assert "1 of these directors" in flag["detail"]


class FakeVendor:
    id = "V1"
    name = "Zepto"
    legal_name = "ZEPTO LIMITED"
    cin = CIN
    domain = None
    website = None
    gst = None
    selected: list[str] = []


def _runner() -> CheckRunner:
    runner = CheckRunner.__new__(CheckRunner)
    runner.session = None
    runner.settings = Settings()
    runner.spend = None
    runner.ecourts = runner.filesure = runner.whoisxml = runner.archive = None
    runner.finagg = runner.gridlines = runner.vision = None
    return runner


def _dirs(payload: dict) -> Finding:
    """The `dirs` branch of `_dispatch`, EXECUTED — not a reimplementation.

    `dirs` makes no call of its own; it reads the master payload already
    on file, which is what `master` is here.
    """
    return _runner()._dispatch(
        "dirs", FakeVendor(), CIN, {}, {"payload": payload}, None, {},
    )


class TestTheCheckReportsWhatItGot:
    def test_the_status_is_not_unavailable(self):
        """THE REGRESSION, at the surface the user saw."""
        assert _dirs(ZEPTO).status is not CheckStatus.UNAVAILABLE

    def test_the_value_counts_the_directors(self):
        assert _dirs(ZEPTO).value == "2 directors"

    def test_the_names_are_in_the_detail(self):
        detail = _dirs(ZEPTO).detail
        assert "AADIT KAVIT PALICHA (DIN 08057013)" in detail

    def test_the_detail_says_disqualification_was_not_reported(self):
        """PASS here means "the board came back", and the one thing a
        reader must not take from it is that the board is cleared. So the
        shortfall is in the sentence, not only in a flag further down."""
        detail = _dirs(ZEPTO).detail
        assert "not reported in this response" in detail
        assert "not covered by this check" in detail

    def test_a_reported_clean_board_says_nothing_about_coverage(self):
        payload = _payload(
            {"DIN": "08057013", "FirstName": "A", "LastName": "B",
             "MCAUserRole": [_role(isDisqualified="N")]},
        )
        finding = _dirs(payload)
        assert finding.status is CheckStatus.PASS
        assert "not reported" not in finding.detail

    def test_a_disqualified_director_still_fails_the_check(self):
        payload = _payload(
            {"DIN": "08057013", "FirstName": "A", "LastName": "B",
             "MCAUserRole": [_role(isDisqualified="Y")]},
        )
        finding = _dirs(payload)
        assert finding.status is CheckStatus.FAIL
        assert "1 disqualified" in finding.detail

    def test_an_unreported_board_is_not_mistaken_for_a_disqualified_one(self):
        """`[d for d in directors if d["disqualified"]]` with a None in it
        is falsy and safe; the danger is the reverse test somewhere later
        treating None as present. Pinned here because the status is what
        the ledger and the report both read."""
        assert _dirs(ZEPTO).status is CheckStatus.PASS
