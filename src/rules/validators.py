"""
Zoning Validators

Validates parcel attributes against zoning requirements and identifies
conformance issues and limiting factors for development.
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from .engine import ZoningRulesEngine, DevelopmentStandards

logger = logging.getLogger(__name__)


class ConformanceStatus(Enum):
    """Lot conformance status."""
    CONFORMING = "conforming"
    NONCONFORMING = "nonconforming"
    UNKNOWN = "unknown"


@dataclass
class ConformanceIssue:
    """Represents a single conformance issue."""
    
    attribute: str
    """The attribute that is non-conforming (e.g., 'lot_area', 'lot_width')"""
    
    required_value: float
    """The minimum/maximum required value"""
    
    actual_value: float
    """The actual value of the lot"""
    
    deficiency: float
    """The amount by which the lot fails to meet the requirement"""
    
    description: str
    """Human-readable description of the issue"""


@dataclass
class ValidationResult:
    """Result of validating a parcel against zoning requirements."""
    
    district_code: str
    """Zoning district code"""
    
    status: ConformanceStatus
    """Overall conformance status"""
    
    is_conforming: bool
    """True if lot meets all by-right requirements"""
    
    issues: list[ConformanceIssue] = field(default_factory=list)
    """List of conformance issues (empty if conforming)"""
    
    limiting_factors: list[str] = field(default_factory=list)
    """Attributes that limit development potential"""
    
    max_dwelling_units: int = 0
    """Maximum dwelling units allowed by-right"""
    
    notes: list[str] = field(default_factory=list)
    """Additional notes or warnings"""


class ZoningValidator:
    """
    Validates parcel attributes against zoning requirements.
    
    Checks lot area, width, and other dimensional requirements
    to determine conformance status and identify limiting factors.
    """
    
    def __init__(self, rules_engine: ZoningRulesEngine):
        """
        Initialize the validator.
        
        Args:
            rules_engine: ZoningRulesEngine instance with loaded rules
        """
        self.rules = rules_engine
    
    def validate(
        self,
        district_code: str,
        lot_area_sf: float,
        lot_width_ft: float,
        lot_depth_ft: Optional[float] = None
    ) -> ValidationResult:
        """
        Validate a lot against zoning requirements.
        
        Args:
            district_code: Zoning district code
            lot_area_sf: Lot area in square feet
            lot_width_ft: Lot width in feet
            lot_depth_ft: Optional lot depth in feet
            
        Returns:
            ValidationResult with conformance status and issues
        """
        # Get standards for district
        standards = self.rules.get_standards(district_code)
        
        if standards is None:
            return ValidationResult(
                district_code=district_code,
                status=ConformanceStatus.UNKNOWN,
                is_conforming=False,
                notes=[f"Zoning district '{district_code}' not found in rules"]
            )
        
        issues = []
        limiting_factors = []
        notes = []
        
        # Check lot area
        if lot_area_sf < standards.min_lot_area_sf:
            deficiency = standards.min_lot_area_sf - lot_area_sf
            issues.append(ConformanceIssue(
                attribute="lot_area",
                required_value=standards.min_lot_area_sf,
                actual_value=lot_area_sf,
                deficiency=deficiency,
                description=(
                    f"Lot area ({lot_area_sf:,.0f} sf) is less than "
                    f"minimum required ({standards.min_lot_area_sf:,} sf)"
                )
            ))
            limiting_factors.append("lot_area")
        
        # Check lot width
        if lot_width_ft < standards.min_lot_width_ft:
            deficiency = standards.min_lot_width_ft - lot_width_ft
            issues.append(ConformanceIssue(
                attribute="lot_width",
                required_value=standards.min_lot_width_ft,
                actual_value=lot_width_ft,
                deficiency=deficiency,
                description=(
                    f"Lot width ({lot_width_ft:.1f} ft) is less than "
                    f"minimum required ({standards.min_lot_width_ft} ft)"
                )
            ))
            limiting_factors.append("lot_width")
        
        # Calculate maximum dwelling units
        # For one-family, this is always 1 if the lot is conforming
        # For undersized lots, it may still be 1 under certain conditions
        if lot_area_sf >= standards.min_lot_area_per_unit_sf:
            max_units = int(lot_area_sf // standards.min_lot_area_per_unit_sf)
            # For by-right one-family, cap at 1
            max_units = min(max_units, 1)
        else:
            # Undersized lot - may still allow 1 unit if meets other criteria
            # per §3.2 rules for nonconforming lots
            max_units = 1 if self._qualifies_as_undersized_buildable(
                lot_area_sf, lot_width_ft, standards
            ) else 0
            if max_units == 1:
                notes.append(
                    "Undersized lot may be buildable under §3.2.5.A.2 "
                    "(nonconforming lot provisions)"
                )
        
        # Determine overall status
        is_conforming = len(issues) == 0
        status = ConformanceStatus.CONFORMING if is_conforming else ConformanceStatus.NONCONFORMING
        
        # Add notes for standards
        if standards.notes:
            notes.append(f"District note: {standards.notes}")
        
        return ValidationResult(
            district_code=district_code,
            status=status,
            is_conforming=is_conforming,
            issues=issues,
            limiting_factors=limiting_factors,
            max_dwelling_units=max_units,
            notes=notes
        )
    
    def _qualifies_as_undersized_buildable(
        self,
        lot_area_sf: float,
        lot_width_ft: float,
        standards: DevelopmentStandards
    ) -> bool:
        """
        Check if an undersized lot qualifies for development.
        
        Per §3.2.5.A.2, undersized lots may still be buildable under
        certain conditions (lots recorded before ordinance adoption, etc.).
        
        This is a simplified check - actual determination requires
        reviewing lot history and recording dates.
        
        Args:
            lot_area_sf: Lot area in square feet
            lot_width_ft: Lot width in feet
            standards: Development standards for the district
            
        Returns:
            True if lot may qualify for development
        """
        # For this simplified implementation, we assume lots that are
        # at least 70% of minimum area may qualify as buildable undersized lots
        # This is a heuristic - actual determination needs historical research
        
        min_threshold_pct = 0.70
        area_threshold = standards.min_lot_area_sf * min_threshold_pct
        width_threshold = standards.min_lot_width_ft * min_threshold_pct
        
        return lot_area_sf >= area_threshold and lot_width_ft >= width_threshold
    
    def get_coverage_limits(
        self,
        district_code: str,
        lot_area_sf: float,
        has_front_porch: bool = False,
        has_detached_garage: bool = False
    ) -> dict:
        """
        Get coverage limits for a specific lot.
        
        Args:
            district_code: Zoning district code
            lot_area_sf: Lot area in square feet
            has_front_porch: Whether building has qualifying front porch
            has_detached_garage: Whether lot has detached garage in rear
            
        Returns:
            Dictionary with coverage limits
        """
        standards = self.rules.get_standards(district_code)
        if standards is None:
            return {"error": f"District '{district_code}' not found"}
        
        # Calculate footprint limit
        max_footprint = self.rules.calculate_max_building_footprint(
            district_code, lot_area_sf, has_front_porch
        )
        
        # Calculate lot coverage limit
        max_coverage = self.rules.calculate_max_lot_coverage(
            district_code, lot_area_sf, has_front_porch, has_detached_garage
        )
        
        return {
            "max_building_footprint_sf": round(max_footprint, 0),
            "max_lot_coverage_sf": round(max_coverage, 0),
            "max_height_ft": standards.max_height_ft,
            "bonuses_applied": {
                "front_porch": has_front_porch,
                "detached_garage": has_detached_garage
            }
        }
