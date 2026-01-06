# shaq

[![CI](https://github.com/woodruffw/shaq/actions/workflows/ci.yml/badge.svg)](https://github.com/woodruffw/shaq/actions/workflows/ci.yml)
[![PyPI version](https://badge.fury.io/py/shaq.svg)](https://badge.fury.io/py/shaq)

A bare-bones CLI client for [Shazam](https://www.shazam.com/home).

![shaq in action](https://github.com/woodruffw/shaq/assets/3059210/3ee02414-b1c0-4379-8c9d-cb646dba9902)

## Installation

`shaq` is available via `pip` or `pipx`:

```bash
pip install shaq
pipx install shaq
```

If you run into installation errors, make sure that you have PortAudio
installed. On Debian-based systems:

```bash
sudo apt install -y portaudio19-dev
```

`shaq` is also available on the Arch User Repository as [`shaq`](https://aur.archlinux.org/packages/shaq).

## Usage

Detect by listening to the system microphone:

```bash
# shaq listens for 10 seconds by default
shaq --listen

# tell shaq to listen for 15 seconds instead
shaq --listen --duration 15
```

Detect by listening to your system audio output (Windows only):

```bash
# shaq listens for 10 seconds by default
shaq --loopback

# also available as --listen-output
shaq --listen-output --duration 15
```

Detect from an audio file on disk:

```bash
# shaq truncates the input to 10 seconds
shaq --input obscure.mp3

# ...which can be overriden
shaq --input obscure.mp3 --duration 15
```

## File scanning GUI

`shaqfilegui` is a minimal wxPython GUI that scans an audio/video file on disk by taking
short samples every N seconds and writing unique recognized tracks to a `.txt` file.

The output filename matches the input basename (e.g. `show.ts` -> `show.txt`) and is written
either next to the input file or into the selected output folder.

When running from source, `shaqfilegui` requires `ffmpeg`/`ffprobe` on `$PATH`.

To build a self-contained Windows `.exe` (bundled `ffmpeg.exe`/`ffprobe.exe`):

```powershell
cd shaq
.\build_shaqfilegui_windows.ps1
```

See `shaq --help` for more options.

## Beep

`shaq` can optionally play a short beep when recognition finishes:

```bash
shaq --listen --beep

# in the Windows .exe build, beeping is enabled by default
shaq --listen --no-beep
```

## History

By default, `shaq` appends successfully recognized tracks to a history file
in `artist - title` format.

The default location is:

- Windows: `%APPDATA%\shaq\history.txt`
- Other platforms: `$XDG_STATE_HOME/shaq/history.txt` (if set), otherwise `~/.shaq_history.txt`

You can override the history location with `--history-file` (or via the
`SHAQ_HISTORY_FILE` environment variable), or disable history writing with
`--no-history`.

## The name?

[Shazam](https://www.shazam.com/home),
[Shazaam](https://en.wikipedia.org/wiki/Kazaam#%22Shazaam%22),
[Kazaam](https://en.wikipedia.org/wiki/Kazaam),
[Shaquille O'Neal](https://en.wikipedia.org/wiki/Shaquille_O%27Neal).
