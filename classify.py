"""LLM 站点打标：抓首页标题/描述，调用 OpenAI 兼容接口生成分类与一句话简介。

凭据（可选，未配置则跳过）：
  LLM_API_KEY   — API 密钥
  LLM_BASE_URL  — 默认智谱 https://open.bigmodel.cn/api/paas/v4（换成 OpenAI/DeepSeek 亦兼容）
  LLM_MODEL     — 默认 glm-4-flash（便宜够用）
"""
import json
import os
import re

import requests

from db import connect

TIMEOUT = 30


def _llm_config() -> tuple[str, str, str] | None:
    key = os.environ.get("LLM_API_KEY")
    if not key:
        return None
    # 默认智谱 Coding Plan 端点（与本机 .env 一致）；普通开放平台 key 去掉 /coding/ 段
    base = os.environ.get("LLM_BASE_URL",
                          "https://open.bigmodel.cn/api/coding/paas/v4").rstrip("/")
    model = os.environ.get("LLM_MODEL", "glm-4.5-air")
    return key, base, model


def _fetch_meta(session: requests.Session, domain: str) -> str:
    try:
        resp = session.get(f"https://{domain}", timeout=15,
                           headers={"User-Agent": "Mozilla/5.0 (compatible; AIStationIntelBot/0.1)"},
                           )
        if resp.status_code != 200:
            return ""
        html = resp.text[:20000]
    except requests.RequestException:
        return ""
    title = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    desc = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']',
                     html, re.S | re.I) or \
           re.search(r'<meta[^>]+content=["\'](.*?)["\'][^>]+name=["\']description["\']',
                     html, re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", html)
    return f"标题: {title.group(1).strip() if title else ''}\n" \
           f"描述: {desc.group(1).strip()[:200] if desc else ''}\n" \
           f"正文摘录: {re.sub(r'\\s+', ' ', text)[:600]}"


def classify_one(session: requests.Session, llm: tuple[str, str, str], domain: str) -> dict:
    key, base, model = llm
    meta = _fetch_meta(session, domain)
    if not meta.strip():
        return {}
    prompt = (
        "根据以下网页元信息，输出 JSON（不要 markdown 代码块）："
        '{"name": "站点名(英文/原文)", "category": "分类，从这些里选: '
        'AI写作/AI图像/AI视频/AI音频/AI编程/AI对话/AI效率/AI开发工具/AI学习/AI其他/非AI站点", '
        '"description_cn": "一句话中文简介(30字内)"}\n\n' + meta)
    try:
        resp = requests.post(
            f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": model, "temperature": 0.2,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=TIMEOUT)
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        data = json.loads(re.sub(r"^```(json)?|```$", "", content.strip(), flags=re.M))
        return {k: str(data.get(k, ""))[:200] for k in ("name", "category", "description_cn")}
    except (requests.RequestException, KeyError, ValueError, json.JSONDecodeError) as e:
        print(f"  LLM 打标失败 {domain}: {e}")
        return {}


def run(limit: int = 50) -> None:
    llm = _llm_config()
    if not llm:
        print("[classify] 未设置 LLM_API_KEY，跳过（打标可选，不影响榜单）")
        return
    conn = connect()
    rows = conn.execute(
        "SELECT domain FROM sites WHERE category = '' AND scan_status = 'ok' LIMIT ?",
        (limit,)).fetchall()
    print(f"[classify] 待打标 {len(rows)} 个")
    with requests.Session() as session:
        for row in rows:
            data = classify_one(session, llm, row["domain"])
            if data:
                conn.execute("UPDATE sites SET name=?, category=?, description=? WHERE domain=?",
                             (data["name"], data["category"], data["description_cn"],
                              row["domain"]))
                conn.commit()
                print(f"  {row['domain']} -> {data['category']}")
    conn.close()


if __name__ == "__main__":
    run()
