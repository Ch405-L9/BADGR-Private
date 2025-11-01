# tests/test_integration_discover.py
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
import tempfile
import yaml

from scripts.discover import GoogleCSEProvider, DuckDuckGoProvider, load_config, ensure_writable

@pytest.fixture
def google_cfg(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "fake")
    monkeypatch.setenv("GOOGLE_CSE_ID", "cx123")
    return {
        "enabled": True,
        "api_key_env": "GOOGLE_API_KEY",
        "cx_env": "GOOGLE_CSE_ID",
        "rate_limit_rps": 10.0,
        "retry_attempts": 3,
        "backoff_base_seconds": 0.001,
        "backoff_max_seconds": 0.002,
        "daily_quota_threshold": 2
    }

@pytest.fixture
def ddg_cfg():
    return {
        "enabled": True,
        "method": "scrape",
        "rate_limit_rps": 10.0,
        "retry_attempts": 2,
        "backoff_base_seconds": 0.001,
        "backoff_max_seconds": 0.002,
        "daily_quota_threshold": 2
    }

def test_google_query_success(google_cfg, monkeypatch):
    gp = GoogleCSEProvider(google_cfg)

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {
        "items": [{"link": "https://One.com/a"}, {"link": "https://two.com/b"}]
    }

    with patch("scripts.discover.requests.get", return_value=fake_resp) as pget:
        out = gp.query("kw", max_results=5)
    assert set(out) == {"https://One.com/a", "https://two.com/b"}
    assert gp.queries_made == 1

def test_google_query_429_then_ok(google_cfg, monkeypatch):
    gp = GoogleCSEProvider(google_cfg)

    resp_429 = MagicMock(); resp_429.status_code = 429
    resp_ok = MagicMock(); resp_ok.status_code = 200; resp_ok.json.return_value = {"items":[{"link":"https://a.com"}]}

    seq = [resp_429, resp_ok]
    def side_effect(*args, **kwargs):
        return seq.pop(0)

    with patch("scripts.discover.requests.get", side_effect=side_effect):
        out = gp.query("kw", max_results=1)
    assert out == ["https://a.com"]
    assert gp.queries_made == 1

def test_ddg_query_success(ddg_cfg, monkeypatch):
    dp = DuckDuckGoProvider(ddg_cfg)

    class FakeDDGS:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def text(self, keyword, max_results=10):
            return [{"href": "https://x.com/a"}, {"href": "https://y.com/b"}]

    with patch("scripts.discover.DDGS", FakeDDGS):
        out = dp.query("kw", max_results=5)
    assert set(out) == {"https://x.com/a", "https://y.com/b"}
    assert dp.queries_made == 1

def test_quota_enforced(google_cfg, monkeypatch):
    google_cfg["daily_quota_threshold"] = 1
    gp = GoogleCSEProvider(google_cfg)

    ok = MagicMock(); ok.status_code = 200; ok.json.return_value = {"items":[{"link":"https://a.com"}]}

    with patch("scripts.discover.requests.get", return_value=ok):
        out1 = gp.query("one", max_results=1)
        out2 = gp.query("two", max_results=1)  # should be blocked by can_continue
    assert out1 == ["https://a.com"]
    assert out2 == []  # second attempt ignored
    assert gp.queries_made == 1

# NEW TESTS

def test_load_config_missing_file():
    """Should raise FileNotFoundError if config doesn't exist."""
    with pytest.raises(FileNotFoundError):
        load_config(Path("/nonexistent/config.yaml"))

def test_load_config_missing_keywords():
    """Should raise ValueError if keywords field missing."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        yaml.dump({"providers": {}}, f)
        f.flush()
        
        with pytest.raises(ValueError, match="missing 'keywords'"):
            load_config(Path(f.name))

def test_load_config_empty_keywords():
    """Should raise ValueError if keywords list is empty."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        yaml.dump({"keywords": []}, f)
        f.flush()
        
        with pytest.raises(ValueError, match="empty"):
            load_config(Path(f.name))

def test_load_config_keywords_not_list():
    """Should raise ValueError if keywords is not a list."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        yaml.dump({"keywords": "not a list"}, f)
        f.flush()
        
        with pytest.raises(ValueError, match="must be a list"):
            load_config(Path(f.name))

def test_ensure_writable_success(tmp_path):
    """Should successfully verify writability."""
    test_file = tmp_path / "subdir" / "output.txt"
    ensure_writable(test_file)  # Should not raise
    assert test_file.parent.exists()

def test_ensure_writable_permission_error(monkeypatch):
    """Should raise PermissionError if directory not writable."""
    def mock_touch():
        raise PermissionError("Mock permission denied")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        test_path = Path(tmpdir) / "test.txt"
        
        with patch.object(Path, 'touch', side_effect=mock_touch):
            with pytest.raises(PermissionError, match="Cannot write"):
                ensure_writable(test_path)

