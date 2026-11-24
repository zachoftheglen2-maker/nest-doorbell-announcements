"""Transport for a local announcement provider, independent of HA internals."""
import asyncio
import re
from urllib.parse import urlsplit

import aiohttp

MAX_BODY = 8192


def valid_url(url: str) -> bool:
    try:
        parts = urlsplit(url)
        return (parts.scheme in ("http", "https") and bool(parts.hostname)
                and parts.username is None and parts.password is None
                and not parts.fragment and not parts.query
                and parts.port != 0 and bool(parts.path))
    except ValueError:
        return False


def parse_response(status: int, body: str) -> dict:
    """Validate the actual relay format; HTTP success alone is insufficient."""
    bytes_match = re.search(r"^Bytes sent:\s*(\d+)\s*$", body, re.M)
    exit_match = re.search(r"^FFmpeg exit code:\s*(-?\d+)\s*$", body, re.M)
    codec_match = re.search(r"^Codec:\s*([\w-]+)\s*$", body, re.M)
    sent = int(bytes_match.group(1)) if bytes_match else 0
    exit_code = int(exit_match.group(1)) if exit_match else None
    codec = codec_match.group(1) if codec_match else None
    ok = status == 200 and sent > 0 and exit_code == 0
    if ok:
        reason = "transmission_completed"
    elif status in (401, 403):
        reason = "provider_authorisation_error"
    elif status == 409:
        reason = "provider_busy"
    elif status != 200:
        reason = "provider_http_error"
    else:
        reason = "transmission_not_confirmed"
    return {"ok": ok, "status": status, "bytes_sent": sent,
            "ffmpeg_exit_code": exit_code, "codec": codec, "reason": reason}


class AnnouncementBackend:
    """No automatic retry: a timeout may have occurred after audible playback."""
    def __init__(self, session, url: str, timeout: int):
        self.session = session
        self.url = url
        self.timeout = timeout
        self.lock = asyncio.Lock()
        self.last_result = {"ok": False, "reason": "not_tested"}

    async def play(self) -> dict:
        if self.lock.locked():
            return {"ok": False, "reason": "announcement_already_running"}
        async with self.lock:
            try:
                async with self.session.post(
                    self.url, timeout=aiohttp.ClientTimeout(total=self.timeout),
                    allow_redirects=False,
                ) as response:
                    body = bytearray()
                    async for chunk in response.content.iter_chunked(1024):
                        body.extend(chunk)
                        if len(body) > MAX_BODY:
                            break
                    if len(body) > MAX_BODY:
                        result = {"ok": False, "status": response.status,
                                  "reason": "provider_response_too_large"}
                    else:
                        result = parse_response(response.status, body.decode("utf-8", errors="replace"))
            except asyncio.TimeoutError:
                result = {"ok": False, "reason": "timeout_playback_unknown"}
            except (aiohttp.ClientError, OSError, ValueError):
                result = {"ok": False, "reason": "provider_connection_error"}
            self.last_result = result
            return dict(result)
