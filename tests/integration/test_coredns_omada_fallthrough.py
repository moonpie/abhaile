"""Check native DNS answers after successful Omada controller initialization."""

import json
import os
import shutil
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from jinja2 import Environment, FileSystemLoader

pytestmark = pytest.mark.integration


class MockOmadaController(BaseHTTPRequestHandler):
    """Serve synthetic controller data without production credentials or network access."""

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress routine HTTP access logs."""

    def do_POST(self) -> None:
        """Handle login and client-list requests."""
        self.do_GET()

    def do_GET(self) -> None:
        """Return the minimal controller responses needed to populate dynamic zones."""
        path = self.path.split("?", 1)[0]
        result: Any
        if path == "/api/info":
            result = {
                "controllerVer": "6.2.10.17",
                "apiVer": "3",
                "configured": True,
                "omadacId": "test-controller",
            }
        elif path.endswith("/login"):
            result = {"token": "unused-test-value"}
        elif path.endswith("/users/current"):
            result = {"privilege": {"sites": [{"name": "test-site", "key": "test-site"}]}}
        elif path.endswith("/networks"):
            result = {
                "data": [
                    {
                        "id": "test-network",
                        "name": "test-network",
                        "domain": "abhaile.home.arpa",
                        "purpose": "interface",
                        "gatewaySubnet": "172.20.30.1/24",
                    }
                ]
            }
        elif path.endswith("/clients"):
            result = {
                "data": [
                    {"name": "dynamic-client", "ip": "172.20.30.77", "mac": "02:00:00:00:00:77"},
                    {"name": "overlap", "ip": "172.20.30.88", "mac": "02:00:00:00:00:88"},
                ]
            }
        elif path.endswith("/devices"):
            result = []
        elif path.endswith("/dhcp"):
            result = {"data": []}
        else:
            self.send_error(404)
            return
        body = json.dumps({"errorCode": 0, "result": result}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def test_populated_omada_preserves_static_fallback(tmp_path: Path) -> None:
    """Resolve static and dynamic records while retaining Omada-first precedence."""
    binary = os.environ.get("ABHAILE_TEST_COREDNS") or shutil.which("coredns")
    dig = shutil.which("dig")
    if not binary or not dig:
        pytest.skip(
            "Requires dig and a CoreDNS binary with the Omada plugin; set ABHAILE_TEST_COREDNS"
        )

    zones = [
        "abhaile.home.arpa.",
        "svc.abhaile.home.arpa.",
        "20.20.172.in-addr.arpa.",
        "100.20.172.in-addr.arpa.",
    ]
    zone_dir = tmp_path / "zones"
    zone_dir.mkdir()
    for zone in zones:
        content = (
            f"$ORIGIN {zone}\n$TTL 60\n"
            "@ IN SOA ns1.abhaile.home.arpa. hostmaster.abhaile.home.arpa. 4242 60 60 3600 60\n"
            "@ IN NS ns1.abhaile.home.arpa.\n"
        )
        if zone == "svc.abhaile.home.arpa.":
            content += "static IN A 192.0.2.10\n"
        elif zone == "abhaile.home.arpa.":
            content += "overlap IN A 192.0.2.20\n"
        elif zone == "20.20.172.in-addr.arpa.":
            content += "10 IN PTR static.svc.abhaile.home.arpa.\n"
        (zone_dir / f"{zone.rstrip('.')}.zone").write_text(content)

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    controller = ThreadingHTTPServer(("127.0.0.1", 0), MockOmadaController)
    thread = threading.Thread(target=controller.serve_forever, daemon=True)
    thread.start()
    template_root = Path(__file__).resolve().parents[2] / "config/services/coredns-common/config"
    template = Environment(loader=FileSystemLoader(template_root), autoescape=False).get_template(
        "Corefile.j2"
    )
    config = template.render(
        network={
            "dns": {
                "zones": [{"name": zone, "provider": {"name": "coredns-common"}} for zone in zones]
            }
        },
        service={
            "config": {
                "bind_ip": "127.0.0.1",
                "filtered_forward_to": "127.0.0.1:1",
                "dmz_caddy_ip": "192.0.2.200",
            }
        },
    )
    corefile = tmp_path / "Corefile"
    corefile.write_text(
        config.replace(":53 {", f":{port} {{").replace("/etc/coredns/zones/", f"{zone_dir}/")
    )
    environment = dict(
        os.environ,
        OMADA_URL=f"http://127.0.0.1:{controller.server_port}",
        OMADA_SITE="test-site",
        OMADA_USERNAME="unused-test-value",
        OMADA_PASSWORD="unused-test-value",
    )
    log_path = tmp_path / "coredns.log"
    try:
        with log_path.open("w") as log:
            process = subprocess.Popen(
                [binary, "-conf", str(corefile)], env=environment, stdout=log, stderr=log
            )
            try:
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    assert process.poll() is None, log_path.read_text()
                    if log_path.read_text().count("initial omada setup complete") >= len(zones):
                        break
                    time.sleep(0.1)
                else:
                    pytest.fail(
                        f"Controller initialization did not complete:\n{log_path.read_text()}"
                    )

                def query(name: str, kind: str = "A") -> str:
                    return subprocess.run(
                        [
                            dig,
                            "@127.0.0.1",
                            "-p",
                            str(port),
                            name,
                            kind,
                            "+short",
                            "+time=2",
                            "+tries=1",
                        ],
                        check=True,
                        capture_output=True,
                        text=True,
                        timeout=5,
                    ).stdout.strip()

                assert query("dynamic-client.abhaile.home.arpa") == "172.20.30.77"
                assert query("overlap.abhaile.home.arpa") == "172.20.30.88"
                assert query("static.svc.abhaile.home.arpa") == "192.0.2.10"
                assert query("10.20.20.172.in-addr.arpa", "PTR") == "static.svc.abhaile.home.arpa."
                for zone in zones[1:]:
                    assert "4242" in query(zone, "SOA")
            finally:
                process.terminate()
                process.wait(timeout=10)
    finally:
        controller.shutdown()
        controller.server_close()
        thread.join(timeout=5)
