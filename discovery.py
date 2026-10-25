"""站点发现：从导航/目录站收割新收录的 AI 站点 + 种子名单导入。

收割逻辑：抓目录页 -> 提取站外链接 -> 过滤垃圾域名 -> 入库。
遵守 robots.txt、单源限速，只抓列表页不递归。
"""
import os
import re
import time
import urllib.robotparser
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from db import connect, upsert_site

UA = "Mozilla/5.0 (compatible; AIStationIntelBot/0.1; +https://example.com/about)"
TIMEOUT = 20

# 目录源配置：url + CSS 选择器（提取候选 <a>），选择器失效时退化为全页链接扫描
SOURCES = [
    ("gptdemo", "https://www.gptdemo.net/products", "a"),
    ("topai.tools", "https://topai.tools/s", "a"),
    ("toolify", "https://toolify.ai/best", "a"),
    ("theresanaiforthat", "https://theresanaiforthat.com/most-saved/", "a"),
]

# 排除：社交平台、大厂、目录自身、明显非产品站
BLOCKED_RE = re.compile(
    r"^(www\.)?(twitter|x|facebook|instagram|linkedin|youtube|tiktok|reddit|github|"
    r"google|microsoft|apple|amazon|openai|anthropic|discord|telegram|medium|substack|"
    r"producthunt|news\.ycombinator|patreon|t\.co|bit\.ly|gptdemo|topai\.tools|"
    r"toolify|theresanaiforthat|chatgpt|gemini|claude|npmjs|pypi)\.[a-z.]+$", re.I)
GOOD_TLD_RE = re.compile(r"\.(ai|app|io|com|co|so|dev|net|org|xyz|me|pro|cc)$", re.I)


# 排除：托管平台子域（非独立产品站）
SUBDOMAIN_BLOCKED = (".vercel.app", ".netlify.app", ".pages.dev", ".webflow.io",
                     ".github.io", ".herokuapp.com", ".render.com", ".fly.dev",
                     ".substack.com", ".notion.site", ".linktr.ee", ".hashnode.dev")


def _clean_domain(href: str) -> str | None:
    try:
        host = urlparse(href).netloc.lower()
    except ValueError:
        return None
    if not host or BLOCKED_RE.match(host) or host.endswith(SUBDOMAIN_BLOCKED):
        return None
    host = host.removeprefix("www.")
    if not GOOD_TLD_RE.search(host) or len(host) > 60 or host.count(".") > 3:
        return None
    return host


def harvest_source(source_id: str, url: str, selector: str) -> tuple[int, int]:
    """返回 (抓到候选数, 新入库数)。"""
    rp = urllib.robotparser.RobotFileParser()
    rp.set_url("https://" + urlparse(url).netloc + "/robots.txt")
    try:
        rp.read()
    except Exception:
        pass
    if url and not rp.can_fetch(UA, url):
        print(f"[{source_id}] robots.txt 禁止抓取，跳过")
        return (0, 0)

    try:
        resp = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": UA})
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[{source_id}] 抓取失败: {e}")
        return (0, 0)

    soup = BeautifulSoup(resp.text, "html.parser")
    anchors = soup.select(selector) or soup.find_all("a")
    new = found = 0
    conn = connect()
    for a in anchors:
        href = a.get("href", "")
        domain = _clean_domain(href)
        if not domain:
            continue
        found += 1
        name = a.get_text(strip=True)[:100]
        if upsert_site(conn, domain, discovered_from=source_id, name=name):
            new += 1
    conn.close()
    time.sleep(2)  # 源与源之间限速
    return (found, new)


def import_seeds(path: str) -> int:
    """从 seeds.txt 导入（每行一个域名，# 开头为注释）。"""
    added = 0
    conn = connect()
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#"):
            if upsert_site(conn, line, discovered_from="seed"):
                added += 1
    conn.close()
    return added


def harvest_hn(days: int = 30) -> tuple[int, int]:
    """HN Algolia 公开 API：近 N 天 Show HN（免爬页面、完全合规）。"""
    url = (f"https://hn.algolia.com/api/v1/search_by_date?tags=show_hn"
           f"&numericFilters=created_at_i>{int(time.time()) - days * 86400}&hitsPerPage=300")
    try:
        resp = requests.get(url, timeout=TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[hn] API 失败: {e}")
        return (0, 0)
    found = new = 0
    conn = connect()
    for hit in resp.json().get("hits", []):
        if not hit.get("url"):
            continue
        domain = _clean_domain(hit["url"])
        if not domain:
            continue
        found += 1
        title = hit.get("title", "")[:100]
        if upsert_site(conn, domain, discovered_from="hn-show", name=title):
            new += 1
    conn.close()
    return (found, new)


# GitHub awesome-list：raw README 直接拉，GitHub API 免 token 额度足够
AWESOME_LISTS = [
    "https://raw.githubusercontent.com/mahseema/awesome-ai-tools/main/README.md",
]
MD_LINK_RE = re.compile(r"\((https?://[^)\s]+)\)")
PH_GRAPHQL_URL = "https://api.producthunt.com/v2/api/graphql"
PH_QUERY = """
{ posts(first: 30, order: NEWEST) { edges { node { name tagline website } } } }
"""


def harvest_github() -> tuple[int, int]:
    found = new = 0
    conn = connect()
    for readme_url in AWESOME_LISTS:
        try:
            resp = requests.get(readme_url, timeout=TIMEOUT)
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"[github] {readme_url} 拉取失败: {e}")
            continue
        for href in MD_LINK_RE.findall(resp.text):
            domain = _clean_domain(href)
            if not domain:
                continue
            found += 1
            if upsert_site(conn, domain, discovered_from="github-awesome"):
                new += 1
        time.sleep(2)
    conn.close()
    return (found, new)


def harvest_producthunt() -> tuple[int, int]:
    """需要 PH_ACCESS_TOKEN 环境变量（ProductHunt API v2 GraphQL）。"""
    token = os.environ.get("PH_ACCESS_TOKEN")
    if not token:
        print("[producthunt] 未设置 PH_ACCESS_TOKEN，跳过")
        return (0, 0)
    try:
        resp = requests.post(PH_GRAPHQL_URL, json={"query": PH_QUERY},
                             headers={"Authorization": f"Bearer {token}"},
                             timeout=TIMEOUT)
        resp.raise_for_status()
        edges = resp.json()["data"]["posts"]["edges"]
    except (requests.RequestException, KeyError, ValueError) as e:
        print(f"[producthunt] API 失败: {e}")
        return (0, 0)
    found = new = 0
    conn = connect()
    for edge in edges:
        node = edge["node"]
        domain = _clean_domain(node.get("website") or "")
        if not domain:
            continue
        found += 1
        if upsert_site(conn, domain, discovered_from="producthunt",
                       name=node.get("name", ""), description=node.get("tagline", "")):
            new += 1
    conn.close()
    return (found, new)


def run(harvest: bool = True) -> None:
    if import_seeds("seeds.txt"):
        print("[seed] 种子名单已导入")
    if not harvest:
        return
    total_new = 0
    for label, fn in (("hn-show", harvest_hn),
                      ("github-awesome", harvest_github),
                      ("producthunt", harvest_producthunt)):
        found, new = fn()
        total_new += new
        print(f"[{label}] 候选链接 {found} 个，新入库 {new} 个")
    for source_id, url, selector in SOURCES:
        found, new = harvest_source(source_id, url, selector)
        total_new += new
        print(f"[{source_id}] 候选链接 {found} 个，新入库 {new} 个")
    print(f"发现完成，本轮新增 {total_new} 个站点")
