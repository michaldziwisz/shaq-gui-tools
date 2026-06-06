from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

_MOUNT_SEPARATOR_RE = re.compile(r"[,;\r\n]+")


@dataclass(frozen=True, slots=True)
class UpdateResult:
    ok: bool
    method: str
    status: int | None
    body: str


def _looks_successful(status: int | None, body: str) -> bool:
    if status is None:
        return False
    if status < 200 or status >= 300:
        return False

    lowered = body.lower()
    if any(token in lowered for token in ("invalid", "error", "fail", "denied", "unauthorized")):
        return False

    return True


def parse_mounts(raw: str) -> list[str]:
    mounts: list[str] = []
    seen: set[str] = set()
    for part in _MOUNT_SEPARATOR_RE.split(raw or ""):
        mount = part.strip()
        if not mount:
            continue
        if not mount.startswith("/"):
            mount = "/" + mount
        if mount in seen:
            continue
        mounts.append(mount)
        seen.add(mount)
    return mounts


def update_now_playing(
    *,
    host: str,
    port: int,
    username: str,
    password: str,
    mount: str,
    song: str,
    timeout_s: float = 5.0,
) -> UpdateResult:
    """
    Update Icecast "Now Playing" metadata for a given mountpoint.

    Uses the Icecast admin endpoint:
      /admin/metadata?mount=<mount>&mode=updinfo&song=<song>
    with HTTP Basic auth (username/password).
    """
    username = (username or "source").strip() or "source"
    mounts = parse_mounts(mount)
    mount = mounts[0] if mounts else ""

    base_url = f"http://{host}:{port}/admin/metadata"
    query = urlencode(
        {
            "mount": mount,
            "mode": "updinfo",
            "song": song,
        }
    )
    url = f"{base_url}?{query}"

    basic_auth = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    req = Request(
        url,
        headers={
            "User-Agent": "shaqcast",
            "Authorization": f"Basic {basic_auth}",
        },
    )

    try:
        with urlopen(req, timeout=timeout_s) as resp:
            status = getattr(resp, "status", None)
            body = resp.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        return UpdateResult(ok=False, method="basic", status=exc.code, body=body)
    except URLError as exc:
        return UpdateResult(ok=False, method="basic", status=None, body=str(exc))
    except Exception as exc:
        return UpdateResult(ok=False, method="basic", status=None, body=str(exc))

    ok = _looks_successful(status, body)
    return UpdateResult(ok=ok, method="basic", status=status, body=body)
