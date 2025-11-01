#!/usr/bin/env python3
"""
robots_guard.py - minimal robots.txt helper used by discovery & CI checks.
Provides:
  - robots_allows(url, user_agent)
  - get_crawl_delay(base_url, user_agent)
"""
from urllib.parse import urlparse, urljoin
import urllib.robotparser
import requests

def _robot_parser_for(url):
    parsed = urlparse(url)
    robots_url = urljoin(f"{parsed.scheme}://{parsed.netloc}", "/robots.txt")
    rp = urllib.robotparser.RobotFileParser()
    try:
        rp.set_url(robots_url)
        rp.read()
    except Exception:
        # network/read failure -> conservative deny
        return None
    return rp

def robots_allows(url, user_agent="Agentik-LeadGen-Discover"):
    rp = _robot_parser_for(url)
    if rp is None:
        return False
    return rp.can_fetch(user_agent, url)

def get_crawl_delay(url, user_agent="Agentik-LeadGen-Discover"):
    rp = _robot_parser_for(url)
    if rp is None:
        return None
    try:
        delay = rp.crawl_delay(user_agent)
        return delay
    except Exception:
        return None

if __name__ == "__main__":
    print("robots_guard loaded")
