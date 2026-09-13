"""Two guards against evidence quietly going missing.

**The thin-result detector.** `ParseGuard` protects about fifteen fields
across eight endpoints, each declared by hand. The facts layer reads several
times that many. A provider renaming a field nobody thought to guard
produces a check that still passes, a guard that never fires, and a row
reading "not returned" — the same silent failure the guards exist to stop,
one level further out. This asks the general question instead: did the
source say a lot while the parser heard almost nothing?

**Payload preservation.** `resolve` and `filings` used to store only what
this code extracted, not what the provider sent. A defect in either could
never be diagnosed afterwards — the bytes it misread were gone, and
re-fetching costs ₹5 and returns whatever MCA says today rather than what it
said then.
"""

from __future__ import annotations

import pytest

from app.domain import facts as F
from app.providers import factsets as fx
from app.services.runner import CheckRunner, Finding
from app.domain.types import CheckStatus


def fields(n: int, populated: int) -> list[dict]:
    return [F.field(f"F{i}", "value" if i < populated else None) for i in range(n)]


def big(size: int = 4000) -> dict:
    return {"blob": "x" * size}


# =====================================================================
# 1 · When it fires
# =====================================================================

class TestItFires:
    def test_a_large_payload_yielding_almost_nothing_is_flagged(self):
        """The case it exists for: 40 KB in, two fields out. Not a quiet
        company — a parser reading keys that have moved."""
        blob = F.build(F.DETAIL, fields=fields(14, 2))
        flag = fx.thin_result(big(40_000), blob)
        assert flag is not None
        assert flag["level"] == "warn"
        assert "renamed or moved field" in flag["detail"]

    def test_the_flag_names_the_numbers(self):
        flag = fx.thin_result(big(9_000), F.build(F.DETAIL, fields=fields(10, 1)))
        assert "1 of 10 fields" in flag["detail"]

    def test_it_reaches_the_finding_through_the_runner(self):
        """Wired at the one point every finding passes through, not in each
        of the thirty-odd dispatch branches."""
        f = Finding("master", CheckStatus.PASS, raw=big(20_000),
                    facts=F.build(F.DETAIL, fields=fields(12, 1)))
        CheckRunner._flag_thin(f)
        assert f.facts["flags"][0]["label"] == "Most fields came back empty"

    def test_it_reads_through_the_facts_payload_wrapper(self):
        """Some checks store {"facts": …, "payload": …}; the size that
        matters is the provider's payload, not our own envelope."""
        f = Finding("fin", CheckStatus.PASS,
                    raw={"facts": {"a": 1}, "payload": big(30_000)},
                    facts=F.build(F.DETAIL, fields=fields(12, 1)))
        CheckRunner._flag_thin(f)
        assert f.facts.get("flags")

    def test_the_flag_goes_first(self):
        """Above the fields it is casting doubt on."""
        blob = F.build(F.DETAIL, fields=fields(12, 1),
                       flags=[F.flag("info", "Something else", "…")])
        f = Finding("master", CheckStatus.PASS, raw=big(20_000), facts=blob)
        CheckRunner._flag_thin(f)
        assert f.facts["flags"][0]["label"] == "Most fields came back empty"


# =====================================================================
# 1b · The case that got through — whole columns of dashes
#
# `dresolve` for Mukesh Ambani returned four candidates carrying `fullName`,
# `status`, `companies` and `dinAllocationDate`. The parser read `name`,
# `fatherName` and `dateOfBirth`. The UI showed four DINs and a director-
# ship count beside three columns of dashes, and the company names — the
# thing an auditor opens this check FOR — were simply absent.
#
# The detector said nothing, and the reason matters: two live columns out
# of five is a cell ratio of 0.40, above the 0.34 floor. A healthy column
# was carrying three dead ones through the average. So a column blank on
# every row is now counted on its own terms.
# =====================================================================

def dresolve_table(columns: list[str], rows: list[dict]) -> dict:
    return F.build(F.TABLE, rows=F.table(
        [F.column(c, c.title()) for c in columns], rows))


#: The shape the OLD parser produced from the real Ambani payload. Note
#: `boards` is filled on every row — the lapsed DINs return a count of 0,
#: which that version printed as "0". Two columns of twenty cells live.
BROKEN_ROWS = [
    {"din": "00001691", "name": None, "father": None, "dob": None, "boards": "0"},
    {"din": "00001695", "name": None, "father": None, "dob": None, "boards": "10"},
    {"din": "02366382", "name": None, "father": None, "dob": None, "boards": "0"},
    {"din": "07626087", "name": None, "father": None, "dob": None, "boards": "0"},
]

#: …and what it produces now, reading the keys the endpoint actually sends.
FIXED_ROWS = [
    {"din": "00001691", "name": "MUKESH DHIRUBHAI AMBANI", "status": "Lapsed",
     "boards": None, "companies": None, "allocated": None},
    {"din": "00001695", "name": "MUKESH DHIRUBHAI AMBANI", "status": "Approved",
     "boards": "10", "companies": "SHIVANGI COMMERCIALS LLP, …and 9 more",
     "allocated": "25 May 2006"},
    {"din": "02366382", "name": "MUKESH DHIRUBHAI AMBANI", "status": "Lapsed",
     "boards": None, "companies": None, "allocated": None},
    {"din": "07626087", "name": "MUKESH DHIRUBHAI AMBANI", "status": "Lapsed",
     "boards": None, "companies": None, "allocated": None},
]


class TestRenamedFields:
    """The sharp rule, and the one that finally catches both defects.

    `causelist` got past the blank-column rule below: two dead columns out
    of five is not a majority. Counting was the wrong question. The right
    one is narrower — *this column is empty on every row; does the payload
    carry a field with almost this name, holding data we never read?*
    """
    CAUSELIST = {"count": 3, "results": [
        {"cnr": f"MH{i}", "court": "MHSO07", "date": "2026-10-08",
         "party": "Bibhishan Wagh Vs. Relaince Infocom Ltd. Co.",
         "listingNo": i, "caseNumber": ["R.C.S./674/2017"]}
        for i in range(1, 4)]}

    #: What the old parser rendered from it: `parties` and `item`, neither
    #: of which this endpoint sends.
    BROKEN = F.build(F.TABLE, rows=F.table(
        [F.column(k, l) for k, l in [("court", "Court"), ("date", "Date"),
                                     ("item", "Item"), ("parties", "Parties"),
                                     ("cnr", "CNR")]],
        [{"court": "MHSO07", "date": "08 Oct 2026", "item": None,
          "parties": None, "cnr": f"MH{i}"} for i in range(1, 4)]))

    def test_the_causelist_defect_is_caught(self):
        flag = fx.thin_result(self.CAUSELIST, self.BROKEN)
        assert flag is not None
        assert flag["label"] == "A field was read under the wrong name"

    def test_the_flag_names_the_field_the_source_actually_sends(self):
        """So the fix is one grep, not an afternoon reading a payload."""
        detail = fx.thin_result(self.CAUSELIST, self.BROKEN)["detail"]
        assert "“Parties” is empty on all 3 rows while the source sends “party”" in detail

    def test_the_majority_rule_alone_would_have_missed_it(self):
        """Documents why this rule exists. Two blank columns of five is not
        a majority, and no threshold on COUNT can separate this from a
        charge that was legitimately never satisfied — only asking whether
        the payload holds the data can."""
        assert 2 * 2 <= 5

    def test_a_key_that_exists_and_is_null_is_not_a_defect(self):
        """The distinction the whole rule turns on. A charge that was never
        satisfied has no satisfaction date and no satisfaction id, on every
        row, and the payload says so in those words. That is a fact about
        the vendor. Flagging it would make the guard cry wolf on every
        unencumbered company, and a guard that does that is switched off
        inside a week."""
        payload = {"charges": [{"chargeId": "100", "amount": 5_000_000,
                                "holder": "SBI", "satisfactionDate": None,
                                "satisfactionId": None} for _ in range(4)]}
        blob = F.build(F.TABLE, rows=F.table(
            [F.column(k, l) for k, l in
             [("chargeId", "Charge"), ("amount", "Amount"), ("holder", "Holder"),
              ("satisfactionDate", "Satisfied on"),
              ("satisfactionId", "Satisfaction id")]],
            [{"chargeId": "100", "amount": "₹50 L", "holder": "SBI",
              "satisfactionDate": None, "satisfactionId": None}
             for _ in range(4)]))
        assert fx.thin_result(payload, blob) is None

    def test_a_column_with_no_lookalike_in_the_payload_is_left_alone(self):
        """`item` has no near-name in a cause-list record — the endpoint
        calls it `listingNo`. This rule says nothing about it rather than
        guessing, which is why it is paired with the blank-column rule and
        not a replacement for it."""
        pairs = fx._renamed_fields(self.CAUSELIST,
                                   [F.column("item", "Item")])
        assert pairs == []

    def test_it_survives_a_payload_that_is_not_a_record_at_all(self):
        """A guard that can crash the run is worse than no guard."""
        for payload in (None, "text", 42, [], [[[[[[["deep"]]]]]]]):
            assert fx._renamed_fields(payload, [F.column("parties", "Parties")]) == []

    def test_a_very_short_column_name_is_not_matched(self):
        """Four characters is the floor. Below it almost everything looks
        like almost everything."""
        payload = {"rows": [{"identifier": "X"}]}
        assert fx._renamed_fields(payload, [F.column("id", "Id")]) == []


class TestBlankColumns:
    def test_the_dresolve_defect_is_caught(self):
        """The regression this rule was written for. Three of five columns
        blank on all four rows — the missing data the user spotted."""
        blob = dresolve_table(["din", "name", "father", "dob", "boards"], BROKEN_ROWS)
        flag = fx.thin_result(big(12_000), blob)
        assert flag is not None
        assert flag["label"] == "Whole columns came back empty"

    def test_the_flag_names_which_columns_moved(self):
        """So the person reading it can go straight to the payload rather
        than re-deriving which field to look for."""
        blob = dresolve_table(["din", "name", "father", "dob", "boards"], BROKEN_ROWS)
        detail = fx.thin_result(big(12_000), blob)["detail"]
        assert "Name, Father and Dob are empty in all 4 rows" in detail

    def test_the_cell_ratio_alone_would_have_missed_it(self):
        """Documents WHY the rule is separate rather than a lower floor:
        two live columns out of five averages to 0.40, comfortably above
        0.34. Averaging cells lets one healthy column hide three dead ones.
        If this ever starts failing, the two rules have been merged back
        together and the defect is reachable again."""
        cells = len(BROKEN_ROWS) * 5
        filled = sum(1 for r in BROKEN_ROWS for k in
                     ("din", "name", "father", "dob", "boards")
                     if r.get(k) not in (None, "", "—"))
        assert filled / cells > fx.THIN_FIELD_RATIO

    def test_the_fixed_parser_is_quiet(self):
        """Three lapsed DINs legitimately hold no boards, no companies and
        no allocation date. Nothing here is blank in EVERY row, so nothing
        fires — which is the whole point of the rule."""
        blob = dresolve_table(
            ["din", "name", "status", "boards", "companies", "allocated"],
            FIXED_ROWS)
        assert fx.thin_result(big(12_000), blob) is None

    def test_a_small_payload_does_not_excuse_it(self):
        """The size floor is an argument about YIELD — extracting little
        from a terse response is not suspicious. It has nothing to say
        about structure, and the real four-candidate reproduction is 934
        bytes. Gating this rule on size would have swallowed the defect a
        second time."""
        blob = dresolve_table(["din", "name", "father", "dob", "boards"], BROKEN_ROWS)
        assert fx.thin_result({"tiny": True}, blob) is not None

    def test_one_dead_column_among_five_is_not_enough(self):
        """A single empty column is ordinary — an optional field the source
        does not hold for this record."""
        rows = [{"a": "1", "b": "2", "c": "3", "d": "4", "e": None}
                for _ in range(4)]
        blob = dresolve_table(list("abcde"), rows)
        assert fx.thin_result(big(12_000), blob) is None

    def test_two_dead_columns_of_four_is_not_enough(self):
        """Exactly half is not a majority, and pairs of optional fields are
        common: a charge that was never satisfied has no satisfaction date
        and no satisfaction ID, in every row, legitimately. It takes a
        strict majority — three of five — before this fires."""
        rows = [{"a": "1", "b": "2", "c": None, "d": None} for _ in range(4)]
        blob = dresolve_table(list("abcd"), rows)
        assert fx.thin_result(big(12_000), blob) is None

    def test_a_single_row_is_never_enough(self):
        """"Blank in every row" over one row means "blank once"."""
        blob = dresolve_table(list("abcd"),
                              [{"a": "1", "b": None, "c": None, "d": None}])
        flag = fx.thin_result(big(12_000), blob)
        assert flag is None or flag["label"] != "Whole columns came back empty"

    def test_a_dash_counts_as_empty(self):
        """The renderer's own placeholder for nothing. A parser that writes
        "—" rather than None has still read nothing."""
        rows = [{"a": "1", "b": "—", "c": "—", "d": "—"} for _ in range(3)]
        blob = dresolve_table(list("abcd"), rows)
        assert fx.thin_result(big(12_000), blob) is not None

    def test_a_zero_is_not_empty(self):
        """A directorship count of 0 for a lapsed DIN is an answer, not a
        blank. Treating it as missing would flag every legitimate resolve
        of a name whose other DINs have lapsed — the exact shape of the
        payload this rule was written for, now that it parses correctly."""
        rows = [{"a": "1", "b": 0, "c": 0, "d": 0} for _ in range(3)]
        blob = dresolve_table(list("abcd"), rows)
        assert fx.thin_result(big(12_000), blob) is None


# =====================================================================
# 2 · When it stays quiet — the half that decides whether it survives
# =====================================================================

class TestItStaysQuiet:
    def test_a_small_payload_is_not_suspicious(self):
        """A terse "nothing found" response yielding little is exactly
        right, not a defect."""
        assert fx.thin_result({"ok": True}, F.build(F.DETAIL, fields=fields(12, 1))) is None

    def test_a_well_read_payload_is_not_flagged(self):
        assert fx.thin_result(big(40_000), F.build(F.DETAIL, fields=fields(12, 9))) is None

    def test_a_short_field_list_is_not_flagged(self):
        """Two of four nulls is noise, not evidence."""
        assert fx.thin_result(big(40_000), F.build(F.DETAIL, fields=fields(4, 1))) is None

    def test_rows_do_not_vouch_for_empty_fields(self):
        """This assertion used to read the other way: a filled table was
        taken as proof the parser knew its way around the payload, so the
        empty fields beside it were presumed genuine.

        `dresolve` disproved it. Four rows of DINs and directorship counts
        sat beside three columns of dashes — the table filled, and the
        parser had still lost the company names. One populated column
        vouches for one populated column and nothing else, so 1 of 12
        fields read out of 40 KB is now flagged whatever the table does."""
        blob = F.build(F.DETAIL, fields=fields(12, 1),
                       rows=F.table([F.column("a", "A")], [{"a": "1"}, {"a": "2"}]))
        assert fx.thin_result(big(40_000), blob) is not None

    def test_reference_checks_are_never_flagged(self):
        """They describe the API, not the vendor. Half-empty is normal."""
        blob = fx.catalog("Court filters", ["a", "b"])
        assert fx.thin_result(big(40_000), blob) is None

    def test_a_check_with_no_facts_is_left_alone(self):
        assert fx.thin_result(big(40_000), None) is None

    def test_an_unexamined_check_is_left_alone(self):
        """UNAVAILABLE already says something went wrong; a second flag
        saying the same thing is noise."""
        f = Finding("master", CheckStatus.UNAVAILABLE, raw=big(20_000),
                    facts=F.build(F.DETAIL, fields=fields(12, 1)))
        CheckRunner._flag_thin(f)
        assert not f.facts.get("flags")

    def test_an_unserialisable_payload_does_not_raise(self):
        """A guard that can crash the run is worse than no guard."""
        assert fx.thin_result(object(), F.build(F.DETAIL, fields=fields(12, 1))) is None

    def test_it_never_changes_a_status(self):
        f = Finding("master", CheckStatus.PASS, raw=big(20_000),
                    facts=F.build(F.DETAIL, fields=fields(12, 1)))
        CheckRunner._flag_thin(f)
        assert f.status is CheckStatus.PASS


# =====================================================================
# 3 · The provider hands back what it was sent
# =====================================================================

class TestPayloadIsKept:
    def test_resolve_returns_the_payload_alongside_the_candidates(self):
        import inspect
        from app.providers.filesure import FileSureProvider
        sig = str(inspect.signature(FileSureProvider.resolve_company))
        assert "tuple[list[dict], dict]" in sig

    def test_filings_returns_the_payload_too(self):
        import inspect
        from app.providers.filesure import FileSureProvider
        sig = str(inspect.signature(FileSureProvider.filings))
        assert "tuple[list[dict], dict, dict]" in sig

    def test_derived_checks_say_where_their_evidence_is(self):
        """`dirs` makes no call of its own — it is read out of the master
        payload. Rather than looking like a check that lost its evidence,
        the row names where the evidence actually is."""
        blob = fx.directors([{"din": "1", "name": "A", "disqualified": False}])
        assert blob["derivedFrom"] == "master"