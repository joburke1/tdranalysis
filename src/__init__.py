"""
Arlington Zoning Analyzer

A Python package for analyzing maximum residential development potential
for parcels in Arlington County, Virginia based on the Zoning Ordinance.

This package supports by-right development calculations for one-family
dwellings in R districts (R-20, R-10, R-10T, R-8, R-6, R-5, R15-30T, R2-7).
"""

__version__ = "0.1.0"
__author__ = "Arlington Zoning Analyzer Project"

from .analysis.development_potential import analyze_development_potential

__all__ = ["analyze_development_potential"]
