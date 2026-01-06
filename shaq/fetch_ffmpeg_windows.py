from __future__ import annotations

import argparse
import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

_DEFAULT_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"


def _download(url: str, dest: Path) -> None:
    req = Request(url, headers={"User-Agent": "shaqfilegui-build"})
    with urlopen(req) as resp, dest.open("wb") as out:
        shutil.copyfileobj(resp, out)


def _extract_tools(zip_path: Path, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    extracted: list[Path] = []

    with zipfile.ZipFile(zip_path) as zf:
        name_map = {name.lower(): name for name in zf.namelist()}
        want_suffixes = (
            "\\bin\\ffmpeg.exe",
            "\\bin\\ffprobe.exe",
            "/bin/ffmpeg.exe",
            "/bin/ffprobe.exe",
        )

        members: list[str] = []
        for lower, original in name_map.items():
            if lower.endswith(want_suffixes):
                members.append(original)

        if not members:
            raise RuntimeError("Zip does not contain ffmpeg.exe/ffprobe.exe in a /bin directory")

        for member in members:
            target_name = Path(member).name
            target_path = out_dir / target_name
            with zf.open(member) as src, target_path.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            extracted.append(target_path)

    return extracted


def main() -> None:
    if os.name != "nt":
        raise SystemExit(
            "This helper is intended to be run on Windows (to fetch ffmpeg.exe/ffprobe.exe)."
        )

    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=_DEFAULT_URL, help="ffmpeg zip URL (Windows build)")
    parser.add_argument(
        "--out-dir",
        default=str(Path(__file__).resolve().parent / "vendor" / "ffmpeg"),
        help="destination directory for ffmpeg.exe/ffprobe.exe",
    )
    args = parser.parse_args()

    out_dir = Path(args.out_dir).resolve()
    with tempfile.TemporaryDirectory() as tmp:
        zip_path = Path(tmp) / "ffmpeg.zip"
        print(f"Downloading: {args.url}")
        _download(args.url, zip_path)
        extracted = _extract_tools(zip_path, out_dir)

    print("OK. Extracted:")
    for path in extracted:
        print(f"- {path}")


if __name__ == "__main__":
    main()
