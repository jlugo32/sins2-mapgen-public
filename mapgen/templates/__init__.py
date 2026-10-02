"""Templates: MapParams → MapSpec. Every template compiles through MapSpec (BRIEF §3)."""
from .ring import TemplateError, build_ring

TEMPLATES = {"ring": build_ring}

__all__ = ["TEMPLATES", "TemplateError", "build_ring"]
