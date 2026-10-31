"""Wywołania Windows WASAPI do izolowanego przechwytywania drzewa procesów.

Układ interfejsów odpowiada nagłówkom mmdeviceapi.h, audioclient.h oraz
audioclientactivationparams.h. Moduł jest ładowany dopiero przy użyciu Windows.
"""

from __future__ import annotations

import ctypes as ct
import threading
import time
import uuid
import wave
from io import BytesIO
from typing import Any

from ._process_audio import ProcessAudioError, ProcessExitedError, ProcessInfo

_HRESULT = ct.c_int32
_DWORD = ct.c_uint32
_WORD = ct.c_uint16
_VOID = ct.c_void_p
_STDCALL = getattr(ct, "WINFUNCTYPE", ct.CFUNCTYPE)
_SYNCHRONIZE = 0x00100000
_QUERY_LIMITED = 0x1000
_active_callbacks: list[_Activation] = []
_callbacks_lock = threading.Lock()


class _GUID(ct.Structure):
    _fields_ = [("data1", _DWORD), ("data2", _WORD), ("data3", _WORD), ("data4", ct.c_ubyte * 8)]


def _guid(value: str) -> _GUID:
    return _GUID.from_buffer_copy(uuid.UUID(value).bytes_le)


_IID_AUDIO_CLIENT = _guid("1CB9AD4C-DBFA-4C32-B178-C2F568A703B2")
_IID_CAPTURE_CLIENT = _guid("C8ADBD64-E71E-48A0-A4DE-185C395CD317")
_CALLBACK_IIDS = {
    uuid.UUID(value).bytes_le
    for value in (
        "00000000-0000-0000-C000-000000000046",
        "94EA2B94-E9CC-49E0-C0FF-EE64CA8F5B90",
        "41D949AB-9862-444A-80F6-C261334DA5EB",
    )
}


class _ProcessEntry(ct.Structure):
    _fields_ = [
        ("size", _DWORD),
        ("usage", _DWORD),
        ("pid", _DWORD),
        ("heap", ct.c_size_t),
        ("module", _DWORD),
        ("threads", _DWORD),
        ("parent_pid", _DWORD),
        ("priority", ct.c_int32),
        ("flags", _DWORD),
        ("filename", ct.c_wchar * 260),
    ]


class _ActivationParams(ct.Structure):
    _fields_ = [("activation_type", ct.c_int32), ("pid", _DWORD), ("mode", ct.c_int32)]


class _Blob(ct.Structure):
    _fields_ = [("size", _DWORD), ("data", _VOID)]


class _PropVariant(ct.Structure):
    _fields_ = [("vt", _WORD), ("reserved", _WORD * 3), ("blob", _Blob)]


class _WaveFormat(ct.Structure):
    _pack_ = 1
    _fields_ = [
        ("tag", _WORD),
        ("channels", _WORD),
        ("rate", _DWORD),
        ("bytes_per_second", _DWORD),
        ("block_align", _WORD),
        ("bits", _WORD),
        ("extra_size", _WORD),
    ]


def _function(library: Any, name: str, result: Any, *arguments: Any) -> Any:
    function = getattr(library, name)
    function.restype = result
    function.argtypes = arguments
    return function


def _kernel() -> Any:
    kernel = ct.WinDLL("kernel32", use_last_error=True)
    _function(kernel, "CloseHandle", ct.c_int32, _VOID)
    _function(kernel, "OpenProcess", _VOID, _DWORD, ct.c_int32, _DWORD)
    _function(kernel, "WaitForSingleObject", _DWORD, _VOID, _DWORD)
    _function(kernel, "CreateEventW", _VOID, _VOID, ct.c_int32, ct.c_int32, ct.c_wchar_p)
    _function(
        kernel,
        "QueryFullProcessImageNameW",
        ct.c_int32,
        _VOID,
        _DWORD,
        ct.c_wchar_p,
        ct.POINTER(_DWORD),
    )
    _function(kernel, "GetProcessTimes", ct.c_int32, _VOID, *([ct.POINTER(ct.c_uint64)] * 4))
    return kernel


def _process_details(kernel: Any, handle: int) -> tuple[str, int]:
    path = ct.create_unicode_buffer(32768)
    size = _DWORD(len(path))
    if not kernel.QueryFullProcessImageNameW(handle, 0, path, ct.byref(size)):
        raise ct.WinError(ct.get_last_error())
    times = [ct.c_uint64() for _ in range(4)]
    if not kernel.GetProcessTimes(handle, *(ct.byref(value) for value in times)):
        raise ct.WinError(ct.get_last_error())
    return path.value, times[0].value


def _ensure_running(kernel: Any, handle: int) -> None:
    result = kernel.WaitForSingleObject(handle, 0)
    if result == 0:
        raise ProcessExitedError("Odtwarzacz został zamknięty. Czekam na ponowne uruchomienie.")
    if result == 0xFFFFFFFF:
        raise ct.WinError(ct.get_last_error())


def enumerate_processes() -> list[ProcessInfo]:
    """Odczytuje procesy i ich tożsamość, pomijając niedostępne procesy systemowe."""
    kernel = _kernel()
    snapshot_fn = _function(kernel, "CreateToolhelp32Snapshot", _VOID, _DWORD, _DWORD)
    first = _function(kernel, "Process32FirstW", ct.c_int32, _VOID, ct.POINTER(_ProcessEntry))
    next_process = _function(kernel, "Process32NextW", ct.c_int32, _VOID, ct.POINTER(_ProcessEntry))
    snapshot = snapshot_fn(2, 0)
    if snapshot == _VOID(-1).value:
        raise ProcessAudioError("Nie można odczytać listy uruchomionych programów.")
    processes: list[ProcessInfo] = []
    try:
        entry = _ProcessEntry()
        entry.size = ct.sizeof(entry)
        available = first(snapshot, ct.byref(entry))
        while available:
            handle = kernel.OpenProcess(_QUERY_LIMITED, 0, entry.pid)
            if handle:
                try:
                    path, created = _process_details(kernel, handle)
                    if path.lower().endswith(".exe"):
                        processes.append(ProcessInfo(entry.pid, entry.parent_pid, path, created))
                except OSError:
                    pass
                finally:
                    kernel.CloseHandle(handle)
            available = next_process(snapshot, ct.byref(entry))
    finally:
        kernel.CloseHandle(snapshot)
    return processes


def _call(pointer: _VOID, index: int, result: Any, argtypes: tuple[Any, ...], *args: Any) -> Any:
    if not pointer:
        raise ProcessAudioError("Windows nie udostępnił interfejsu dźwięku.")
    table = ct.cast(pointer, ct.POINTER(ct.POINTER(_VOID))).contents
    method = _STDCALL(result, _VOID, *argtypes)(table[index])
    return method(pointer, *args)


def _check(result: int, operation: str) -> None:
    if result < 0:
        raise ProcessAudioError(f"{operation}: błąd Windows 0x{result & 0xFFFFFFFF:08X}.")


def _release(pointer: _VOID) -> None:
    if pointer:
        _call(pointer, 2, _DWORD, ())
        pointer.value = None


class _Activation:
    """Przechowuje wywołanie zwrotne COM do chwili zwolnienia go przez Windows."""

    def __init__(self, pid: int) -> None:
        self.done = threading.Event()
        self.lock = threading.Lock()
        self.references = 1
        self.abandoned = False
        self.client = _VOID()
        self.error: str | None = None
        self.params = _ActivationParams(1, pid, 0)
        self.variant = _PropVariant()
        self.variant.vt = 65  # VT_BLOB
        self.variant.blob = _Blob(ct.sizeof(self.params), ct.addressof(self.params))
        self.functions = (
            _STDCALL(_HRESULT, _VOID, ct.POINTER(_GUID), ct.POINTER(_VOID))(self._query),
            _STDCALL(_DWORD, _VOID)(self._add_ref),
            _STDCALL(_DWORD, _VOID)(self._release_ref),
            _STDCALL(_HRESULT, _VOID, _VOID)(self._completed),
        )
        self.vtable = (_VOID * 4)(*(ct.cast(fn, _VOID).value for fn in self.functions))
        self.vtable_pointer = ct.cast(self.vtable, ct.POINTER(_VOID))
        self.interface = ct.pointer(self.vtable_pointer)

    def _query(self, _this: int, iid: Any, output: Any) -> int:
        if not output:
            return -2147467261  # E_POINTER
        output[0] = None
        if iid and ct.string_at(iid, 16) in _CALLBACK_IIDS:
            output[0] = ct.cast(self.interface, _VOID).value
            self.references += 1
            return 0
        return -2147467262  # E_NOINTERFACE

    def _add_ref(self, _this: int) -> int:
        self.references += 1
        return self.references

    def _release_ref(self, _this: int) -> int:
        self.references -= 1
        return self.references

    def _completed(self, _this: int, operation: int) -> int:
        unknown = _VOID()
        client = _VOID()
        try:
            result = _HRESULT()
            _check(
                _call(
                    _VOID(operation),
                    3,
                    _HRESULT,
                    (ct.POINTER(_HRESULT), ct.POINTER(_VOID)),
                    ct.byref(result),
                    ct.byref(unknown),
                ),
                "Aktywacja nasłuchu",
            )
            _check(result.value, "Aktywacja nasłuchu programu")
            _check(
                _call(
                    unknown,
                    0,
                    _HRESULT,
                    (ct.POINTER(_GUID), ct.POINTER(_VOID)),
                    ct.byref(_IID_AUDIO_CLIENT),
                    ct.byref(client),
                ),
                "Interfejs dźwięku",
            )
            with self.lock:
                if not self.abandoned:
                    self.client, client = client, _VOID()
        except Exception as exc:
            self.error = str(exc)
        finally:
            _release(client)
            _release(unknown)
            self.done.set()
        return 0

    def abandon(self) -> None:
        """Zwalnia spóźniony wynik, zachowując wywołanie zwrotne do końca operacji."""
        with self.lock:
            self.abandoned = True
            _release(self.client)


def _activate(pid: int, stop_event: threading.Event) -> _VOID:
    state = _Activation(pid)
    with _callbacks_lock:
        # Nie zwalniamy obiektu w trakcie wykonywania jego funkcji Release.
        _active_callbacks[:] = [item for item in _active_callbacks if item.references > 0]
        _active_callbacks.append(state)
    operation = _VOID()
    mmdevice = ct.WinDLL("Mmdevapi")
    activate = _function(
        mmdevice,
        "ActivateAudioInterfaceAsync",
        _HRESULT,
        ct.c_wchar_p,
        ct.POINTER(_GUID),
        ct.POINTER(_PropVariant),
        _VOID,
        ct.POINTER(_VOID),
    )
    try:
        _check(
            activate(
                "VAD\\Process_Loopback",
                ct.byref(_IID_AUDIO_CLIENT),
                ct.byref(state.variant),
                ct.cast(state.interface, _VOID),
                ct.byref(operation),
            ),
            "Uruchamianie nasłuchu programu",
        )
        deadline = time.monotonic() + 10.0
        while not state.done.wait(0.05):
            if stop_event.is_set() or time.monotonic() >= deadline:
                raise ProcessAudioError("Przerwano oczekiwanie na uruchomienie nasłuchu programu.")
        if state.error:
            raise ProcessAudioError(state.error)
        with state.lock:
            client, state.client = state.client, _VOID()
        if not client:
            raise ProcessAudioError("Windows nie zwrócił interfejsu dźwięku programu.")
        return client
    except Exception:
        state.abandon()
        raise
    finally:
        _release(operation)
        state._release_ref(0)


def _read_packets(capture: _VOID, pcm: bytearray, limit: int, block_align: int) -> None:
    available = _DWORD()
    while len(pcm) < limit:
        _check(
            _call(capture, 5, _HRESULT, (ct.POINTER(_DWORD),), ct.byref(available)),
            "Odczyt rozmiaru próbki",
        )
        if not available.value:
            return
        data, frames, flags = _VOID(), _DWORD(), _DWORD()
        _check(
            _call(
                capture,
                3,
                _HRESULT,
                (ct.POINTER(_VOID), ct.POINTER(_DWORD), ct.POINTER(_DWORD), _VOID, _VOID),
                ct.byref(data),
                ct.byref(frames),
                ct.byref(flags),
                None,
                None,
            ),
            "Odczyt próbki programu",
        )
        try:
            count = min(frames.value * block_align, limit - len(pcm))
            if flags.value & 2:  # AUDCLNT_BUFFERFLAGS_SILENT
                pcm.extend(bytes(count))
            elif data:
                pcm.extend(ct.string_at(data, count))
            elif count:
                raise ProcessAudioError("Windows zwrócił pusty bufor dźwięku.")
        finally:
            _check(_call(capture, 4, _HRESULT, (_DWORD,), frames.value), "Zwolnienie próbki")
        if not frames.value:
            return


def capture_wav(
    process: ProcessInfo,
    *,
    duration_s: float,
    sample_rate: int,
    channels: int,
    stop_event: threading.Event,
) -> bytes | None:
    """Przechwytuje WAV PCM16 z jednego drzewa procesów; zwalnia wszystkie zasoby Windows."""
    kernel = _kernel()
    handle = kernel.OpenProcess(_QUERY_LIMITED | _SYNCHRONIZE, 0, process.pid)
    if not handle:
        error = ct.get_last_error()
        if error == 87:
            raise ProcessExitedError("Wybrany program został zamknięty.")
        raise ProcessAudioError(f"Windows nie pozwala otworzyć wybranego programu (błąd {error}).")
    ole = ct.OleDLL("ole32")
    initialize = _function(ole, "CoInitializeEx", _HRESULT, _VOID, _DWORD)
    uninitialize = _function(ole, "CoUninitialize", None)
    client, capture = _VOID(), _VOID()
    event = None
    initialized = False
    started = False
    try:
        _ensure_running(kernel, handle)
        path, created = _process_details(kernel, handle)
        if created != process.creation_time or path.casefold() != process.executable.casefold():
            raise ProcessExitedError("Odtwarzacz zmienił instancję; odnajduję go ponownie.")
        _check(initialize(None, 0), "Inicjalizacja obsługi dźwięku")
        initialized = True
        if stop_event.is_set():
            return None
        try:
            client = _activate(process.pid, stop_event)
        except ProcessAudioError:
            if stop_event.is_set():
                return None
            raise
        block_align = channels * 2
        audio_format = _WaveFormat(
            1, channels, sample_rate, sample_rate * block_align, block_align, 16, 0
        )
        flags = 0x00020000 | 0x00040000 | 0x80000000
        _check(
            _call(
                client,
                3,
                _HRESULT,
                (ct.c_int32, _DWORD, ct.c_int64, ct.c_int64, ct.POINTER(_WaveFormat), _VOID),
                0,
                flags,
                0,
                0,
                ct.byref(audio_format),
                None,
            ),
            "Ustawienie formatu dźwięku",
        )
        _check(
            _call(
                client,
                14,
                _HRESULT,
                (ct.POINTER(_GUID), ct.POINTER(_VOID)),
                ct.byref(_IID_CAPTURE_CLIENT),
                ct.byref(capture),
            ),
            "Otwarcie przechwytywania",
        )
        event = kernel.CreateEventW(None, 0, 0, None)
        if not event:
            raise ct.WinError(ct.get_last_error())
        _check(_call(client, 13, _HRESULT, (_VOID,), event), "Ustawienie powiadomień dźwięku")
        _check(_call(client, 10, _HRESULT, ()), "Rozpoczęcie nagrywania programu")
        started = True
        pcm = bytearray()
        limit = int(duration_s * sample_rate) * block_align
        deadline = time.monotonic() + duration_s + 2.0
        while len(pcm) < limit and not stop_event.is_set():
            _ensure_running(kernel, handle)
            wait = kernel.WaitForSingleObject(event, 50)
            if wait == 0xFFFFFFFF:
                raise ct.WinError(ct.get_last_error())
            _read_packets(capture, pcm, limit, block_align)
            if time.monotonic() >= deadline:
                # Nieaktywna sesja może nie dostarczać pakietów; reszta próbki to cisza.
                pcm.extend(bytes(limit - len(pcm)))
        if stop_event.is_set():
            return None
        _ensure_running(kernel, handle)
        with BytesIO() as output:
            with wave.open(output, "wb") as wav:
                wav.setnchannels(channels)
                wav.setsampwidth(2)
                wav.setframerate(sample_rate)
                wav.writeframes(pcm)
            return output.getvalue()
    except (OSError, ProcessAudioError):
        _ensure_running(kernel, handle)
        raise
    finally:
        if started:
            _call(client, 11, _HRESULT, ())
        _release(capture)
        _release(client)
        if event:
            kernel.CloseHandle(event)
        if initialized:
            uninitialize()
        kernel.CloseHandle(handle)
