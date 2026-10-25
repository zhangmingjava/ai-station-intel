"""收款信号探测：访问站点首页与 /pricing，检测公开支付渠道痕迹并提取价格。

只读公开页面，1 秒间隔，遵守 robots.txt。输出是"信号"而非真实营收。
"""
import re
import time
import urllib.robotparser
from dataclasses import dataclass, field

import requests
from bs4 import BeautifulSoup

UA = "Mozilla/5.0 (compatible; AIStationIntelBot/0.1; +https://example.com/about)"
TIMEOUT = 15
REQUEST_DELAY = 1.0  # 同一站点两次请求间隔（秒），礼貌爬取

# 强指纹：脚本/公钥/支付链接，出现即可认定"在用该渠道"
CHANNEL_PATTERNS = {
    "stripe": ("Stripe", re.compile(
        r"js\.stripe\.com|pk_(live|test)_[A-Za-z0-9]{10,}|(checkout|pay|buy)\.stripe\.com"
        r"|stripe\.com/(v3|p/)", re.I)),
    "paddle": ("Paddle", re.compile(
        r"paddle\.com/bundle|cdn\.paddle\.com|paddle\.(js|setup)|Paddle\.(setup|Checkout)"
        r"|(buy|checkout|pay)\.paddle\.com", re.I)),
    "creem": ("Creem", re.compile(r"creem\.(io|link)", re.I)),
    "dodo": ("Dodo", re.compile(r"dodopayments", re.I)),
    "gumroad": ("Gumroad", re.compile(r"gumroad\.com/js|gumroad\.com/l/|gum\.co/", re.I)),
    "lemonsqueezy": ("Lemon Squeezy", re.compile(r"lemonsqueezy\.com|ls\.link", re.I)),
    "paypal": ("PayPal", re.compile(r"paypal\.com/sdk/js|paypalobjects\.com"
                                    r"|(www\.)?paypal\.com/(cgi-bin|webscr|ncp/payment)", re.I)),
    "polar": ("Polar", re.compile(r"polar\.sh/checkout|js\.polar\.sh", re.I)),
}
# 弱信号：正文/链接里仅提及渠道名（可能是介绍性文字），置信度低
WEAK_PATTERNS = {
    cid: re.compile(r"\b" + re.escape(cid), re.I) for cid in CHANNEL_PATTERNS
}

PRICE_RE = re.compile(r"(?:US)?\$\s?(\d{1,5}(?:\.\d{1,2})?)")

_last_request_time: dict[str, float] = {}


@dataclass
class ScanResult:
    domain: str
    status: str = "ok"                # ok / unreachable / blocked
    channels: list[str] = field(default_factory=list)      # 强信号（可认定在用）
    weak_channels: list[str] = field(default_factory=list) # 弱信号（仅提及）
    has_pricing: bool = False
    min_price_usd: float = 0.0


def _polite_get(url: str, session: requests.Session) -> requests.Response | None:
    host = url.split("/", 3)[2]
    gap = time.time() - _last_request_time.get(host, 0)
    if gap < REQUEST_DELAY:
        time.sleep(REQUEST_DELAY - gap)
    _last_request_time[host] = time.time()
    try:
        resp = session.get(url, timeout=TIMEOUT, headers={"User-Agent": UA})
    except requests.RequestException:
        return None
    if resp.status_code in (401, 403, 429):
        return None
    return resp


def _robots_allows(session: requests.Session, base_url: str, path: str) -> bool:
    rp = urllib.robotparser.RobotFileParser()
    rp.set_url(base_url + "/robots.txt")
    try:
        rp.read()
    except Exception:
        return True  # robots.txt 不可达时默认允许，但仍按礼貌频率
    return rp.can_fetch(UA, base_url + path)


def _extract_min_price(html: str) -> float:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    prices = []
    for m in PRICE_RE.finditer(soup.get_text(" ", strip=True)):
        v = float(m.group(1))
        if 2000 <= v <= 2099:      # "$" 后跟年份的误报
            continue
        if 1 <= v <= 9999:
            prices.append(v)
    return min(prices) if prices else 0.0


def scan_site(domain: str) -> ScanResult:
    """探测一个站点：首页找支付指纹，/pricing 提取最低价。"""
    base = f"https://{domain.removeprefix('www.')}"
    result = ScanResult(domain=domain)
    with requests.Session() as session:
        if not _robots_allows(session, base, "/"):
            result.status = "blocked"
            return result

        resp = _polite_get(base, session)
        if resp is None or resp.status_code >= 400:
            result.status = "unreachable"
            return result

        html = resp.text
        found = {cid for cid, (_, pat) in CHANNEL_PATTERNS.items() if pat.search(html)}
        mentioned = {cid for cid, pat in WEAK_PATTERNS.items() if pat.search(html)}

        # 定价页与结账页都探测：强支付指纹常只出现在 checkout 页
        pricing_html = ""
        for path in ("/pricing", "/price", "/plans"):
            if not _robots_allows(session, base, path):
                continue
            p_resp = _polite_get(base + path, session)
            if p_resp is None:
                continue
            if p_resp.status_code == 200 and len(p_resp.text) > 500:
                result.has_pricing = True
                pricing_html = p_resp.text
                found |= {cid for cid, (_, pat) in CHANNEL_PATTERNS.items()
                          if pat.search(pricing_html)}
                mentioned |= {cid for cid, pat in WEAK_PATTERNS.items()
                              if pat.search(pricing_html)}
                break
        if not found:  # 首页/定价页已有强指纹时无需再探结账页
            for path in ("/checkout", "/buy"):
                if not _robots_allows(session, base, path):
                    continue
                p_resp = _polite_get(base + path, session)
                if p_resp is None:
                    continue
                if p_resp.status_code == 200 and len(p_resp.text) > 500:
                    found |= {cid for cid, (_, pat) in CHANNEL_PATTERNS.items()
                              if pat.search(p_resp.text)}
                    mentioned |= {cid for cid, pat in WEAK_PATTERNS.items()
                                  if pat.search(p_resp.text)}
                    if not pricing_html:
                        pricing_html = p_resp.text
                    if found:
                        break

        if pricing_html and not result.min_price_usd:
            result.min_price_usd = _extract_min_price(pricing_html)
        elif not result.has_pricing:
            result.min_price_usd = _extract_min_price(html)

        # 首页正文里也可能直接有价格
        if not result.min_price_usd:
            result.min_price_usd = _extract_min_price(html)

        result.channels = sorted(found)
        result.weak_channels = sorted(mentioned - found)
        return result
