"""License-mode enforcement tests.

These are the *load-bearing* tests for the Apache-2 isolation story: if the
subprocess adapter can be instantiated in `mit-only` mode, the promise
falls over.
"""
from __future__ import annotations

import pytest

from idas.licenses import (
    COPYLEFT_TAGS,
    LicenseTag,
    LicenseViolation,
    assert_allowed,
    is_copyleft,
    subprocess_isolated,
)
from idas.pipeline.detector import DetectorConfig


def test_copyleft_set() -> None:
    assert LicenseTag.GPL_3 in COPYLEFT_TAGS
    assert LicenseTag.AGPL_3 in COPYLEFT_TAGS
    assert LicenseTag.APACHE_2 not in COPYLEFT_TAGS
    assert LicenseTag.MIT not in COPYLEFT_TAGS
    assert LicenseTag.BSD_3 not in COPYLEFT_TAGS


def test_is_copyleft() -> None:
    assert is_copyleft(LicenseTag.GPL_3)
    assert not is_copyleft(LicenseTag.MIT)


def test_subprocess_isolation_required() -> None:
    assert subprocess_isolated(LicenseTag.GPL_3)
    assert subprocess_isolated(LicenseTag.AGPL_3)
    assert not subprocess_isolated(LicenseTag.APACHE_2)
    assert not subprocess_isolated(LicenseTag.MIT)


def test_assert_allowed_in_standard_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    # Standard mode permits copyleft because the subprocess boundary protects us.
    from idas.config import settings

    monkeypatch.setattr(settings, "license_mode", "standard")
    assert_allowed("yolo-world", LicenseTag.GPL_3)  # no raise
    assert_allowed("owlv2", LicenseTag.APACHE_2)


def test_assert_allowed_blocks_copyleft_in_mit_only(monkeypatch: pytest.MonkeyPatch) -> None:
    from idas.config import settings

    monkeypatch.setattr(settings, "license_mode", "mit-only")
    assert_allowed("owlv2", LicenseTag.APACHE_2)  # Apache-2 is fine
    with pytest.raises(LicenseViolation):
        assert_allowed("yolo-world", LicenseTag.GPL_3)
    with pytest.raises(LicenseViolation):
        assert_allowed("ultralytics", LicenseTag.AGPL_3)


def test_yolo_world_subprocess_construction_fails_in_mit_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression test: the adapter must refuse construction under mit-only.

    If this test ever passes by *not* raising, the license switch is broken
    and GPL-3 code could be spawned despite the policy.
    """
    from idas.config import settings
    from idas.perception.yolo_world import YoloWorldSubprocessDetector

    monkeypatch.setattr(settings, "license_mode", "mit-only")
    cfg = DetectorConfig(prompt_labels=("person",))
    with pytest.raises(LicenseViolation):
        YoloWorldSubprocessDetector(cfg)


def test_runtime_factory_picks_stub_when_forced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With IDAS_FORCE_STUB=1 the factory must never instantiate YOLO-World."""
    monkeypatch.setenv("IDAS_FORCE_STUB", "1")
    from idas.runtime import build_detector

    det = build_detector(DetectorConfig(prompt_labels=("person",)))
    assert det.name == "stub"
    assert det.license_tag == LicenseTag.APACHE_2
    det.close()


def test_runtime_factory_honors_mit_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """In mit-only + no weights + no force-stub, we still must not spawn YOLO-World."""
    from idas.config import settings
    from idas.runtime import build_detector

    monkeypatch.setattr(settings, "license_mode", "mit-only")
    monkeypatch.delenv("IDAS_FORCE_STUB", raising=False)
    det = build_detector(DetectorConfig(prompt_labels=("person",)))
    # No OWLv2 weights in test env → falls back to stub. Never to YOLO-World.
    assert det.name in {"stub", "owlv2"}
    assert det.license_tag in {LicenseTag.APACHE_2, LicenseTag.MIT}
    det.close()
