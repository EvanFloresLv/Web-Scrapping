"""Unit tests for CanonicalHost / CanonicalURL (spec 0002, AC-3 + AC-7 shape).

Pure functions over inputs; no DB, no network. Each test is tagged with the
acceptance criterion it covers so the suite traces back to spec 0002.
"""

from __future__ import annotations

import pytest

from app.domains.websites.value_objects import (
    CanonicalHost,
    CanonicalURL,
    ValidationError,
)

# ---------- CanonicalHost (AC-3, AC-7) --------------------------------------


class TestCanonicalHost:
    def test_lowercases_mixed_case_host(self) -> None:
        """covers: AC-3 (lowercase host)."""
        assert CanonicalHost.from_str("Example.COM").value == "example.com"

    def test_strips_default_port_suffix(self) -> None:
        """covers: AC-3 (strip :port on bare host input)."""
        assert CanonicalHost.from_str("Example.COM:443").value == "example.com"

    def test_strips_nondefault_port_suffix(self) -> None:
        """covers: AC-3. The stored host is bare; port lives only on URLs."""
        assert CanonicalHost.from_str("example.com:8080").value == "example.com"

    def test_idn_punycoded(self) -> None:
        """covers: AC-3 (IDN -> punycode)."""
        assert CanonicalHost.from_str("Bücher.example").value == "xn--bcher-kva.example"

    def test_already_punycoded_is_idempotent(self) -> None:
        """covers: AC-3 (canonicalization is idempotent)."""
        encoded = "xn--bcher-kva.example"
        assert CanonicalHost.from_str(encoded).value == encoded

    def test_empty_host_rejected(self) -> None:
        """covers: AC-7 (empty host)."""
        with pytest.raises(ValidationError):
            CanonicalHost.from_str("")

    def test_whitespace_only_host_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CanonicalHost.from_str("   ")

    def test_host_over_253_chars_rejected(self) -> None:
        """covers: AC-7 (host length)."""
        label = "a" * 50
        too_long = ".".join([label] * 6)  # 6*50 + 5 dots = 305 chars
        with pytest.raises(ValidationError):
            CanonicalHost.from_str(too_long)

    def test_label_over_63_chars_rejected(self) -> None:
        """covers: AC-7 (per-label length)."""
        with pytest.raises(ValidationError):
            CanonicalHost.from_str("a" * 64 + ".example")

    def test_leading_hyphen_label_rejected(self) -> None:
        """covers: AC-7 (DNS label syntax)."""
        with pytest.raises(ValidationError):
            CanonicalHost.from_str("-bad.example")

    def test_trailing_hyphen_label_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CanonicalHost.from_str("bad-.example")

    def test_empty_label_rejected(self) -> None:
        """A doubled dot leaves an empty label."""
        with pytest.raises(ValidationError):
            CanonicalHost.from_str("foo..example")

    def test_underscore_rejected(self) -> None:
        """covers: AC-7 (letters/digits/hyphens only)."""
        with pytest.raises(ValidationError):
            CanonicalHost.from_str("under_score.example")


# ---------- CanonicalURL (AC-3, AC-7) ---------------------------------------


class TestCanonicalURL:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            # covers: AC-3 (lowercase scheme + host, drop fragment, strip default port)
            ("HTTPS://Example.COM:443/p/1#top", "https://example.com/p/1"),
            # covers: AC-3 (dot-segment resolution)
            (
                "HTTPS://Canon.Example:443/a/./b/../c#frag",
                "https://canon.example/a/c",
            ),
            # covers: AC-3 (http default port :80 is stripped too)
            ("http://example.com:80/", "http://example.com/"),
            # covers: AC-3 (nondefault port is preserved)
            ("https://example.com:8443/x", "https://example.com:8443/x"),
            # covers: AC-3 (query is preserved as submitted)
            ("https://example.com/x?B=2&a=1", "https://example.com/x?B=2&a=1"),
            # covers: AC-3 (path case is preserved; only host/scheme are lowered)
            ("https://Example.com/API/v1", "https://example.com/API/v1"),
            # covers: AC-3 (IDN host in URL -> punycode)
            ("https://Bücher.example/", "https://xn--bcher-kva.example/"),
        ],
    )
    def test_canonicalization(self, raw: str, expected: str) -> None:
        assert CanonicalURL.from_str(raw).value == expected

    def test_host_attribute_matches_canonical_host(self) -> None:
        """covers: AC-5. Host-match on target is a plain string compare."""
        url = CanonicalURL.from_str("HTTPS://Example.COM/p")
        assert url.host == "example.com"
        assert url.scheme == "https"

    def test_already_canonical_is_idempotent(self) -> None:
        """covers: AC-3 (idempotence)."""
        canonical = "https://example.com/p/1"
        assert CanonicalURL.from_str(canonical).value == canonical

    def test_ftp_scheme_rejected(self) -> None:
        """covers: AC-7 (http/https only)."""
        with pytest.raises(ValidationError):
            CanonicalURL.from_str("ftp://example.com/x")

    def test_file_scheme_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CanonicalURL.from_str("file:///etc/passwd")

    def test_userinfo_rejected(self) -> None:
        """covers: AC-3 (reject userinfo)."""
        with pytest.raises(ValidationError):
            CanonicalURL.from_str("https://user:pass@example.com/x")

    def test_empty_url_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CanonicalURL.from_str("")

    def test_whitespace_only_url_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CanonicalURL.from_str("   ")

    def test_no_host_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CanonicalURL.from_str("https:///path")

    def test_url_over_2048_chars_rejected(self) -> None:
        """covers: AC-7 (max url length)."""
        with pytest.raises(ValidationError):
            CanonicalURL.from_str("https://example.com/" + "a" * 2048)
