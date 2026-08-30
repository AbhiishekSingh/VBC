"""Regression tests for the scoring engines.

The fixture assertions are a contract, not a convenience. If one fails,
the correct response is to ask whether the scoring change was intended and
what it does to vendors already on file — never to update the expected
number so the suite goes green.
"""

from __future__ import annotations

import pytest

from app.catalog.manual_fields import TEMPLATES_BY_ID
from app.catalog.scan import SCAN_PARAMETERS, BEST_ACHIEVABLE_ALL
from app.domain.scoring import score_risk, score_scan, score_surveillance
from app.domain.types import Pillar, RuleState
from app.tests import fixtures as fx


# =====================================================================
# The three seeded vendors
# =====================================================================


class TestAzahanFixture:
    """Unincorporated proprietorship. Passes on 6 of 18 — the thin audit."""

    def test_scan_totals(self):
        s = score_scan(fx.AZAHAN_SCAN)
        assert s.weighted == 0.90
        assert s.best == 1.50
        assert s.pct == 60.0
        assert s.applicable == 6
        assert s.passed is True
        assert s.verdict == "Positive for Onboarding"

    def test_sits_exactly_on_the_threshold(self):
        """60.0% is not a comfortable pass — it is the boundary itself."""
        s = score_scan(fx.AZAHAN_SCAN)
        assert s.weighted == s.tolerance_60

    def test_coverage_note_exposes_the_thinness(self):
        s = score_scan(fx.AZAHAN_SCAN)
        assert s.coverage_note == "60.0% achieved, based on 6 of 18 parameters"

    def test_risk_band(self):
        r = score_risk(fx.AZAHAN_CHECKS, fx.AZAHAN_SELECTED)
        assert r.score == 50
        assert r.band.label == "DEEP REVIEW"


class TestMeridianFixture:
    """The healthy case. 14 of 18 applicable."""

    def test_scan_totals(self):
        s = score_scan(fx.MERIDIAN_SCAN)
        assert s.weighted == 3.80
        assert s.best == 3.90
        assert s.pct == 97.4
        assert s.applicable == 14
        assert s.passed is True

    def test_risk_band(self):
        r = score_risk(fx.MERIDIAN_CHECKS, fx.MERIDIAN_SELECTED)
        assert r.score == 95
        assert r.band.label == "APPROVE"

    def test_open_charge_costs_points_despite_overall_pass(self):
        r = score_risk(fx.MERIDIAN_CHECKS, fx.MERIDIAN_SELECTED)
        charge_rule = next(l for l in r.ledger if l.id == "r7")
        assert charge_rule.applied is True
        assert charge_rule.points == -15

    def test_surveillance_passes(self):
        sv = score_surveillance(fx.MERIDIAN_SURVEILLANCE)
        assert sv.passed is True
        assert sv.verdict == "Positive"
        assert sv.scan_value == "Positive"


class TestKaveriFixture:
    """Suspended GSTIN, surfaced only by a manual entry."""

    def test_scan_totals(self):
        s = score_scan(fx.KAVERI_SCAN)
        assert s.weighted == 0.40
        assert s.best == 1.10
        assert s.pct == 36.4
        assert s.applicable == 6
        assert s.passed is False
        assert s.verdict == "Negative for Onboarding"

    def test_risk_band(self):
        r = score_risk(fx.KAVERI_CHECKS, fx.KAVERI_SELECTED)
        assert r.score == 30
        assert r.band.label == "REJECT"

    def test_manual_gst_entry_lowers_the_score(self):
        """The hand-checked suspension moves Kaveri from 40.0% to 36.4%.

        NOTE — this contradicts §6 of the project handoff, which states the
        vendor "scored 62.5% and passed" without the manual entry. That
        figure belongs to an earlier build (§18.1 says as much) and does not
        reproduce against the signed-off v2 data. On the current fixtures
        Kaveri fails in every configuration:

            C4 = "Yes" (suspended, as shipped)   0.40 / 1.10   36.4%  FAIL
            C4 removed entirely                  0.40 / 1.00   40.0%  FAIL
            C4 = "No"  (had GST been active)     0.50 / 1.10   45.5%  FAIL

        The manual-field module is still doing real work here — it records
        a disqualifying fact that no configured check can see, and it moves
        the score in the right direction. But on this vendor it deepens an
        existing failure rather than causing one, and the client should not
        be shown the 62.5% flip as evidence.
        """
        without = score_scan(fx.KAVERI_SCAN_WITHOUT_MANUAL_GST)
        assert without.pct == 40.0
        assert without.passed is False

        with_entry = score_scan(fx.KAVERI_SCAN)
        assert with_entry.pct == 36.4
        assert with_entry.passed is False

        assert with_entry.pct < without.pct

    def test_manual_entry_is_the_only_source_of_the_suspension(self):
        """No configured check can produce C4 — that is the real argument.

        The GST provider is the sole feed for all five Compliance
        parameters and it is not configured. Whatever the score does, a
        suspended GSTIN reaches this system through a human or not at all.
        """
        from app.catalog.checks import check
        from app.catalog.scan import scan_parameter

        assert scan_parameter("C4").fed_by == "gst"
        assert check("gst").is_configured is False


# =====================================================================
# SCAN arithmetic
# =====================================================================


class TestScanArithmetic:
    def test_two_yellows_make_one_green(self):
        two_yellow = score_scan({"N1": "Industry", "N2": "1 to 5"})
        one_green = score_scan({"N1": "Better than Industry", "N2": None})
        assert two_yellow.pillars[Pillar.N].positives == 1
        assert one_green.pillars[Pillar.N].positives == 1

    def test_an_odd_yellow_is_not_counted(self):
        s = score_scan({"N1": "Industry"})
        assert s.pillars[Pillar.N].Y == 1
        assert s.pillars[Pillar.N].positives == 0

    def test_three_yellows_count_as_one(self):
        s = score_scan({"N1": "Industry", "N2": "1 to 5", "N4": "State"})
        assert s.pillars[Pillar.N].positives == 1

    def test_na_parameters_leave_both_sides(self):
        """The threshold moves with coverage — that is the design."""
        full = score_scan({"S1": "Private Ltd", "S2": "> 10 Years"})
        partial = score_scan({"S1": "Private Ltd", "S2": None})
        assert full.best == 0.4
        assert partial.best == 0.2
        assert full.pct == partial.pct == 100.0

    def test_nothing_scored_is_not_a_pass(self):
        s = score_scan({p.id: None for p in SCAN_PARAMETERS})
        assert s.best == 0
        assert s.passed is False
        assert s.verdict == "Not Scored"

    def test_unrecognised_value_is_treated_as_not_applicable(self):
        s = score_scan({"S1": "Something the catalog has never heard of"})
        assert s.applicable == 0
        assert s.best == 0

    def test_best_achievable_across_all_eighteen(self):
        s = score_scan({p.id: p.options[0][0] for p in SCAN_PARAMETERS})
        assert s.best == BEST_ACHIEVABLE_ALL == 4.30
        assert s.pct == 100.0

    def test_assessment_pillar_flag_tracks_coverage(self):
        assert score_scan(fx.MERIDIAN_SCAN).assessment_evaluated is True
        assert score_scan(fx.KAVERI_SCAN).assessment_evaluated is False

    def test_pillar_weights_are_the_workbook_weights(self):
        s = score_scan({p.id: p.options[0][0] for p in SCAN_PARAMETERS})
        assert s.pillars[Pillar.S].weight == 0.2
        assert s.pillars[Pillar.C].weight == 0.1
        assert s.pillars[Pillar.A].weight == 0.6
        assert s.pillars[Pillar.N].weight == 0.1


# =====================================================================
# Surveillance
# =====================================================================


class TestSurveillance:
    def test_hard_gate_overrides_a_strong_percentage(self):
        """Twelve positives cannot rescue a site that does not exist."""
        values = {**fx.MERIDIAN_SURVEILLANCE, "V1": "No"}
        sv = score_surveillance(values)
        assert sv.gate_failed is True
        assert sv.passed is False
        assert sv.verdict == "Negative"
        assert sv.pct >= 60.0  # the percentage was fine; the gate was not

    def test_not_conducted_is_not_a_failure(self):
        sv = score_surveillance({}, done=False)
        assert sv.done is False
        assert sv.scan_value is None  # A2 stays N/A rather than Negative

    def test_threshold_is_inclusive_at_sixty(self):
        values = {"V1": "Yes", "V2": "High", "V3": "Yes", "V4": "Yes", "V5": "Weak"}
        sv = score_surveillance(values)
        assert sv.pct == 80.0
        assert sv.passed is True

    def test_below_threshold_fails(self):
        values = {"V1": "Yes", "V2": "Low", "V3": "No", "V4": "No", "V5": "Weak"}
        sv = score_surveillance(values)
        assert sv.pct == 20.0
        assert sv.passed is False


# =====================================================================
# Risk ledger
# =====================================================================


class TestRiskLedger:
    def test_baseline_with_no_checks_at_all(self):
        r = score_risk({}, [])
        assert r.score == 50

    def test_unconfigured_rules_report_why(self):
        r = score_risk(fx.MERIDIAN_CHECKS, fx.MERIDIAN_SELECTED)
        gst = next(l for l in r.ledger if l.id == "r10")
        assert gst.state is RuleState.NOT_CONFIGURED
        assert gst.explanation == "source not configured"
        assert gst.contribution == 0

    def test_deselected_check_is_distinct_from_unconfigured(self):
        r = score_risk(fx.KAVERI_CHECKS, fx.KAVERI_SELECTED)
        filings = next(l for l in r.ledger if l.id == "r2")
        assert filings.state is RuleState.NOT_SELECTED
        assert filings.explanation == "check not selected for this vendor"

    def test_four_rules_are_dead_in_phase_one(self):
        r = score_risk(fx.MERIDIAN_CHECKS, fx.MERIDIAN_SELECTED)
        assert r.dead == 4
        assert r.participating == 9

    def test_ledger_is_always_complete(self):
        """Every rule appears, whatever its state. The ledger never shrinks."""
        for checks, selected in (
            ({}, []),
            (fx.AZAHAN_CHECKS, fx.AZAHAN_SELECTED),
            (fx.MERIDIAN_CHECKS, fx.MERIDIAN_SELECTED),
        ):
            assert len(score_risk(checks, selected).ledger) == 13

    def test_score_is_clamped(self):
        assert score_risk({}, []).score == 50
        r = score_risk(fx.MERIDIAN_CHECKS, fx.MERIDIAN_SELECTED)
        assert 0 <= r.score <= 100

    def test_a_malformed_payload_does_not_crash_scoring(self):
        from app.domain.types import CheckResult, CheckStatus

        broken = {"whois": CheckResult("whois", CheckStatus.PASS, value=None)}
        r = score_risk(broken, ["whois"])
        assert next(l for l in r.ledger if l.id == "r4").applied is False


# =====================================================================
# Manual field mapping
# =====================================================================


class TestManualFieldMapping:
    def test_gst_suspended_maps_to_c4_yes(self):
        template = TEMPLATES_BY_ID["m6"]
        assert template.maps_to == "C4"
        assert template.map_when["Suspended"] == "Yes"
        assert template.map_when["Active"] == "No"

    def test_physical_office_is_deliberately_unmapped(self):
        """m1 and m2 ask different questions; only m2 writes S5."""
        assert TEMPLATES_BY_ID["m1"].maps_to is None
        assert TEMPLATES_BY_ID["m2"].maps_to == "S5"

    def test_every_mapping_targets_a_real_parameter_and_option(self):
        valid_ids = {p.id for p in SCAN_PARAMETERS}
        for template in TEMPLATES_BY_ID.values():
            if not template.maps_to:
                continue
            assert template.maps_to in valid_ids
            parameter = next(p for p in SCAN_PARAMETERS if p.id == template.maps_to)
            for target in template.map_when.values():
                assert target in parameter.option_values, (
                    f"{template.id} maps to {target!r}, not an option of "
                    f"{parameter.id}"
                )
