#!/usr/bin/env python3
"""Sync bulk exhibitor JSON for target conferences.

This script keeps the current page structure unchanged and only refreshes the
external exhibitor-data/*.json files consumed by the frontend.
"""
from __future__ import annotations

import argparse
import json
import re
import ssl
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "exhibitor-data"
CONFERENCES_PATH = DATA_DIR / "conferences.json"
COMPANY_LINKS_PATH = DATA_DIR / "company-links.json"

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
SSL_CTX = ssl.create_default_context()

STAGE_DEFAULT = "融资未公开"
CAT_LABELS = [
    "大模型 / 算法",
    "AI Agent / 应用",
    "芯片 / 算力",
    "AI 基础设施",
    "机器人 / 具身智能",
    "消费电子 / 终端",
    "工业 / 制造",
    "数据 / 云 / 安全",
]

COUNTRY_ZH = {
    "United States": "美国",
    "United States Minor Outlying Islands": "美国本土外小岛屿",
    "Mainland China": "中国",
    "China": "中国",
    "Taiwan": "台湾",
    "Hong Kong": "香港",
    "Hong Kong SAR": "香港",
    "Japan": "日本",
    "Korea, South Korea": "韩国",
    "South Korea": "韩国",
    "Singapore": "新加坡",
    "Germany": "德国",
    "France": "法国",
    "United Kingdom": "英国",
    "Netherlands": "荷兰",
    "Belgium": "比利时",
    "Canada": "加拿大",
    "Australia": "澳大利亚",
    "India": "印度",
    "Israel": "以色列",
    "Thailand": "泰国",
    "Malaysia": "马来西亚",
    "Viet Nam": "越南",
    "Vietnam": "越南",
    "Czech Republic": "捷克",
    "Czechia": "捷克",
    "Spain": "西班牙",
    "Italy": "意大利",
    "Poland": "波兰",
    "Latvia": "拉脱维亚",
    "Turkey": "土耳其",
    "United Arab Emirates": "阿联酋",
    "Saudi Arabia": "沙特阿拉伯",
    "Sweden": "瑞典",
    "Switzerland": "瑞士",
    "Denmark": "丹麦",
    "Estonia": "爱沙尼亚",
    "Algeria": "阿尔及利亚",
}

KEYWORD_TO_CAT = [
    (("llm", "large language", "foundation model", "generative ai", "genai", "gpt"), "大模型 / 算法"),
    (("agent", "copilot", "assistant", "workflow", "knowledge base"), "AI Agent / 应用"),
    (("gpu", "npu", "chip", "semiconductor", "server", "accelerator", "edge ai", "ai pc"), "芯片 / 算力"),
    (("cloud", "platform", "infrastructure", "data center", "storage", "database", "mcp", "api"), "AI 基础设施"),
    (("robot", "robotics", "drone", "agv", "amr", "humanoid"), "机器人 / 具身智能"),
    (("consumer", "notebook", "pc", "display", "headset", "wearable", "phone"), "消费电子 / 终端"),
    (("industrial", "manufacturing", "factory", "iot", "iiot", "automation", "factory ai"), "工业 / 制造"),
    (("security", "network", "data", "analytics", "observability", "privacy"), "数据 / 云 / 安全"),
]

SEED_CONF_IDS = ["WAIC2025", "SEMICONWest2025", "MWC2025"]


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def fetch_html(url: str, timeout: int = 30) -> str:
    req = Request(url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
    with urlopen(req, timeout=timeout, context=SSL_CTX) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, "replace")


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip())


def normalize_name(name: str) -> str:
    val = clean_text(name).lower()
    val = re.sub(r"\([^)]*\)", " ", val)
    val = re.sub(r"\b(incorporated|corporation|company|limited|ltd|llc|corp|co|gmbh|ag|plc|bv|pte)\b\.?", " ", val)
    val = re.sub(r"[^a-z0-9\u4e00-\u9fff\s&+.-]", " ", val)
    return re.sub(r"\s+", " ", val).strip()


def normalize_host(url: str) -> str:
    raw = clean_text(url)
    if not raw:
        return ""
    raw = re.sub(r"^https?://", "", raw, flags=re.I).split("/")[0].split("?")[0]
    return raw.lower().replace("www.", "", 1)


def dedupe_exhibitors(items: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}
    for item in items:
        key = normalize_host(item.get("url") or "") or normalize_name(item.get("name") or "")
        if not key:
            continue
        prev = merged.get(key)
        if not prev:
            merged[key] = dict(item)
            continue
        for field in ("name", "nameEn", "nameZh", "booth", "url", "country", "countryZh", "product", "productZh", "pitch", "exhibitProduct", "description"):
            cur = clean_text(prev.get(field))
            cand = clean_text(item.get(field))
            if cand and (not cur or len(cand) > len(cur)):
                prev[field] = item.get(field)
        prev["cats"] = sorted(set((prev.get("cats") or []) + (item.get("cats") or [])))
        if prev.get("stage") in ("", "待补充", STAGE_DEFAULT) and clean_text(item.get("stage")):
            prev["stage"] = item["stage"]
    return sorted(merged.values(), key=lambda x: clean_text(x.get("name")).lower())


def infer_cats(*texts: str) -> List[str]:
    blob = " ".join(clean_text(t).lower() for t in texts if t)
    out: List[str] = []
    for keywords, cat in KEYWORD_TO_CAT:
        if any(keyword in blob for keyword in keywords):
            out.append(cat)
    return out[:4]


def format_seed_record(item: Dict[str, Any], fallback_country: str = "") -> Dict[str, Any]:
    country = clean_text(item.get("country") or fallback_country)
    country_zh = clean_text(item.get("countryZh")) or COUNTRY_ZH.get(country, "")
    record = {
        "name": clean_text(item.get("name")),
        "nameEn": clean_text(item.get("nameEn")),
        "nameZh": clean_text(item.get("nameZh")),
        "booth": clean_text(item.get("booth")),
        "stage": clean_text(item.get("stage")) or STAGE_DEFAULT,
        "cats": list(item.get("cats") or []),
        "product": clean_text(item.get("product")),
        "productZh": clean_text(item.get("productZh")),
        "pitch": clean_text(item.get("pitch")),
        "pitchSource": clean_text(item.get("pitchSource")),
        "pitchVerified": bool(item.get("pitchVerified")),
        "exhibitProduct": clean_text(item.get("exhibitProduct")),
        "exhibitProductZh": clean_text(item.get("exhibitProductZh")),
        "url": clean_text(item.get("url")),
        "country": country,
        "countryZh": country_zh,
    }
    if not record["cats"]:
        record["cats"] = infer_cats(record["product"], record["productZh"], record["pitch"], record["name"])
    return {k: v for k, v in record.items() if v not in ("", [], False)}


def load_conference(conf_id: str) -> Dict[str, Any]:
    conferences = read_json(CONFERENCES_PATH)
    conf = next((c for c in conferences if c.get("id") == conf_id), None)
    if not conf:
        raise KeyError(f"Conference not found: {conf_id}")
    return conf


@dataclass
class SyncResult:
    conf_id: str
    source: str
    exhibitors: List[Dict[str, Any]]
    notes: Optional[str] = None


class BaseAdapter:
    conf_id: str
    source: str

    def run(self) -> SyncResult:
        raise NotImplementedError

    def write(self, result: SyncResult) -> Path:
        out = {
            "id": result.conf_id,
            "source": result.source,
            "count": len(result.exhibitors),
            "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "exhibitors": result.exhibitors,
        }
        if result.notes:
            out["notes"] = result.notes
        path = DATA_DIR / f"{result.conf_id}.json"
        write_json(path, out)
        return path


class InlineSeedAdapter(BaseAdapter):
    def __init__(self, conf_id: str, source: str, note: str = "") -> None:
        self.conf_id = conf_id
        self.source = source
        self.note = note

    def run(self) -> SyncResult:
        conf = load_conference(self.conf_id)
        fallback_country = clean_text(conf.get("country", "")).split(",")[-1].strip()
        exhibitors = [
            format_seed_record(item, fallback_country=fallback_country)
            for item in (conf.get("detail") or {}).get("exhibitors") or []
        ]
        return SyncResult(
            conf_id=self.conf_id,
            source=self.source,
            exhibitors=dedupe_exhibitors(exhibitors),
            notes=self.note or None,
        )


class ComputexAdapter(BaseAdapter):
    conf_id = "Computex2025"
    source = "www.computextaipei.com.tw"
    listing_url = "https://www.computextaipei.com.tw/en/exhibitor/country-list-data/"

    def __init__(self, include_details: bool = True) -> None:
        self.include_details = include_details

    def parse_country_pages(self) -> List[tuple[str, str]]:
        html = fetch_html(self.listing_url)
        soup = BeautifulSoup(html, "html.parser")
        pages: List[tuple[str, str]] = []
        for link in soup.select('a[href*="/en/exhibitor/country-list-data/"]'):
            href = clean_text(link.get("href"))
            if not href.endswith("/list.html"):
                continue
            label = clean_text(link.get_text(" ", strip=True))
            country = re.sub(r"\(\d+\)$", "", label).strip()
            full = urljoin(self.listing_url, href)
            if (country, full) not in pages:
                pages.append((country, full))
        return pages

    def iter_listing_pages(self, page_url: str) -> List[str]:
        first_html = fetch_html(page_url)
        soup = BeautifulSoup(first_html, "html.parser")
        page_numbers = [1]
        for link in soup.select('a[href^="javascript:doPage("]'):
            text = clean_text(link.get_text(" ", strip=True))
            if text.isdigit():
                page_numbers.append(int(text))
        total_pages = max(page_numbers) if page_numbers else 1
        urls = [page_url]
        for page_no in range(2, total_pages + 1):
            sep = "&" if "?" in page_url else "?"
            urls.append(f"{page_url}{sep}currentPage={page_no}")
        return urls

    def parse_detail_page(self, url: str) -> Dict[str, str]:
        html = fetch_html(url)
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text("\n", strip=True)
        website = ""
        for link in soup.select("a[href]"):
            href = clean_text(link.get("href"))
            if href.startswith("http") and "computextaipei.com.tw" not in href:
                website = href
                break
        desc = ""
        m = re.search(r"Description\s*(.+?)(?:\n(?:Exhibitor's Press Release|Brand Name|Products|Contact))", text, re.S)
        if m:
            desc = clean_text(m.group(1))
        return {"url": website, "pitch": desc}

    def parse_listing_card(self, card: Any, country: str) -> Optional[Dict[str, Any]]:
        name_el = card.select_one("h3")
        if not name_el:
            return None
        name = clean_text(name_el.get_text(" ", strip=True))
        if not name or name.lower() == "download":
            return None

        texts = [clean_text(x.get_text(" ", strip=True)) for x in card.select("a, span, p, div")]
        joined = "\n".join(t for t in texts if t)

        booth = ""
        booth_match = re.search(r"Physical Show\s*Booth No\.:\s*(.+?)\s*\n([A-Z0-9-]+)$", joined, re.S)
        if booth_match:
            booth = clean_text(booth_match.group(2))
        else:
            booth_link = card.select_one('a[href^="javascript:doBoothApplyMap"]')
            if booth_link:
                booth = clean_text(booth_link.get_text(" ", strip=True))

        product = ""
        prod_match = re.search(r"Products：\s*(.+?)\s*(?:Physical Show|Online Show|$)", joined, re.S)
        if prod_match:
            product = clean_text(prod_match.group(1))

        brand = ""
        brand_match = re.search(r"Brand Name：\s*(.+?)\s*Products：", joined, re.S)
        if brand_match:
            brand = clean_text(brand_match.group(1))

        tags = []
        for link in card.select('a[href^="javascript:searchExhTag"]'):
            tag = clean_text(link.get_text(" ", strip=True))
            if tag and tag not in tags:
                tags.append(tag)

        detail_href = ""
        detail_link = card.select_one('a[href*="/en/exhibitor/"][href*="/info.html"]')
        if detail_link:
            detail_href = urljoin(self.listing_url, detail_link.get("href"))

        record = {
            "name": name,
            "nameEn": brand or name,
            "booth": booth,
            "stage": STAGE_DEFAULT,
            "cats": infer_cats(product, " ".join(tags), brand, name),
            "product": product,
            "url": "",
            "country": country,
            "countryZh": COUNTRY_ZH.get(country, ""),
            "detailUrl": detail_href,
        }
        return record

    def run(self) -> SyncResult:
        exhibitors: List[Dict[str, Any]] = []
        for country, page_url in self.parse_country_pages():
            for listing_url in self.iter_listing_pages(page_url):
                html = fetch_html(listing_url)
                soup = BeautifulSoup(html, "html.parser")
                for card in soup.select(".company_list > ul > li"):
                    record = self.parse_listing_card(card, country)
                    if not record:
                        continue
                    if self.include_details and record.get("detailUrl"):
                        try:
                            detail = self.parse_detail_page(record["detailUrl"])
                            record["url"] = detail.get("url", "")
                            if detail.get("pitch"):
                                record["pitch"] = detail["pitch"]
                                record["pitchSource"] = "computex-detail"
                        except Exception:
                            pass
                    record.pop("detailUrl", None)
                    exhibitors.append({k: v for k, v in record.items() if v not in ("", [], False)})
        return SyncResult(conf_id=self.conf_id, source=self.source, exhibitors=dedupe_exhibitors(exhibitors))


def build_company_links() -> None:
    conferences = read_json(CONFERENCES_PATH)
    links: Dict[str, Dict[str, Any]] = {}
    for conf in conferences:
        conf_id = conf.get("id")
        if not conf_id:
            continue
        exhibitors = list((conf.get("detail") or {}).get("exhibitors") or [])
        bulk_path = DATA_DIR / f"{conf_id}.json"
        if bulk_path.exists():
            exhibitors.extend((read_json(bulk_path).get("exhibitors") or []))
        for item in exhibitors:
            name = clean_text(item.get("name") or item.get("nameEn") or item.get("nameZh"))
            if not name:
                continue
            key = normalize_host(item.get("url") or "") or normalize_name(name)
            if not key:
                continue
            entry = links.setdefault(
                key,
                {
                    "name": name,
                    "nameEn": clean_text(item.get("nameEn")),
                    "nameZh": clean_text(item.get("nameZh")),
                    "url": clean_text(item.get("url")),
                    "confIds": [],
                },
            )
            if conf_id not in entry["confIds"]:
                entry["confIds"].append(conf_id)
    payload = {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "companies": sorted(links.values(), key=lambda x: normalize_name(x.get("name", ""))),
    }
    write_json(COMPANY_LINKS_PATH, payload)


def run_sync(selected: str, include_details: bool) -> List[Path]:
    adapters: Dict[str, BaseAdapter] = {
        "Computex2025": ComputexAdapter(include_details=include_details),
        "WAIC2025": InlineSeedAdapter(
            "WAIC2025",
            "worldaic-inline-seed",
            "Official public full directory not yet stabilized for unattended crawling; seeded from curated inline records.",
        ),
        "SEMICONWest2025": InlineSeedAdapter(
            "SEMICONWest2025",
            "semiconwest-inline-seed",
            "Official exhibitor portal currently requires brittle ASP.NET postback traversal; seeded from curated inline records.",
        ),
        "MWC2025": InlineSeedAdapter(
            "MWC2025",
            "mwcbarcelona-inline-seed",
            "Official directory is JS/search driven; seeded from curated inline records until a stable unattended adapter is finalized.",
        ),
    }
    if selected == "all":
        order = ["Computex2025", *SEED_CONF_IDS]
    else:
        order = [selected]
    out: List[Path] = []
    for conf_id in order:
        adapter = adapters[conf_id]
        result = adapter.run()
        out.append(adapter.write(result))
        print(f"{conf_id}: wrote {len(result.exhibitors)} exhibitors from {result.source}")
    build_company_links()
    print(f"company-links: wrote {COMPANY_LINKS_PATH}")
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--conf", default="all", choices=["all", "Computex2025", "WAIC2025", "SEMICONWest2025", "MWC2025"])
    parser.add_argument("--skip-details", action="store_true", help="Skip detail-page enrichment for Computex.")
    args = parser.parse_args()
    run_sync(args.conf, include_details=not args.skip_details)


if __name__ == "__main__":
    main()
