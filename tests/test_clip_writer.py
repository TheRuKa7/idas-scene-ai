"""ClipWriter: graceful degradation when ffmpeg is missing."""
from __future__ import annotations

from pathlib import Path

import pytest

from idas.pipeline.clip_writer import ClipWriter
from idas.streams.source import Frame


def _frame(i: int = 0, w: int = 16, h: int = 16) -> Frame:
    return Frame(data=b"\x00" * (w * h * 3), width=w, height=h, index=i)


@pytest.mark.asyncio
async def test_missing_ffmpeg_returns_none_path(tmp_path: Path) -> None:
    """If ffmpeg isn't on PATH the writer must no-op cleanly, not raise."""
    w = ClipWriter(
        stream_id="s1",
        hit_id=42,
        pre_frames=[_frame(0)],
        post_target=3,
        fps=5,
        clip_dir=tmp_path,
        ffmpeg_bin="/definitely/not/real/ffmpeg-does-not-exist",
    )
    # Force the "missing binary" code path by clearing the path manually.
    w._ffmpeg_bin = None  # type: ignore[attr-defined]

    await w.start()  # must not raise
    for i in range(1, 4):
        await w.ingest(_frame(i))
    assert await w.finalize() is None


@pytest.mark.asyncio
async def test_clip_path_contains_stream_and_hit_id(tmp_path: Path) -> None:
    w = ClipWriter(
        stream_id="alpha",
        hit_id=99,
        pre_frames=[_frame(0)],
        post_target=1,
        fps=5,
        clip_dir=tmp_path,
        ffmpeg_bin="/fake/ffmpeg",
    )
    path = w.clip_path
    assert path is not None
    assert path.name == "alpha_99.mp4"
    assert path.parent == tmp_path


@pytest.mark.asyncio
async def test_no_ffmpeg_ingest_is_noop(tmp_path: Path) -> None:
    """Without ffmpeg the writer closes on start() and ingest becomes a no-op.

    The important guarantee is that the *pipeline* keeps running — extra
    ingest calls must never raise.
    """
    w = ClipWriter(
        stream_id="s1",
        hit_id=1,
        pre_frames=[_frame(0)],
        post_target=2,
        fps=5,
        clip_dir=tmp_path,
        ffmpeg_bin=None,
    )
    await w.start()
    await w.ingest(_frame(1))
    await w.ingest(_frame(2))
    await w.ingest(_frame(3))  # beyond post_target — must not raise
    assert await w.finalize() is None


@pytest.mark.asyncio
async def test_abort_is_idempotent(tmp_path: Path) -> None:
    w = ClipWriter(
        stream_id="s1",
        hit_id=1,
        pre_frames=[_frame(0)],
        post_target=5,
        fps=5,
        clip_dir=tmp_path,
        ffmpeg_bin=None,
    )
    await w.abort()
    await w.abort()  # no double-free, no raise
