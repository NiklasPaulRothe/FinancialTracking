"""VL models re-export for backward compatibility.

The VL and VLContributionLog models are defined in app.models.bav.
This module re-exports them so existing imports from app.models.vl continue to work.
"""

from app.models.bav import VL, VLContributionLog  # noqa: F401

__all__ = ["VL", "VLContributionLog"]
