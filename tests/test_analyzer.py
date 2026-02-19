"""
Tests for Arlington Zoning Analyzer

Basic tests to verify the rules engine and analysis functions work correctly.
"""

import pytest
from pathlib import Path
from shapely.geometry import box, Polygon




from src.rules.engine import ZoningRulesEngine, load_rules
from src.rules.validators import ZoningValidator, ConformanceStatus
from src.geometry.lot_metrics import LotMetricsCalculator, calculate_lot_metrics
from src.analysis.development_potential import (
    analyze_development_potential,
    DevelopmentPotentialAnalyzer
)


# Path to config directory
CONFIG_DIR = Path(__file__).parent.parent / "config"


class TestZoningRulesEngine:
    """Tests for the zoning rules engine."""
    
    def test_load_rules(self):
        """Test that rules load successfully."""
        engine = ZoningRulesEngine(CONFIG_DIR)
        districts = engine.get_district_codes()
        
        assert len(districts) > 0
        assert "R-6" in districts
        assert "R-20" in districts
    
    def test_get_standards_r6(self):
        """Test getting standards for R-6 district."""
        engine = ZoningRulesEngine(CONFIG_DIR)
        standards = engine.get_standards("R-6")
        
        assert standards is not None
        assert standards.district_code == "R-6"
        assert standards.min_lot_area_sf == 6000
        assert standards.min_lot_width_ft == 60
        assert standards.max_height_ft == 35
        assert standards.max_lot_coverage_pct == 40
    
    def test_normalize_district_code(self):
        """Test district code normalization."""
        engine = ZoningRulesEngine(CONFIG_DIR)
        
        # Test various formats
        assert engine.is_supported_district("R-6")
        assert engine.is_supported_district("R6")
        assert engine.is_supported_district("r-6")
        assert engine.is_supported_district("R-20")
        assert engine.is_supported_district("R15-30T")
    
    def test_calculate_max_footprint(self):
        """Test maximum footprint calculation."""
        engine = ZoningRulesEngine(CONFIG_DIR)
        
        # R-6 with 6000 sf lot
        # Max footprint is 30% = 1800 sf, but capped at 2520 sf
        footprint = engine.calculate_max_building_footprint("R-6", 6000)
        assert footprint == 1800  # 6000 * 0.30 = 1800 (less than cap)
        
        # R-6 with 10000 sf lot
        # Max footprint would be 30% = 3000 sf, but capped at 2520 sf
        footprint = engine.calculate_max_building_footprint("R-6", 10000)
        assert footprint == 2520  # Capped


class TestZoningValidator:
    """Tests for the zoning validator."""
    
    def test_conforming_lot(self):
        """Test validation of a conforming lot."""
        engine = ZoningRulesEngine(CONFIG_DIR)
        validator = ZoningValidator(engine)
        
        # R-6 requires 6000 sf and 60 ft width
        result = validator.validate(
            district_code="R-6",
            lot_area_sf=7000,
            lot_width_ft=70
        )
        
        assert result.is_conforming
        assert result.status == ConformanceStatus.CONFORMING
        assert len(result.issues) == 0
        assert result.max_dwelling_units == 1
    
    def test_nonconforming_lot_area(self):
        """Test validation of a lot with insufficient area."""
        engine = ZoningRulesEngine(CONFIG_DIR)
        validator = ZoningValidator(engine)
        
        result = validator.validate(
            district_code="R-6",
            lot_area_sf=5000,  # Less than 6000 required
            lot_width_ft=70
        )
        
        assert not result.is_conforming
        assert result.status == ConformanceStatus.NONCONFORMING
        assert "lot_area" in result.limiting_factors
    
    def test_nonconforming_lot_width(self):
        """Test validation of a lot with insufficient width."""
        engine = ZoningRulesEngine(CONFIG_DIR)
        validator = ZoningValidator(engine)
        
        result = validator.validate(
            district_code="R-6",
            lot_area_sf=7000,
            lot_width_ft=50  # Less than 60 required
        )
        
        assert not result.is_conforming
        assert "lot_width" in result.limiting_factors


class TestLotMetricsCalculator:
    """Tests for lot metrics calculator."""
    
    def test_rectangular_lot(self):
        """Test metrics calculation for a simple rectangle."""
        calculator = LotMetricsCalculator(crs_units="feet")
        
        # 60 ft x 100 ft rectangle
        geometry = box(0, 0, 60, 100)
        metrics = calculator.calculate(geometry)
        
        assert metrics.area_sf == 6000
        assert metrics.width_ft == 60
        assert metrics.depth_ft == 100
        assert not metrics.is_irregular
    
    def test_square_lot(self):
        """Test metrics calculation for a square."""
        calculator = LotMetricsCalculator(crs_units="feet")
        
        # 80 ft x 80 ft square
        geometry = box(0, 0, 80, 80)
        metrics = calculator.calculate(geometry)
        
        assert metrics.area_sf == 6400
        assert metrics.width_ft == 80
        assert metrics.depth_ft == 80


class TestDevelopmentPotentialAnalyzer:
    """Tests for the main analyzer."""
    
    def test_analyze_conforming_parcel(self):
        """Test analysis of a conforming parcel."""
        # Create a 60 x 110 ft parcel (6600 sf) - conforming for R-6
        geometry = box(0, 0, 60, 110)
        
        result = analyze_development_potential(
            geometry=geometry,
            zoning_district="R-6",
            parcel_id="test-001",
            config_dir=CONFIG_DIR
        )
        
        assert result.parcel_id == "test-001"
        assert result.zoning_district == "R-6"
        assert result.is_residential_zoning
        assert result.is_conforming
        assert result.lot_area_sf == 6600
        assert result.max_height_ft == 35
        assert result.max_dwelling_units == 1
        assert result.max_building_footprint_sf > 0
    
    def test_analyze_nonconforming_parcel(self):
        """Test analysis of a nonconforming parcel."""
        # Create a 40 x 100 ft parcel (4000 sf) - too small for R-6
        geometry = box(0, 0, 40, 100)
        
        result = analyze_development_potential(
            geometry=geometry,
            zoning_district="R-6",
            parcel_id="test-002",
            config_dir=CONFIG_DIR
        )
        
        assert not result.is_conforming
        assert "lot_area" in result.limiting_factors
        assert "lot_width" in result.limiting_factors
    
    def test_analyze_unsupported_district(self):
        """Test analysis with unsupported zoning district."""
        geometry = box(0, 0, 60, 100)
        
        result = analyze_development_potential(
            geometry=geometry,
            zoning_district="C-2",  # Commercial, not supported
            parcel_id="test-003",
            config_dir=CONFIG_DIR
        )
        
        assert not result.is_residential_zoning
        assert len(result.notes) > 0
    
    def test_result_summary(self):
        """Test that result summary generates without error."""
        geometry = box(0, 0, 60, 100)
        
        result = analyze_development_potential(
            geometry=geometry,
            zoning_district="R-6",
            config_dir=CONFIG_DIR
        )
        
        summary = result.summary()
        assert isinstance(summary, str)
        assert "R-6" in summary
        assert "Conformance" in summary


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
