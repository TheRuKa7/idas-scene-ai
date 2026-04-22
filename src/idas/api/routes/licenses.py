"""License introspection endpoint."""
from __future__ import annotations

from fastapi import APIRouter

from idas.api.deps import make_detector, make_tracker
from idas.models.schemas import LicenseInfo
from idas.runtime import describe_runtime

router = APIRouter(tags=["licenses"])


@router.get("/licenses", response_model=LicenseInfo)
async def get_license_info() -> LicenseInfo:
    """Tell the caller what's running and under which licenses.

    Useful for compliance audits and for the mobile client to show a badge
    when the service is in mit-only mode.
    """
    detector = make_detector(["person"])  # labels don't affect license
    tracker = make_tracker()
    try:
        return describe_runtime(detector, tracker)
    finally:
        detector.close()
