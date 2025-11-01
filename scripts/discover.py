#!/usr/bin/env python3
"""
scripts/discover.py

Discovery stage script for Agentik LeadGen-Audit pipeline.
- GoogleCSEProvider: real HTTP API calls to Google Custom Search JSON API
- DuckDuckGoProvider: results via duckduckgo_search (respects DDG robots)
- Rate limiting with jitter
- Exponential backoff (429/503/timeout): 0.5 → 1 → 2 → 4 → 8s (cap)
- Quota/threshold per provider (daily_quota_threshold)
- robots.txt fetch + Crawl-delay parse for DDG host before queries
- max-results per keyword per provider
- Structured logging (JSON) with collected_at, queries_made, provider usage summary
"""

from __future__ import annotations
import argparse
import json
import os
import sys
import time
import random
import socket
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
from pathlib import Path
import logging
import datetime as dt

import yaml
import requests

try:
    from duckduckgo_search import DDGS
except Exception:
    DDGS = None

# ---------- Logging (structured JSON to stdout) ----------
class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = {
            "timestamp": dt.datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "message": record.getMessage(),
        }
        # merge extras if present
        for k, v in getattr(record, "__dict__", {}).items():
            if k in ("args", "msg", "exc_info", "exc_text", "stack_info", "relativeCreated",
                     "created", "msecs", "levelno", "levelname", "name", "pathname", "filename",
                     "module", "lineno", "funcName", "processName", "process", "threadName", "thread"):
                continue
            if k not in base and not k.startswith("_"):
                base[k] = v
        return json.dumps(base, ensure_ascii=False)

logger = logging.getLogger("agentik.discover")
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(JsonFormatter())
logger.addHandler(handler)
logger.setLevel(logging.INFO)

# ---------- Helpers ----------
def now_utc() -> str:
    return dt.datetime.utcnow().isoformat() + "Z"

def sanitize_error(msg: str) -> str:
    """Remove potential secrets from error messages."""
    patterns = [
        (r'key[=:]\s*[\w-]+', 'key=***'),
        (r'token[=:]\s*[\w-]+', 'token=***'),
        (r'cx[=:]\s*[\w-]+', 'cx=***'),
        (r'api[_-]?key[=:]\s*[\w-]+', 'api_key=***'),
    ]
    for pattern, repl in patterns:
        msg = re.sub(pattern, repl, msg, flags=re.I)
    return msg

def normalize_domain(raw: str) -> str:
    d = (raw or "").strip()
    d = d.split("//", 1)[-1]  # remove scheme if present
    d = d.split("/", 1)[0]    # keep host
    d = d.split(":", 1)[0]    # drop port
    d = d.lower()
    if d.startswith("www."):
        d = d[4:]
    return d

def is_valid_domain(domain: str) -> bool:
    """Validate domain is safe to process."""
    if not domain or len(domain) > 253:
        return False
    # Block localhost/internal
    if domain in ("localhost", "127.0.0.1", "0.0.0.0", "::1"):
        return False
    # Block IP addresses
    if re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', domain):
        return False
    # Must have valid TLD
    if not re.match(r'^[a-z0-9.-]+\.[a-z]{2,}$', domain):
        return False
    return True

def unique_sorted(domains: Iterable[str]) -> List[str]:
    normalized = {normalize_domain(d) for d in domains if normalize_domain(d)}
    valid = {d for d in normalized if is_valid_domain(d)}
    return sorted(valid)

def parse_crawl_delay(robots_txt: str) -> Optional[float]:
    # simple heuristic: look for lines like "Crawl-delay: 3"
    for line in robots_txt.splitlines():
        if re.match(r"(?i)\s*crawl-?delay\s*:\s*[0-9.]+", line):
            try:
                return float(re.sub(r"(?i)\s*crawl-?delay\s*:\s*", "", line).strip())
            except Exception:
                return None
    return None

def fetch_robots_and_delay(host: str, ua: str = "Agentik-LeadGen-Discover/1.0") -> Tuple[bool, Optional[float]]:
    """Return (allowed, crawl_delay_seconds). If robots fetch fails, default allow=True."""
    try:
        url = f"https://{host}/robots.txt"
        resp = requests.get(url, headers={"User-Agent": ua}, timeout=6)
        if resp.status_code != 200:
            return True, None
        txt = resp.text or ""
        delay = parse_crawl_delay(txt)
        return True, delay
    except Exception:
        return True, None

def backoff_delays(base: float, max_s: float, attempts: int) -> List[float]:
    delays = []
    cur = base
    for _ in range(max(0, attempts - 1)):
        delays.append(cur)
        cur = min(max_s, cur * 2.0)
    return delays

@dataclass
class RateLimiter:
    rps: float
    jitter_pct: float = 0.0

    def wait(self):
        if self.rps <= 0:
            return
        interval = 1.0 / self.rps
        jitter = interval * (self.jitter_pct / 100.0)
        delay = interval + random.uniform(-jitter, jitter)
        if delay > 0:
            time.sleep(delay)

# ---------- Providers ----------
class BaseProvider:
    def __init__(self, name: str, cfg: Dict[str, Any]):
        self.name = name
        self.cfg = cfg or {}
        self.queries_made = 0
        self.daily_quota_threshold = int(self.cfg.get("daily_quota_threshold", 10**9))

        # rate limiting + backoff
        self.rate_limit_rps = float(self.cfg.get("rate_limit_rps", 0.5))
        self.jitter_percent = float(self.cfg.get("jitter_percent", 20))
        self.retry_attempts = int(self.cfg.get("retry_attempts", 3))
        self.backoff_base_seconds = float(self.cfg.get("backoff_base_seconds", 0.5))
        self.backoff_max_seconds = float(self.cfg.get("backoff_max_seconds", 8.0))

        self._limiter = RateLimiter(self.rate_limit_rps, self.jitter_percent)

    def can_continue(self) -> bool:
        return self.queries_made < self.daily_quota_threshold

    def _sleep_limiter(self):
        self._limiter.wait()

    def _delays(self) -> List[float]:
        return backoff_delays(self.backoff_base_seconds, self.backoff_max_seconds, self.retry_attempts)

    def query(self, keyword: str, max_results: int) -> List[str]:
        raise NotImplementedError

class GoogleCSEProvider(BaseProvider):
    def __init__(self, cfg: Dict[str, Any]):
        super().__init__("google_cse", cfg)
        self.api_key = os.getenv(self.cfg.get("api_key_env", "GOOGLE_API_KEY"), "")
        self.cx = os.getenv(self.cfg.get("cx_env", "GOOGLE_CSE_ID"), "")
        self.safe = "active"
        if not self.api_key or not self.cx:
            logger.warning("GoogleCSEProvider missing API key or CX; provider will return empty results.",
                           extra={"provider": self.name, "collected_at": now_utc()})

    def query(self, keyword: str, max_results: int) -> List[str]:
        if not self.can_continue():
            return []

        if not (self.api_key and self.cx):
            self.queries_made += 1
            return []

        results: List[str] = []
        per_page = 10
        start_index = 1
        delays = self._delays()

        while len(results) < max_results and start_index <= 91:
            self._sleep_limiter()  # FIX: Rate limit before each page request
            
            params = {
                "key": self.api_key,
                "cx": self.cx,
                "q": keyword,
                "num": min(per_page, max_results - len(results)),
                "safe": self.safe,
                "start": start_index,
            }
            attempt = 0
            while True:
                attempt += 1
                try:
                    resp = requests.get(
                        "https://www.googleapis.com/customsearch/v1",
                        params=params,
                        timeout=12,
                    )
                    code = resp.status_code
                    if code == 200:
                        data = resp.json() or {}
                        items = data.get("items") or []
                        for it in items:
                            link = it.get("link") or it.get("formattedUrl")
                            if not link:
                                continue
                            results.append(link)
                        logger.info(
                            "google results",
                            extra={
                                "provider": self.name,
                                "keyword": keyword,
                                "collected_at": now_utc(),
                                "delay_used": round(1.0 / self.rate_limit_rps if self.rate_limit_rps else 0, 3),
                                "domains_returned": len(items),
                                "error_code": None,
                                "fallback": False,
                                "queries_made": self.queries_made + 1,
                            },
                        )
                        break
                    elif code in (429, 503):
                        idx = min(attempt - 1, len(delays) - 1)
                        if idx >= 0 and idx < len(delays):
                            time.sleep(delays[idx])
                            continue
                        else:
                            logger.warning(
                                f"google backoff exhausted ({code})",
                                extra={"provider": self.name, "keyword": keyword, "error_code": code, "collected_at": now_utc()},
                            )
                            break
                    else:
                        logger.warning(
                            "google non-200",
                            extra={"provider": self.name, "keyword": keyword, "error_code": code, "collected_at": now_utc()},
                        )
                        break
                except (requests.Timeout, requests.ConnectionError, socket.timeout) as e:
                    idx = min(attempt - 1, len(delays) - 1)
                    if idx >= 0 and idx < len(delays):
                        time.sleep(delays[idx])
                        continue
                    logger.warning(
                        "google network error",
                        extra={"provider": self.name, "keyword": keyword, "error_code": "timeout/conn", "collected_at": now_utc()},
                    )
                    break
                except Exception as e:
                    logger.warning(
                        "google unknown error",
                        extra={"provider": self.name, "keyword": keyword, "error_code": sanitize_error(str(e)[:120]), "collected_at": now_utc()},
                    )
                    break

            if len(results) >= max_results:
                break
            start_index += per_page

        self.queries_made += 1
        return results[:max_results]

class DuckDuckGoProvider(BaseProvider):
    """
    Uses duckduckgo_search library (not raw scraping of DDG HTML).
    Still consults DDG robots.txt for politeness and Crawl-delay.
    """
    DDG_HOST = "duckduckgo.com"

    def __init__(self, cfg: Dict[str, Any]):
        super().__init__("duckduckgo", cfg)
        self.method = self.cfg.get("method", "scrape")
        self.ua = "Agentik-LeadGen-Discover/1.0 (+https://github.com/Ch405-L9/BADGR-Private)"
        allowed, delay = fetch_robots_and_delay(self.DDG_HOST, ua=self.ua)
        self.ddg_allowed = allowed
        self.ddg_crawl_delay = delay

    def _respect_ddg_delay(self):
        if self.ddg_crawl_delay and self.ddg_crawl_delay > 0:
            time.sleep(self.ddg_crawl_delay)

    def query(self, keyword: str, max_results: int) -> List[str]:
        if not self.can_continue():
            return []
        if DDGS is None:
            logger.warning("duckduckgo_search not available; returning empty.", extra={"provider": self.name, "collected_at": now_utc()})
            self.queries_made += 1
            return []

        self._sleep_limiter()
        self._respect_ddg_delay()

        results: List[str] = []
        delays = self._delays()

        attempt = 0
        while True:
            attempt += 1
            try:
                with DDGS() as ddgs:
                    for r in ddgs.text(keyword, max_results=max_results):
                        url = r.get("href") or r.get("link") or r.get("url")
                        if url:
                            results.append(url)
                logger.info(
                    "ddg results",
                    extra={
                        "provider": self.name,
                        "keyword": keyword,
                        "collected_at": now_utc(),
                        "delay_used": round(1.0 / self.rate_limit_rps if self.rate_limit_rps else 0, 3),
                        "domains_returned": len(results),
                        "error_code": None,
                        "fallback": False,
                        "queries_made": self.queries_made + 1,
                        "robots_respected": True,
                        "crawl_delay": self.ddg_crawl_delay or 0,
                    },
                )
                break
            except Exception as e:
                if attempt <= len(delays):
                    time.sleep(delays[attempt - 1])
                    continue
                logger.warning(
                    "ddg error",
                    extra={"provider": self.name, "keyword": keyword, "error_code": sanitize_error(str(e)[:120]), "collected_at": now_utc()},
                )
                break

        self.queries_made += 1
        return results[:max_results]

# ---------- Config ----------
def load_config(path: Path) -> Dict[str, Any]:
    """Load and validate YAML config."""
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    
    with path.open("r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    
    # Validate required fields
    if "keywords" not in cfg or cfg.get("keywords") is None:
        raise ValueError("Config missing 'keywords' field")
    if not isinstance(cfg["keywords"], list):
        raise ValueError("'keywords' must be a list")
    if not cfg["keywords"]:
        raise ValueError("'keywords' list is empty")
    
    return cfg

def ensure_writable(path: Path) -> None:
    """Ensure output path is writable."""
    path.parent.mkdir(parents=True, exist_ok=True)
    test_file = path.parent / ".write_test"
    try:
        test_file.touch()
        test_file.unlink()
    except Exception as e:
        raise PermissionError(f"Cannot write to {path.parent}: {e}")

# ---------- Main ----------
def main():
    p = argparse.ArgumentParser(description="Agentik – Discovery phase")
    p.add_argument("--config", type=Path, required=True, help="Path to manifest/config YAML")
    p.add_argument("--output", type=Path, required=True, help="Path to domains output txt")
    p.add_argument("--provider", type=str, choices=["google","duckduckgo","all"], default="all",
                   help="Which provider(s) to use")
    p.add_argument("--max-results", type=int, default=100, help="Max domains PER KEYWORD PER PROVIDER")
    p.add_argument("--dry-run", action="store_true", help="Validate config without running queries")
    p.add_argument("--verbose", action="store_true", help="Enable verbose logs")
    args = p.parse_args()

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    try:
        cfg = load_config(args.config)
    except Exception as e:
        logger.error(f"Config load failed: {sanitize_error(str(e))}", extra={"collected_at": now_utc()})
        sys.exit(2)

    keywords = cfg.get("keywords") or []
    providers_cfg = cfg.get("providers") or {}

    providers: List[BaseProvider] = []
    if args.provider in ("google", "all") and (providers_cfg.get("google_cse", {}).get("enabled", True)):
        providers.append(GoogleCSEProvider(providers_cfg.get("google_cse", {})))
    if args.provider in ("duckduckgo", "all") and (providers_cfg.get("duckduckgo", {}).get("enabled", True)):
        providers.append(DuckDuckGoProvider(providers_cfg.get("duckduckgo", {})))

    if not providers:
        logger.error("No providers enabled/selected", extra={"collected_at": now_utc()})
        sys.exit(3)

    # Dry-run validation
    if args.dry_run:
        logger.info("Dry-run: validating providers...", extra={"collected_at": now_utc()})
        for prov in providers:
            if isinstance(prov, GoogleCSEProvider):
                if not (prov.api_key and prov.cx):
                    logger.error("Google CSE: missing credentials (GOOGLE_API_KEY or GOOGLE_CSE_ID)")
                else:
                    logger.info("Google CSE: credentials present")
            elif isinstance(prov, DuckDuckGoProvider):
                if DDGS is None:
                    logger.warning("DuckDuckGo: duckduckgo_search library not installed")
                else:
                    logger.info("DuckDuckGo: library available")
        logger.info(f"Config valid: {len(keywords)} keywords, {len(providers)} providers")
        sys.exit(0)

    # Check output writability
    try:
        ensure_writable(args.output)
    except PermissionError as e:
        logger.error(f"Output not writable: {e}", extra={"collected_at": now_utc()})
        sys.exit(4)

    all_domains: Set[str] = set()
    provider_usage = {p.name: {"queries_made": 0, "domains": 0} for p in providers}

    for kw in keywords:
        for prov in providers:
            if not prov.can_continue():
                logger.info(f"{prov.name} quota reached; skipping",
                            extra={"provider": prov.name, "keyword": kw, "collected_at": now_utc()})
                continue
            res = prov.query(kw, max_results=args.max_results)
            nd = unique_sorted(res)
            all_domains.update(nd)

            provider_usage[prov.name]["queries_made"] = prov.queries_made
            provider_usage[prov.name]["domains"] += len(nd)

    out_list = sorted(all_domains)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        for d in out_list:
            f.write(d + "\n")

    logger.info(
        "discovery summary",
        extra={
            "collected_at": now_utc(),
            "keywords": len(keywords),
            "unique_domains": len(out_list),
            "provider_usage": provider_usage,
            "output_path": str(args.output),
        },
    )
    print(f"[discover] wrote {len(out_list)} → {args.output}")

if __name__ == "__main__":
    main()

