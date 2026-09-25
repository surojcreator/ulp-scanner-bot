"""Unit tests for validator.py."""

from __future__ import annotations

import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.validator import validate_ulp_line


def test_valid_standard_lines():
    res = validate_ulp_line("https://example.com/login:john_doe:Secret123")
    assert res.is_valid
    assert res.url == "https://example.com/login"
    assert res.user == "john_doe"
    assert res.password == "Secret123"
    assert res.formatted_line() == "https://example.com/login:john_doe:Secret123"


def test_valid_with_email_and_port():
    res = validate_ulp_line("http://192.168.1.1:8080:admin@domain.com:P@ss:w0rd!")
    assert res.is_valid
    assert res.url == "http://192.168.1.1:8080"
    assert res.user == "admin@domain.com"
    assert res.password == "P@ss:w0rd!"


def test_valid_domain_without_scheme():
    res = validate_ulp_line("myportal.company.org:alice:superSecret!")
    assert res.is_valid
    assert res.url == "myportal.company.org"
    assert res.user == "alice"


def test_pipe_delimiter():
    res = validate_ulp_line("https://site.com|user123|mypassword")
    assert res.is_valid
    assert res.url == "https://site.com"
    assert res.user == "user123"
    assert res.password == "mypassword"
    assert res.formatted_line() == "https://site.com:user123:mypassword"


def test_complex_password_with_colons():
    res = validate_ulp_line("https://site.com:test_user:pass:with:several:colons:123")
    assert res.is_valid
    assert res.url == "https://site.com"
    assert res.user == "test_user"
    assert res.password == "pass:with:several:colons:123"


def test_semicolon_and_tab_delimiter():
    res1 = validate_ulp_line("domain.com;user1;pass1")
    assert res1.is_valid
    assert res1.user == "user1"

    res2 = validate_ulp_line("domain.com\tuser2\tpass2")
    assert res2.is_valid
    assert res2.user == "user2"


def test_error_too_few_fields():
    res = validate_ulp_line("user:password")
    assert not res.is_valid
    assert res.error_code == "TOO_FEW_FIELDS"


def test_error_empty_line():
    res = validate_ulp_line("   \n")
    assert not res.is_valid
    assert res.error_code == "EMPTY_LINE"


def test_error_missing_password():
    res = validate_ulp_line("https://site.com:user:")
    assert not res.is_valid
    assert res.error_code == "EMPTY_PASSWORD"


def test_error_missing_user():
    res = validate_ulp_line("https://site.com::password")
    assert not res.is_valid
    assert res.error_code == "EMPTY_USER"


def test_error_invalid_url():
    res = validate_ulp_line("notaurl:user:pass")
    assert not res.is_valid
    assert res.error_code == "INVALID_URL"


def test_error_binary_null_bytes():
    res = validate_ulp_line("https://site.com:user\x00name:pass")
    assert not res.is_valid
    assert res.error_code == "BINARY_CORRUPTION"


if __name__ == "__main__":
    test_valid_standard_lines()
    test_valid_with_email_and_port()
    test_valid_domain_without_scheme()
    test_pipe_delimiter()
    test_complex_password_with_colons()
    test_semicolon_and_tab_delimiter()
    test_error_too_few_fields()
    test_error_empty_line()
    test_error_missing_password()
    test_error_missing_user()
    test_error_invalid_url()
    test_error_binary_null_bytes()
    print("All validator tests passed!")
