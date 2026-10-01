"""Test immutable bounded download and archive mechanics without network access."""

import hashlib
import io
from email.message import Message
import urllib.error
import urllib.request
import zipfile

import pytest

from abhaile.trust.download import DownloadPolicy, download_bytes, extract_zip_member
from abhaile.trust.errors import TrustError


class Response(io.BytesIO):
    """Provide the bounded urllib response surface used by the downloader."""

    def __init__(self, payload: bytes, url: str, length: str | None = None) -> None:
        super().__init__(payload)
        self._url = url
        self.headers = {} if length is None else {"Content-Length": length}

    def geturl(self) -> str:
        """Return the response URL without implicit redirects."""
        return self._url


def test_download_enforces_digest_and_streaming_bound() -> None:
    """Accept exact bounded bytes and reject overflow or digest mismatch."""
    payload = b"immutable"
    policy = DownloadPolicy(
        "https://example.invalid/tool", hashlib.sha256(payload).hexdigest(), len(payload)
    )
    assert (
        download_bytes(policy, open_url=lambda request: Response(payload, request.full_url))
        == payload
    )
    with pytest.raises(TrustError, match="size bound"):
        download_bytes(
            DownloadPolicy(policy.url, policy.sha256, len(payload) - 1),
            open_url=lambda request: Response(payload, request.full_url),
        )
    with pytest.raises(TrustError, match="digest"):
        download_bytes(
            DownloadPolicy(policy.url, "0" * 64, len(payload)),
            open_url=lambda request: Response(payload, request.full_url),
        )


def test_download_rejects_implicit_and_unapproved_redirects() -> None:
    """Authorize only explicit exact HTTPS redirect origins and counts."""
    payload = b"tool"
    digest = hashlib.sha256(payload).hexdigest()
    with pytest.raises(TrustError, match="unsafe redirect"):
        download_bytes(
            DownloadPolicy("https://example.invalid/tool", digest, 10),
            open_url=lambda request: Response(payload, "https://other.invalid/tool"),
        )

    calls = 0

    def redirected(request: urllib.request.Request) -> Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            headers = Message()
            headers["Location"] = "https://assets.invalid/tool"
            raise urllib.error.HTTPError(
                request.full_url,
                302,
                "redirect",
                headers,
                None,
            )
        return Response(payload, request.full_url)

    policy = DownloadPolicy(
        "https://example.invalid/tool", digest, 10, ("https://assets.invalid",), 1
    )
    assert download_bytes(policy, open_url=redirected) == payload


def _archive(entries: list[tuple[str, bytes, int | None]]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content, external in entries:
            info = zipfile.ZipInfo(name)
            info.compress_type = zipfile.ZIP_DEFLATED
            if external is not None:
                info.external_attr = external << 16
            archive.writestr(info, content)
    return output.getvalue()


def test_archive_extracts_one_exact_safe_member() -> None:
    """Validate the complete table and extract only the declared member."""
    payload = _archive([("vault", b"binary", 0o100755), ("LICENSE", b"license", 0o100644)])
    assert (
        extract_zip_member(payload, member="vault", max_member_bytes=1024, max_compression_ratio=20)
        == b"binary"
    )


@pytest.mark.parametrize(
    "name,external",
    [("../vault", 0o100755), ("/vault", 0o100755), ("vault", 0o120777)],
)
def test_archive_rejects_traversal_absolute_and_links(name: str, external: int) -> None:
    """Reject unsafe members even when they are not selected output."""
    payload = _archive([(name, b"bad", external)])
    with pytest.raises(TrustError, match="unsafe|missing"):
        extract_zip_member(payload, member="vault", max_member_bytes=1024, max_compression_ratio=20)


def test_archive_rejects_missing_oversize_and_ratio() -> None:
    """Enforce exact member, expanded-size, and compression-ratio bounds."""
    payload = _archive([("vault", b"a" * 4096, 0o100755)])
    with pytest.raises(TrustError):
        extract_zip_member(
            payload, member="other", max_member_bytes=8192, max_compression_ratio=100
        )
    with pytest.raises(TrustError):
        extract_zip_member(
            payload, member="vault", max_member_bytes=1024, max_compression_ratio=100
        )
    with pytest.raises(TrustError):
        extract_zip_member(payload, member="vault", max_member_bytes=8192, max_compression_ratio=1)
