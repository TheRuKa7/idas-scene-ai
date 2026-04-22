"""License-mode enforcement.

iDAS ships under Apache-2. A few state-of-the-art open-vocabulary detectors
(notably Ultralytics-packaged YOLO-World) carry AGPL / GPL-3 obligations that
would transitively infect the core if imported in-process. We keep those out
of the core Python path entirely: they are only ever invoked through a
subprocess shim. The `mit-only` license mode additionally disables the
subprocess path so a downstream integrator can ship a license-clean binary.

The guard in this module is the single enforcement point. Any code path that
wants to touch a GPL-3 module must call :func:`assert_allowed` first; the
tests assert that calling it under `mit-only` raises.
"""
from __future__ import annotations

from enum import Enum
from typing import Final

from idas.config import settings


class LicenseTag(str, Enum):
    """Canonical license labels we care about for routing decisions."""

    APACHE_2 = "Apache-2.0"
    MIT = "MIT"
    BSD_3 = "BSD-3-Clause"
    GPL_3 = "GPL-3.0"
    AGPL_3 = "AGPL-3.0"


#: Licenses that are forbidden in `mit-only` mode. We don't block BSD/MIT.
COPYLEFT_TAGS: Final[frozenset[LicenseTag]] = frozenset(
    {LicenseTag.GPL_3, LicenseTag.AGPL_3}
)


class LicenseViolation(RuntimeError):
    """Raised when code attempts to load a forbidden-license component."""


def is_copyleft(tag: LicenseTag) -> bool:
    """Whether a component's license is copyleft by our definition."""
    return tag in COPYLEFT_TAGS


def assert_allowed(component: str, tag: LicenseTag) -> None:
    """Raise :class:`LicenseViolation` if `tag` is forbidden under current mode.

    This is the ONLY sanctioned way for a detector/tracker module to announce
    that it is about to run code under `tag`. Call it before any expensive
    import or subprocess spawn.
    """
    mode = settings.license_mode
    if mode == "mit-only" and is_copyleft(tag):
        raise LicenseViolation(
            f"Component {component!r} is licensed {tag.value}, which is not "
            f"permitted in license_mode='mit-only'. Switch to "
            f"IDAS_LICENSE_MODE=standard or pick a different component."
        )
    # `standard` mode permits copyleft, but only when the caller has already
    # ensured subprocess isolation. The subprocess adapter is responsible for
    # that; the in-process path must use Apache-2/MIT/BSD components only.


def subprocess_isolated(tag: LicenseTag) -> bool:
    """Whether components under `tag` must run behind a subprocess boundary.

    Even in `standard` mode we isolate copyleft code so the core process's
    import graph never contains GPL-3 symbols. The subprocess-level isolation
    is what keeps the main distribution Apache-2 in spirit.
    """
    return is_copyleft(tag)
