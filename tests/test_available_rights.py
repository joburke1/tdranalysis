"""
Tests for Available Development Rights calculation module.
"""

import pytest
from pathlib import Path

import pandas as pd




from src.analysis.current_built import CurrentBuiltResult
from src.analysis.development_potential import DevelopmentPotentialResult
from src.analysis.available_rights import (
    calculate_available_rights,
    analyze_available_rights_by_id,
    AvailableRightsResult,
    DEFAULT_ASSUMED_STORIES,
)

CONFIG_DIR = Path(__file__).parent.parent / "config"


def _make_potential(**kwargs) -> DevelopmentPotentialResult:
    """Helper to create a DevelopmentPotentialResult."""
    defaults = dict(
        parcel_id="01-234-567",
        zoning_district="R-6",
        is_residential_zoning=True,
        lot_area_sf=6600.0,
        lot_width_ft=60.0,
        lot_depth_ft=110.0,
        is_conforming=True,
        conformance_status="conforming",
        max_height_ft=35,
        max_lot_coverage_pct=40.0,
        max_lot_coverage_sf=2640.0,
        max_building_footprint_pct=30.0,
        max_building_footprint_sf=1980.0,
        max_dwelling_units=1,
        required_parking_spaces=1,
    )
    defaults.update(kwargs)
    return DevelopmentPotentialResult(**defaults)


def _make_current(**kwargs) -> CurrentBuiltResult:
    """Helper to create a CurrentBuiltResult."""
    defaults = dict(
        parcel_id="01-234-567",
        gross_floor_area_sf=2400.0,
        story_count=2.0,
        year_built=1955,
        dwelling_units=1,
        estimated_footprint_sf=1200.0,
        has_building=True,
        data_available=True,
        improvement_value=350000.0,
        land_value=500000.0,
        total_assessed_value=850000.0,
    )
    defaults.update(kwargs)
    return CurrentBuiltResult(**defaults)


class TestCalculateAvailableRights:
    """Tests for calculate_available_rights function."""

    def test_basic_calculation(self):
        """Test basic available rights = max - current."""
        potential = _make_potential(max_building_footprint_sf=1980.0)
        current = _make_current(gross_floor_area_sf=2400.0, estimated_footprint_sf=1200.0)

        result = calculate_available_rights(potential, current)

        assert result.is_analyzable is True
        assert result.max_gfa_sf == 1980.0 * DEFAULT_ASSUMED_STORIES
        assert result.current_gfa_sf == 2400.0
        assert result.available_gfa_sf == (1980.0 * DEFAULT_ASSUMED_STORIES) - 2400.0
        assert result.available_footprint_sf == 1980.0 - 1200.0
        assert result.available_dwelling_units == 0  # 1 - 1

    def test_vacant_parcel(self):
        """Test available rights for a vacant lot."""
        potential = _make_potential(max_building_footprint_sf=1980.0)
        current = _make_current(
            gross_floor_area_sf=0.0,
            story_count=0.0,
            estimated_footprint_sf=None,
            has_building=False,
            dwelling_units=0,
        )

        result = calculate_available_rights(potential, current)

        assert result.is_analyzable is True
        assert result.is_vacant is True
        assert result.is_underdeveloped is True
        assert result.is_overdeveloped is False
        assert result.available_gfa_sf == 1980.0 * DEFAULT_ASSUMED_STORIES
        assert result.available_dwelling_units == 1

    def test_overdeveloped_parcel(self):
        """Test detection of legal nonconforming (overdeveloped) use."""
        potential = _make_potential(max_building_footprint_sf=1980.0)
        # Current GFA exceeds max: 1980 * 2.5 = 4950
        current = _make_current(gross_floor_area_sf=6000.0, estimated_footprint_sf=2000.0)

        result = calculate_available_rights(potential, current)

        assert result.is_overdeveloped is True
        assert result.is_underdeveloped is False
        assert result.available_gfa_sf < 0
        assert result.gfa_utilization_pct > 100.0
        assert any("nonconforming" in n for n in result.notes)

    def test_underdeveloped_parcel(self):
        """Test detection of underdeveloped parcel (< 80% utilization)."""
        potential = _make_potential(max_building_footprint_sf=1980.0)
        # Max GFA = 1980 * 2.5 = 4950. Current = 1000 => 20.2% utilization
        current = _make_current(gross_floor_area_sf=1000.0, estimated_footprint_sf=500.0)

        result = calculate_available_rights(potential, current)

        assert result.is_underdeveloped is True
        assert result.is_overdeveloped is False
        assert result.gfa_utilization_pct < 80.0

    def test_utilization_percentage(self):
        """Test utilization percentage calculation."""
        potential = _make_potential(max_building_footprint_sf=2000.0)
        # Max GFA = 2000 * 2.5 = 5000. Current = 2500 => 50%
        current = _make_current(gross_floor_area_sf=2500.0, estimated_footprint_sf=1250.0)

        result = calculate_available_rights(potential, current)

        assert result.gfa_utilization_pct == pytest.approx(50.0)
        assert result.footprint_utilization_pct == pytest.approx(62.5)  # 1250/2000

    def test_non_residential_zoning(self):
        """Test that non-residential parcels are flagged but not analyzed."""
        potential = _make_potential(is_residential_zoning=False)
        current = _make_current()

        result = calculate_available_rights(potential, current)

        assert result.is_analyzable is False
        assert any("not in a residential" in n for n in result.notes)

    def test_no_property_data(self):
        """Test when property data is unavailable."""
        potential = _make_potential(max_building_footprint_sf=1980.0)
        current = CurrentBuiltResult(parcel_id="01-234-567", data_available=False)

        result = calculate_available_rights(potential, current)

        assert result.is_analyzable is False
        assert result.max_building_footprint_sf == 1980.0  # still populated
        assert result.max_gfa_sf == 1980.0 * DEFAULT_ASSUMED_STORIES
        assert any("cannot determine" in n for n in result.notes)

    def test_custom_assumed_stories(self):
        """Test that assumed_stories parameter affects max GFA."""
        potential = _make_potential(max_building_footprint_sf=2000.0)
        current = _make_current(gross_floor_area_sf=3000.0)

        result_2 = calculate_available_rights(potential, current, assumed_stories=2.0)
        result_3 = calculate_available_rights(potential, current, assumed_stories=3.0)

        assert result_2.max_gfa_sf == 4000.0  # 2000 * 2
        assert result_3.max_gfa_sf == 6000.0  # 2000 * 3
        assert result_2.available_gfa_sf == 1000.0
        assert result_3.available_gfa_sf == 3000.0

    def test_potential_with_errors(self):
        """Test that potential analysis errors are propagated."""
        potential = _make_potential(
            is_residential_zoning=True,
            analysis_errors=["Geometry calculation error: invalid"],
        )
        current = _make_current()

        result = calculate_available_rights(potential, current)

        assert result.is_analyzable is False
        assert len(result.analysis_errors) > 0

    def test_summary_output(self):
        """Test that summary generates without error."""
        potential = _make_potential(max_building_footprint_sf=1980.0)
        current = _make_current()

        result = calculate_available_rights(potential, current)
        summary = result.summary()

        assert isinstance(summary, str)
        assert "Available" in summary
        assert "R-6" in summary

    def test_summary_not_analyzable(self):
        """Test summary when analysis is not possible."""
        potential = _make_potential(is_residential_zoning=False)
        current = _make_current()

        result = calculate_available_rights(potential, current)
        summary = result.summary()

        assert "Unable to compute" in summary

    def test_to_dict_excludes_nested(self):
        """Test that to_dict excludes nested component results."""
        potential = _make_potential()
        current = _make_current()

        result = calculate_available_rights(potential, current)
        d = result.to_dict()

        assert "potential" not in d
        assert "current" not in d
        assert "parcel_id" in d

    def test_dwelling_units_available(self):
        """Test dwelling unit arithmetic with zero current units."""
        potential = _make_potential(max_dwelling_units=1)
        current = _make_current(dwelling_units=0)

        result = calculate_available_rights(potential, current)

        assert result.available_dwelling_units == 1

    def test_dwelling_units_none_current(self):
        """Test dwelling unit calculation when current is None."""
        potential = _make_potential(max_dwelling_units=1)
        current = _make_current(dwelling_units=None)

        result = calculate_available_rights(potential, current)

        assert result.available_dwelling_units == 1  # 1 - 0 (None treated as 0)


class TestAnalyzeAvailableRightsById:
    """Tests for analyze_available_rights_by_id function."""

    def test_full_pipeline(self):
        """Test the end-to-end by-ID lookup."""
        import geopandas as gpd
        from shapely.geometry import box

        gdf = gpd.GeoDataFrame(
            [
                {
                    "RPC": "01-234-567",
                    "zoning_district": "R-6",
                    "grossFloorAreaSquareFeetQty": 2400.0,
                    "storyHeightCnt": 2.0,
                    "propertyYearBuilt": 1955,
                    "numberOfUnitsCnt": 1,
                    "improvementValueAmt": 350000.0,
                    "landValueAmt": 500000.0,
                    "totalValueAmt": 850000.0,
                    "geometry": box(0, 0, 60, 110),
                }
            ],
            crs="EPSG:2283",
        )

        result = analyze_available_rights_by_id(
            "01-234-567", gdf, config_dir=CONFIG_DIR
        )

        assert result.parcel_id == "01-234-567"
        assert result.zoning_district == "R-6"
        assert result.is_analyzable is True
        assert result.current_gfa_sf == 2400.0
        assert result.max_gfa_sf is not None
        assert result.available_gfa_sf is not None

    def test_missing_parcel_raises(self):
        """Test that missing parcel raises ValueError."""
        import geopandas as gpd
        from shapely.geometry import box

        gdf = gpd.GeoDataFrame(
            [
                {
                    "RPC": "01-234-567",
                    "zoning_district": "R-6",
                    "geometry": box(0, 0, 60, 100),
                }
            ],
            crs="EPSG:2283",
        )

        with pytest.raises(ValueError, match="not found"):
            analyze_available_rights_by_id("99-999-999", gdf, config_dir=CONFIG_DIR)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
