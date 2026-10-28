"""Refresh a service-owned Mosquitto password file from Vault Agent staging material."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
from pathlib import Path
import subprocess
import tempfile

from abhaile.utils.errors import RenderError

LOG = logging.getLogger(__name__)


def _password_lines(source: bytes) -> str:
    """Validate three distinct MQTT accounts without including their values in errors."""
    try:
        accounts = json.loads(source)
    except (ValueError, UnicodeError):
        raise RenderError("MQTT staging material is not valid JSON") from None
    if not isinstance(accounts, list) or len(accounts) != 3:
        raise RenderError("MQTT staging material must contain three accounts")
    usernames: set[str] = set()
    lines = []
    for account in accounts:
        if not isinstance(account, dict) or set(account) != {"username", "password"}:
            raise RenderError("MQTT account must contain username and password fields")
        username, password = account["username"], account["password"]
        if (
            not isinstance(username, str)
            or not username
            or any(char.isspace() or char in ":\x00" for char in username)
            or username in usernames
        ):
            raise RenderError("MQTT usernames must be distinct non-empty single-line names")
        if not isinstance(password, str) or not password or any(c in password for c in "\r\n\x00"):
            raise RenderError("MQTT passwords must be non-empty single-line strings")
        usernames.add(username)
        lines.append(f"{username}:{password}\n")
    return "".join(lines)


def _atomic_install(path: Path, content: bytes, *, mode: int, group: int) -> None:
    """Install a protected file atomically on the destination filesystem."""
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            os.fchmod(stream.fileno(), mode)
            os.fchown(stream.fileno(), 0, group)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _hashed_passwords(lines: str, image: str, work_root: Path) -> bytes:
    """Hash plaintext inside an isolated helper container without credential arguments."""
    with tempfile.TemporaryDirectory(prefix="abhaile-mqtt-", dir=work_root) as directory:
        password_file = Path(directory) / "passwords"
        password_file.write_text(lines, encoding="utf-8")
        password_file.chmod(0o600)
        try:
            subprocess.run(
                [
                    "/usr/bin/podman",
                    "run",
                    "--rm",
                    "--pull=missing",
                    "--network=none",
                    "--read-only",
                    "--image-volume=ignore",
                    "--cap-drop=all",
                    "--security-opt=no-new-privileges",
                    "--user=0:0",
                    "--volume",
                    f"{directory}:/passwords:rw",
                    "--entrypoint=/usr/bin/mosquitto_passwd",
                    image,
                    "-H",
                    "sha512-pbkdf2",
                    "-U",
                    "/passwords/passwords",
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=120,
            )
        except (OSError, subprocess.SubprocessError):
            raise RenderError(
                "Mosquitto password conversion failed; installed file preserved"
            ) from None
        hashed = password_file.read_bytes()
        expected_users = [line.split(":", 1)[0] for line in lines.splitlines()]
        try:
            entries = [line.split(":", 1) for line in hashed.decode("utf-8").splitlines()]
        except UnicodeError:
            raise RenderError("Mosquitto password conversion produced invalid output") from None
        if len(entries) != len(expected_users) or any(
            len(entry) != 2 or entry[0] != user or not entry[1].startswith("$7$")
            for entry, user in zip(entries, expected_users)
        ):
            raise RenderError("Mosquitto password conversion did not produce expected hashes")
        return hashed


def refresh_passwords(
    source: Path, destination: Path, image: str, *, group: int, work_root: Path
) -> bool:
    """Install changed broker credentials and report whether the broker needs restarting."""
    staged = source.read_bytes()
    lines = _password_lines(staged)
    fingerprint = hashlib.sha256(staged + image.encode("utf-8")).hexdigest()
    state = destination.with_name(f".{destination.name}.state")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.parent.chmod(0o750)
    os.chown(destination.parent, 0, group)
    if destination.exists() and state.exists():
        installed_hash = hashlib.sha256(destination.read_bytes()).hexdigest()
        if state.read_bytes() == f"{fingerprint}:{installed_hash}\n".encode("ascii"):
            destination.chmod(0o640)
            os.chown(destination, 0, group)
            state.chmod(0o600)
            os.chown(state, 0, 0)
            return False
    hashed = _hashed_passwords(lines, image, work_root)
    _atomic_install(destination, hashed, mode=0o640, group=group)
    _restart_running_broker()
    installed_hash = hashlib.sha256(hashed).hexdigest()
    _atomic_install(state, f"{fingerprint}:{installed_hash}\n".encode("ascii"), mode=0o600, group=0)
    return True


def _restart_running_broker() -> None:
    """Restart an active broker without adding a restart job during initial startup."""
    status = subprocess.run(
        ["/usr/bin/systemctl", "is-active", "--quiet", "mosquitto.service"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=30,
    )
    if status.returncode == 0:
        subprocess.run(
            ["/usr/bin/systemctl", "--no-block", "try-restart", "mosquitto.service"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
    elif status.returncode not in (3, 4):
        raise RenderError("Could not inspect Mosquitto service state")


def main(argv: list[str] | None = None) -> int:
    """Refresh broker credentials and restart an already running broker after changes."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--image", required=True)
    parser.add_argument("--group", type=int, default=1883)
    parser.add_argument("--work-root", type=Path, default=Path("/run"))
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        changed = refresh_passwords(
            args.source, args.destination, args.image, group=args.group, work_root=args.work_root
        )
        if changed:
            LOG.info("Installed updated Mosquitto password hashes")
    except (OSError, RenderError, subprocess.SubprocessError):
        LOG.error("Mosquitto password refresh failed; check staging access and the helper image")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
