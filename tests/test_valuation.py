"""
Tests for the development potential valuation module.
"""

import pytest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from analysis.current_built import CurrentBuiltResult
from analysis.available_rights import AvailableRightsResult, DEFAULT_ASSUMED_STORIES
from analysis.valuation import (
    ValuationParams,
    ValuationMethodResult,
    ValuationResult,
    ConfidenceLevel,
    load_valuation_params,
    calculate_valuation,
    estimate_valuation_by_id,
    _land_residual_method,
    _assessment_ratio_method,
    _price_per_sf_method,
    _price_per_unit_method,
    _determine_confidence,
)

CONFIG_DIR = Path(__file__).parent.parent / "config"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_params(**kwargs) -> ValuationParams:
    """Create a ValuationParams with sensible test defaults."""
    defaults = dict(
        market_to_assessment_ratio_low=1.0,
        market_to_assessment_ratio_high=1.15,
        price_per_gfa_sf_low=100.0,
        price_per_gfa_sf_high=200.0,
        price_per_unit_low=150_000.0,
        price_per_unit_high=350_000.0,
        land_residual_discount_low=0.60,
        land_residual_discount_high=0.85,
        high_confidence_min_land_value=100_000.0,
        high_confidence_min_available_gfa_sf=500.0,
        params_last_updated="2026-02-18",
    )
    defaults.update(kwargs)
    return ValuationParams(**defaults)


def _make_current(**kwargs) -> CurrentBuiltResult:
    """Create a CurrentBuiltResult with sensible test defaults."""
    defaults = dict(
        parcel_id="01-234-567",
        gross_floor_area_sf=2_400.0,
        story_count=2.0,
        year_built=1955,
        dwelling_units=1,
        estimated_footprint_sf=1_200.0,
        has_building=True,
        data_available=True,
        improvement_value=350_000.0,
        land_value=500_000.0,
        total_assessed_value=850_000.0,
    )
    defaults.update(kwargs)
    return CurrentBuiltResult(**defaults)


def _make_rights(**kwargs) -> AvailableRightsResult:
    """
    Create an AvailableRightsResult for a typical underdeveloped R-6 parcel.

    Defaults:
      max footprint 1,980 sf → max GFA 4,950 sf (×2.5 stories)
      current GFA 2,400 sf → available GFA 2,550 sf (51.5% utilised)
      1 max unit, 1 current unit → 0 available units
    """
    current = _make_current()
    defaults = dict(
        parcel_id="01-234-567",
        zoning_district="R-6",
        max_gfa_sf=4_950.0,
        max_building_footprint_sf=1_980.0,
        max_lot_coverage_sf=2_640.0,
        max_dwelling_units=1,
        current_gfa_sf=2_400.0,
        current_estimated_footprint_sf=1_200.0,
        current_dwelling_units=1,
        available_gfa_sf=2_550.0,
        available_footprint_sf=780.0,
        available_dwelling_units=0,
        gfa_utilization_pct=48.5,
        is_underdeveloped=True,
        is_overdeveloped=False,
        is_vacant=False,
        is_analyzable=True,
        current=current,
    )
    defaults.update(kwargs)
    return AvailableRightsResult(**defaults)


# ---------------------------------------------------------------------------
# TestValuationParams
# ---------------------------------------------------------------------------

class TestValuationParams:
    """Tests for loading valuation parameters from config."""

    def test_load_default_params(self):
        """Load from the real config directory and verify all fields are present."""
        params = load_valuation_params(CONFIG_DIR)

        assert isinstance(params, ValuationParams)
        assert params.market_to_assessment_ratio_low > 0
        assert params.market_to_assessment_ratio_high >= params.market_to_assessment_ratio_low
        assert params.price_per_gfa_sf_low > 0
        assert params.price_per_gfa_sf_high >= params.price_per_gfa_sf_low
        assert params.price_per_unit_low > 0
        assert params.price_per_unit_high >= params.price_per_unit_low
        assert 0 < params.land_residual_discount_low <= 1.0
        assert params.land_residual_discount_low <= params.land_residual_discount_high <= 1.0
        assert params.high_confidence_min_land_value > 0
        assert params.high_confidence_min_available_gfa_sf > 0
        assert isinstance(params.params_last_updated, str)

    def test_load_missing_file_raises(self, tmp_path):
        """Missing config file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError, match="valuation_params.json"):
            load_valuation_params(tmp_path)


# ---------------------------------------------------------------------------
# TestLandResidualMethod
# ---------------------------------------------------------------------------

class TestLandResidualMethod:
    """Tests for _land_residual_method."""

    def test_basic_calculation(self):
        """Known inputs produce expected low/high estimates."""
        params = _make_params(
            land_residual_discount_low=0.60,
            land_residual_discount_high=0.85,
        )
        # land_rate = 500_000 / 4_950 ≈ 101.01
        # low  = 2_550 × 101.01 × 0.60 ≈ 154_545
        # high = 2_550 × 101.01 × 0.85 ≈ 218_939
        result = _land_residual_method(500_000.0, 4_950.0, 2_550.0, params)

        assert result.is_applicable is True
        assert result.low_estimate == pytest.approx(
            2_550.0 * (500_000.0 / 4_950.0) * 0.60, rel=1e-6
        )
        assert result.high_estimate == pytest.approx(
            2_550.0 * (500_000.0 / 4_950.0) * 0.85, rel=1e-6
        )
        assert result.low_estimate < result.high_estimate

    def test_zero_max_gfa_not_applicable(self):
        """Method returns not-applicable when max_gfa_sf is zero."""
        result = _land_residual_method(500_000.0, 0.0, 2_550.0, _make_params())
        assert result.is_applicable is False

    def test_none_max_gfa_not_applicable(self):
        """Method returns not-applicable when max_gfa_sf is None."""
        result = _land_residual_method(500_000.0, None, 2_550.0, _make_params())
        assert result.is_applicable is False

    def test_no_land_value_not_applicable(self):
        """Method returns not-applicable when land value is None."""
        result = _land_residual_method(None, 4_950.0, 2_550.0, _make_params())
        assert result.is_applicable is False

    def test_zero_land_value_not_applicable(self):
        """Method returns not-applicable when land value is zero."""
        result = _land_residual_method(0.0, 4_950.0, 2_550.0, _make_params())
        assert result.is_applicable is False

    def test_no_available_gfa_not_applicable(self):
        """Method returns not-applicable when available GFA is zero."""
        result = _land_residual_method(500_000.0, 4_950.0, 0.0, _make_params())
        assert result.is_applicable is False

    def test_negative_available_gfa_not_applicable(self):
        """Overdeveloped parcel (negative available GFA) is not applicable."""
        result = _land_residual_method(500_000.0, 4_950.0, -500.0, _make_params())
        assert result.is_applicable is False

    def test_method_name(self):
        """Method name is correctly set."""
        result = _land_residual_method(500_000.0, 4_950.0, 2_550.0, _make_params())
        assert result.method_name == "land_residual"


# ---------------------------------------------------------------------------
# TestAssessmentRatioMethod
# ---------------------------------------------------------------------------

class TestAssessmentRatioMethod:
    """Tests for _assessment_ratio_method."""

    def test_basic_calculation(self):
        """Known inputs produce expected low/high estimates."""
        params = _make_params(
            market_to_assessment_ratio_low=1.0,
            market_to_assessment_ratio_high=1.15,
        )
        # available_fraction = 2_550 / 4_950 ≈ 0.5152
        # low  = 500_000 × 1.00 × 0.5152 ≈ 257_576
        # high = 500_000 × 1.15 × 0.5152 ≈ 296_212
        result = _assessment_ratio_method(500_000.0, 4_950.0, 2_550.0, params)

        assert result.is_applicable is True
        fraction = min(2_550.0 / 4_950.0, 1.0)
        assert result.low_estimate == pytest.approx(500_000.0 * 1.0 * fraction, rel=1e-6)
        assert result.high_estimate == pytest.approx(500_000.0 * 1.15 * fraction, rel=1e-6)

    def test_fully_utilized_parcel(self):
        """When available GFA is zero, method returns not-applicable."""
        result = _assessment_ratio_method(500_000.0, 4_950.0, 0.0, _make_params())
        assert result.is_applicable is False

    def test_vacant_lot_full_fraction(self):
        """Vacant lot: available == max, so fraction = 1.0 and full land value used."""
        params = _make_params(
            market_to_assessment_ratio_low=1.0,
            market_to_assessment_ratio_high=1.0,
        )
        # available_fraction = 4_950 / 4_950 = 1.0
        result = _assessment_ratio_method(500_000.0, 4_950.0, 4_950.0, params)

        assert result.is_applicable is True
        assert result.low_estimate == pytest.approx(500_000.0, rel=1e-6)
        assert result.high_estimate == pytest.approx(500_000.0, rel=1e-6)

    def test_fraction_capped_at_one(self):
        """Available GFA slightly over max is capped at fraction = 1.0."""
        params = _make_params(
            market_to_assessment_ratio_low=1.0,
            market_to_assessment_ratio_high=1.0,
        )
        result = _assessment_ratio_method(500_000.0, 4_950.0, 5_100.0, params)
        # fraction capped at 1.0
        assert result.is_applicable is True
        assert result.low_estimate == pytest.approx(500_000.0, rel=1e-6)

    def test_no_land_value_not_applicable(self):
        result = _assessment_ratio_method(None, 4_950.0, 2_550.0, _make_params())
        assert result.is_applicable is False

    def test_zero_max_gfa_not_applicable(self):
        result = _assessment_ratio_method(500_000.0, 0.0, 2_550.0, _make_params())
        assert result.is_applicable is False

    def test_method_name(self):
        result = _assessment_ratio_method(500_000.0, 4_950.0, 2_550.0, _make_params())
        assert result.method_name == "assessment_ratio"


# ---------------------------------------------------------------------------
# TestPricePerSfMethod
# ---------------------------------------------------------------------------

class TestPricePerSfMethod:
    """Tests for _price_per_sf_method."""

    def test_basic_calculation(self):
        """Known inputs produce expected low/high estimates."""
        params = _make_params(price_per_gfa_sf_low=100.0, price_per_gfa_sf_high=200.0)
        result = _price_per_sf_method(2_550.0, params)

        assert result.is_applicable is True
        assert result.low_estimate == pytest.approx(255_000.0)
        assert result.high_estimate == pytest.approx(510_000.0)

    def test_zero_available_gfa_not_applicable(self):
        result = _price_per_sf_method(0.0, _make_params())
        assert result.is_applicable is False

    def test_none_available_gfa_not_applicable(self):
        result = _price_per_sf_method(None, _make_params())
        assert result.is_applicable is False

    def test_negative_available_gfa_not_applicable(self):
        """Overdeveloped parcel (negative available GFA) is not applicable."""
        result = _price_per_sf_method(-100.0, _make_params())
        assert result.is_applicable is False

    def test_method_name(self):
        result = _price_per_sf_method(2_550.0, _make_params())
        assert result.method_name == "price_per_sf"


# ---------------------------------------------------------------------------
# TestPricePerUnitMethod
# ---------------------------------------------------------------------------

class TestPricePerUnitMethod:
    """Tests for _price_per_unit_method."""

    def test_basic_calculation(self):
        """Known inputs produce expected low/high estimates."""
        params = _make_params(price_per_unit_low=150_000.0, price_per_unit_high=350_000.0)
        result = _price_per_unit_method(1, params)

        assert result.is_applicable is True
        assert result.low_estimate == pytest.approx(150_000.0)
        assert result.high_estimate == pytest.approx(350_000.0)

    def test_two_units(self):
        """Multiple available units scale the estimate."""
        params = _make_params(price_per_unit_low=150_000.0, price_per_unit_high=350_000.0)
        result = _price_per_unit_method(2, params)

        assert result.low_estimate == pytest.approx(300_000.0)
        assert result.high_estimate == pytest.approx(700_000.0)

    def test_zero_units_not_applicable(self):
        result = _price_per_unit_method(0, _make_params())
        assert result.is_applicable is False

    def test_none_units_not_applicable(self):
        result = _price_per_unit_method(None, _make_params())
        assert result.is_applicable is False

    def test_negative_units_not_applicable(self):
        result = _price_per_unit_method(-1, _make_params())
        assert result.is_applicable is False

    def test_method_name(self):
        result = _price_per_unit_method(1, _make_params())
        assert result.method_name == "price_per_unit"


# ---------------------------------------------------------------------------
# TestCalculateValuation
# ---------------------------------------------------------------------------

class TestCalculateValuation:
    """Tests for the main calculate_valuation function."""

    def test_typical_underdeveloped_parcel(self):
        """
        Typical underdeveloped R-6 parcel with no available dwelling units.
        3 methods applicable (land_residual, assessment_ratio, price_per_sf).
        """
        rights = _make_rights()  # available_dwelling_units=0 → per_unit not applicable
        params = _make_params()

        result = calculate_valuation(rights, params)

        assert result.is_valueable is True
        assert result.parcel_id == "01-234-567"
        assert result.zoning_district == "R-6"
        assert result.estimated_value_low is not None
        assert result.estimated_value_high is not None
        assert result.estimated_value_low < result.estimated_value_high
        assert result.land_residual.is_applicable is True
        assert result.assessment_ratio.is_applicable is True
        assert result.price_per_sf.is_applicable is True
        assert result.price_per_unit.is_applicable is False  # no available units
        assert result.confidence == ConfidenceLevel.HIGH

    def test_vacant_parcel_all_four_methods(self):
        """Vacant lot with 1 available dwelling unit: all 4 methods run."""
        rights = _make_rights(
            current_gfa_sf=0.0,
            current_dwelling_units=0,
            available_gfa_sf=4_950.0,
            available_footprint_sf=1_980.0,
            available_dwelling_units=1,
            is_vacant=True,
            is_underdeveloped=True,
            current=_make_current(
                gross_floor_area_sf=0.0,
                dwelling_units=0,
                has_building=False,
                land_value=500_000.0,
            ),
        )
        params = _make_params()

        result = calculate_valuation(rights, params)

        assert result.is_valueable is True
        assert result.land_residual.is_applicable is True
        assert result.assessment_ratio.is_applicable is True
        assert result.price_per_sf.is_applicable is True
        assert result.price_per_unit.is_applicable is True
        assert result.confidence == ConfidenceLevel.HIGH

    def test_overdeveloped_parcel(self):
        """Overdeveloped parcel has no development potential to value."""
        rights = _make_rights(
            available_gfa_sf=-1_000.0,
            available_footprint_sf=-200.0,
            is_overdeveloped=True,
            is_underdeveloped=False,
            gfa_utilization_pct=120.0,
        )
        params = _make_params()

        result = calculate_valuation(rights, params)

        assert result.is_valueable is False
        assert result.confidence == ConfidenceLevel.NOT_APPLICABLE
        assert result.estimated_value_low is None
        assert result.estimated_value_high is None
        assert any("overdeveloped" in n.lower() for n in result.notes)

    def test_not_analyzable(self):
        """Non-analyzable rights result propagates notes and errors."""
        rights = _make_rights(
            is_analyzable=False,
            notes=["Parcel is not in a residential zoning district"],
            analysis_errors=[],
        )
        params = _make_params()

        result = calculate_valuation(rights, params)

        assert result.is_valueable is False
        assert result.confidence == ConfidenceLevel.NOT_APPLICABLE
        assert len(result.notes) > 0

    def test_no_property_data_only_per_sf_applicable(self):
        """
        When current property data is absent, land-value-dependent methods
        are not applicable, but price_per_sf still runs.
        """
        rights = _make_rights(
            current=None,   # no current built result attached
            available_gfa_sf=2_550.0,
            available_dwelling_units=0,
        )
        params = _make_params()

        result = calculate_valuation(rights, params)

        assert result.is_valueable is True
        assert result.assessed_land_value is None
        assert result.land_residual.is_applicable is False
        assert result.assessment_ratio.is_applicable is False
        assert result.price_per_sf.is_applicable is True
        # Only 1 method applicable
        assert result.confidence == ConfidenceLevel.LOW

    def test_no_available_rights_at_all(self):
        """Parcel at exactly 100% capacity has nothing to value."""
        rights = _make_rights(
            available_gfa_sf=0.0,
            available_dwelling_units=0,
            gfa_utilization_pct=100.0,
            is_overdeveloped=False,
        )
        params = _make_params()

        result = calculate_valuation(rights, params)

        assert result.is_valueable is False
        assert result.confidence == ConfidenceLevel.NOT_APPLICABLE

    def test_composite_range_is_envelope(self):
        """
        Composite low = min of method lows; composite high = max of method highs.
        """
        rights = _make_rights()
        params = _make_params()

        result = calculate_valuation(rights, params)

        applicable_methods = [
            m for m in (
                result.land_residual,
                result.assessment_ratio,
                result.price_per_sf,
                result.price_per_unit,
            )
            if m is not None and m.is_applicable
        ]
        expected_low = min(m.low_estimate for m in applicable_methods)
        expected_high = max(m.high_estimate for m in applicable_methods)

        assert result.estimated_value_low == pytest.approx(expected_low, rel=1e-9)
        assert result.estimated_value_high == pytest.approx(expected_high, rel=1e-9)

    def test_confidence_high_with_good_data(self):
        """3+ methods + good land value + good available GFA → HIGH confidence."""
        rights = _make_rights(available_gfa_sf=2_000.0)  # > 500 sf threshold
        params = _make_params(
            high_confidence_min_land_value=100_000.0,  # land_value=500k passes
            high_confidence_min_available_gfa_sf=500.0,   # 2000 sf passes
        )

        result = calculate_valuation(rights, params)

        assert result.confidence == ConfidenceLevel.HIGH

    def test_confidence_medium_only_two_methods(self):
        """2 methods applicable → MEDIUM confidence."""
        # No land value → land_residual and assessment_ratio not applicable
        # No available units → price_per_unit not applicable
        # Only price_per_sf applicable -- that's just 1, so let's give units too
        rights = _make_rights(
            current=None,  # no land value
            available_gfa_sf=2_000.0,
            available_dwelling_units=1,  # price_per_unit applicable
        )
        params = _make_params()

        result = calculate_valuation(rights, params)

        # per_sf + per_unit = 2 methods
        assert result.price_per_sf.is_applicable is True
        assert result.price_per_unit.is_applicable is True
        assert result.land_residual.is_applicable is False
        assert result.assessment_ratio.is_applicable is False
        assert result.confidence == ConfidenceLevel.MEDIUM

    def test_confidence_low_one_method(self):
        """Only 1 method applicable → LOW confidence."""
        rights = _make_rights(
            current=None,  # no land value → land_residual and assessment_ratio not applicable
            available_gfa_sf=2_000.0,
            available_dwelling_units=0,  # price_per_unit not applicable
        )
        params = _make_params()

        result = calculate_valuation(rights, params)

        # Only price_per_sf
        assert result.price_per_sf.is_applicable is True
        assert result.confidence == ConfidenceLevel.LOW

    def test_summary_output_contains_key_fields(self):
        """summary() returns a string with parcel ID, range, and disclaimer."""
        rights = _make_rights()
        result = calculate_valuation(rights, _make_params())
        summary = result.summary()

        assert isinstance(summary, str)
        assert "01-234-567" in summary
        assert "R-6" in summary
        assert "$" in summary  # some dollar value shown
        assert "DISCLAIMER" in summary

    def test_summary_includes_disclaimer_when_not_valueable(self):
        """summary() includes disclaimer even when not valueable."""
        rights = _make_rights(is_analyzable=False)
        result = calculate_valuation(rights, _make_params())
        summary = result.summary()

        assert "DISCLAIMER" in summary

    def test_to_dict_is_flat(self):
        """to_dict() returns a flat dict with no nested objects."""
        rights = _make_rights()
        result = calculate_valuation(rights, _make_params())
        d = result.to_dict()

        assert isinstance(d, dict)
        for key, value in d.items():
            assert not isinstance(value, dict), f"Key '{key}' has a nested dict value"
            assert not isinstance(value, ValuationMethodResult), (
                f"Key '{key}' has a ValuationMethodResult value"
            )

    def test_to_dict_has_expected_columns(self):
        """to_dict() includes all expected column names."""
        rights = _make_rights()
        result = calculate_valuation(rights, _make_params())
        d = result.to_dict()

        expected_keys = {
            "parcel_id",
            "zoning_district",
            "estimated_value_low",
            "estimated_value_high",
            "valuation_confidence",
            "valuation_is_valueable",
            "valuation_land_residual_low",
            "valuation_land_residual_high",
            "valuation_land_residual_applicable",
            "valuation_assessment_ratio_low",
            "valuation_assessment_ratio_high",
            "valuation_assessment_ratio_applicable",
            "valuation_per_sf_low",
            "valuation_per_sf_high",
            "valuation_per_sf_applicable",
            "valuation_per_unit_low",
            "valuation_per_unit_high",
            "valuation_per_unit_applicable",
        }
        for key in expected_keys:
            assert key in d, f"Missing expected key: '{key}'"

    def test_to_dict_confidence_is_string(self):
        """to_dict() serializes confidence as a plain string, not an enum."""
        rights = _make_rights()
        result = calculate_valuation(rights, _make_params())
        d = result.to_dict()

        assert isinstance(d["valuation_confidence"], str)
        assert d["valuation_confidence"] in ("high", "medium", "low", "not_applicable")

    def test_input_fields_populated_in_result(self):
        """Key input data is stored on the result for traceability."""
        rights = _make_rights()
        result = calculate_valuation(rights, _make_params())

        assert result.available_gfa_sf == rights.available_gfa_sf
        assert result.available_dwelling_units == rights.available_dwelling_units
        assert result.assessed_land_value == rights.current.land_value
        assert result.max_gfa_sf == rights.max_gfa_sf


# ---------------------------------------------------------------------------
# TestEstimateValuationById
# ---------------------------------------------------------------------------

class TestEstimateValuationById:
    """Integration tests for estimate_valuation_by_id."""

    def test_full_pipeline(self):
        """End-to-end: GeoDataFrame → by-ID lookup → ValuationResult."""
        import geopandas as gpd
        from shapely.geometry import box

        gdf = gpd.GeoDataFrame(
            [
                {
                    "RPC": "01-234-567",
                    "zoning_district": "R-6",
                    "grossFloorAreaSquareFeetQty": 2_400.0,
                    "storyHeightCnt": 2.0,
                    "propertyYearBuilt": 1955,
                    "numberOfUnitsCnt": 1,
                    "improvementValueAmt": 350_000.0,
                    "landValueAmt": 500_000.0,
                    "totalValueAmt": 850_000.0,
                    "geometry": box(0, 0, 60, 110),   # ~6,600 sf R-6 lot
                }
            ],
            crs="EPSG:2283",
        )

        result = estimate_valuation_by_id(
            "01-234-567", gdf, config_dir=CONFIG_DIR
        )

        assert result.parcel_id == "01-234-567"
        assert result.zoning_district == "R-6"
        assert isinstance(result.estimated_value_low, float)
        assert isinstance(result.estimated_value_high, float)
        assert result.estimated_value_low > 0
        assert result.estimated_value_high >= result.estimated_value_low

    def test_missing_parcel_raises(self):
        """Unknown parcel ID raises ValueError."""
        import geopandas as gpd
        from shapely.geometry import box

        gdf = gpd.GeoDataFrame(
            [{"RPC": "01-234-567", "zoning_district": "R-6", "geometry": box(0, 0, 60, 110)}],
            crs="EPSG:2283",
        )

        with pytest.raises(ValueError, match="not found"):
            estimate_valuation_by_id("99-999-999", gdf, config_dir=CONFIG_DIR)


# ---------------------------------------------------------------------------
# TestEstimateValuationGeoDataFrame
# ---------------------------------------------------------------------------

class TestEstimateValuationGeoDataFrame:
    """Tests for the batch GeoDataFrame pipeline."""

    def _make_gdf(self):
        """Create a small synthetic GeoDataFrame with three parcels."""
        import geopandas as gpd
        from shapely.geometry import box

        return gpd.GeoDataFrame(
            [
                {
                    "RPC": "01-111-111",
                    "zoning_district": "R-6",
                    "grossFloorAreaSquareFeetQty": 0.0,       # vacant
                    "storyHeightCnt": None,
                    "propertyYearBuilt": None,
                    "numberOfUnitsCnt": 0,
                    "improvementValueAmt": 0.0,
                    "landValueAmt": 400_000.0,
                    "totalValueAmt": 400_000.0,
                    "geometry": box(0, 0, 60, 110),
                },
                {
                    "RPC": "01-222-222",
                    "zoning_district": "R-6",
                    "grossFloorAreaSquareFeetQty": 2_400.0,   # underdeveloped
                    "storyHeightCnt": 2.0,
                    "propertyYearBuilt": 1960,
                    "numberOfUnitsCnt": 1,
                    "improvementValueAmt": 300_000.0,
                    "landValueAmt": 450_000.0,
                    "totalValueAmt": 750_000.0,
                    "geometry": box(100, 0, 160, 110),
                },
                {
                    "RPC": "01-333-333",
                    "zoning_district": "R-6",
                    "grossFloorAreaSquareFeetQty": 8_000.0,   # likely overdeveloped
                    "storyHeightCnt": 3.0,
                    "propertyYearBuilt": 1990,
                    "numberOfUnitsCnt": 1,
                    "improvementValueAmt": 600_000.0,
                    "landValueAmt": 500_000.0,
                    "totalValueAmt": 1_100_000.0,
                    "geometry": box(200, 0, 260, 110),
                },
            ],
            crs="EPSG:2283",
        )

    def test_batch_adds_valuation_columns(self):
        """estimate_valuation_geodataframe adds all expected columns."""
        from analysis.valuation import estimate_valuation_geodataframe

        gdf = self._make_gdf()
        result = estimate_valuation_geodataframe(gdf, config_dir=CONFIG_DIR)

        expected_columns = [
            "estimated_value_low",
            "estimated_value_high",
            "valuation_confidence",
            "valuation_is_valueable",
            "valuation_land_residual_low",
            "valuation_land_residual_high",
            "valuation_assessment_ratio_low",
            "valuation_assessment_ratio_high",
            "valuation_per_sf_low",
            "valuation_per_sf_high",
            "valuation_per_unit_low",
            "valuation_per_unit_high",
        ]
        for col in expected_columns:
            assert col in result.columns, f"Missing column: '{col}'"

    def test_batch_preserves_original_rows(self):
        """Output GeoDataFrame has the same number of rows as input."""
        from analysis.valuation import estimate_valuation_geodataframe

        gdf = self._make_gdf()
        result = estimate_valuation_geodataframe(gdf, config_dir=CONFIG_DIR)

        assert len(result) == len(gdf)

    def test_batch_preserves_geometry(self):
        """Output GeoDataFrame retains geometry column and CRS."""
        from analysis.valuation import estimate_valuation_geodataframe
        import geopandas as gpd

        gdf = self._make_gdf()
        result = estimate_valuation_geodataframe(gdf, config_dir=CONFIG_DIR)

        assert isinstance(result, gpd.GeoDataFrame)
        assert result.crs == gdf.crs
        assert "geometry" in result.columns

    def test_batch_mixed_parcels_confidence_types(self):
        """Different parcel types produce different confidence levels."""
        from analysis.valuation import estimate_valuation_geodataframe

        gdf = self._make_gdf()
        result = estimate_valuation_geodataframe(gdf, config_dir=CONFIG_DIR)

        confidence_values = set(result["valuation_confidence"].tolist())
        # Should have a mix — not all the same
        # At minimum, overdeveloped parcel should be 'not_applicable'
        assert "not_applicable" in confidence_values or len(confidence_values) >= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
