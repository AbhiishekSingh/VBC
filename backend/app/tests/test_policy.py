"""Tests for the coverage-floor policy (§18.1).

The central assertion is the Azahan case: the same score, under the two
policies, produces two different verdicts. That is the decision the client
still has to make, made visible and switchable.
"""

from __future__ import annotations

from app.domain.policy import (
    DEFAULT_POLICY,
    PROTOTYPE_POLICY,
    CoveragePolicy,
    Verdict,
    apply_policy,
)
from app.domain.scoring import score_scan
from app.domain.types import Pillar
from app.tests import fixtures as fx


class TestAzahanUnderBothPolicies:
    """The vendor that made this an open decision."""

    def test_prototype_policy_recommends_onboarding(self):
        """Reproduces the signed-off behaviour, which a human overrode."""
        gated = apply_policy(score_scan(fx.AZAHAN_SCAN), policy=PROTOTYPE_POLICY)
        assert gated.verdict is Verdict.POSITIVE
        assert gated.gated is False

    def test_default_policy_routes_it_to_senior_review(self):
        gated = apply_policy(score_scan(fx.AZAHAN_SCAN), policy=DEFAULT_POLICY)
        assert gated.verdict is Verdict.INSUFFICIENT_COVERAGE
        assert gated.gated is True
        assert len(gated.reasons) == 2  # no Assessment pillar, and 6 < 8

    def test_the_score_itself_is_untouched(self):
        """Gating changes what may be claimed, never the arithmetic."""
        scan = score_scan(fx.AZAHAN_SCAN)
        gated = apply_policy(scan, policy=DEFAULT_POLICY)
        assert gated.scan.weighted == 0.90
        assert gated.scan.pct == 60.0
        assert gated.raw_verdict is Verdict.POSITIVE

    def test_headline_cannot_hide_the_thin_coverage(self):
        gated = apply_policy(score_scan(fx.AZAHAN_SCAN), policy=DEFAULT_POLICY)
        assert "based on 6 of 18 parameters" in gated.headline


class TestHealthyVendorIsUnaffected:
    def test_meridian_passes_under_the_default_policy(self):
        gated = apply_policy(score_scan(fx.MERIDIAN_SCAN), policy=DEFAULT_POLICY)
        assert gated.verdict is Verdict.POSITIVE
        assert gated.gated is False
        assert gated.reasons == []

    def test_coverage_still_travels_with_a_strong_verdict(self):
        gated = apply_policy(score_scan(fx.MERIDIAN_SCAN), policy=DEFAULT_POLICY)
        assert "based on 14 of 18 parameters" in gated.headline


class TestGatingIsOneDirectional:
    def test_a_negative_verdict_is_never_gated(self):
        """Thin evidence must not manufacture a rejection."""
        gated = apply_policy(score_scan(fx.KAVERI_SCAN), policy=DEFAULT_POLICY)
        assert gated.verdict is Verdict.NEGATIVE
        assert gated.gated is False

    def test_an_unscored_vendor_stays_unscored(self):
        gated = apply_policy(score_scan({}), policy=DEFAULT_POLICY)
        assert gated.verdict is Verdict.NOT_SCORED
        assert gated.gated is False


class TestPolicyOptions:
    def test_assessment_requirement_alone_gates_azahan(self):
        policy = CoveragePolicy(
            version="test", min_assessment_parameters=2,
            min_applicable_parameters=0,
        )
        gated = apply_policy(score_scan(fx.AZAHAN_SCAN), policy=policy)
        assert gated.gated is True
        assert "Assessment parameters" in gated.reasons[0]

    def test_the_free_automated_check_alone_does_not_satisfy_the_floor(self):
        """Azahan has A3 (conflict of interest) and nothing else in A.

        A3 is computed in-house for nothing and passes by default. If a
        floor of 1 were used, the cheapest check in the catalog would
        unlock a positive verdict — which is the loophole this floor exists
        to close.
        """
        scan = score_scan(fx.AZAHAN_SCAN)
        assert scan.pillars[Pillar.A].applicable == 1

        lenient = CoveragePolicy(version="t", min_assessment_parameters=1,
                                 min_applicable_parameters=0)
        strict = CoveragePolicy(version="t", min_assessment_parameters=2,
                                min_applicable_parameters=0)
        assert apply_policy(scan, policy=lenient).gated is False
        assert apply_policy(scan, policy=strict).gated is True

    def test_parameter_floor_alone_gates_azahan(self):
        policy = CoveragePolicy(
            version="test", min_assessment_parameters=0,
            min_applicable_parameters=8,
        )
        gated = apply_policy(score_scan(fx.AZAHAN_SCAN), policy=policy)
        assert gated.gated is True
        assert "below the floor" in gated.reasons[0]

    def test_option_c_gst_evidence_requirement(self):
        policy = CoveragePolicy(
            version="test", min_assessment_parameters=0,
            min_applicable_parameters=0, require_gst_evidence=True,
        )
        scan = score_scan(fx.MERIDIAN_SCAN)
        assert apply_policy(scan, policy=policy, has_gst_evidence=True).gated is False
        assert apply_policy(scan, policy=policy, has_gst_evidence=False).gated is True

    def test_policy_version_is_recorded_on_every_verdict(self):
        """Two vendors scored under different policies are not comparable."""
        scan = score_scan(fx.MERIDIAN_SCAN)
        assert apply_policy(scan, policy=DEFAULT_POLICY).policy_version == "1.0"
        assert (
            apply_policy(scan, policy=PROTOTYPE_POLICY).policy_version
            == "0.0-prototype"
        )
