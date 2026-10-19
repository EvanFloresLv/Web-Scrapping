"""Immutable value objects for the websites domain (spec 0002, AC-3, AC-7).

`CanonicalHost` and `CanonicalURL` are the one place canonicalization lives.
Every writer in the domain produces canonical values through these; every DB
row stores the canonical form only. The invariants here are load bearing for
dedup (AC-4), host match (AC-5), and partial unique indexes (AC-12).

Canonicalization rules applied (RFC 3986 section 6 syntax-based normalization
plus the feature-specific additions pinned in spec 0002):

- lowercase scheme
- lowercase host, IDN punycode via stdlib `encodings.idna`
- strip default port (`:80` for http, `:443` for https)
- drop fragment
- resolve dot-segments in the path (`/a/./b/../c` -> `/a/c`)
- reject userinfo (`user:pass@`) with ValidationError
- reject non-`http`/`https` schemes with ValidationError

Path case, query, and percent-encoding are preserved as submitted (no case
folding of path, no query sorting, no query stripping). The transforms are
idempotent: a value already in canonical form passes through unchanged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

_ALLOWED_SCHEMES: frozenset[str] = frozenset({"http", "https"})
_DEFAULT_PORTS: dict[str, int] = {"http": 80, "https": 443}

_MAX_HOST_LENGTH = 253
_MAX_LABEL_LENGTH = 63
_MAX_URL_LENGTH = 2048

# DNS label: letters/digits/hyphens, no leading or trailing hyphen, 1..63 chars.
_LABEL_RE = re.compile(r"^(?!-)[A-Za-z0-9-]{1,63}(?<!-)$")


class ValidationError(ValueError):
    """Raised when input cannot be canonicalized into a valid host or URL.

    Services translate this into a Problem Details response (`422`,
    `code=validation_error` by default; the router may override with a
    domain-specific code when the context asks for it).
    """

    def __init__(self, message: str, *, code: str = "validation_error") -> None:
        super().__init__(message)
        self.code = code


def _strip_port_suffix(host_with_optional_port: str) -> str:
    """Drop a trailing `:port` from a bare authority segment, if present."""
    if ":" in host_with_optional_port and not host_with_optional_port.startswith("["):
        return host_with_optional_port.rsplit(":", 1)[0]
    return host_with_optional_port


def _validate_dns_hostname(host: str) -> None:
    """Enforce syntactic DNS hostname rules (AC-7).

    Called on the already-canonicalized ASCII form, so each label is at most
    63 bytes of letters/digits/hyphens.
    """
    if not host:
        raise ValidationError("host is empty")
    if len(host) > _MAX_HOST_LENGTH:
        raise ValidationError(f"host exceeds {_MAX_HOST_LENGTH} characters")
    labels = host.split(".")
    if not labels or any(label == "" for label in labels):
        raise ValidationError("host contains an empty label")
    for label in labels:
        if len(label) > _MAX_LABEL_LENGTH:
            raise ValidationError(f"host label exceeds {_MAX_LABEL_LENGTH} characters")
        if not _LABEL_RE.match(label):
            raise ValidationError(f"host label {label!r} is not a valid DNS label")


def _canonicalize_host(host: str) -> str:
    """Lowercase + IDN punycode the host; raise ValidationError on bad input."""
    stripped = host.strip()
    if not stripped:
        raise ValidationError("host is empty")
    without_port = _strip_port_suffix(stripped)
    if not without_port:
        raise ValidationError("host is empty")
    lowered = without_port.lower()
    try:
        encoded = lowered.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValidationError(f"host is not valid IDN: {exc}") from exc
    _validate_dns_hostname(encoded)
    return encoded


def _resolve_dot_segments(path: str) -> str:
    """Resolve `.` and `..` segments per RFC 3986 section 5.2.4.

    `urllib.parse` does not do this on its own; the loop below mirrors the
    reference algorithm closely enough for the inputs this feature accepts.
    """
    if not path:
        return path
    leading_slash = path.startswith("/")
    trailing_slash = path.endswith("/")
    segments = path.split("/")
    output: list[str] = []
    for segment in segments:
        if segment in ("", "."):
            continue
        if segment == "..":
            if output:
                output.pop()
            continue
        output.append(segment)
    resolved = "/".join(output)
    if leading_slash:
        resolved = "/" + resolved
    if trailing_slash and (not leading_slash or output):
        resolved = resolved + "/"
    return resolved or ("/" if leading_slash else "")


@dataclass(frozen=True, slots=True)
class CanonicalHost:
    """A validated, canonical DNS hostname (ASCII, lowercase, IDN punycoded)."""

    value: str

    @classmethod
    def from_str(cls, raw: str) -> CanonicalHost:
        return cls(value=_canonicalize_host(raw))

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


@dataclass(frozen=True, slots=True)
class CanonicalURL:
    """A validated, canonical absolute http/https URL.

    `host` is already in canonical form (same rules as `CanonicalHost`), so a
    host match between a target URL and its parent website is a plain string
    compare (AC-5).
    """

    value: str
    scheme: str
    host: str

    @classmethod
    def from_str(cls, raw: str) -> CanonicalURL:
        if raw is None:  # pragma: no cover - defensive
            raise ValidationError("url is empty")
        stripped = raw.strip()
        if not stripped:
            raise ValidationError("url is empty")
        if len(stripped) > _MAX_URL_LENGTH:
            raise ValidationError(f"url exceeds {_MAX_URL_LENGTH} characters")

        try:
            parts = urlsplit(stripped)
        except ValueError as exc:
            raise ValidationError(f"url is not parseable: {exc}") from exc

        scheme = parts.scheme.lower()
        if scheme not in _ALLOWED_SCHEMES:
            raise ValidationError(f"scheme {parts.scheme!r} is not allowed; use http or https")

        if parts.username is not None or parts.password is not None:
            raise ValidationError("url must not include userinfo")

        if not parts.hostname:
            raise ValidationError("url has no host component")

        host = _canonicalize_host(parts.hostname)

        try:
            port = parts.port
        except ValueError as exc:
            raise ValidationError(f"url has an invalid port: {exc}") from exc

        netloc = host
        if port is not None and port != _DEFAULT_PORTS[scheme]:
            netloc = f"{host}:{port}"

        path = _resolve_dot_segments(parts.path or "")

        canonical = urlunsplit((scheme, netloc, path, parts.query, ""))
        if len(canonical) > _MAX_URL_LENGTH:
            raise ValidationError(f"canonical url exceeds {_MAX_URL_LENGTH} characters")

        return cls(value=canonical, scheme=scheme, host=host)

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value
