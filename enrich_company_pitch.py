#!/usr/bin/env python3
"""Clean company intro/product fields and enrich pitch + exhibitProduct in bulk JSON & registry."""
from __future__ import annotations

import argparse
import json
import re
import ssl
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
REGISTRY_PATH = ROOT / "exhibitor-data" / "company-registry.json"
PITCH_CACHE_PATH = ROOT / "exhibitor-data" / "pitch-cache.json"
BULK_FILES = [
    ROOT / "exhibitor-data" / "CES2026.json",
    ROOT / "exhibitor-data" / "GITEX2025.json",
]

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
SSL_CTX = ssl.create_default_context()
EXHIBIT_MARKER = "【参展产品】"

PRODUCT_KW = re.compile(
    r"(机器人|人形|大模型|LLM|GPT|芯片|GPU|NPU|平台|助手|Agent|Copilot|"
    r"Cloud|眼镜|LiDAR|雷达|服务器|数据库|框架|SDK|API|Model|系列|"
    r"手机|PC|IoT|AIoT|无人机|机械臂|灵巧手|外骨骼|视频生成|自动驾驶)",
    re.I,
)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_website(url: str) -> str:
    u = str(url or "").strip().lower()
    if not u:
        return ""
    u = re.sub(r"^https?://", "", u)
    u = u.split("/")[0].split("?")[0]
    if u.startswith("www."):
        u = u[4:]
    return u


def normalize_registry_name(name: str) -> str:
    n = str(name or "").lower().strip()
    n = re.sub(r"\([^)]*\)", " ", n)
    n = re.sub(
        r"\b(incorporated|corporation|company|limited|ltd|llc|corp|co|gmbh|ag|plc|bv|pty)\b\.?",
        " ",
        n,
    )
    n = re.sub(r"[^a-z0-9\u4e00-\u9fff\s&+.-]", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n


def company_names(record: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    for k in ("name", "nameZh", "nameEn"):
        v = str(record.get(k) or "").strip()
        if v:
            out.append(v)
    return sorted(set(out), key=len, reverse=True)


def strip_company_names(text: str, names: List[str]) -> str:
    p = str(text or "").strip()
    if not p:
        return ""
    for n in names:
        if not n:
            continue
        esc = re.escape(n)
        p = re.sub(rf"^{esc}\s*[,，]?\s*", "", p, flags=re.I)
        p = re.sub(rf"^{esc}\s+", "", p, flags=re.I)
    p = re.sub(r"^[\w\u4e00-\u9fff\s&+.()-]{2,48}\s*(是(一个|一家)?)", r"是一\2", p)
    p = re.sub(r"^成立于\d{4}年?[，,]\s*", "", p)
    p = re.sub(r"^它(?=以)", "", p)
    return p.strip()


def is_curated_exhibit(text: str) -> bool:
    p = str(text or "").strip()
    if not p:
        return False
    if EXHIBIT_MARKER in p:
        return True
    if re.search(r"是一家|致力于|专注于|成立于|我们打造|We are|Our company|company dedicated|product-oriented platform", p, re.I):
        return False
    cjk = len(re.findall(r"[\u4e00-\u9fff]", p))
    return cjk >= 6 and cjk / max(len(p), 1) > 0.25 and len(p) <= 220


def is_company_intro(text: str) -> bool:
    p = str(text or "").strip()
    if not p:
        return True
    if is_curated_exhibit(p):
        return False
    if EXHIBIT_MARKER in p:
        return False
    if re.search(
        r"^(Established|Founded|We are|We build|We create|Our company|Since \d{4}|"
        r"At \w+|With over|is a .*(company|platform|provider|leader|startup|organization))",
        p,
        re.I,
    ):
        return True
    if re.search(r"company dedicated to|product-oriented platform|global leader in", p, re.I):
        return True
    if re.search(r"成立于\s*\d{4}|是一家.{2,80}|是一个.{2,40}(组织|联盟|协会|机构|非营利)", p):
        return True
    if re.search(r"^我们是一(个|家)", p):
        return True
    if "我们打造" in p:
        return True
    if re.search(r"致力于.{4,}|专注于.{4,}|汇聚了全球|leading .{0,20} company", p, re.I):
        return True
    if re.search(r"[\u4e00-\u9fff]", p) and re.search(r"(公司|企业|平台).{0,12}(致力于|专注于|是一家)", p):
        return True
    if len(p) > 80 and "是一家" in p:
        return True
    if len(p) > 140 and len(re.findall(r"[\u4e00-\u9fff]", p)) < 6:
        return True
    return False


def is_product_like(text: str) -> bool:
    p = str(text or "").strip()
    if not p or is_company_intro(p):
        return False
    if EXHIBIT_MARKER in p:
        return True
    if len(p) > 120:
        return False
    if re.search(r"^(Established|Founded|We are|Our company)", p, re.I):
        return False
    if PRODUCT_KW.search(p):
        return True
    if len(p) <= 80 and not re.search(r"(是一家|致力于|成立于|我们打造|我们致力于)", p):
        return True
    return False


def normalize_pitch(text: str, names: List[str]) -> str:
    p = strip_company_names(text, names)
    if not p:
        return ""
    p = p.replace("。它以", "。以").replace("。它通过", "。通过")
    if not re.search(r"[。！？]$", p):
        p += "。"
    return p


def intro_to_pitch(intro: str, names: List[str]) -> str:
    p = strip_company_names(intro, names)
    p = re.sub(r"^成立于\d{4}年?[，,]\s*", "", p)
    if re.match(r"^是一(个|家)", p) and "为核心价值" in p:
        return normalize_pitch(p, names)
    kind = re.search(r"是一(个|家)([^。；]+)", p)
    if kind:
        what = kind.group(2).strip("。； ")
        core_m = re.search(r"以[「\"']([^」\"']+)[」\"']", p)
        dedicated_m = re.search(r"致力于([^。；]+)", p)
        core = core_m.group(1) if core_m else ""
        if not core and dedicated_m:
            core = dedicated_m.group(1).strip()
        if not core and what.startswith("致力于"):
            core = what.replace("致力于", "", 1).strip()
        if not core and len(what) <= 36:
            core = what
        team_m = re.search(r"(通过[^。；]+|团队[^。；]+)", p)
        if core:
            team = team_m.group(1) if team_m else "团队专注产品研发与行业落地"
            return normalize_pitch(
                f"是一{kind.group(1)}{what}。以「{core}」为核心价值，{team}。",
                names,
            )
        return normalize_pitch(f"是一{kind.group(1)}{what}。", names)
    if p.startswith("我们") or re.match(r"^[A-Z][a-z].{20,}", p):
        suffix = "" if re.search(r"团队|through|team", p, re.I) else "，团队专注产品创新与市场落地"
        return normalize_pitch(p.rstrip("。") + suffix + "。", names)
    if len(p) >= 16:
        return normalize_pitch(p, names)
    return ""


def extract_exhibit_product(text: str) -> str:
    p = str(text or "").strip()
    if EXHIBIT_MARKER not in p:
        return ""
    return p.replace(EXHIBIT_MARKER, "").strip()


def pick_better_pitch(current: str, candidate: str) -> str:
    cur = str(current or "").strip()
    cand = str(candidate or "").strip()
    if not cand:
        return cur
    if not cur:
        return cand
    if "为核心价值" in cand and "为核心价值" not in cur:
        return cand
    return cand if len(cand) >= len(cur) else cur


def pick_better_product(current: str, candidate: str) -> str:
    cur = str(current or "").strip()
    cand = str(candidate or "").strip()
    if not cand or is_company_intro(cand):
        return cur
    if not cur or is_company_intro(cur):
        return cand
    if is_product_like(cand) and not is_product_like(cur):
        return cand
    return cur if len(cur) >= len(cand) else cand


def classify_field(text: str, names: List[str]) -> Tuple[str, Optional[str], Optional[str]]:
    """Return (kind, pitch, product_or_exhibit) where kind is exhibit|intro|product|empty."""
    p = str(text or "").strip()
    if not p:
        return "empty", None, None
    if EXHIBIT_MARKER in p:
        return "exhibit", None, extract_exhibit_product(p)
    if is_company_intro(p):
        return "intro", intro_to_pitch(p, names), None
    if is_product_like(p):
        return "product", None, p
    if len(p) <= 160:
        return "product", None, p
    return "intro", intro_to_pitch(p, names), None


def enrich_exhibitor(record: Dict[str, Any], stats: Dict[str, int]) -> bool:
    changed = False
    names = company_names(record)
    raw = str(record.get("productZh") or record.get("product") or "").strip()

    if record.get("pitchVerified"):
        # still fix product if polluted
        if raw and is_company_intro(raw) and not record.get("pitch"):
            record["pitch"] = intro_to_pitch(raw, names)
            record["pitchSource"] = record.get("pitchSource") or "intro-migration"
            record["product"] = ""
            record["productZh"] = ""
            stats["intro_migrated"] += 1
            changed = True
        return changed

    exhibit_from_field = extract_exhibit_product(raw)
    kind, pitch, product = classify_field(raw, names)

    if kind == "exhibit":
        if record.get("exhibitProductZh") != product:
            record["exhibitProductZh"] = product
            record["exhibitProduct"] = product
            stats["exhibit_set"] += 1
            changed = True
        if record.get("product") or record.get("productZh"):
            record["product"] = ""
            record["productZh"] = ""
            stats["product_cleared"] += 1
            changed = True
    elif kind == "intro":
        if pitch and pick_better_pitch(record.get("pitch", ""), pitch) == pitch:
            record["pitch"] = pitch
            record["pitchSource"] = "intro-migration"
            record["pitchVerified"] = False
            stats["intro_migrated"] += 1
            changed = True
        if record.get("product") or record.get("productZh"):
            record["product"] = ""
            record["productZh"] = ""
            stats["product_cleared"] += 1
            changed = True
    elif kind == "product" and product:
        if record.get("productZh") != product or record.get("product") != product:
            record["product"] = product
            record["productZh"] = product
            stats["product_kept"] += 1
            changed = True
    elif kind == "empty":
        stats["empty"] += 1

    # preserve explicit exhibit field if already split
    if exhibit_from_field and not record.get("exhibitProductZh"):
        record["exhibitProductZh"] = exhibit_from_field
        record["exhibitProduct"] = exhibit_from_field
        changed = True

    return changed


def process_bulk(path: Path, stats: Dict[str, int]) -> int:
    data = load_json(path)
    changed = 0
    for ex in data.get("exhibitors") or []:
        if enrich_exhibitor(ex, stats):
            changed += 1
    if changed:
        save_json(path, data)
    return changed


def enrich_registry(registry: Dict[str, Any], domain_pitch: Dict[str, str], stats: Dict[str, int]) -> int:
    changed = 0
    for key, entry in registry.items():
        if not isinstance(entry, dict):
            continue
        rec = {"name": key, **entry}
        names = company_names(rec)
        raw = str(entry.get("productZh") or entry.get("product") or "").strip()

        if entry.get("pitchVerified"):
            if raw and is_company_intro(raw):
                entry["product"] = ""
                entry["productZh"] = ""
                changed += 1
                stats["registry_product_cleared"] += 1
            continue

        if entry.get("pitch") and not is_company_intro(entry.get("pitch", "")):
            if raw and is_company_intro(raw):
                entry["product"] = pick_better_product("", entry.get("productZh", ""))
                entry["productZh"] = entry["product"]
                if is_company_intro(entry["productZh"] or ""):
                    entry["product"] = ""
                    entry["productZh"] = ""
                changed += 1
            continue

        if raw:
            kind, pitch, product = classify_field(raw, names)
            if kind == "intro" and pitch:
                entry["pitch"] = pitch
                entry["pitchSource"] = "intro-migration"
                entry["pitchVerified"] = False
                entry["product"] = ""
                entry["productZh"] = ""
                stats["registry_intro_migrated"] += 1
                changed += 1
            elif kind == "exhibit":
                entry["exhibitProductZh"] = product
                entry["exhibitProduct"] = product
                entry["product"] = ""
                entry["productZh"] = ""
                stats["registry_exhibit_set"] += 1
                changed += 1
            elif kind == "product" and product:
                entry["product"] = product
                entry["productZh"] = product

        host = normalize_website(entry.get("url", ""))
        if host and host in domain_pitch and not entry.get("pitch"):
            entry["pitch"] = domain_pitch[host]
            entry["pitchSource"] = "bulk-merge"
            entry["pitchVerified"] = False
            stats["registry_pitch_merged"] += 1
            changed += 1

    return changed


def collect_domain_pitches() -> Dict[str, str]:
    out: Dict[str, str] = {}
    for path in BULK_FILES:
        if not path.exists():
            continue
        data = load_json(path)
        for ex in data.get("exhibitors") or []:
            pitch = str(ex.get("pitch") or "").strip()
            if not pitch:
                continue
            host = normalize_website(ex.get("url", ""))
            if not host:
                continue
            out[host] = pick_better_pitch(out.get(host, ""), pitch)
    return out


def fetch_meta_description(url: str) -> str:
    if not url:
        return ""
    if not url.startswith("http"):
        url = "https://" + url
    req = Request(url, headers={"User-Agent": UA, "Accept": "text/html,*/*"})
    try:
        with urlopen(req, timeout=14, context=SSL_CTX) as resp:
            html = resp.read().decode("utf-8", "replace", errors="replace")[:120000]
    except (HTTPError, URLError, TimeoutError, OSError):
        return ""
    for pat in [
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']description["\']',
    ]:
        m = re.search(pat, html, re.I)
        if m:
            return re.sub(r"\s+", " ", m.group(1)).strip()
    return ""


def web_enrich_registry(registry: Dict[str, Any], limit: int, stats: Dict[str, int]) -> int:
    cache: Dict[str, Any] = {}
    if PITCH_CACHE_PATH.exists():
        cache = load_json(PITCH_CACHE_PATH)
    changed = 0
    candidates = [
        (k, v)
        for k, v in registry.items()
        if isinstance(v, dict)
        and v.get("url")
        and not v.get("pitch")
        and not v.get("pitchVerified")
    ]
    candidates = candidates[:limit]
    for key, entry in candidates:
        host = normalize_website(entry.get("url", ""))
        if host and cache.get(host, {}).get("pitch"):
            entry["pitch"] = cache[host]["pitch"]
            entry["pitchSource"] = "website-cache"
            entry["pitchVerified"] = False
            stats["web_cache_hit"] += 1
            changed += 1
            continue
        desc = fetch_meta_description(entry.get("url", ""))
        time.sleep(0.35)
        if not desc or len(desc) < 20:
            continue
        names = company_names({"name": key, **entry})
        pitch = intro_to_pitch(desc, names) if is_company_intro(desc) else normalize_pitch(desc, names)
        if pitch:
            entry["pitch"] = pitch
            entry["pitchSource"] = "website-meta"
            entry["pitchVerified"] = False
            cache[host] = {"pitch": pitch, "url": entry.get("url"), "source": "website-meta"}
            stats["web_fetched"] += 1
            changed += 1
    save_json(PITCH_CACHE_PATH, cache)
    return changed


def main() -> None:
    parser = argparse.ArgumentParser(description="Enrich company pitch/product fields")
    parser.add_argument("--scope", choices=["bulk", "registry", "all"], default="all")
    parser.add_argument("--web", action="store_true", help="Fetch website meta for registry entries missing pitch")
    parser.add_argument("--web-limit", type=int, default=80, help="Max registry URLs to fetch when --web")
    args = parser.parse_args()

    stats: Dict[str, int] = {
        "intro_migrated": 0,
        "exhibit_set": 0,
        "product_cleared": 0,
        "product_kept": 0,
        "empty": 0,
        "registry_intro_migrated": 0,
        "registry_exhibit_set": 0,
        "registry_product_cleared": 0,
        "registry_pitch_merged": 0,
        "web_fetched": 0,
        "web_cache_hit": 0,
    }

    bulk_changed = 0
    if args.scope in ("bulk", "all"):
        for path in BULK_FILES:
            if path.exists():
                n = process_bulk(path, stats)
                bulk_changed += n
                print(f"{path.name}: updated {n} exhibitors")

    reg_changed = 0
    if args.scope in ("registry", "all"):
        registry = load_json(REGISTRY_PATH)
        domain_pitch = collect_domain_pitches()
        reg_changed = enrich_registry(registry, domain_pitch, stats)
        if args.web:
            reg_changed += web_enrich_registry(registry, args.web_limit, stats)
        if reg_changed:
            save_json(REGISTRY_PATH, registry)
        print(f"company-registry.json: updated {reg_changed} entries")

    print("--- stats ---")
    for k, v in stats.items():
        if v:
            print(f"  {k}: {v}")
    print(f"done bulk_changed={bulk_changed} registry_changed={reg_changed}")


if __name__ == "__main__":
    main()
