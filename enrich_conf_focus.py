#!/usr/bin/env python3
"""Enrich conference focus[] tags from themes, intro, speakers, productCats, and official URLs."""
from __future__ import annotations

import json
import re
import ssl
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
CONFERENCES_PATH = ROOT / "exhibitor-data" / "conferences.json"
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


def load_conferences() -> List[Dict[str, Any]]:
    conferences = json.loads(CONFERENCES_PATH.read_text(encoding="utf-8"))
    confs: List[Dict[str, Any]] = []
    for conf in conferences:
        if not isinstance(conf, dict):
            continue
        cid = clean_tag(conf.get("id"))
        if not cid or "_DUP_REMOVED" in cid:
            continue
        detail = conf.get("detail") or {}
        confs.append(
            {
                "id": cid,
                "url": clean_tag(conf.get("url")),
                "focus": list(conf.get("focus") or []),
                "themes": list(detail.get("themes") or []),
                "productCats": list(conf.get("productCats") or []),
                "intro": clean_text(detail.get("intro")),
                "speakers": [
                    clean_tag(s.get("topic"))
                    for s in (detail.get("speakers") or [])
                    if isinstance(s, dict) and clean_tag(s.get("topic"))
                ],
                "_source": conf,
            }
        )
    return confs


def clean_text(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip())


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


def apply_focus_updates(confs: List[Dict[str, Any]], url_tags: Dict[str, List[str]]) -> Tuple[int, List[Tuple[str, int, int]]]:
    updated = 0
    stats: List[Tuple[str, int, int]] = []
    for conf in confs:
        scraped = url_tags.get(conf["id"], [])
        tags = merge_tags(conf, scraped)
        old_n = len(conf.get("focus") or [])
        source = conf.get("_source") or {}
        if tags != conf.get("focus"):
            source["focus"] = tags
            updated += 1
        stats.append((conf["id"], old_n, len(tags)))
    return updated, stats


def main() -> None:
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    confs = load_conferences()
    print(f"conferences: {len(confs)}")
    if not confs:
        print("no conferences found; skipping focus enrichment")
        return

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

    updated, stats = apply_focus_updates(confs, url_tags)
    conferences = [conf["_source"] for conf in confs]
    CONFERENCES_PATH.write_text(json.dumps(conferences, ensure_ascii=False, indent=2), encoding="utf-8")

    avg = sum(s[2] for s in stats) / len(stats)
    print(f"updated focus arrays: {updated}/{len(confs)}, avg tags {avg:.1f}")
    print("top expansions:")
    for cid, old, new in sorted(stats, key=lambda x: x[2] - x[1], reverse=True)[:10]:
        print(f"  {cid}: {old} -> {new}")


if __name__ == "__main__":
    main()
