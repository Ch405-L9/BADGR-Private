# tests/test_discover.py
import json
import time
from pathlib import Path
import types
import pytest

from scripts.discover import (
    RateLimiter, normalize_domain, unique_sorted, parse_crawl_delay, 
    backoff_delays, is_valid_domain, sanitize_error
)

def test_rate_limiter_no_wait(monkeypatch):
    rl = RateLimiter(0.0)
    called = {"n": 0}
    def fake_sleep(x):
        called["n"] += 1
    monkeypatch.setattr(time, "sleep", fake_sleep)
    rl.wait()
    assert called["n"] == 0

def test_rate_limiter_with_wait(monkeypatch):
    rl = RateLimiter(2.0, jitter_pct=0)  # 2 rps -> 0.5s
    slept = {"val": None}
    def fake_sleep(x):
        slept["val"] = x
    monkeypatch.setattr(time, "sleep", fake_sleep)
    rl.wait()
    assert slept["val"] == pytest.approx(0.5, rel=0.15)

@pytest.mark.parametrize("raw,expect", [
    ("https://Example.com/path", "example.com"),
    ("http://www.Example.org:443", "example.org"),
    ("EXAMPLE.net", "example.net"),
    ("", ""),
])
def test_normalize_domain(raw, expect):
    assert normalize_domain(raw) == expect

def test_unique_sorted():
    out = unique_sorted(["https://a.com/x", "A.com", "b.com", "www.b.com"])
    assert out == ["a.com", "b.com"]

def test_parse_crawl_delay():
    txt = """
    User-agent: *
    Disallow:
    Crawl-delay: 2.5
    """
    assert parse_crawl_delay(txt) == 2.5
    assert parse_crawl_delay("User-agent: *\nDisallow: /") is None

def test_backoff_delays():
    # attempts=3 -> two delays: 0.5, 1.0; capped at 2.0
    assert backoff_delays(0.5, 2.0, attempts=3) == [0.5, 1.0]

# NEW TESTS

@pytest.mark.parametrize("domain,expected", [
    ("example.com", True),
    ("sub.example.co.uk", True),
    ("localhost", False),
    ("127.0.0.1", False),
    ("0.0.0.0", False),
    ("192.168.1.1", False),
    ("", False),
    ("a" * 254, False),  # Too long
    ("no-tld", False),
    ("example", False),
])
def test_is_valid_domain(domain, expected):
    assert is_valid_domain(domain) == expected

def test_sanitize_error():
    msg = "Error: key=sk_test_123456 and token=abc_xyz_789"
    result = sanitize_error(msg)
    assert "sk_test_123456" not in result
    assert "abc_xyz_789" not in result
    assert "key=***" in result
    assert "token=***" in result

def test_sanitize_error_api_key():
    msg = "Failed with api_key=AKIA_REDACTED"
    result = sanitize_error(msg)
    assert "AKIA_REDACTED" not in result
    assert "api_key=***" in result

def APIKEY_REDACTED():
    """Should filter out invalid domains."""
    domains = [
        "https://valid.com",
        "https://localhost",
        "http://127.0.0.1",
        "invalid",
        "also-valid.org"
    ]
    result = unique_sorted(domains)
    assert result == ["also-valid.org", "valid.com"]

