#!/usr/bin/env python3
"""Enrich conference focus[] tags from themes, intro, speakers, productCats, and official URLs."""
from __future__ import annotations

import json
import re
import ssl
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Set
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
INDEX = ROOT / "index.html"
CACHE = ROOT / "exhibitor-data" / "conf-focus-cache.json"

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
SSL_CTX = ssl.create_default_context()
MAX_TAGS = 18
TAG_MAX_LEN = 28

CAT_SHORT = {
    "大模型 / 算法": "大模型",
    "AI Agent / 应用": "Agent",
    "芯片 / 算力": "芯片",
    "AI 基础设施": "Infra",
    "机器人 / 具身智能": "机器人",
    "消费电子 / 终端": "终端",
    "工业 / 制造": "工业",
    "数据 / 云 / 安全": "数据云",
}

STOP = {
    "待官方公布",
    "敬请关注官网",
    "敬请关注 gitex.com",
    "敬请关注",
    "待补充",
    "n/a",
    "tbd",
}


def fetch_url(url: str, timeout: int = 14) -> str:
    req = Request(url, headers={"User-Agent": UA, "Accept": "text/html,*/*"})
    with urlopen(req, timeout=timeout, context=SSL_CTX) as resp:
        return resp.read().decode("utf-8", "replace", errors="replace")


def clean_tag(text: str) -> str:
    t = re.sub(r"\s+", " ", str(text or "").strip())
    t = t.strip("·-—|/，,;；:： ")
    t = re.sub(r"^【.*?】", "", t)
    t = re.sub(r"^[\d\.]+\s*", "", t)
    if not t or len(t) < 2:
        return ""
    if len(t) > TAG_MAX_LEN:
        t = t[: TAG_MAX_LEN - 1].rstrip() + "…"
    low = t.lower()
    if low in STOP or any(s in t for s in STOP):
        return ""
    return t


def split_phrases(text: str) -> List[str]:
    if not text:
        return []
    parts = re.split(r"[·•|/，,;；\n]+", text)
    out = []
    for p in parts:
        p = clean_tag(p)
        if p and len(p) >= 2:
            out.append(p)
    return out


def meta_from_html(html: str) -> List[str]:
    out: List[str] = []
    for pat in [
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']description["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:description["\']',
        r'<meta[^>]+name=["\']keywords["\'][^>]+content=["\']([^"\']+)["\']',
    ]:
        for m in re.finditer(pat, html, re.I):
            out.extend(split_phrases(m.group(1)))
    for m in re.finditer(r"<title>([^<]{5,120})</title>", html, re.I):
        title = re.sub(r"\s*[|\-–—].*$", "", m.group(1)).strip()
        out.extend(split_phrases(title))
    return out


def keywords_from_intro(intro: str) -> List[str]:
    if not intro:
        return []
    out: List[str] = []
    # quoted theme fragments
    for m in re.finditer(r"[「『\"']([^」』\"']{4,26})[」』\"']", intro):
        out.append(clean_tag(m.group(1)))
    # chinese topic lists after colon
    for m in re.finditer(r"涵盖([^。；;]{4,40})", intro):
        out.extend(split_phrases(m.group(1)))
    for m in re.finditer(r"聚焦([^。；;]{4,40})", intro):
        out.extend(split_phrases(m.group(1)))
    for m in re.finditer(r"主题[是为：:]([^。；;]{4,40})", intro):
        out.extend(split_phrases(m.group(1)))
    return [x for x in out if x]


def parse_string_array(block: str, key: str) -> List[str]:
    m = re.search(rf"{key}:\[(.*?)\]", block, re.S)
    if not m:
        return []
    return [clean_tag(x) for x in re.findall(r"'((?:\\'|[^'])*)'", m.group(1)) if clean_tag(x)]


def parse_conf_blocks(html: str) -> List[Dict[str, Any]]:
    confs: List[Dict[str, Any]] = []
    for m in re.finditer(r"\{\s*\n\s*id:'([^']+)'", html):
        cid = m.group(1)
        if "_DUP_REMOVED" in cid:
            continue
        start = m.start()
        # find matching closing `},` for this conference object
        depth = 0
        i = start
        in_str = False
        esc = False
        while i < len(html):
            ch = html[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == "'":
                    in_str = False
            else:
                if ch == "'":
                    in_str = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        if end < len(html) and html[end : end + 1] == ",":
                            end += 1
                        block = html[start:end]
                        intro_m = re.search(r"intro:'((?:\\'|[^'])*)'", block)
                        url_m = re.search(r"url:'([^']*)'", block)
                        confs.append(
                            {
                                "id": cid,
                                "url": url_m.group(1) if url_m else "",
                                "focus": parse_string_array(block, "focus"),
                                "themes": parse_string_array(block, "themes"),
                                "productCats": parse_string_array(block, "productCats"),
                                "intro": intro_m.group(1).replace("\\'", "'") if intro_m else "",
                                "speakers": [
                                    clean_tag(t)
                                    for t in re.findall(r"topic:'((?:\\'|[^'])*)'", block)
                                    if clean_tag(t)
                                ],
                                "block": block,
                            }
                        )
                        break
            i += 1
    return confs


def scrape_url_tags(url: str, cache: Dict[str, Any]) -> List[str]:
    if not url or not url.startswith("http"):
        return []
    if url in cache:
        return cache[url].get("tags") or []
    tags: List[str] = []
    try:
        html = fetch_url(url)
        tags = meta_from_html(html)
        cache[url] = {"tags": tags, "ts": int(time.time()), "ok": True}
    except (HTTPError, URLError, TimeoutError, Exception) as exc:
        cache[url] = {"tags": [], "ts": int(time.time()), "ok": False, "error": str(exc)}
    return tags


def merge_tags(conf: Dict[str, Any], scraped: List[str]) -> List[str]:
    seen: Set[str] = set()
    merged: List[str] = []

    def add(items: List[str], priority: bool = False) -> None:
        for raw in items:
            tag = clean_tag(raw)
            if not tag:
                continue
            key = tag.lower()
            if key in seen:
                continue
            seen.add(key)
            if priority:
                merged.insert(0, tag)
            else:
                merged.append(tag)

    add(conf.get("focus") or [], priority=True)
    add(conf.get("themes") or [])
    add([CAT_SHORT.get(c, c) for c in (conf.get("productCats") or [])])
    add(conf.get("speakers") or [])
    add(keywords_from_intro(conf.get("intro") or ""))
    add(scraped)
    return merged[:MAX_TAGS]


def format_focus_array(tags: List[str]) -> str:
    if not tags:
        return "  focus:[]"
    lines = ["  focus:["]
    for t in tags:
        esc = t.replace("\\", "\\\\").replace("'", "\\'")
        lines.append(f"    '{esc}',")
    lines[-1] = lines[-1].rstrip(",")
    lines.append("  ]")
    return "\n".join(lines)


def replace_focus_by_id(html: str, cid: str, tags: List[str]) -> str:
    pat = rf"(id:'{re.escape(cid)}'[\s\S]*?)focus:\[[\s\S]*?\]"
    repl = r"\1" + format_focus_array(tags)
    new_html, n = re.subn(pat, repl, html, count=1)
    if n != 1:
        raise ValueError(f"focus replace failed for {cid} (matches={n})")
    return new_html


def main() -> None:
    html = INDEX.read_text(encoding="utf-8")
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    confs = parse_conf_blocks(html)
    print(f"conferences: {len(confs)}")

    url_tags: Dict[str, List[str]] = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {
            pool.submit(scrape_url_tags, c["url"], cache): c["id"]
            for c in confs
            if c.get("url")
        }
        done = 0
        for fut in as_completed(futures):
            cid = futures[fut]
            try:
                url_tags[cid] = fut.result()
            except Exception:
                url_tags[cid] = []
            done += 1
            if done % 20 == 0:
                CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"  scraped {done}/{len(futures)}")

    CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")

    updated = 0
    stats = []
    new_html = html
    for conf in confs:
        scraped = url_tags.get(conf["id"], [])
        tags = merge_tags(conf, scraped)
        old_n = len(conf.get("focus") or [])
        if tags != conf.get("focus"):
            updated += 1
        stats.append((conf["id"], old_n, len(tags)))
        try:
            new_html = replace_focus_by_id(new_html, conf["id"], tags)
        except ValueError as exc:
            print(f"  warn: {exc}")

    INDEX.write_text(new_html, encoding="utf-8")
    avg = sum(s[2] for s in stats) / len(stats)
    print(f"updated focus arrays: {updated}/{len(confs)}, avg tags {avg:.1f}")
    print("top expansions:")
    for cid, old, new in sorted(stats, key=lambda x: x[2] - x[1], reverse=True)[:10]:
        print(f"  {cid}: {old} -> {new}")


if __name__ == "__main__":
    main()
