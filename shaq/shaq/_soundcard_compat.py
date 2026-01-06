# -*- coding: utf-8 -*-

from __future__ import annotations

import os
from typing import Any


def patch_soundcard_numpy_fromstring() -> None:
    """
    soundcard 0.4.5 uses numpy.fromstring(binary) on Windows (mediafoundation backend),
    which is removed in NumPy 2.x. Patch the implementation to use frombuffer().copy().
    """

    if os.name != "nt":
        return

    try:
        from soundcard import mediafoundation as mf  # type: ignore
    except Exception:
        return

    recorder_cls: Any
    try:
        recorder_cls = mf._Recorder  # noqa: SLF001
    except Exception:
        return

    original = getattr(recorder_cls, "_record_chunk", None)
    if original is None or getattr(original, "__shaq_patched__", False):
        return

    def _record_chunk(self):  # type: ignore[no-untyped-def]
        while self._capture_available_frames() == 0:
            if self._idle_start_time is None:
                self._idle_start_time = mf.time.perf_counter_ns()

            default_block_length, minimum_block_length = self.deviceperiod
            mf.time.sleep(minimum_block_length / 4)
            elapsed_time_ns = mf.time.perf_counter_ns() - self._idle_start_time
            if elapsed_time_ns / 1_000_000_000 > default_block_length * 4:
                num_frames = int(self.samplerate * elapsed_time_ns / 1_000_000_000)
                num_channels = len(set(self.channelmap))
                self._idle_start_time += elapsed_time_ns
                return mf.numpy.zeros([num_frames * num_channels], dtype="float32")

        self._idle_start_time = None
        data_ptr, nframes, flags = self._capture_buffer()
        if data_ptr != mf._ffi.NULL:
            buf = mf._ffi.buffer(data_ptr, nframes * 4 * len(set(self.channelmap)))
            chunk = mf.numpy.frombuffer(buf, dtype="float32").copy()
        else:
            raise RuntimeError("Could not create capture buffer")

        if flags & mf._ole32.AUDCLNT_BUFFERFLAGS_SILENT:
            chunk[:] = 0
        if self._is_first_frame:
            flags &= ~mf._ole32.AUDCLNT_BUFFERFLAGS_DATA_DISCONTINUITY
            self._is_first_frame = False
        if flags & mf._ole32.AUDCLNT_BUFFERFLAGS_DATA_DISCONTINUITY:
            mf.warnings.warn("data discontinuity in recording", mf.SoundcardRuntimeWarning)

        if nframes > 0:
            self._capture_release(nframes)
            return chunk
        return mf.numpy.zeros([0], dtype="float32")

    _record_chunk.__shaq_patched__ = True  # type: ignore[attr-defined]
    recorder_cls._record_chunk = _record_chunk

