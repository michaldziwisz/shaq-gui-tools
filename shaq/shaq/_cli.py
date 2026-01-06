import argparse
import asyncio
import json
import logging
import os
import shutil
import sys
import wave
from collections.abc import Iterator
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from typing import Any

import pyaudio
from pydub import AudioSegment
from rich import progress
from rich.console import Console
from rich.logging import RichHandler
from rich.status import Status
from shazamio import Serialize, Shazam

logging.basicConfig(
    level=os.environ.get("SHAQ_LOGLEVEL", "INFO").upper(),
    format="%(message)s",
    datefmt="[%X]",
)

_DEFAULT_CHUNK_SIZE = 1024
_FORMAT = pyaudio.paInt16
_DEFAULT_CHANNELS = 1
_DEFAULT_SAMPLE_RATE = 16000
_DEFAULT_DURATION = 10

logger = logging.getLogger(__name__)


def _default_history_file() -> Path:
    if history_file := os.environ.get("SHAQ_HISTORY_FILE"):
        return Path(history_file)

    if getattr(sys, "frozen", False):
        return Path(sys.executable).with_name("historia.txt")

    if sys.platform == "win32":
        if appdata := os.environ.get("APPDATA"):
            return Path(appdata) / "shaq" / "history.txt"

    if xdg_state_home := os.environ.get("XDG_STATE_HOME"):
        return Path(xdg_state_home) / "shaq" / "history.txt"

    return Path.home() / ".shaq_history.txt"


def _append_history(history_file: Path, line: str) -> None:
    history_file = history_file.expanduser()
    history_file.parent.mkdir(parents=True, exist_ok=True)
    with history_file.open("a", encoding="utf-8") as io:
        io.write(f"{line}\n")


def _beep() -> None:
    try:
        if sys.platform == "win32":
            import winsound

            winsound.MessageBeep(winsound.MB_OK)
        else:
            sys.stderr.write("\a")
            sys.stderr.flush()
    except Exception:
        pass


@contextmanager
def _console() -> Iterator[Console]:
    """
    Temporarily dups and nulls the standard streams, while yielding a
    rich `Console` on the dup'd stderr.

    This is done because of PyAudio's misbehaving internals.
    See: https://stackoverflow.com/questions/67765911
    """
    try:
        # Save stdout and stderr, then clobber them.
        dup_fds = (os.dup(sys.stdout.fileno()), os.dup(sys.stderr.fileno()))
        null_fds = tuple(os.open(os.devnull, os.O_WRONLY) for _ in range(2))
        os.dup2(null_fds[0], sys.stdout.fileno())
        os.dup2(null_fds[1], sys.stderr.fileno())

        dup_stderr = os.fdopen(dup_fds[1], mode="w")
        yield Console(file=dup_stderr)
    finally:
        # Restore the original stdout and stderr; close everything except
        # the original FDs.
        os.dup2(dup_fds[0], sys.stdout.fileno())
        os.dup2(dup_fds[1], sys.stderr.fileno())

        for fd in [*null_fds, *dup_fds]:
            os.close(fd)


@contextmanager
def _pyaudio() -> Iterator[pyaudio.PyAudio]:
    try:
        p = pyaudio.PyAudio()
        yield p
    finally:
        p.terminate()


def _listen(console: Console, args: argparse.Namespace) -> bytearray:
    with _pyaudio() as p, BytesIO() as io, wave.open(io, "wb") as wav:
        # Use the same parameters as shazamio uses internally for audio
        # normalization, to reduce unnecessary transcoding.
        wav.setnchannels(args.channels)
        wav.setsampwidth(p.get_sample_size(_FORMAT))
        wav.setframerate(args.sample_rate)

        total_frames = args.sample_rate * args.duration
        frames_recorded = 0

        stream = p.open(
            format=_FORMAT,
            channels=args.channels,
            rate=args.sample_rate,
            input=True,
            frames_per_buffer=args.chunk_size,
        )
        for _ in progress.track(
            range(0, total_frames, args.chunk_size),
            description="shaq is listening...",
            console=console,
        ):
            frames = min(args.chunk_size, total_frames - frames_recorded)
            if frames <= 0:
                break
            wav.writeframes(stream.read(frames))
            frames_recorded += frames

        stream.close()

        # TODO: Optimize if necessary; this makes at least one pointless copy.
        return bytearray(io.getvalue())


def _loopback(console: Console, args: argparse.Namespace) -> bytearray:
    if sys.platform != "win32":
        console.print("[red]Fatal: --loopback is currently supported on Windows only[/red]")
        sys.exit(1)

    try:
        import soundcard as sc  # type: ignore[import-not-found]
    except ImportError:
        console.print("[red]Fatal: --loopback requires the 'soundcard' dependency[/red]")
        console.print("Install it with: pip install soundcard")
        sys.exit(1)

    # soundcard returns audio as float32 in [-1.0, 1.0], so we need numpy
    # to efficiently convert it to PCM16 for shazamio.
    import numpy as np  # type: ignore[import-not-found]

    from shaq._soundcard_compat import patch_soundcard_numpy_fromstring

    patch_soundcard_numpy_fromstring()

    speaker = sc.default_speaker()
    microphone = sc.get_microphone(speaker.id, include_loopback=True)

    total_frames = args.sample_rate * args.duration
    frames_recorded = 0

    with (
        BytesIO() as io,
        wave.open(io, "wb") as wav,
        microphone.recorder(samplerate=args.sample_rate, channels=args.channels) as recorder,
    ):
        wav.setnchannels(args.channels)
        wav.setsampwidth(2)  # PCM16
        wav.setframerate(args.sample_rate)

        for _ in progress.track(
            range(0, total_frames, args.chunk_size),
            description="shaq is listening (loopback)...",
            console=console,
        ):
            frames = min(args.chunk_size, total_frames - frames_recorded)
            if frames <= 0:
                break

            chunk = recorder.record(numframes=frames)
            pcm16 = (np.clip(chunk, -1.0, 1.0) * 32767).astype(np.int16)
            wav.writeframes(pcm16.tobytes())
            frames_recorded += frames

        # TODO: Optimize if necessary; this makes at least one pointless copy.
        return bytearray(io.getvalue())


def _from_file(console: Console, args: argparse.Namespace) -> bytearray:
    with Status(f"Extracting from {args.input}", console=console):
        input = AudioSegment.from_file(args.input)

        # pydub measures things in milliseconds
        duration = args.duration * 1000
        input = input[:duration]

        # Keep output similar to our microphone/loopback recording format.
        input = input.set_frame_rate(args.sample_rate).set_channels(args.channels).set_sample_width(2)

        with BytesIO() as io:
            input.export(io, format="wav")
            return bytearray(io.getvalue())


async def _shaq(console: Console, args: argparse.Namespace) -> dict[str, Any]:
    if args.listen:
        input = _listen(console, args)
    elif args.loopback:
        input = _loopback(console, args)
    else:
        input = _from_file(console, args)

    shazam = Shazam(language="en-US", endpoint_country="US")

    return await shazam.recognize(input, proxy=args.proxy)  # type: ignore


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    input_group = parser.add_mutually_exclusive_group(required=False)
    input_group.add_argument(
        "--listen", action="store_true", help="detect from the system's microphone"
    )
    input_group.add_argument(
        "--loopback",
        "--listen-output",
        dest="loopback",
        action="store_true",
        help="detect from the system's default audio output device (Windows only)",
    )
    input_group.add_argument("--input", type=Path, help="detect from the given audio input file")

    parser.add_argument(
        "-d",
        "--duration",
        metavar="SECS",
        type=int,
        default=_DEFAULT_DURATION,
        help="only analyze the first SECS of the input (microphone, loopback, or file)",
    )
    parser.add_argument(
        "-j", "--json", action="store_true", help="emit Shazam's response as JSON on stdout"
    )
    parser.add_argument("--albumcover", action="store_true", help="return url to HD album cover")
    parser.add_argument(
        "--beep",
        action=argparse.BooleanOptionalAction,
        default=getattr(sys, "frozen", False),
        help="play a beep when recognition finishes",
    )
    parser.add_argument(
        "--history-file",
        type=Path,
        default=_default_history_file(),
        help="append recognized tracks to this history file",
    )
    parser.add_argument("--no-history", action="store_true", help="disable writing history")

    advanced_group = parser.add_argument_group(
        title="Advanced Options",
        description="Advanced users only: options to tweak recording, transcoding, etc. behavior.",
    )
    advanced_group.add_argument(
        "--chunk-size",
        type=int,
        default=_DEFAULT_CHUNK_SIZE,
        help="read audio in chunks of this size; only affects --listen/--loopback",
    )
    advanced_group.add_argument(
        "--channels",
        type=int,
        choices=(1, 2),
        default=_DEFAULT_CHANNELS,
        help="the number of channels to use; only affects --listen/--loopback",
    )
    advanced_group.add_argument(
        "--sample-rate",
        type=int,
        default=_DEFAULT_SAMPLE_RATE,
        help="the sample rate to use; only affects --listen/--loopback",
    )
    advanced_group.add_argument(
        "--proxy",
        type=str,
        help="send the request to a proxy server",
    )
    return parser


def main() -> None:
    args = _parser().parse_args()
    with _console() as console:
        logger.addHandler(RichHandler(console=console))
        logger.debug(f"parsed {args=}")

        if not (args.listen or args.loopback or args.input):
            if sys.platform == "win32":
                args.loopback = True
            else:
                args.listen = True

        if args.input and not shutil.which("ffmpeg"):
            console.print("[red]Fatal: ffmpeg not found on $PATH[/red]")
            sys.exit(1)

        try:
            raw = asyncio.run(_shaq(console, args))
            track = Serialize.full_track(raw)
        except KeyboardInterrupt:
            console.print("[red]Interrupted.[/red]")
            sys.exit(2)

    if track.matches and not args.no_history:
        try:
            _append_history(args.history_file, f"{track.track.subtitle} - {track.track.title}")
        except OSError as exc:
            print(f"Warning: couldn't write history to {args.history_file}: {exc}", file=sys.stderr)

    if args.beep:
        _beep()

    if args.json:
        json.dump(raw, sys.stdout, indent=2)
    else:
        track = Serialize.full_track(raw)
        if not track.matches:
            print("No matches.")
        else:
            print(f"Track: {track.track.title}")
            print(f"Artist: {track.track.subtitle}")
            if args.albumcover:
                if "images" in raw["track"]:
                    album_cover = raw["track"]["images"]["coverart"]
                    # Forces the shazam image server to fetch a
                    # high-resolution album cover.
                    album_cover_hq = album_cover.replace("/400x400cc.jpg", "/1000x1000cc.png")
                    print(f"Album Cover: {album_cover_hq}")

    if not track.matches:
        sys.exit(1)
