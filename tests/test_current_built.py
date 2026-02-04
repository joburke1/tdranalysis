"""
Tests for Current Built Area Analysis module.
"""

import pytest
from pathlib import Path

import pandas as pd

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from analysis.current_built import (
    analyze_current_built,
    analyze_current_built_by_id,
    CurrentBuiltResult,
    _get_value,
    _get_numeric,
    _get_bool,
)


def _make_row(**kwargs) -> pd.Series:
    """Helper to create a parcel row Series with property data."""
    defaults = {
        "RPC": "01-234-567",
        "grossFloorAreaSquareFeetQty": 2400.0,
        "storyHeightCnt": 2.0,
        "propertyYearBuilt": 1955,
        "numberOfUnitsCnt": 1,
        "propertyClassTypeCode": "R",
        "propertyClassTypeDsc": "Single Family",
        "commercialInd": False,
        "mixedUseInd": False,
        "improvementValueAmt": 350000.0,
        "landValueAmt": 500000.0,
        "totalValueAmt": 850000.0,
    }
    defaults.update(kwargs)
    return pd.Series(defaults)


class TestAnalyzeCurrentBuilt:
    """Tests for analyze_current_built function."""

    def test_basic_parcel(self):
        """Test analysis of a parcel with complete property data."""
        row = _make_row()
        result = analyze_current_built(row)

        assert result.parcel_id == "01-234-567"
        assert result.data_available is True
        assert result.has_building is True
        assert result.gross_floor_area_sf == 2400.0
        assert result.story_count == 2.0
        assert result.year_built == 1955
        assert result.dwelling_units == 1
        assert result.estimated_footprint_sf == 1200.0  # 2400 / 2
        assert result.is_commercial is False
        assert result.is_mixed_use is False

    def test_vacant_parcel(self):
        """Test analysis of a vacant parcel (GFA = 0)."""
        row = _make_row(
            grossFloorAreaSquareFeetQty=0.0,
            storyHeightCnt=0.0,
            propertyYearBuilt=None,
            numberOfUnitsCnt=0,
            improvementValueAmt=0.0,
        )
        result = analyze_current_built(row)

        assert result.data_available is True
        assert result.has_building is False
        assert result.gross_floor_area_sf == 0.0
        assert result.estimated_footprint_sf is None  # GFA is 0

    def test_missing_property_data(self):
        """Test when no property data was joined."""
        row = pd.Series({"RPC": "99-999-999"})
        result = analyze_current_built(row)

        assert result.data_available is False
        assert result.has_building is False
        assert result.gross_floor_area_sf is None
        assert len(result.notes) > 0

    def test_missing_stories_assumes_single(self):
        """Test fallback when story count is missing."""
        row = _make_row(storyHeightCnt=None)
        result = analyze_current_built(row)

        assert result.gross_floor_area_sf == 2400.0
        assert result.story_count is None
        assert result.estimated_footprint_sf == 2400.0  # assumes 1 story
        assert any("single story" in n for n in result.notes)

    def test_zero_gfa_with_improvement_value_warns(self):
        """Test warning when GFA is 0 but improvement value exists."""
        row = _make_row(
            grossFloorAreaSquareFeetQty=0.0,
            storyHeightCnt=0.0,
            improvementValueAmt=200000.0,
        )
        result = analyze_current_built(row)

        assert result.has_building is False
        assert any("incomplete" in n for n in result.notes)

    def test_assessment_values(self):
        """Test that assessment values are extracted."""
        row = _make_row()
        result = analyze_current_built(row)

        assert result.improvement_value == 350000.0
        assert result.land_value == 500000.0
        assert result.total_assessed_value == 850000.0

    def test_nan_values_treated_as_none(self):
        """Test that NaN values in property data are treated as None."""
        row = _make_row(
            grossFloorAreaSquareFeetQty=float("nan"),
            storyHeightCnt=float("nan"),
            propertyYearBuilt=float("nan"),
        )
        result = analyze_current_built(row)

        assert result.data_available is False  # all key fields are NaN

    def test_summary_output(self):
        """Test that summary generates without error."""
        row = _make_row()
        result = analyze_current_built(row)
        summary = result.summary()

        assert isinstance(summary, str)
        assert "2,400" in summary
        assert "1955" in summary

    def test_summary_no_data(self):
        """Test summary when no property data available."""
        row = pd.Series({"RPC": "99-999-999"})
        result = analyze_current_built(row)
        summary = result.summary()

        assert "No property data" in summary

    def test_to_dict(self):
        """Test dictionary conversion."""
        row = _make_row()
        result = analyze_current_built(row)
        d = result.to_dict()

        assert isinstance(d, dict)
        assert d["parcel_id"] == "01-234-567"
        assert d["gross_floor_area_sf"] == 2400.0


class TestAnalyzeCurrentBuiltById:
    """Tests for analyze_current_built_by_id function."""

    def test_found_parcel(self):
        """Test lookup of existing parcel."""
        import geopandas as gpd
        from shapely.geometry import box

        gdf = gpd.GeoDataFrame(
            [
                {
                    "RPC": "01-234-567",
                    "grossFloorAreaSquareFeetQty": 2400.0,
                    "storyHeightCnt": 2.0,
                    "propertyYearBuilt": 1955,
                    "numberOfUnitsCnt": 1,
                    "geometry": box(0, 0, 60, 100),
                }
            ],
            crs="EPSG:2283",
        )

        result = analyze_current_built_by_id("01-234-567", gdf)
        assert result.parcel_id == "01-234-567"
        assert result.gross_floor_area_sf == 2400.0

    def test_missing_parcel_raises(self):
        """Test that missing parcel raises ValueError."""
        import geopandas as gpd
        from shapely.geometry import box

        gdf = gpd.GeoDataFrame(
            [{"RPC": "01-234-567", "geometry": box(0, 0, 60, 100)}],
            crs="EPSG:2283",
        )

        with pytest.raises(ValueError, match="not found"):
            analyze_current_built_by_id("99-999-999", gdf)


class TestHelpers:
    """Tests for helper extraction functions."""

    def test_get_value_present(self):
        row = pd.Series({"col": "hello"})
        assert _get_value(row, "col") == "hello"

    def test_get_value_missing(self):
        row = pd.Series({"other": "hello"})
        assert _get_value(row, "col") is None

    def test_get_value_nan(self):
        row = pd.Series({"col": float("nan")})
        assert _get_value(row, "col") is None

    def test_get_numeric_valid(self):
        row = pd.Series({"col": 42.5})
        assert _get_numeric(row, "col") == 42.5

    def test_get_numeric_string(self):
        row = pd.Series({"col": "123"})
        assert _get_numeric(row, "col") == 123.0

    def test_get_numeric_invalid(self):
        row = pd.Series({"col": "not a number"})
        assert _get_numeric(row, "col") is None

    def test_get_bool_true(self):
        row = pd.Series({"col": True})
        assert _get_bool(row, "col") is True

    def test_get_bool_string_yes(self):
        row = pd.Series({"col": "Yes"})
        assert _get_bool(row, "col") is True

    def test_get_bool_missing(self):
        row = pd.Series({"other": True})
        assert _get_bool(row, "col") is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
