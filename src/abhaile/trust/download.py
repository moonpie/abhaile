"""Acquire immutable HTTPS artifacts with explicit resource and archive bounds."""

from __future__ import annotations

import hashlib
import io
import stat
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from typing import Callable, Protocol

from abhaile.trust.errors import TrustError


@dataclass(frozen=True)
class DownloadPolicy:
    """Bind one acquisition to exact HTTPS, redirect, size, and digest authority."""

    url: str
    sha256: str
    max_bytes: int
    redirect_origins: tuple[str, ...] = ()
    max_redirects: int = 0


class _Headers(Protocol):
    """Describe the response-header lookup used by the downloader."""

    def get(self, name: str) -> str | None:
        """Return one header value when present."""


class _Readable(Protocol):
    """Describe a bounded binary reader."""

    def read(self, size: int = -1) -> bytes:
        """Read bytes from the source."""


class _DownloadResponse(_Readable, Protocol):
    """Describe the response surface consumed by the bounded downloader."""

    @property
    def headers(self) -> _Headers:
        """Return response headers."""

    def geturl(self) -> str:
        """Return the effective response URL."""

    def read(self, size: int = -1) -> bytes:
        """Read response bytes."""

    def close(self) -> None:
        """Close the response."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Return redirects to the bounded loop instead of following implicitly."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: _Readable,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> None:
        return None


def download_bytes(
    policy: DownloadPolicy,
    *,
    open_url: Callable[[urllib.request.Request], _DownloadResponse] | None = None,
) -> bytes:
    """Download and verify one bounded artifact without implicit redirects."""
    _validate_policy(policy)
    opener = urllib.request.build_opener(_NoRedirect())
    open_request = open_url or opener.open
    current = policy.url
    initial_origin = _origin(current)
    allowed = {initial_origin, *policy.redirect_origins}
    for redirect_count in range(policy.max_redirects + 1):
        request = urllib.request.Request(
            current,
            headers={"User-Agent": "abhaile-protected-downloader/1"},
            method="GET",
        )
        try:
            response = open_request(request)
        except urllib.error.HTTPError as exc:
            if exc.code not in {301, 302, 303, 307, 308}:
                raise TrustError("Immutable download failed") from None
            location = exc.headers.get("Location")
            if redirect_count >= policy.max_redirects or not location:
                raise TrustError("Immutable download redirect is not authorized") from None
            redirected = urllib.parse.urljoin(current, location)
            if _origin(redirected) not in allowed:
                raise TrustError("Immutable download redirect origin is not authorized")
            current = redirected
            continue
        try:
            final_url = response.geturl()
            if final_url != current or _origin(final_url) not in allowed:
                raise TrustError("Immutable download transport followed an unsafe redirect")
            length = response.headers.get("Content-Length")
            if length is not None and (not length.isdecimal() or int(length) > policy.max_bytes):
                raise TrustError("Immutable download exceeds the declared size bound")
            payload = _read_bounded(response, policy.max_bytes)
        finally:
            response.close()
        if hashlib.sha256(payload).hexdigest() != policy.sha256:
            raise TrustError("Immutable download digest is mismatched")
        return payload
    raise TrustError("Immutable download redirect limit was exceeded")


def extract_zip_member(
    payload: bytes,
    *,
    member: str,
    max_member_bytes: int,
    max_compression_ratio: int,
) -> bytes:
    """Extract one exact safe ZIP member after validating the complete archive table."""
    if (
        not member
        or "/" in member
        or member in {".", ".."}
        or not 1 <= max_member_bytes <= 512 * 1024 * 1024
        or not 1 <= max_compression_ratio <= 100
    ):
        raise TrustError("Archive extraction authority is invalid")
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            entries = archive.infolist()
            if not entries or len(entries) > 1024:
                raise TrustError("Archive member count is outside the declared safety bound")
            names: set[str] = set()
            selected: zipfile.ZipInfo | None = None
            for entry in entries:
                normalized = entry.filename.replace("\\", "/")
                parts = normalized.split("/")
                file_type = (entry.external_attr >> 16) & 0o170000
                if (
                    not normalized
                    or normalized.startswith("/")
                    or any(part in {"", ".", ".."} for part in parts)
                    or normalized in names
                    or entry.flag_bits & 0x1
                    or file_type not in {0, stat.S_IFREG, stat.S_IFDIR}
                    or entry.file_size > max_member_bytes
                    or (entry.file_size > 0 and entry.compress_size == 0 and not entry.is_dir())
                    or (
                        entry.compress_size > 0
                        and entry.file_size > entry.compress_size * max_compression_ratio
                    )
                ):
                    raise TrustError("Archive contains an unsafe or ambiguous member")
                names.add(normalized)
                if normalized == member:
                    if entry.is_dir():
                        raise TrustError("Declared archive output is not a regular file")
                    selected = entry
            if selected is None:
                raise TrustError("Declared archive member is missing")
            with archive.open(selected, "r") as source:
                return _read_bounded(source, max_member_bytes)
    except (zipfile.BadZipFile, RuntimeError, OSError) as exc:
        if isinstance(exc, TrustError):
            raise
        raise TrustError("Archive validation failed") from None


def _read_bounded(source: _Readable, maximum: int) -> bytes:
    chunks: list[bytes] = []
    size = 0
    while chunk := source.read(min(1024 * 1024, maximum - size + 1)):
        size += len(chunk)
        if size > maximum:
            raise TrustError("Artifact exceeds the declared size bound")
        chunks.append(chunk)
    return b"".join(chunks)


def _validate_policy(policy: DownloadPolicy) -> None:
    if (
        _origin(policy.url) == ""
        or len(policy.sha256) != 64
        or any(character not in "0123456789abcdef" for character in policy.sha256)
        or not 1 <= policy.max_bytes <= 512 * 1024 * 1024
        or not 0 <= policy.max_redirects <= 5
        or len(set(policy.redirect_origins)) != len(policy.redirect_origins)
        or any(_origin(origin) != origin.rstrip("/") for origin in policy.redirect_origins)
    ):
        raise TrustError("Immutable download policy is invalid")


def _origin(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        return ""
    port = f":{parsed.port}" if parsed.port is not None else ""
    return f"https://{parsed.hostname.lower()}{port}"
