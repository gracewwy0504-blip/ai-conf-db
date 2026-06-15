#!/usr/bin/env python3
"""Re-crawl company headquarters (HQ) and update registry + bulk exhibitor JSON."""
from __future__ import annotations

import argparse
import json
import re
import ssl
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
CACHE_PATH = ROOT / "exhibitor-data" / "hq-cache.json"
REGISTRY_PATH = ROOT / "exhibitor-data" / "company-registry.json"
BULK_FILES = [
    ROOT / "exhibitor-data" / "CES2026.json",
    ROOT / "exhibitor-data" / "GITEX2025.json",
]

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
WIKI_UA = "AI-Conf-DB-HQ-Bot/1.0 (local research; hq-enrichment)"

COUNTRY_ZH = {
    "united states": "美国",
    "united states of america": "美国",
    "usa": "美国",
    "u.s.a.": "美国",
    "u.s.": "美国",
    "us": "美国",
    "china": "中国",
    "people's republic of china": "中国",
    "prc": "中国",
    "united kingdom": "英国",
    "uk": "英国",
    "great britain": "英国",
    "england": "英国",
    "germany": "德国",
    "france": "法国",
    "japan": "日本",
    "south korea": "韩国",
    "korea": "韩国",
    "republic of korea": "韩国",
    "taiwan": "台湾",
    "hong kong": "香港",
    "hong kong sar": "香港",
    "hong kong sar, china": "香港",
    "macau": "澳门",
    "macao": "澳门",
    "singapore": "新加坡",
    "united arab emirates": "阿联酋",
    "uae": "阿联酋",
    "saudi arabia": "沙特阿拉伯",
    "india": "印度",
    "canada": "加拿大",
    "australia": "澳大利亚",
    "netherlands": "荷兰",
    "switzerland": "瑞士",
    "austria": "奥地利",
    "italy": "意大利",
    "spain": "西班牙",
    "portugal": "葡萄牙",
    "ireland": "爱尔兰",
    "sweden": "瑞典",
    "norway": "挪威",
    "denmark": "丹麦",
    "finland": "芬兰",
    "poland": "波兰",
    "czech republic": "捷克",
    "czechia": "捷克",
    "hungary": "匈牙利",
    "romania": "罗马尼亚",
    "bulgaria": "保加利亚",
    "serbia": "塞尔维亚",
    "croatia": "克罗地亚",
    "slovenia": "斯洛文尼亚",
    "greece": "希腊",
    "turkey": "土耳其",
    "türkiye": "土耳其",
    "ukraine": "乌克兰",
    "russia": "俄罗斯",
    "russian federation": "俄罗斯",
    "estonia": "爱沙尼亚",
    "latvia": "拉脱维亚",
    "lithuania": "立陶宛",
    "malaysia": "马来西亚",
    "indonesia": "印度尼西亚",
    "thailand": "泰国",
    "vietnam": "越南",
    "philippines": "菲律宾",
    "israel": "以色列",
    "mexico": "墨西哥",
    "brazil": "巴西",
    "argentina": "阿根廷",
    "south africa": "南非",
    "nigeria": "尼日利亚",
    "egypt": "埃及",
    "morocco": "摩洛哥",
    "qatar": "卡塔尔",
    "kuwait": "科威特",
    "bahrain": "巴林",
    "oman": "阿曼",
    "jordan": "约旦",
    "lebanon": "黎巴嫩",
    "pakistan": "巴基斯坦",
    "bangladesh": "孟加拉国",
    "new zealand": "新西兰",
    "belgium": "比利时",
    "luxembourg": "卢森堡",
    "iceland": "冰岛",
    "slovakia": "斯洛伐克",
    "cyprus": "塞浦路斯",
    "kazakhstan": "哈萨克斯坦",
    "uzbekistan": "乌兹别克斯坦",
    "nepal": "尼泊尔",
    "sri lanka": "斯里兰卡",
    "iran": "伊朗",
    "iraq": "伊拉克",
    "algeria": "阿尔及利亚",
    "tunisia": "突尼斯",
    "kenya": "肯尼亚",
    "ghana": "加纳",
    "chile": "智利",
    "colombia": "哥伦比亚",
    "peru": "秘鲁",
}

TRAD_ZH = {"美國": "美国", "韓國": "韩国", "英國": "英国", "德國": "德国", "法國": "法国", "日本": "日本"}
ZH_COUNTRY_ALIASES = {
    "中华人民共和国": "中国",
    "中華人民共和國": "中国",
    "美利坚合众国": "美国",
    "美利堅合眾國": "美国",
    "大韩民国": "韩国",
    "大韓民國": "韩国",
}

HOST_COUNTRY_BIAS = {
    "GITEX2025.json": "阿联酋",
    "MWC2025.json": "西班牙",
    "MWC2024.json": "西班牙",
    "IFA2025.json": "德国",
}


def reconcile_country_hit(
    best: Optional[Dict[str, Any]],
    names: List[str],
    url: str,
) -> Optional[Dict[str, Any]]:
    """Chinese/HK/TW names: English-site JSON-LD often lists a branch office, not HQ."""
    name_hit = country_from_name(names)
    if not name_hit:
        return best
    home_zh = name_hit.get("countryZh")
    if home_zh not in ("中国", "香港", "台湾"):
        return best
    host = norm_site(url)
    if not best:
        return name_hit
    if best.get("countryZh") == home_zh:
        return best
    # Chinese name + global .com etc.: weak domain/JSON-LD hits are often wrong (e.g. hesaitech.com → .ch false match)
    if home_zh == "中国" and best.get("countryZh") != "中国":
        if best.get("source") in ("jsonld", "website_text", "domain") and best.get("score", 0) < 90:
            if not host.endswith((".us", ".gov", ".cn", ".com.cn")):
                return {**name_hit, "score": 78, "source": "cn_name_override"}
    # English global site JSON-LD / scraped text → often US/EU sales office
    if best.get("source") in ("jsonld", "website_text"):
        if home_zh == "中国" and not host.endswith((".us", ".gov")):
            return {**name_hit, "score": 78, "source": "cn_name_override"}
        if home_zh in ("香港", "台湾") and not host.endswith((".hk", ".tw", ".us")):
            return {**name_hit, "score": 78, "source": "cn_name_override"}
    if (
        home_zh == "中国"
        and best.get("countryZh") == "美国"
        and best.get("source") == "website_text"
        and best.get("score", 0) < 85
        and not host.endswith(".us")
    ):
        return name_hit
    return best

DOMAIN_COUNTRY = [
    (".com.cn", "China", "中国", 75),
    (".cn", "China", "中国", 75),
    (".hk", "Hong Kong SAR", "香港", 75),
    (".tw", "Taiwan", "台湾", 75),
    (".co.kr", "South Korea", "韩国", 72),
    (".kr", "South Korea", "韩国", 72),
    (".co.jp", "Japan", "日本", 72),
    (".jp", "Japan", "日本", 72),
    (".de", "Germany", "德国", 72),
    (".fr", "France", "法国", 72),
    (".uk", "United Kingdom", "英国", 72),
    (".co.uk", "United Kingdom", "英国", 72),
    (".in", "India", "印度", 72),
    (".ae", "United Arab Emirates", "阿联酋", 72),
    (".sg", "Singapore", "新加坡", 72),
    (".nl", "Netherlands", "荷兰", 72),
    (".fi", "Finland", "芬兰", 72),
    (".se", "Sweden", "瑞典", 72),
    (".ch", "Switzerland", "瑞士", 72),
    (".it", "Italy", "意大利", 72),
    (".es", "Spain", "西班牙", 72),
    (".ca", "Canada", "加拿大", 72),
    (".au", "Australia", "澳大利亚", 72),
    (".il", "Israel", "以色列", 72),
    (".ru", "Russia", "俄罗斯", 72),
    (".br", "Brazil", "巴西", 72),
    (".mx", "Mexico", "墨西哥", 72),
    (".tr", "Turkey", "土耳其", 72),
    (".sa", "Saudi Arabia", "沙特阿拉伯", 72),
    (".za", "South Africa", "南非", 72),
    (".pl", "Poland", "波兰", 72),
    (".ro", "Romania", "罗马尼亚", 72),
    (".us", "United States", "美国", 70),
]

HQ_TEXT_PATTERNS = [
    re.compile(
        r"headquarters?\s*(?:located\s*)?(?:in|at|:)\s*([A-Za-z\u4e00-\u9fff][^<\n]{2,80})",
        re.I,
    ),
    re.compile(r"总部(?:位于|在|：|:)\s*([^\n<，,；;]{2,40})", re.I),
    re.compile(r"公司(?:总部|地址)(?:位于|在|：|:)\s*([^\n<，,；;]{2,40})", re.I),
]

COUNTRY_IN_TEXT = [
    (re.compile(r"\b(united states|u\.s\.a\.|usa|u\.s\.)\b", re.I), "United States", "美国", 68),
    (re.compile(r"\b(china|中国|beijing|shanghai|shenzhen|hangzhou|guangzhou|beijing)\b", re.I), "China", "中国", 68),
    (re.compile(r"\b(south korea|republic of korea|korea|首尔|韩国)\b", re.I), "South Korea", "韩国", 68),
    (re.compile(r"\b(japan|tokyo|osaka|日本)\b", re.I), "Japan", "日本", 68),
    (re.compile(r"\b(united kingdom|england|london|英国)\b", re.I), "United Kingdom", "英国", 68),
    (re.compile(r"\b(germany|berlin|munich|德国)\b", re.I), "Germany", "德国", 68),
    (re.compile(r"\b(france|paris|法国)\b", re.I), "France", "法国", 68),
    (re.compile(r"\b(india|bangalore|mumbai|delhi|印度)\b", re.I), "India", "印度", 68),
    (re.compile(r"\b(singapore|新加坡)\b", re.I), "Singapore", "新加坡", 68),
    (re.compile(r"\b(israel|tel aviv|以色列)\b", re.I), "Israel", "以色列", 68),
    (re.compile(r"\b(canada|toronto|vancouver|加拿大)\b", re.I), "Canada", "加拿大", 68),
    (re.compile(r"\b(australia|sydney|melbourne|澳大利亚)\b", re.I), "Australia", "澳大利亚", 68),
    (re.compile(r"\b(united arab emirates|uae|dubai|abu dhabi|阿联酋|迪拜)\b", re.I), "United Arab Emirates", "阿联酋", 65),
    (re.compile(r"\b(taiwan|taipei|台湾|台北)\b", re.I), "Taiwan", "台湾", 68),
    (re.compile(r"\b(hong kong|香港)\b", re.I), "Hong Kong SAR", "香港", 68),
    (re.compile(r"\b(romania|bucharest|罗马尼亚)\b", re.I), "Romania", "罗马尼亚", 68),
    (re.compile(r"\b(spain|madrid|barcelona|西班牙)\b", re.I), "Spain", "西班牙", 68),
    (re.compile(r"\b(serbia|belgrade|塞尔维亚)\b", re.I), "Serbia", "塞尔维亚", 68),
    (re.compile(r"\b(morocco|摩洛哥)\b", re.I), "Morocco", "摩洛哥", 68),
    (re.compile(r"\b(saudi arabia|riyadh|沙特阿拉伯)\b", re.I), "Saudi Arabia", "沙特阿拉伯", 68),
    (re.compile(r"\b(russia|moscow|俄罗斯)\b", re.I), "Russia", "俄罗斯", 68),
    (re.compile(r"\b(turkey|istanbul|土耳其)\b", re.I), "Turkey", "土耳其", 68),
    (re.compile(r"\b(netherlands|amsterdam|荷兰)\b", re.I), "Netherlands", "荷兰", 68),
    (re.compile(r"\b(switzerland|zurich|瑞士)\b", re.I), "Switzerland", "瑞士", 68),
    (re.compile(r"\b(sweden|stockholm|瑞典)\b", re.I), "Sweden", "瑞典", 68),
    (re.compile(r"\b(finland|helsinki|芬兰)\b", re.I), "Finland", "芬兰", 68),
    (re.compile(r"\b(italy|milan|rome|意大利)\b", re.I), "Italy", "意大利", 68),
]

import threading

SSL_CTX = ssl.create_default_context()
_wiki_last = 0.0
_wiki_lock = threading.Lock()
_cache_lock = threading.Lock()


def normalize_zh(zh: str) -> str:
    zh = (zh or "").strip()
    zh = TRAD_ZH.get(zh, zh)
    return ZH_COUNTRY_ALIASES.get(zh, zh)


def country_to_zh(name: str) -> str:
    if not name:
        return ""
    raw = str(name).strip()
    key = raw.lower().replace("  ", " ")
    if key in ("other", "-", "n/a"):
        return ""
    if key in COUNTRY_ZH:
        return COUNTRY_ZH[key]
    if "united states" in key:
        return "美国"
    if "taiwan" in key:
        return "台湾"
    if "hong kong" in key:
        return "香港"
    if "china" in key:
        return "中国"
    if "korea" in key and "north" not in key:
        return "韩国"
    short = key.split(",")[0].strip()
    return COUNTRY_ZH.get(short, raw)


def norm_site(url: str) -> str:
    if not url:
        return ""
    u = url.strip().lower()
    if not u.startswith("http"):
        u = "https://" + u
    try:
        host = urlparse(u).netloc.lower().replace("www.", "")
        return host.split(":")[0]
    except Exception:
        return ""


def has_chinese(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text or ""))


def fetch_url(url: str, wiki: bool = False, timeout: int = 12) -> str:
    req = Request(url, headers={"User-Agent": WIKI_UA if wiki else UA, "Accept": "*/*"})
    try:
        with urlopen(req, timeout=timeout, context=SSL_CTX) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        raise URLError(str(exc)) from exc


def wiki_throttle(min_gap: float = 1.15) -> None:
    global _wiki_last
    with _wiki_lock:
        now = time.time()
        wait = min_gap - (now - _wiki_last)
        if wait > 0:
            time.sleep(wait)
        _wiki_last = time.time()


def wiki_json(params: Dict[str, str]) -> Any:
    from urllib.parse import urlencode

    wiki_throttle()
    url = "https://www.wikidata.org/w/api.php?" + urlencode(params)
    return json.loads(fetch_url(url, wiki=True))


def wikidata_hq(names: List[str]) -> Optional[Dict[str, Any]]:
    search_terms = []
    for n in names:
        n = (n or "").strip()
        if not n or len(n) < 2:
            continue
        if n not in search_terms:
            search_terms.append(n)
    for term in search_terms[:4]:
        try:
            data = wiki_json(
                {
                    "action": "wbsearchentities",
                    "search": term,
                    "language": "en",
                    "format": "json",
                    "limit": "5",
                }
            )
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
            continue
        hits = data.get("search") or []
        if not hits:
            continue
        for hit in hits[:3]:
            eid = hit.get("id")
            if not eid:
                continue
            try:
                ent = wiki_json(
                    {
                        "action": "wbgetentities",
                        "ids": eid,
                        "props": "claims|labels",
                        "format": "json",
                        "languages": "en|zh",
                    }
                )["entities"][eid]
            except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, KeyError):
                continue
            countries = set()
            loc_ids = []
            for claim in ent.get("claims", {}).get("P159", []):
                try:
                    loc_ids.append(claim["mainsnak"]["datavalue"]["value"]["id"])
                except (KeyError, TypeError):
                    pass
            for claim in ent.get("claims", {}).get("P17", []):
                try:
                    countries.add(claim["mainsnak"]["datavalue"]["value"]["id"])
                except (KeyError, TypeError):
                    pass
            if loc_ids:
                try:
                    locs = wiki_json(
                        {
                            "action": "wbgetentities",
                            "ids": "|".join(loc_ids[:5]),
                            "props": "claims",
                            "format": "json",
                        }
                    )["entities"]
                    for le in locs.values():
                        for claim in le.get("claims", {}).get("P17", []):
                            try:
                                countries.add(claim["mainsnak"]["datavalue"]["value"]["id"])
                            except (KeyError, TypeError):
                                pass
                except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, KeyError):
                    pass
            if not countries:
                continue
            cid = sorted(countries)[0]
            try:
                c = wiki_json(
                    {
                        "action": "wbgetentities",
                        "ids": cid,
                        "props": "labels",
                        "format": "json",
                        "languages": "en|zh",
                    }
                )["entities"][cid]
            except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, KeyError):
                continue
            en = (c.get("labels", {}).get("en") or {}).get("value") or ""
            zh = normalize_zh((c.get("labels", {}).get("zh") or {}).get("value") or "")
            if not zh and en:
                zh = country_to_zh(en)
            if en or zh:
                return {
                    "country": en or zh,
                    "countryZh": zh or country_to_zh(en),
                    "source": "wikidata",
                    "score": 90,
                    "qid": eid,
                }
    return None


def iter_jsonld_nodes(node: Any):
    if isinstance(node, list):
        for item in node:
            yield from iter_jsonld_nodes(item)
    elif isinstance(node, dict):
        yield node
        for key in ("@graph", "mainEntity", "hasPart"):
            if key in node:
                yield from iter_jsonld_nodes(node[key])


def country_from_jsonld(html: str) -> Optional[Dict[str, Any]]:
    for block in re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        re.S | re.I,
    ):
        try:
            data = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        for node in iter_jsonld_nodes(data):
            if not isinstance(node, dict):
                continue
            typ = node.get("@type") or ""
            if isinstance(typ, list):
                typ = " ".join(typ)
            if not re.search(r"Organization|Corporation|Company|LocalBusiness", str(typ), re.I):
                continue
            addr = node.get("address")
            if isinstance(addr, list):
                addr = addr[0] if addr else {}
            if not isinstance(addr, dict):
                continue
            country = addr.get("addressCountry") or addr.get("addressRegion")
            if not country:
                continue
            if isinstance(country, dict):
                country = country.get("name") or country.get("@id") or ""
            zh = country_to_zh(str(country))
            en = str(country).strip()
            if len(en) == 2:
                iso = en.upper()
                iso_map = {
                    "US": ("United States", "美国"),
                    "CN": ("China", "中国"),
                    "GB": ("United Kingdom", "英国"),
                    "DE": ("Germany", "德国"),
                    "FR": ("France", "法国"),
                    "JP": ("Japan", "日本"),
                    "KR": ("South Korea", "韩国"),
                    "IN": ("India", "印度"),
                    "SG": ("Singapore", "新加坡"),
                    "AE": ("United Arab Emirates", "阿联酋"),
                    "CA": ("Canada", "加拿大"),
                    "AU": ("Australia", "澳大利亚"),
                    "HK": ("Hong Kong SAR", "香港"),
                    "TW": ("Taiwan", "台湾"),
                }
                if iso in iso_map:
                    en, zh = iso_map[iso]
            if zh or en:
                return {
                    "country": en,
                    "countryZh": zh or country_to_zh(en),
                    "source": "jsonld",
                    "score": 85,
                }
    return None


def country_from_text(html: str) -> Optional[Dict[str, Any]]:
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    for pat in HQ_TEXT_PATTERNS:
        m = pat.search(text)
        if not m:
            continue
        snippet = m.group(1)
        for regex, en, zh, score in COUNTRY_IN_TEXT:
            if regex.search(snippet) or regex.search(text[:5000]):
                return {"country": en, "countryZh": zh, "source": "website_text", "score": score}
    for regex, en, zh, score in COUNTRY_IN_TEXT:
        if regex.search(text[:8000]):
            return {"country": en, "countryZh": zh, "source": "website_text", "score": score - 8}
    return None


def country_from_domain(url: str) -> Optional[Dict[str, Any]]:
    host = norm_site(url)
    if not host:
        return None
    for suffix, en, zh, score in sorted(DOMAIN_COUNTRY, key=lambda x: len(x[0]), reverse=True):
        if host.endswith(suffix) or host == suffix.lstrip("."):
            return {"country": en, "countryZh": zh, "source": "domain", "score": score}
    return None


def country_from_name(names: List[str]) -> Optional[Dict[str, Any]]:
    blob = " ".join(n for n in names if n)
    if has_chinese(blob):
        if re.search(r"香港|hong\s*kong", blob, re.I):
            return {"country": "Hong Kong SAR", "countryZh": "香港", "source": "name", "score": 58}
        if re.search(r"台湾|taiwan|台北", blob, re.I):
            return {"country": "Taiwan", "countryZh": "台湾", "source": "name", "score": 58}
        return {"country": "China", "countryZh": "中国", "source": "name", "score": 55}
    return None


def scrape_website(url: str) -> Optional[Dict[str, Any]]:
    if not url:
        return None
    base = url.strip()
    if not base.startswith("http"):
        base = "https://" + base
    root = re.sub(r"/+$", "", base)
    pages = [base, root + "/about"]
    seen = set()
    best = None
    for page in pages:
        if page in seen:
            continue
        seen.add(page)
        try:
            html = fetch_url(page, timeout=12)
        except (HTTPError, URLError, TimeoutError):
            continue
        for fn in (country_from_jsonld, country_from_text):
            hit = fn(html)
            if hit and (not best or hit["score"] > best["score"]):
                best = hit
        if best and best["score"] >= 85:
            return best
    return best


def resolve_hq(
    record: Dict[str, Any],
    cache: Dict[str, Any],
    use_wiki: bool = True,
    wiki_if_missing: bool = True,
) -> Dict[str, Any]:
    site = norm_site(record.get("url", ""))
    key = site or (record.get("nameEn") or record.get("nameZh") or record.get("name") or "").lower().strip()
    if not key:
        return {"country": "", "countryZh": "", "source": "none", "score": 0}
    with _cache_lock:
        if key in cache and cache[key].get("countryZh"):
            return cache[key]

    names = [
        record.get("nameEn"),
        record.get("name"),
        record.get("nameZh"),
    ]
    best = None

    domain_hit = country_from_domain(record.get("url", ""))
    if domain_hit:
        best = domain_hit

    if not best or best.get("score", 0) < 72:
        web_hit = scrape_website(record.get("url", ""))
        if web_hit and (not best or web_hit["score"] > best["score"]):
            best = web_hit

    if use_wiki and (not wiki_if_missing or not best):
        wiki_hit = wikidata_hq(names)
        if wiki_hit and (not best or wiki_hit["score"] > best["score"]):
            best = wiki_hit

    name_hit = country_from_name(names)
    if name_hit and (not best or name_hit["score"] > best["score"]):
        best = name_hit

    best = reconcile_country_hit(best, names, record.get("url", ""))

    if not best:
        result = {"country": "", "countryZh": "", "source": "none", "score": 0}
    else:
        result = {
            "country": best.get("country", ""),
            "countryZh": normalize_zh(best.get("countryZh") or country_to_zh(best.get("country", ""))),
            "source": best.get("source", ""),
            "score": best.get("score", 0),
        }
        if result["country"] and not result["countryZh"]:
            result["countryZh"] = country_to_zh(result["country"])
        if result["countryZh"] in ZH_COUNTRY_ALIASES:
            result["countryZh"] = ZH_COUNTRY_ALIASES[result["countryZh"]]

    payload = {
        **result,
        "url": record.get("url", ""),
        "names": [n for n in names if n],
        "ts": int(time.time()),
    }
    with _cache_lock:
        cache[key] = payload
    return result


def collect_targets(scope: str) -> List[Dict[str, Any]]:
    targets: Dict[str, Dict[str, Any]] = {}

    def add(rec: Dict[str, Any]) -> None:
        site = norm_site(rec.get("url", ""))
        key = site or (rec.get("nameEn") or rec.get("nameZh") or rec.get("name") or "").lower().strip()
        if not key:
            return
        prev = targets.get(key)
        if not prev:
            targets[key] = dict(rec)
            return
        for field in ("name", "nameEn", "nameZh", "url"):
            if not prev.get(field) and rec.get(field):
                prev[field] = rec[field]

    if scope in ("registry", "all"):
        reg = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        seen_zh = set()
        for v in reg.values():
            name_zh = v.get("nameZh") or ""
            if name_zh and name_zh in seen_zh:
                continue
            if name_zh:
                seen_zh.add(name_zh)
            add(
                {
                    "name": v.get("nameEn") or name_zh,
                    "nameEn": v.get("nameEn") or "",
                    "nameZh": name_zh,
                    "url": v.get("url") or "",
                }
            )

    if scope in ("bulk", "all"):
        for path in BULK_FILES:
            data = json.loads(path.read_text(encoding="utf-8"))
            for e in data.get("exhibitors") or []:
                add(e)

    return list(targets.values())


def load_cache() -> Dict[str, Any]:
    if CACHE_PATH.exists():
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    return {}


def save_cache(cache: Dict[str, Any]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def crawl(
    scope: str,
    limit: Optional[int],
    workers: int,
    use_wiki: bool,
    wiki_if_missing: bool,
    refresh: bool,
) -> Dict[str, Any]:
    cache = load_cache()
    if refresh:
        cache = {}
    else:
        # drop failed/error cache rows so they can be retried
        cache = {k: v for k, v in cache.items() if v.get("source") != "error"}

    targets = collect_targets(scope)
    if limit:
        targets = targets[:limit]

    todo = []
    for rec in targets:
        site = norm_site(rec.get("url", ""))
        key = site or (rec.get("nameEn") or rec.get("nameZh") or rec.get("name") or "").lower().strip()
        if refresh or not cache.get(key, {}).get("countryZh"):
            todo.append(rec)

    print(f"targets={len(targets)} todo={len(todo)} cached={len(targets)-len(todo)}")

    done = 0
    if workers <= 1:
        for rec in todo:
            site = norm_site(rec.get("url", ""))
            key = site or (rec.get("nameEn") or rec.get("nameZh") or rec.get("name") or "").lower().strip()
            try:
                hit = resolve_hq(rec, cache, use_wiki=use_wiki, wiki_if_missing=wiki_if_missing)
            except Exception as exc:
                with _cache_lock:
                    cache[key] = {
                        "country": "",
                        "countryZh": "",
                        "source": "error",
                        "score": 0,
                        "error": str(exc),
                    }
                hit = cache[key]
            done += 1
            if done % 25 == 0:
                save_cache(cache)
                print(f"  progress {done}/{len(todo)} last={key} -> {hit.get('countryZh')} ({hit.get('source')})")
    else:
        lock_save_every = 50
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(resolve_hq, rec, cache, use_wiki, wiki_if_missing): rec for rec in todo
            }
            for fut in as_completed(futures):
                rec = futures[fut]
                try:
                    hit = fut.result()
                except Exception as exc:
                    site = norm_site(rec.get("url", ""))
                    key = site or rec.get("name", "")
                    with _cache_lock:
                        cache[key] = {
                            "country": "",
                            "countryZh": "",
                            "source": "error",
                            "score": 0,
                            "error": str(exc),
                        }
                    hit = cache[key]
                done += 1
                if done % lock_save_every == 0:
                    save_cache(cache)
                    print(f"  progress {done}/{len(todo)}")
                if done % 100 == 0:
                    site = norm_site(rec.get("url", ""))
                    key = site or rec.get("name", "")
                    print(f"    last={key} -> {hit.get('countryZh')} ({hit.get('source')})")

    save_cache(cache)
    filled = sum(1 for v in cache.values() if v.get("countryZh"))
    print(f"cache entries={len(cache)} with HQ={filled}")
    return cache


def pick_hq_for_record(
    record: Dict[str, Any],
    cache: Dict[str, Any],
    conf_file: str = "",
) -> Optional[Dict[str, Any]]:
    site = norm_site(record.get("url", ""))
    key = site or (record.get("nameEn") or record.get("nameZh") or record.get("name") or "").lower().strip()
    hit = cache.get(key) or cache.get(site)
    if hit and hit.get("countryZh") and hit.get("score", 0) >= 55:
        return hit

    old_zh = (record.get("countryZh") or country_to_zh(record.get("country") or "")).strip()
    host_bias = HOST_COUNTRY_BIAS.get(conf_file, "")
    if old_zh and host_bias and old_zh == host_bias:
        domain_hit = country_from_domain(record.get("url", ""))
        name_hit = country_from_name([record.get("nameEn"), record.get("name"), record.get("nameZh")])
        for candidate in (domain_hit, name_hit):
            if candidate and candidate.get("countryZh") and candidate["countryZh"] != old_zh:
                return candidate
        if hit and hit.get("countryZh"):
            return hit
        return None

    if old_zh:
        return {"country": record.get("country") or old_zh, "countryZh": old_zh, "source": "legacy", "score": 45}
    return hit if hit and hit.get("countryZh") else None


def apply_cache(cache: Dict[str, Any]) -> Tuple[int, int, int]:
    reg_changed = 0
    reg = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    for k, v in reg.items():
        hit = pick_hq_for_record(v, cache)
        if not hit or not hit.get("countryZh"):
            continue
        if v.get("countryZh") != hit["countryZh"] or v.get("country") != hit.get("country"):
            v["country"] = hit.get("country") or hit["countryZh"]
            v["countryZh"] = hit["countryZh"]
            reg_changed += 1
    REGISTRY_PATH.write_text(json.dumps(reg, ensure_ascii=False, indent=2), encoding="utf-8")

    bulk_changed = 0
    for path in BULK_FILES:
        data = json.loads(path.read_text(encoding="utf-8"))
        local = 0
        for e in data.get("exhibitors") or []:
            hit = pick_hq_for_record(e, cache, conf_file=path.name)
            if not hit or not hit.get("countryZh"):
                if HOST_COUNTRY_BIAS.get(path.name) and (e.get("countryZh") or "") == HOST_COUNTRY_BIAS[path.name]:
                    e["country"] = ""
                    e["countryZh"] = ""
                    local += 1
                continue
            new_zh = hit["countryZh"]
            new_en = hit.get("country") or new_zh
            if e.get("countryZh") != new_zh or e.get("country") != new_en:
                e["country"] = new_en
                e["countryZh"] = new_zh
                local += 1
        if local:
            path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ": ")), encoding="utf-8")
            bulk_changed += local
            print(f"updated {path.name}: {local} exhibitors")

    print(f"registry changed={reg_changed}, bulk changed={bulk_changed}")
    return reg_changed, bulk_changed, len(cache)


def main() -> None:
    parser = argparse.ArgumentParser(description="Re-crawl company HQ and update data files")
    parser.add_argument("--scope", choices=["registry", "bulk", "all"], default="all")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of companies (0=all)")
    parser.add_argument("--workers", type=int, default=6, help="Parallel workers for website fetch")
    parser.add_argument("--no-wiki", action="store_true", help="Skip Wikidata lookups")
    parser.add_argument("--wiki-always", action="store_true", help="Query Wikidata even when website/domain matched")
    parser.add_argument("--refresh", action="store_true", help="Re-fetch even if cached")
    parser.add_argument("--apply-only", action="store_true", help="Only apply existing cache")
    parser.add_argument("--crawl-only", action="store_true", help="Only crawl, do not write data files")
    args = parser.parse_args()

    limit = args.limit or None
    if args.apply_only:
        cache = load_cache()
        apply_cache(cache)
        return

    cache = crawl(
        scope=args.scope,
        limit=limit,
        workers=max(1, args.workers),
        use_wiki=not args.no_wiki,
        wiki_if_missing=not args.wiki_always,
        refresh=args.refresh,
    )
    if not args.crawl_only:
        apply_cache(cache)


if __name__ == "__main__":
    main()
