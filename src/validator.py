"""Validation and error checking for url:user:password combo lines."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

# Regular expression to test if a string resembles a valid domain or IP address
DOMAIN_OR_IP_RE = re.compile(
    r"^(?:(?:[a-zA-Z0-9-]{1,63}\.)+[a-zA-Z]{2,63}|"  # Domain name
    r"(?:\d{1,3}\.){3}\d{1,3}|"                     # IPv4
    r"localhost)(?::\d{1,5})?$",                     # Optional port
    re.IGNORECASE
)

PORT_RE = re.compile(r"^\d{1,5}(?:/.*)?$")


@dataclass(slots=True)
class ValidationResult:
    is_valid: bool
    url: str = ""
    user: str = ""
    password: str = ""
    error_code: str = ""
    error_detail: str = ""
    raw_line: str = ""

    def formatted_line(self) -> str:
        """Returns normalized url:user:password string."""
        if not self.is_valid:
            return ""
        return f"{self.url}:{self.user}:{self.password}"


def _detect_delimiter(line: str) -> str:
    """Detects the primary delimiter (':', '|', ';', or '\t') used in the line."""
    for delim in ("|", ";", "\t"):
        if line.count(delim) >= 2:
            return delim
    return ":"


def _clean_url(raw_url: str) -> str:
    """Cleans up and standardizes a URL token."""
    url = raw_url.strip().strip("\"'<>[]()")
    return url


def is_plausible_url(url: str) -> bool:
    """Verifies that the URL has a plausible scheme, domain, or IP."""
    if not url or len(url) < 3:
        return False

    # Check for scheme like http:// or https:// or ftp://
    if "://" in url:
        try:
            parsed = urlparse(url)
            if parsed.scheme.lower() in ("http", "https", "ftp", "ftps", "ws", "wss", "sftp"):
                if parsed.netloc or parsed.path:
                    return True
        except Exception:
            pass

    # If scheme was omitted (e.g. site.com/path or site.com:8080)
    domain_part = url.split("/")[0].split("?")[0].split("#")[0].strip()
    if DOMAIN_OR_IP_RE.match(domain_part):
        return True

    # Check if host contains at least one dot and valid chars
    if "." in domain_part and len(domain_part) >= 4:
        return True

    return False


def _parse_colon_line(line: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Intelligently parses a line into (url, user, password) handling URL colons and ports."""
    # Check if starts with a scheme like http:// or https://
    scheme_match = re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", line)
    
    if scheme_match:
        scheme_end = scheme_match.end()
        # Look for the first colon after the scheme
        rest = line[scheme_end:]
        colon_idx = rest.find(":")
        if colon_idx == -1:
            return None, None, None
        
        token_after = rest[colon_idx + 1:]
        # Check if the token after colon is a port number (e.g., 8080, 80/path)
        next_colon_idx = token_after.find(":")
        if next_colon_idx != -1:
            potential_port = token_after[:next_colon_idx]
            if PORT_RE.match(potential_port):
                # This colon was a port in the URL! Advance past the port
                url = line[: scheme_end + colon_idx + 1 + next_colon_idx]
                after_url = token_after[next_colon_idx + 1:]
            else:
                url = line[: scheme_end + colon_idx]
                after_url = token_after
        else:
            url = line[: scheme_end + colon_idx]
            after_url = token_after
            
        # Now after_url contains `user:password...`
        user_colon_idx = after_url.find(":")
        if user_colon_idx == -1:
            return None, None, None
        
        user = after_url[:user_colon_idx]
        password = after_url[user_colon_idx + 1:]
        return url, user, password

    # If line does not have a scheme (e.g. site.com:8080:user:pass or site.com:user:pass)
    first_colon = line.find(":")
    if first_colon == -1:
        return None, None, None
    
    token1 = line[:first_colon]
    rem1 = line[first_colon + 1:]
    second_colon = rem1.find(":")
    if second_colon == -1:
        return None, None, None
    
    token2 = rem1[:second_colon]
    rem2 = rem1[second_colon + 1:]
    
    # Check if token2 is a port
    if PORT_RE.match(token2):
        third_colon = rem2.find(":")
        if third_colon == -1:
            return None, None, None
        url = f"{token1}:{token2}"
        user = rem2[:third_colon]
        password = rem2[third_colon + 1:]
        return url, user, password
    else:
        url = token1
        user = token2
        password = rem2
        return url, user, password


def validate_ulp_line(raw_line: str) -> ValidationResult:
    """Validates and parses a single line expecting `url:user:password` format."""
    line = raw_line.strip()
    if not line:
        return ValidationResult(
            is_valid=False,
            error_code="EMPTY_LINE",
            error_detail="Line is empty or whitespace only",
            raw_line=raw_line
        )

    # Check for binary corruption / null bytes
    if "\x00" in line:
        return ValidationResult(
            is_valid=False,
            error_code="BINARY_CORRUPTION",
            error_detail="Line contains null bytes or binary characters",
            raw_line=raw_line
        )

    delim = _detect_delimiter(line)

    if delim != ":":
        parts = [p.strip() for p in line.split(delim)]
        if len(parts) < 3:
            return ValidationResult(
                is_valid=False,
                error_code="TOO_FEW_FIELDS",
                error_detail=f"Expected 3 fields (url{delim}user{delim}pass), found {len(parts)}",
                raw_line=raw_line
            )
        url = parts[0]
        user = parts[1]
        password = delim.join(parts[2:])
    else:
        url, user, password = _parse_colon_line(line)
        if url is None:
            return ValidationResult(
                is_valid=False,
                error_code="TOO_FEW_FIELDS",
                error_detail="Line does not contain enough ':' delimiters for url:user:password",
                raw_line=raw_line
            )

    url = _clean_url(url)
    user = user.strip()
    password = password.strip()

    if not url:
        return ValidationResult(
            is_valid=False,
            error_code="EMPTY_URL",
            error_detail="URL field is empty",
            raw_line=raw_line
        )

    if not is_plausible_url(url):
        return ValidationResult(
            is_valid=False,
            error_code="INVALID_URL",
            error_detail=f"URL '{url}' is not a valid domain or web address",
            raw_line=raw_line
        )

    if not user:
        return ValidationResult(
            is_valid=False,
            error_code="EMPTY_USER",
            error_detail="User/login field is empty",
            raw_line=raw_line
        )

    if not password:
        return ValidationResult(
            is_valid=False,
            error_code="EMPTY_PASSWORD",
            error_detail="Password field is empty",
            raw_line=raw_line
        )

    # Valid!
    return ValidationResult(
        is_valid=True,
        url=url,
        user=user,
        password=password,
        raw_line=raw_line
    )
