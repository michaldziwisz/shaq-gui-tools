from __future__ import annotations

import ctypes as ct
import threading

import pytest

from shaqcast import _process_audio as audio
from shaqcast import _win_process_audio as native


def process(
    pid: int = 10, *, path: str = r"C:\Muzyka\winamp.exe", parent: int = 1
) -> audio.ProcessInfo:
    return audio.ProcessInfo(pid, parent, path, pid * 100)


def test_target_survives_config_roundtrip_without_pid() -> None:
    target = audio.ProcessTarget(r"C:\Muzyka\winamp.exe")
    assert target.to_config() == {"executable": r"C:\Muzyka\winamp.exe"}
    assert audio.ProcessTarget.from_config(target.to_config()) == target
    assert target.name == "winamp.exe"


@pytest.mark.parametrize("value", [None, {}, [], {"executable": 12}, {"executable": "winamp.exe"}])
def test_invalid_config_has_no_target(value: object) -> None:
    assert audio.ProcessTarget.from_config(value) is None


@pytest.mark.parametrize(
    "value", ["", "relative.exe", r"C:\muzyka.wav", "C:\\bad\x00.exe", r"\winamp.exe"]
)
def test_invalid_path_is_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        audio.ProcessTarget(value)


def test_invalid_path_type_is_rejected() -> None:
    with pytest.raises(TypeError):
        audio.ProcessTarget(15)


def test_restart_resolves_new_pid_by_full_path() -> None:
    target = process().target
    assert audio.resolve_process(target, []) is None
    assert audio.resolve_process(target, [process(50)]).pid == 50
    assert audio.resolve_process(target, [process(60)]).pid == 60
    assert audio.resolve_process(target, [process(path=r"D:\Inny\winamp.exe")]) is None


def test_process_matching_ignores_path_case() -> None:
    target = audio.ProcessTarget(r"c:/MUZYKA/WINAMP.EXE")
    assert audio.resolve_process(target, [process()]).pid == 10


def test_children_use_one_root_and_multiple_roots_are_rejected() -> None:
    target = process().target
    assert audio.resolve_process(target, [process(), process(11, parent=10)]).pid == 10
    with pytest.raises(audio.MultipleProcessesError):
        audio.resolve_process(target, [process(), process(11)])


@pytest.mark.parametrize("depth", [1, 4, 1500])
def test_process_tree_follows_all_helpers_without_recursion(depth: int) -> None:
    """Odtwarzacz pod pomocnikami należy do tego samego drzewa, także w odwrotnej kolejności."""
    root = process()
    helpers = [
        process(pid, path=r"C:\Programy\helper.exe", parent=pid - 1)
        for pid in range(11, 11 + depth)
    ]
    child = process(11 + depth, parent=10 + depth)
    assert audio.resolve_process(root.target, iter([child, *reversed(helpers), root])) == root


def test_common_helper_does_not_merge_separate_player_instances() -> None:
    helper = process(10, path=r"C:\Programy\helper.exe")
    first, second = process(11, parent=10), process(12, parent=10)
    with pytest.raises(audio.MultipleProcessesError):
        audio.resolve_process(first.target, [helper, first, second])


def test_missing_helper_does_not_guess_relationship() -> None:
    with pytest.raises(audio.MultipleProcessesError):
        audio.resolve_process(process().target, [process(), process(20, parent=15)])


def test_reused_parent_pid_does_not_merge_unrelated_players() -> None:
    first = process(10)
    helper = audio.ProcessInfo(20, 10, r"C:\Programy\helper.exe", 5000)
    second = audio.ProcessInfo(30, 20, first.executable, 4000)
    with pytest.raises(audio.MultipleProcessesError):
        audio.resolve_process(first.target, [first, helper, second])


@pytest.mark.parametrize("parent", [10, 20])
def test_invalid_ancestor_cycle_is_rejected_without_hanging(parent: int) -> None:
    root = audio.ProcessInfo(10, parent, process().executable, 100)
    helper = audio.ProcessInfo(20, 10, r"C:\Programy\helper.exe", 100)
    with pytest.raises(audio.MultipleProcessesError):
        audio.resolve_process(root.target, [root, helper])


def test_choices_keep_missing_saved_program_and_deduplicate() -> None:
    target = process().target
    assert audio.process_choices([], target) == [(target, False)]
    assert audio.process_choices([process(), process(11)], target) == [(target, True)]
    assert audio.process_choices([], None) == []


@pytest.fixture
def supported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(audio, "require_process_capture", lambda: None)


def test_capture_waits_for_closed_program_then_uses_new_pid(
    supported: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshots = iter([[], [process(55)]])
    monkeypatch.setattr(audio, "list_processes", lambda: next(snapshots))
    event = threading.Event()
    monkeypatch.setattr(event, "wait", lambda _seconds: False)
    captured: list[int] = []

    def capture(item: audio.ProcessInfo, **_kwargs: object) -> bytes:
        captured.append(item.pid)
        return b"test-wav"

    monkeypatch.setattr(native, "capture_wav", capture)
    messages: list[str] = []
    result = audio.record_process_wav(
        process().target,
        duration_s=1,
        stop_event=event,
        on_status=messages.append,
    )
    assert result == b"test-wav"
    assert captured == [55]
    assert "nie jest uruchomiony" in messages[0]
    assert "Nasłuch programu" in messages[1]


def test_capture_reconnects_after_player_exits_during_sample(
    supported: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshots = iter([[process(10)], [process(20)]])
    monkeypatch.setattr(audio, "list_processes", lambda: next(snapshots))
    pids: list[int] = []

    def capture(item: audio.ProcessInfo, **_kwargs: object) -> bytes:
        pids.append(item.pid)
        if item.pid == 10:
            raise audio.ProcessExitedError("Zamknięto odtwarzacz.")
        return b"nowe-nagranie"

    monkeypatch.setattr(native, "capture_wav", capture)
    result = audio.record_process_wav(
        process().target,
        duration_s=1,
        stop_event=threading.Event(),
        on_status=lambda _: None,
    )
    assert result == b"nowe-nagranie"
    assert pids == [10, 20]


def test_stop_interrupts_wait_without_capturing_another_application(
    supported: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(audio, "list_processes", lambda: [process(path=r"D:\Inny\winamp.exe")])
    event = threading.Event()
    monkeypatch.setattr(event, "wait", lambda _seconds: event.set())
    monkeypatch.setattr(native, "capture_wav", lambda *_a, **_k: pytest.fail("Nie wolno nagrywać."))
    assert (
        audio.record_process_wav(
            process().target,
            duration_s=1,
            stop_event=event,
            on_status=lambda _: None,
        )
        is None
    )


@pytest.mark.parametrize("duration", [0, -1, 61, float("inf"), float("nan")])
def test_invalid_duration_is_rejected(duration: float) -> None:
    with pytest.raises(ValueError):
        audio.record_process_wav(
            process().target,
            duration_s=duration,
            stop_event=threading.Event(),
            on_status=lambda _: None,
        )


@pytest.mark.parametrize("rate,channels", [(7999, 1), (48001, 1), (16000, 0), (16000, 3)])
def test_invalid_audio_format_is_rejected(rate: int, channels: int) -> None:
    with pytest.raises(ValueError):
        audio.record_process_wav(
            process().target,
            duration_s=1,
            sample_rate=rate,
            channels=channels,
            stop_event=threading.Event(),
            on_status=lambda _: None,
        )


def test_unsupported_windows_has_readable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(audio, "process_capture_supported", lambda: False)
    with pytest.raises(audio.ProcessAudioError, match="20348"):
        audio.require_process_capture()


@pytest.mark.parametrize("silent", [False, True])
def test_capture_packets_handle_silence_and_release_full_buffer(
    monkeypatch: pytest.MonkeyPatch,
    silent: bool,
) -> None:
    samples = ct.create_string_buffer(b"\x01\x02\x03\x04\x05\x06")
    released: list[int] = []

    def call(_pointer: object, index: int, _result: object, _types: object, *args: object) -> int:
        if index == 5:
            args[0]._obj.value = 3
        elif index == 3:
            args[0]._obj.value = ct.addressof(samples)
            args[1]._obj.value = 3
            args[2]._obj.value = 2 if silent else 0
        elif index == 4:
            released.append(args[0])
        return 0

    monkeypatch.setattr(native, "_call", call)
    pcm = bytearray()
    native._read_packets(ct.c_void_p(1), pcm, 4, 2)
    assert pcm == (b"\x00" * 4 if silent else b"\x01\x02\x03\x04")
    assert released == [3]


def test_null_packet_releases_buffer_before_error(monkeypatch: pytest.MonkeyPatch) -> None:
    released: list[int] = []

    def call(_pointer: object, index: int, _result: object, _types: object, *args: object) -> int:
        if index == 5:
            args[0]._obj.value = 2
        elif index == 3:
            args[1]._obj.value = 2
        elif index == 4:
            released.append(args[0])
        return 0

    monkeypatch.setattr(native, "_call", call)
    with pytest.raises(audio.ProcessAudioError, match="pusty bufor"):
        native._read_packets(ct.c_void_p(1), bytearray(), 4, 2)
    assert released == [2]


def test_com_activation_includes_only_target_tree() -> None:
    activation = native._Activation(123)
    assert activation.params.activation_type == 1
    assert activation.params.pid == 123
    assert activation.params.mode == 0
    assert activation.variant.vt == 65
    assert ct.sizeof(native._ActivationParams) == 12
    assert ct.sizeof(native._WaveFormat) == 18


def test_failed_activation_releases_late_client(monkeypatch: pytest.MonkeyPatch) -> None:
    activation = native._Activation(123)
    released: list[int] = []
    monkeypatch.setattr(native, "_release", lambda pointer: released.append(pointer.value))
    activation.client = ct.c_void_p(77)
    activation.abandon()
    assert activation.abandoned
    assert released == [77]
