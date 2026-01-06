from __future__ import annotations

import base64
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


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

    # Shoutcast often responds with "OK" / "OK2" on success.
    if any(token in body for token in ("OK", "OK2", "ICY 200")):
        return True

    # Some setups return HTML; treat any 2xx without obvious failure as success.
    return True


def update_now_playing(
    *,
    host: str,
    port: int,
    password: str,
    sid: int,
    song: str,
    timeout_s: float = 5.0,
) -> UpdateResult:
    """
    Update Shoutcast "Now Playing" metadata for a given SID.

    Different Shoutcast setups use slightly different auth mechanisms; we try a couple:
    - query param `pass=<password>` (common for DNAS)
    - HTTP Basic auth (`admin:<password>`)
    """
    base_url = f"http://{host}:{port}/admin.cgi"

    query_with_pass = urlencode(
        {
            "mode": "updinfo",
            "sid": str(sid),
            "pass": password,
            "song": song,
        }
    )
    url_with_pass = f"{base_url}?{query_with_pass}"

    query_basic = urlencode(
        {
            "mode": "updinfo",
            "sid": str(sid),
            "song": song,
        }
    )
    url_basic = f"{base_url}?{query_basic}"
    basic_auth = base64.b64encode(f"admin:{password}".encode("utf-8")).decode("ascii")

    candidates: list[tuple[str, Request]] = [
        ("query-pass", Request(url_with_pass, headers={"User-Agent": "shaqcast"})),
        (
            "basic-admin",
            Request(
                url_basic,
                headers={"User-Agent": "shaqcast", "Authorization": f"Basic {basic_auth}"},
            ),
        ),
    ]

    last_result: UpdateResult | None = None
    for method, req in candidates:
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
            last_result = UpdateResult(ok=False, method=method, status=exc.code, body=body)
        except URLError as exc:
            last_result = UpdateResult(ok=False, method=method, status=None, body=str(exc))
        except Exception as exc:
            last_result = UpdateResult(ok=False, method=method, status=None, body=str(exc))
        else:
            ok = _looks_successful(status, body)
            result = UpdateResult(ok=ok, method=method, status=status, body=body)
            if ok:
                return result
            last_result = result

    return last_result or UpdateResult(ok=False, method="none", status=None, body="no candidates attempted")

