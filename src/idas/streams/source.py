"""Frame sources — produce raw RGB frames for the pipeline.

Two implementations:

* :class:`FFmpegFrameSource` — shells out to the ``ffmpeg`` CLI and reads
  `rgb24` bytes off stdout. Works for RTSP, HTTP-MJPEG, and local files
  alike; no Python binding required.
* :class:`StaticFrameSource` — returns a single pre-loaded frame forever.
  Used by tests and by the /detect one-shot endpoint.

Both expose the same async iterator interface so the pipeline runner
doesn't care where frames come from.
"""
from __future__ import annotations

import asyncio
import shutil
import subprocess
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class Frame:
    """One decoded frame in raw RGB24."""

    data: bytes
    width: int
    height: int
    index: int  # 0-based frame index within the source's stream


@runtime_checkable
class FrameSource(Protocol):
    """Async iterable frame source."""

    def __aiter__(self) -> AsyncIterator[Frame]: ...
    async def close(self) -> None: ...


class StaticFrameSource:
    """Emits a single frame forever (with monotonic index)."""

    def __init__(self, frame: Frame, *, limit: int | None = None) -> None:
        self._frame = frame
        self._limit = limit
        self._i = 0

    def __aiter__(self) -> AsyncIterator[Frame]:
        return self

    async def __anext__(self) -> Frame:
        if self._limit is not None and self._i >= self._limit:
            raise StopAsyncIteration
        f = Frame(self._frame.data, self._frame.width, self._frame.height, self._i)
        self._i += 1
        return f

    async def close(self) -> None:
        return None


class FFmpegFrameSource:
    """Pull frames from a URL/path via the ffmpeg CLI.

    Spawns::

        ffmpeg -i <url> -vf scale=<w>:<h>,fps=<fps> -f rawvideo -pix_fmt rgb24 -

    and reads exactly `w*h*3` bytes per frame off stdout. When ffmpeg exits
    we terminate iteration with StopAsyncIteration.
    """

    def __init__(
        self,
        url: str,
        *,
        width: int = 640,
        height: int = 360,
        fps: int = 5,
        ffmpeg_bin: str | None = None,
    ) -> None:
        self.url = url
        self.width = width
        self.height = height
        self.fps = fps
        self._bin = ffmpeg_bin or shutil.which("ffmpeg") or "ffmpeg"
        self._proc: asyncio.subprocess.Process | None = None
        self._i = 0

    async def _ensure_proc(self) -> asyncio.subprocess.Process:
        if self._proc is not None:
            return self._proc
        args = [
            self._bin,
            "-nostdin",
            "-loglevel", "warning",
            "-rtsp_transport", "tcp",
            "-i", self.url,
            "-vf", f"scale={self.width}:{self.height},fps={self.fps}",
            "-f", "rawvideo",
            "-pix_fmt", "rgb24",
            "-",
        ]
        self._proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
        )
        return self._proc

    def __aiter__(self) -> AsyncIterator[Frame]:
        return self

    async def __anext__(self) -> Frame:
        proc = await self._ensure_proc()
        assert proc.stdout is not None
        n = self.width * self.height * 3
        buf = await proc.stdout.readexactly(n) if False else await _read_exact(proc.stdout, n)
        if buf is None:
            await self.close()
            raise StopAsyncIteration
        frame = Frame(buf, self.width, self.height, self._i)
        self._i += 1
        return frame

    async def close(self) -> None:
        if self._proc is None:
            return
        proc = self._proc
        self._proc = None
        try:
            if proc.returncode is None:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=3)
                except asyncio.TimeoutError:
                    proc.kill()
        except ProcessLookupError:
            pass


async def _read_exact(stream: asyncio.StreamReader, n: int) -> bytes | None:
    """Read exactly n bytes or return None on EOF.

    `readexactly` raises :class:`IncompleteReadError` on early EOF, which
    is noisier than we want — we just want "stream ended, stop iterating".
    """
    buf = bytearray()
    while len(buf) < n:
        chunk = await stream.read(n - len(buf))
        if not chunk:
            return None if not buf else bytes(buf)
        buf.extend(chunk)
    return bytes(buf)
