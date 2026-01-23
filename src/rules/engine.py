"""
Zoning Rules Engine

Loads zoning regulations from JSON configuration files and provides
methods to look up development standards for specific districts.

The rules are based on Arlington County Zoning Ordinance Article 5
(Residential Districts) and Article 3 (Density and Dimensional Standards).
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Any

logger = logging.getLogger(__name__)


@dataclass
class DevelopmentStandards:
    """
    Container for by-right development standards for a zoning district.
    
    All values are for one-family dwelling use unless otherwise noted.
    """
    
    district_code: str
    """Zoning district code (e.g., 'R-6')"""
    
    district_name: str
    """Full name of the district"""
    
    # Density standards
    min_lot_area_sf: int
    """Minimum lot area in square feet"""
    
    min_lot_area_per_unit_sf: int
    """Minimum lot area per dwelling unit in square feet"""
    
    min_lot_width_ft: int
    """Minimum average lot width in feet"""
    
    # Height standards
    max_height_ft: int
    """Maximum building height in feet"""
    
    # Coverage standards
    max_lot_coverage_pct: float
    """Maximum lot coverage as percentage (0-100)"""
    
    max_lot_coverage_with_porch_pct: float
    """Maximum lot coverage with front porch bonus"""
    
    max_lot_coverage_with_garage_pct: float
    """Maximum lot coverage with detached garage bonus"""
    
    max_lot_coverage_with_both_pct: float
    """Maximum lot coverage with both porch and garage"""
    
    max_building_footprint_pct: float
    """Maximum main building footprint as percentage"""
    
    max_building_footprint_with_porch_pct: float
    """Maximum main building footprint with porch bonus"""
    
    max_building_footprint_sf: int
    """Maximum main building footprint in square feet (cap)"""
    
    max_building_footprint_with_porch_sf: int
    """Maximum main building footprint with porch (cap)"""
    
    # Parking
    parking_spaces_per_unit: float
    """Required parking spaces per dwelling unit"""
    
    # Metadata
    article_section: str
    """Reference to zoning ordinance section"""
    
    notes: Optional[str] = None
    """Additional notes about the district"""


class ZoningRulesEngine:
    """
    Engine for loading and querying zoning rules.
    
    Loads rules from JSON configuration files and provides lookup
    methods for development standards by district code.
    """
    
    def __init__(self, config_dir: str | Path = "config"):
        """
        Initialize the rules engine.
        
        Args:
            config_dir: Directory containing configuration JSON files
        """
        self.config_dir = Path(config_dir)
        self._districts: dict[str, dict] = {}
        self._setbacks: dict = {}
        self._metadata: dict = {}
        
        self._load_rules()
    
    def _load_rules(self) -> None:
        """Load all rules from configuration files."""
        # Load residential district rules
        districts_path = self.config_dir / "residential_districts.json"
        if districts_path.exists():
            with open(districts_path, 'r') as f:
                data = json.load(f)
                self._metadata = data.get('_metadata', {})
                self._districts = data.get('districts', {})
                logger.info(f"Loaded {len(self._districts)} residential district rules")
        else:
            logger.warning(f"Districts config not found: {districts_path}")
        
        # Load setback rules
        setbacks_path = self.config_dir / "setback_rules.json"
        if setbacks_path.exists():
            with open(setbacks_path, 'r') as f:
                data = json.load(f)
                self._setbacks = data
                logger.info("Loaded setback rules")
        else:
            logger.warning(f"Setbacks config not found: {setbacks_path}")
    
    def get_district_codes(self) -> list[str]:
        """
        Get list of all configured district codes.
        
        Returns:
            List of district codes
        """
        return list(self._districts.keys())
    
    def is_supported_district(self, district_code: str) -> bool:
        """
        Check if a district code is supported.
        
        Args:
            district_code: Zoning district code
            
        Returns:
            True if district has configured rules
        """
        normalized = self._normalize_district_code(district_code)
        return normalized in self._districts
    
    def _normalize_district_code(self, code: str) -> str:
        """
        Normalize district code to match configuration keys.
        
        Handles variations like 'R6' vs 'R-6', case differences, etc.
        
        Args:
            code: Raw district code
            
        Returns:
            Normalized district code
        """
        if not isinstance(code, str):
            return ""
        
        code = code.strip().upper()
        
        # Direct match
        if code in self._districts:
            return code
        
        # Try with/without hyphen
        if '-' in code:
            no_hyphen = code.replace('-', '')
            for key in self._districts:
                if key.replace('-', '') == no_hyphen:
                    return key
        else:
            # Try adding hyphen after R
            if code.startswith('R') and len(code) > 1:
                with_hyphen = 'R-' + code[1:]
                if with_hyphen in self._districts:
                    return with_hyphen
        
        # Special cases
        code_mappings = {
            'R1530T': 'R15-30T',
            'R27': 'R2-7',
            'R10T': 'R-10T'
        }
        if code in code_mappings:
            return code_mappings[code]
        
        return code
    
    def get_standards(self, district_code: str) -> Optional[DevelopmentStandards]:
        """
        Get development standards for a zoning district.
        
        Args:
            district_code: Zoning district code (e.g., 'R-6', 'R6')
            
        Returns:
            DevelopmentStandards object, or None if district not found
        """
        normalized = self._normalize_district_code(district_code)
        
        if normalized not in self._districts:
            logger.warning(f"District '{district_code}' not found in rules")
            return None
        
        district = self._districts[normalized]
        density = district.get('density', {})
        height = district.get('height', {})
        coverage = district.get('coverage', {})
        parking = district.get('parking', {})
        
        return DevelopmentStandards(
            district_code=normalized,
            district_name=district.get('name', ''),
            
            # Density
            min_lot_area_sf=density.get('min_lot_area_sf', 0),
            min_lot_area_per_unit_sf=density.get('min_lot_area_per_dwelling_unit_sf', 0),
            min_lot_width_ft=density.get('min_lot_width_ft', 0),
            
            # Height
            max_height_ft=height.get('max_height_ft', 35),
            
            # Coverage
            max_lot_coverage_pct=coverage.get('max_lot_coverage_pct', 0),
            max_lot_coverage_with_porch_pct=coverage.get('max_lot_coverage_with_front_porch_pct', 0),
            max_lot_coverage_with_garage_pct=coverage.get('max_lot_coverage_with_detached_garage_pct', 0),
            max_lot_coverage_with_both_pct=coverage.get('max_lot_coverage_with_both_pct', 0),
            max_building_footprint_pct=coverage.get('max_main_building_footprint_pct', 0),
            max_building_footprint_with_porch_pct=coverage.get('max_main_building_footprint_with_porch_pct', 0),
            max_building_footprint_sf=coverage.get('max_main_building_footprint_sf', 0),
            max_building_footprint_with_porch_sf=coverage.get('max_main_building_footprint_with_porch_sf', 0),
            
            # Parking
            parking_spaces_per_unit=parking.get('spaces_per_dwelling_unit', 2),
            
            # Metadata
            article_section=district.get('article_section', ''),
            notes=district.get('notes')
        )
    
    def get_setback_rules(self) -> dict:
        """
        Get setback rules.
        
        Returns:
            Dictionary of setback rules
        """
        return self._setbacks.copy()
    
    def get_metadata(self) -> dict:
        """
        Get rules metadata (source, effective date, etc.).
        
        Returns:
            Dictionary of metadata
        """
        return self._metadata.copy()
    
    def calculate_max_building_footprint(
        self,
        district_code: str,
        lot_area_sf: float,
        has_front_porch: bool = False
    ) -> float:
        """
        Calculate maximum building footprint for a specific lot.
        
        The maximum is the LESSER of:
        1. The percentage-based calculation (lot area × max footprint %)
        2. The absolute cap for the district
        
        Args:
            district_code: Zoning district code
            lot_area_sf: Lot area in square feet
            has_front_porch: Whether building includes qualifying front porch
            
        Returns:
            Maximum building footprint in square feet
        """
        standards = self.get_standards(district_code)
        if standards is None:
            return 0
        
        # Get appropriate percentages and caps
        if has_front_porch:
            pct = standards.max_building_footprint_with_porch_pct
            cap = standards.max_building_footprint_with_porch_sf
        else:
            pct = standards.max_building_footprint_pct
            cap = standards.max_building_footprint_sf
        
        # Calculate percentage-based maximum
        pct_based = lot_area_sf * (pct / 100)
        
        # Return lesser of percentage-based or cap
        return min(pct_based, cap)
    
    def calculate_max_lot_coverage(
        self,
        district_code: str,
        lot_area_sf: float,
        has_front_porch: bool = False,
        has_detached_garage: bool = False
    ) -> float:
        """
        Calculate maximum lot coverage for a specific lot.
        
        Args:
            district_code: Zoning district code
            lot_area_sf: Lot area in square feet
            has_front_porch: Whether building includes qualifying front porch
            has_detached_garage: Whether lot has detached garage in rear yard
            
        Returns:
            Maximum lot coverage in square feet
        """
        standards = self.get_standards(district_code)
        if standards is None:
            return 0
        
        # Select appropriate percentage based on bonuses
        if has_front_porch and has_detached_garage:
            pct = standards.max_lot_coverage_with_both_pct
        elif has_detached_garage:
            pct = standards.max_lot_coverage_with_garage_pct
        elif has_front_porch:
            pct = standards.max_lot_coverage_with_porch_pct
        else:
            pct = standards.max_lot_coverage_pct
        
        return lot_area_sf * (pct / 100)


def load_rules(config_dir: str | Path = "config") -> ZoningRulesEngine:
    """
    Convenience function to load zoning rules.
    
    Args:
        config_dir: Directory containing configuration files
        
    Returns:
        Initialized ZoningRulesEngine
    """
    return ZoningRulesEngine(config_dir)
