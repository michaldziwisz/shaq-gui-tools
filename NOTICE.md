# Notices / attribution

This repository contains multiple tools and bundles third‑party components.

## shaq (upstream)

The `shaq/` folder contains code derived from the upstream project:

- Project: `shaq` (Shazam CLI client)
- Author: William Woodruff
- License: MIT (see `shaq/LICENSE`)
- Upstream: https://github.com/woodruffw/shaq

## Third‑party Python dependencies

These apps use third‑party Python packages (e.g. `shazamio`, `wxPython`, `soundcard`, `numpy`).
Their licenses are provided by the respective projects/distributions.

ShaqGUI wykorzystuje również Accessible Output 2 0.17 (licencja MIT,
Copyright 2019 Christopher Toth): https://github.com/accessibleapps/accessible_output2.
Pakiet EXE zawiera metadane i licencję tej biblioteki oraz jej biblioteki interfejsów czytników.

## ffmpeg binaries

ShaqGUI dołącza także FFmpeg do cichego odbioru radia internetowego.

The Windows builds of `shaqfilegui.exe` can bundle `ffmpeg.exe`/`ffprobe.exe`.
If you redistribute binaries that include ffmpeg, ensure you comply with ffmpeg’s license and
redistribution requirements for the specific build you ship.
