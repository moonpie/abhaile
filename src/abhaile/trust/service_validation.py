"""Parse the closed renderer-owned Caddy and CoreDNS configuration grammars."""

from __future__ import annotations

import re
import shlex

from abhaile.trust.errors import TrustError

_NAME = re.compile(r"[A-Za-z0-9_.@*:-]+")
_SNIPPET = re.compile(r"\(([A-Za-z][A-Za-z0-9_-]*)\)")
_IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_-]*")
_HEADER = re.compile(r"[A-Za-z][A-Za-z0-9-]*")
_RESOLVED_KEYS = frozenset(
    {
        "Cache",
        "DNS",
        "DNSOverTLS",
        "DNSSEC",
        "DNSStubListener",
        "Domains",
        "LLMNR",
        "MulticastDNS",
        "ReadEtcHosts",
        "ResolveUnicastSingleLabel",
    }
)


def validate_resolved_config(payload: bytes) -> None:
    """Parse the closed systemd-resolved configuration emitted by the renderer."""
    try:
        text = payload.decode("utf-8")
    except UnicodeError:
        raise TrustError("Resolved configuration structure is invalid") from None
    if not payload or len(payload) > 1024 * 1024 or b"\x00" in payload:
        raise TrustError("Resolved configuration structure is invalid")
    section = False
    seen: set[str] = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line == "[Resolve]" and not section:
            section = True
            continue
        if not section or "=" not in line:
            raise TrustError("Resolved configuration violates the renderer grammar")
        key, value = line.split("=", 1)
        if key not in _RESOLVED_KEYS or key in seen or not value or "\n" in value:
            raise TrustError("Resolved configuration violates the renderer grammar")
        if key not in {"DNS", "Domains"} and value not in {"yes", "no"}:
            raise TrustError("Resolved configuration has an invalid bounded value")
        seen.add(key)
    if not section or seen != _RESOLVED_KEYS:
        raise TrustError("Resolved configuration is incomplete")


def validate_coredns_corefile(payload: bytes) -> None:
    """Parse the exact bounded Corefile grammar emitted by the renderer."""
    stack: list[str] = []
    servers = 0
    for tokens in _token_lines(payload):
        if tokens == ["}"]:
            if not stack:
                raise TrustError("CoreDNS configuration blocks are unbalanced")
            stack.pop()
            continue
        if not stack:
            if len(tokens) != 2 or tokens[1] != "{" or _NAME.fullmatch(tokens[0]) is None:
                raise TrustError("CoreDNS configuration has an invalid server block")
            stack.append("server")
            servers += 1
            continue
        context, head = stack[-1], tokens[0]
        if context == "server":
            if head in {"log", "errors"} and len(tokens) == 1:
                continue
            if head in {"bind", "file", "cache"} and len(tokens) == 2:
                continue
            blocks = {
                "omada": (2, "omada"),
                "view": (3, "view"),
                "template": (5, "template"),
                "forward": (None, "forward"),
            }
            block = blocks.get(head)
            if block and tokens[-1] == "{" and (block[0] is None or len(tokens) == block[0]):
                stack.append(block[1])
                continue
        elif (
            context == "omada"
            and head
            in {
                "controller_url",
                "site",
                "username",
                "password",
                "resolve_clients",
                "resolve_devices",
                "resolve_dhcp_reservations",
                "stale_record_duration",
                "ignore_startup_errors",
            }
            and len(tokens) == 2
        ):
            continue
        elif context == "view" and head == "expr" and len(tokens) >= 2:
            continue
        elif context == "template" and (
            (head in {"match", "answer"} and len(tokens) >= 2)
            or (head == "fallthrough" and len(tokens) == 1)
        ):
            continue
        elif context == "forward" and head == "force_tcp" and len(tokens) == 1:
            continue
        raise TrustError("CoreDNS configuration violates the renderer grammar")
    if stack or servers == 0:
        raise TrustError("CoreDNS configuration blocks are incomplete")


def validate_caddyfile(payload: bytes) -> None:
    """Parse the exact bounded Caddyfile grammar emitted by the renderer."""
    stack: list[str] = []
    snippets: set[str] = set()
    imports: set[str] = set()
    blocks = 0
    for tokens in _token_lines(payload):
        if tokens == ["}"]:
            if not stack:
                raise TrustError("Caddy configuration blocks are unbalanced")
            stack.pop()
            continue
        if not stack:
            if tokens == ["{"]:
                stack.append("global")
            elif len(tokens) == 2 and tokens[1] == "{":
                snippet = _SNIPPET.fullmatch(tokens[0])
                if snippet is not None:
                    snippets.add(snippet.group(1))
                    stack.append("snippet")
                elif _NAME.fullmatch(tokens[0]) is not None:
                    stack.append("site")
                else:
                    raise TrustError("Caddy configuration has an invalid top-level block")
            else:
                raise TrustError("Caddy configuration has an invalid top-level block")
            blocks += 1
            continue
        context, head = stack[-1], tokens[0]
        if context == "global":
            if tokens == ["admin", "off"]:
                continue
            if tokens == ["storage", "file_system", "{"]:
                stack.append("storage")
                continue
        elif context == "storage" and head == "root" and len(tokens) == 2:
            continue
        elif context in {"snippet", "site"}:
            if head == "import" and len(tokens) == 2 and _IDENTIFIER.fullmatch(tokens[1]):
                imports.add(tokens[1])
                continue
            child_blocks = {
                ("header", 2): "header",
                ("tls", 2): "tls",
                ("forward_auth", 3): "forward-auth",
                ("handle", 2): "handle",
                ("handle", 3): "handle",
                ("reverse_proxy", 3): "reverse-proxy",
            }
            child = child_blocks.get((head, len(tokens)))
            if child and tokens[-1] == "{":
                stack.append(child)
                continue
            if (head == "tls" and len(tokens) == 2) or (head == "root" and len(tokens) == 3):
                continue
            if head.startswith("@") and len(tokens) >= 3 and tokens[1] == "path":
                continue
            if (head == "file_server" and len(tokens) == 1) or (
                (head == "respond" and len(tokens) in {2, 3})
                or (head == "redir" and len(tokens) == 3)
            ):
                continue
            if head == "reverse_proxy" and len(tokens) == 2:
                continue
            if head == "bind" and len(tokens) == 2:
                continue
        elif context == "header" and _HEADER.fullmatch(head) and len(tokens) >= 2:
            continue
        elif context == "tls":
            if tokens == ["dns", "desec", "{"]:
                stack.append("dns")
                continue
            if (head == "resolvers" and len(tokens) >= 2) or (
                head in {"propagation_delay", "propagation_timeout"} and len(tokens) == 2
            ):
                continue
        elif context == "dns" and head == "token" and len(tokens) == 2:
            continue
        elif context == "forward-auth" and (
            (head == "uri" and len(tokens) == 2) or (head == "copy_headers" and len(tokens) >= 2)
        ):
            continue
        elif context == "handle" and (
            (head == "try_files" and len(tokens) >= 3)
            or (head == "file_server" and len(tokens) == 1)
            or (head == "rewrite" and len(tokens) == 3)
        ):
            continue
        elif context == "reverse-proxy":
            if tokens == ["transport", "http", "{"]:
                stack.append("transport")
                continue
            if head == "header_up" and len(tokens) >= 3:
                continue
        elif context == "transport" and head == "tls_server_name" and len(tokens) == 2:
            continue
        raise TrustError(f"Caddy configuration violates the renderer grammar at {context}:{head}")
    if stack or blocks == 0 or not imports.issubset(snippets):
        raise TrustError("Caddy configuration blocks or imports are incomplete")


def _token_lines(payload: bytes) -> list[list[str]]:
    """Decode and tokenize a bounded text configuration without expanding values."""
    if (
        not payload
        or len(payload) > 1024 * 1024
        or b"\x00" in payload
        or not payload.endswith(b"\n")
    ):
        raise TrustError("Service configuration structure is invalid")
    try:
        text = payload.decode("utf-8")
        values: list[list[str]] = []
        for line in text.splitlines():
            lexer = shlex.shlex(line, posix=True)
            lexer.whitespace_split = True
            lexer.commenters = "#"
            tokens = list(lexer)
            if tokens:
                values.append(tokens)
        return values
    except (UnicodeError, ValueError):
        raise TrustError("Service configuration structure is invalid") from None
