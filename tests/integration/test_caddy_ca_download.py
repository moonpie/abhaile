"""Verify that internal CA downloads cannot serve other CA storage files."""

import os
from pathlib import Path
import shutil
import socket
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pytest

from abhaile.renderers.ingress import render_ingress_configs

pytestmark = pytest.mark.integration
REPO = Path(__file__).resolve().parents[2]


def _render_ca_site(tmp_path: Path) -> str:
    """Render the actual internal ingress and select the CA site."""
    render_ingress_configs(
        "phobos", ["caddy-internal"], ["caddy-internal"], REPO / "config", tmp_path
    )
    rendered = (tmp_path / "caddy-internal/srv/caddy/internal/Caddyfile").read_text()
    return rendered.split("ca.abhaile.home.arpa {\n", 1)[1].split("\n}\n", 1)[0]


def test_ca_download_render_has_exact_allowlist_and_deny_fallback(tmp_path: Path) -> None:
    site = _render_ca_site(tmp_path)
    assert "@rootcrt path /root.crt /abhaile-ca.crt" in site
    assert "rewrite * /root.crt" in site
    assert site.count("file_server") == 1
    assert 'handle {\n\t\trespond "Not found" 404\n\t}' in site


def test_ca_download_serves_only_public_certificate_with_native_caddy(tmp_path: Path) -> None:
    executable = os.environ.get("CADDY_BINARY") or shutil.which("caddy")
    if not executable:
        pytest.skip("Set CADDY_BINARY or install Caddy for the native HTTP regression")
    site = _render_ca_site(tmp_path)
    fixture_root = tmp_path / "ca"
    fixture_root.mkdir()
    public_certificate = b"public certificate fixture\n"
    (fixture_root / "root.crt").write_bytes(public_certificate)
    for name in ("root.key", "intermediate.key", "intermediate.crt"):
        (fixture_root / name).write_text("non-public fixture\n")
    site = site.replace("\timport common_headers\n", "").replace("\timport tls_internal\n", "")
    site = site.replace("/data/pki/authorities/local", str(fixture_root))
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    caddyfile = tmp_path / "Caddyfile"
    caddyfile.write_text(
        "{\n admin off\n auto_https off\n}\n" + f"http://127.0.0.1:{port} {{\n{site}\n}}\n"
    )
    with (tmp_path / "caddy.log").open("w+") as log:
        process = subprocess.Popen(
            [executable, "run", "--config", str(caddyfile), "--adapter", "caddyfile"],
            stdout=log,
            stderr=log,
            env={
                **os.environ,
                "XDG_DATA_HOME": str(tmp_path / "data"),
                "XDG_CONFIG_HOME": str(tmp_path / "config"),
            },
        )
        try:
            base = f"http://127.0.0.1:{port}"
            deadline = time.monotonic() + 5
            while True:
                try:
                    with urlopen(base + "/root.crt", timeout=1) as response:
                        assert response.read() == public_certificate
                    break
                except URLError:
                    if process.poll() is not None or time.monotonic() >= deadline:
                        log.seek(0)
                        pytest.fail(log.read())
                    time.sleep(0.05)
            with urlopen(base + "/abhaile-ca.crt", timeout=1) as response:
                assert response.read() == public_certificate
            for path in (
                "/",
                "/root.key",
                "/intermediate.key",
                "/intermediate.crt",
                "/root.crt/",
                "/root.crt/root.key",
                "/%72oot.key",
                "/unknown",
            ):
                with pytest.raises(HTTPError) as error:
                    urlopen(base + path, timeout=1)
                assert error.value.code == 404, path
        finally:
            process.terminate()
            process.wait(timeout=5)


def test_application_csp_headers_with_native_caddy(tmp_path: Path) -> None:
    executable = os.environ.get("CADDY_BINARY") or shutil.which("caddy")
    if not executable:
        pytest.skip("Set CADDY_BINARY or install Caddy for the native HTTP regression")
    render_ingress_configs(
        "phobos",
        ["caddy-internal", "authelia", "zigbee2mqtt"],
        ["caddy-internal", "authelia", "zigbee2mqtt"],
        REPO / "config",
        tmp_path,
    )
    rendered = (tmp_path / "caddy-internal/srv/caddy/internal/Caddyfile").read_text()
    common = rendered.split("(common_headers) {\n", 1)[1].split("\n}\n", 1)[0]
    with socket.socket() as listener, socket.socket() as backend:
        listener.bind(("127.0.0.1", 0))
        backend.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        backend_port = backend.getsockname()[1]
    upstream_policy = "default-src 'self'; style-src 'self' 'nonce-testfixture'"
    config = (
        "{\n admin off\n auto_https off\n}\n"
        + f"(common_headers) {{\n{common}\n}}\n"
        + "(authelia_forward_auth) {\n # Authentication is outside this header-only test.\n}\n"
        + f"http://:{backend_port} {{\n bind 127.0.0.1\n"
        + f' header Content-Security-Policy "{upstream_policy}"\n'
        + ' header X-Frame-Options "DENY"\n respond "fixture" 200\n}\n'
    )
    for host, service in (
        ("authelia.abhaile.home.arpa", "authelia"),
        ("zigbee2mqtt.abhaile.home.arpa", "zigbee2mqtt"),
    ):
        site = rendered.split(host + " {\n", 1)[1].split("\n}\n", 1)[0]
        site = site.replace("\timport tls_internal\n", "")
        upstream = f"http://{service}.svc.abhaile.home.arpa:"
        # Keep the rendered route and headers; replace only its backend address.
        site = site.replace(
            upstream + ("9091" if service == "authelia" else "8080"),
            f"http://127.0.0.1:{backend_port}",
        )
        config += f"http://{host}:{port} {{\n bind 127.0.0.1\n{site}\n}}\n"
    config += f"http://default.abhaile.home.arpa:{port} {{\n bind 127.0.0.1\n import common_headers\n respond 200\n}}\n"
    caddyfile = tmp_path / "headers.Caddyfile"
    caddyfile.write_text(config)
    with (tmp_path / "headers.log").open("w+") as log:
        process = subprocess.Popen(
            [executable, "run", "--config", str(caddyfile), "--adapter", "caddyfile"],
            stdout=log,
            stderr=log,
            env={
                **os.environ,
                "XDG_DATA_HOME": str(tmp_path / "data"),
                "XDG_CONFIG_HOME": str(tmp_path / "config"),
            },
        )
        try:
            deadline = time.monotonic() + 5
            while True:
                try:
                    with urlopen(f"http://127.0.0.1:{backend_port}", timeout=1):
                        break
                except URLError:
                    if process.poll() is not None or time.monotonic() >= deadline:
                        log.seek(0)
                        pytest.fail(log.read())
                    time.sleep(0.05)
            for host, expected in (
                ("authelia", upstream_policy),
                (
                    "zigbee2mqtt",
                    "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'",
                ),
                ("default", "default-src 'self'; frame-ancestors 'none'"),
            ):
                request = Request(
                    f"http://127.0.0.1:{port}/", headers={"Host": f"{host}.abhaile.home.arpa"}
                )
                with urlopen(request, timeout=1) as response:
                    assert response.headers.get_all("Content-Security-Policy") == [expected]
                    assert response.headers["X-Frame-Options"] == "DENY"
        finally:
            process.terminate()
            process.wait(timeout=5)
