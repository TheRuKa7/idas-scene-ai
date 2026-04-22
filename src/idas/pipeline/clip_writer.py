"""Event clip writer.

When a rule fires, we want a short MP4 showing the seconds leading up to
the hit and the seconds after. This module implements the capture side
of that: collect raw RGB frames, hand them to an ffmpeg subprocess, and
return the output path.

Design:

* **Pre-event buffer.** The :class:`StreamRunner` keeps a ring of the most
  recent frames. When a hit opens we snapshot that ring; those frames are
  the clip's head.
* **Post-event collection.** The writer ingests subsequent frames until
  ``post_target`` have been accumulated (or the stream ends).
* **Encode once, at the end.** Frames stream into ``ffmpeg ... -f rawvideo
  -pix_fmt rgb24 -`` as soon as each arrives. The writer never holds the
  entire clip in memory simultaneously — the ring buffer drains frame by
  frame into ffmpeg's stdin.
* **Graceful missing-ffmpeg.** If ``ffmpeg`` is not on PATH we log once
  and return None instead of raising; the rest of the pipeline continues.
  Clip-less alerts are still valid.
"""
from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path

from idas.streams.source import Frame

log = logging.getLogger(__name__)


class ClipWriter:
    """One-shot MP4 encoder for a single rule hit."""

    def __init__(
        self,
        *,
        stream_id: str,
        hit_id: int,
        pre_frames: list[Frame],
        post_target: int,
        fps: int,
        clip_dir: Path,
        ffmpeg_bin: str | None = None,
    ) -> None:
        self.stream_id = stream_id
        self.hit_id = hit_id
        self._post_target = max(0, post_target)
        self._fps = fps
        self._clip_dir = clip_dir
        self._ffmpeg_bin = ffmpeg_bin or shutil.which("ffmpeg")
        self._proc: asyncio.subprocess.Process | None = None
        self._frames_written = 0
        self._post_frames_written = 0
        self._closed = False
        self._pre_frames = pre_frames  # stored for retry/debug inspection

    @property
    def is_complete(self) -> bool:
        return self._post_frames_written >= self._post_target

    @property
    def clip_path(self) -> Path | None:
        if self._ffmpeg_bin is None or not self._pre_frames:
            return None
        self._clip_dir.mkdir(parents=True, exist_ok=True)
        return self._clip_dir / f"{self.stream_id}_{self.hit_id}.mp4"

    # ---- subprocess lifecycle ------------------------------------------------

    async def _ensure_proc(self, width: int, height: int) -> asyncio.subprocess.Process | None:
        if self._proc is not None:
            return self._proc
        if self._ffmpeg_bin is None:
            log.info(
                "ffmpeg not on PATH; skipping clip for stream=%s hit=%d",
                self.stream_id,
                self.hit_id,
            )
            return None

        out_path = self.clip_path
        if out_path is None:
            return None

        self._proc = await asyncio.create_subprocess_exec(
            self._ffmpeg_bin,
            "-y",
            "-loglevel", "error",
            "-f", "rawvideo",
            "-pix_fmt", "rgb24",
            "-s", f"{width}x{height}",
            "-r", str(self._fps),
            "-i", "-",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-preset", "ultrafast",
            "-movflags", "+faststart",
            str(out_path),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        return self._proc

    # ---- frame ingest --------------------------------------------------------

    async def start(self) -> None:
        """Kick off encoding by writing the pre-event buffer."""
        if self._closed:
            return
        if not self._pre_frames:
            return
        first = self._pre_frames[0]
        proc = await self._ensure_proc(first.width, first.height)
        if proc is None or proc.stdin is None:
            self._closed = True
            return
        for f in self._pre_frames:
            await self._write_frame(proc, f)

    async def ingest(self, frame: Frame) -> None:
        """Feed a post-event frame. No-op once ``post_target`` is reached."""
        if self._closed or self.is_complete:
            return
        proc = await self._ensure_proc(frame.width, frame.height)
        if proc is None or proc.stdin is None:
            self._closed = True
            return
        await self._write_frame(proc, frame)
        self._post_frames_written += 1

    async def _write_frame(self, proc: asyncio.subprocess.Process, frame: Frame) -> None:
        assert proc.stdin is not None
        try:
            proc.stdin.write(frame.data)
            await proc.stdin.drain()
            self._frames_written += 1
        except (BrokenPipeError, ConnectionResetError) as exc:
            log.warning("clip writer pipe broken (%s); closing", exc)
            self._closed = True

    # ---- finalization --------------------------------------------------------

    async def finalize(self) -> str | None:
        """Close ffmpeg stdin and wait for encode to finish.

        Returns the output path on success, or None if ffmpeg was missing
        / encoding failed.
        """
        if self._closed and self._proc is None:
            return None
        self._closed = True
        if self._proc is None:
            return None
        proc = self._proc
        try:
            if proc.stdin is not None and not proc.stdin.is_closing():
                proc.stdin.close()
            await asyncio.wait_for(proc.wait(), timeout=30)
        except asyncio.TimeoutError:
            log.warning("ffmpeg encode timed out; killing")
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            return None
        if proc.returncode != 0:
            stderr = (await proc.stderr.read()).decode("utf-8", "replace") if proc.stderr else ""
            log.warning("ffmpeg exit=%s stderr=%s", proc.returncode, stderr[:400])
            return None
        path = self.clip_path
        return str(path) if path is not None else None

    async def abort(self) -> None:
        """Cancel the in-flight encode. Used on stream stop."""
        self._closed = True
        if self._proc is None:
            return
        try:
            if self._proc.returncode is None:
                self._proc.kill()
        except ProcessLookupError:
            pass
