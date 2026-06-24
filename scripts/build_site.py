#!/usr/bin/env python3
"""Precompute search artifacts and update build version."""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "exhibitor-data"
INDEX_PATH = ROOT / "index.html"
README_PATH = ROOT / "README.md"
CONF_PATH = DATA_DIR / "conferences.json"
CONF_LITE_PATH = DATA_DIR / "conferences-lite.json"
REGISTRY_PATH = DATA_DIR / "company-registry.json"
COMPANY_INDEX_PATH = DATA_DIR / "company-search-index.json"
COMPANY_META_PATH = DATA_DIR / "company-search-meta.json"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def clean_text(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip())


def normalize_name(name: str) -> str:
    val = clean_text(name).lower()
    val = re.sub(r"\([^)]*\)", " ", val)
    val = re.sub(r"\b(incorporated|corporation|company|limited|ltd|llc|corp|co|gmbh|ag|plc|bv|pty|pte)\b\.?", " ", val)
    val = re.sub(r"[^a-z0-9\u4e00-\u9fff\s&+.-]", " ", val)
    return re.sub(r"\s+", " ", val).strip()


def normalize_host(url: str) -> str:
    raw = clean_text(url)
    if not raw:
        return ""
    raw = re.sub(r"^https?://", "", raw, flags=re.I).split("/")[0].split("?")[0]
    return raw.lower().replace("www.", "", 1)


def merge_exhibitors(items: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}
    for item in items:
        key = normalize_host(item.get("url") or "") or normalize_name(item.get("name") or item.get("nameEn") or item.get("nameZh") or "")
        if not key:
            continue
        cur = merged.get(key)
        if not cur:
            merged[key] = dict(item)
            continue
        for field in ("name", "nameEn", "nameZh", "booth", "url", "country", "countryZh", "product", "productZh", "pitch", "pitchSource", "exhibitProduct", "exhibitProductZh"):
            a = clean_text(cur.get(field))
            b = clean_text(item.get(field))
            if b and (not a or len(b) > len(a)):
                cur[field] = item.get(field)
        cur["pitchVerified"] = bool(cur.get("pitchVerified")) or bool(item.get("pitchVerified"))
        cur["cats"] = sorted(set((cur.get("cats") or []) + (item.get("cats") or [])))
        if clean_text(cur.get("stage")) in ("", "待补充", "融资未公开") and clean_text(item.get("stage")):
            cur["stage"] = item["stage"]
    return list(merged.values())


def build_conference_search_text(conf: Dict[str, Any]) -> str:
    detail = conf.get("detail") or {}
    parts: List[str] = [
        conf.get("name", ""),
        conf.get("full", ""),
        conf.get("city", ""),
        conf.get("country", ""),
        conf.get("searchExtra", ""),
        detail.get("intro", ""),
    ]
    parts.extend(conf.get("types") or [])
    parts.extend(conf.get("focus") or [])
    parts.extend(detail.get("themes") or [])
    parts.extend("%s %s %s" % (s.get("name", ""), s.get("org", ""), s.get("topic", "")) for s in (detail.get("speakers") or []))
    parts.extend(
        "%s %s %s %s" % (
            e.get("name", ""),
            e.get("productZh") or e.get("product") or "",
            " ".join(e.get("cats") or []),
            e.get("stage", ""),
        )
        for e in (detail.get("exhibitors") or [])
    )
    return clean_text(" ".join(parts)).lower()


def conference_stub(conf: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": conf.get("id"),
        "name": conf.get("name"),
        "full": conf.get("full"),
        "year": conf.get("year"),
        "month": conf.get("month"),
        "dates": conf.get("dates"),
        "city": conf.get("city"),
        "country": conf.get("country"),
        "url": conf.get("url"),
        "types": conf.get("types") or [],
        "focus": conf.get("focus") or [],
    }


def conference_lite(conf: Dict[str, Any]) -> Dict[str, Any]:
    item = conference_stub(conf)
    item["productCats"] = conf.get("productCats") or []
    item["searchExtra"] = conf.get("searchExtra", "")
    item["searchText"] = conf.get("searchText", "")
    item["bulkExhibitorCount"] = conf.get("bulkExhibitorCount", 0)
    return item


def build_company_search_text(item: Dict[str, Any], confs: List[Dict[str, Any]], aliases: List[str]) -> str:
    parts: List[str] = [
        item.get("name", ""),
        item.get("nameEn", ""),
        item.get("nameZh", ""),
        item.get("product", ""),
        item.get("productZh", ""),
        item.get("pitch", ""),
        item.get("exhibitProduct", ""),
        item.get("exhibitProductZh", ""),
        item.get("country", ""),
        item.get("countryZh", ""),
        item.get("url", ""),
        item.get("stage", ""),
    ]
    parts.extend(item.get("cats") or [])
    parts.extend(aliases)
    parts.extend(c.get("name", "") for c in confs)
    parts.extend(c.get("full", "") for c in confs)
    parts.extend(" ".join(c.get("focus") or []) for c in confs)
    return clean_text(" ".join(parts)).lower()


def build_company_index(conferences: List[Dict[str, Any]], registry: Dict[str, Any]) -> List[Dict[str, Any]]:
    company_map: Dict[str, Dict[str, Any]] = {}
    conf_by_id = {c["id"]: conference_stub(c) for c in conferences if c.get("id")}

    for conf in conferences:
        conf_id = conf.get("id")
        if not conf_id:
            continue
        detail = conf.get("detail") or {}
        exhibitors = list(detail.get("exhibitors") or [])
        bulk_path = DATA_DIR / f"{conf_id}.json"
        if bulk_path.exists():
            exhibitors = merge_exhibitors(exhibitors + (read_json(bulk_path).get("exhibitors") or []))
        for exhibitor in exhibitors:
            name = clean_text(exhibitor.get("name") or exhibitor.get("nameEn") or exhibitor.get("nameZh"))
            if not name:
                continue
            key = normalize_host(exhibitor.get("url") or "") or normalize_name(name)
            if not key:
                continue
            entry = company_map.setdefault(
                key,
                {
                    "e": {
                        "name": name,
                        "nameEn": clean_text(exhibitor.get("nameEn")),
                        "nameZh": clean_text(exhibitor.get("nameZh")),
                        "stage": clean_text(exhibitor.get("stage")) or "融资未公开",
                        "cats": list(exhibitor.get("cats") or []),
                        "product": clean_text(exhibitor.get("product")),
                        "productZh": clean_text(exhibitor.get("productZh")),
                        "pitch": clean_text(exhibitor.get("pitch")),
                        "pitchSource": clean_text(exhibitor.get("pitchSource")),
                        "pitchVerified": bool(exhibitor.get("pitchVerified")),
                        "exhibitProduct": clean_text(exhibitor.get("exhibitProduct")),
                        "exhibitProductZh": clean_text(exhibitor.get("exhibitProductZh")),
                        "url": clean_text(exhibitor.get("url")),
                        "booth": clean_text(exhibitor.get("booth")),
                        "country": clean_text(exhibitor.get("country")),
                        "countryZh": clean_text(exhibitor.get("countryZh")),
                    },
                    "confIds": [],
                    "aliases": [],
                },
            )
            e = entry["e"]
            for field in ("name", "nameEn", "nameZh", "product", "productZh", "pitch", "pitchSource", "exhibitProduct", "exhibitProductZh", "url", "booth", "country", "countryZh"):
                cur = clean_text(e.get(field))
                cand = clean_text(exhibitor.get(field))
                if cand and (not cur or len(cand) > len(cur)):
                    e[field] = exhibitor.get(field)
            e["pitchVerified"] = bool(e.get("pitchVerified")) or bool(exhibitor.get("pitchVerified"))
            e["cats"] = sorted(set((e.get("cats") or []) + (exhibitor.get("cats") or [])))
            if clean_text(e.get("stage")) in ("", "待补充", "融资未公开") and clean_text(exhibitor.get("stage")):
                e["stage"] = exhibitor["stage"]
            for alias in [name, exhibitor.get("nameEn"), exhibitor.get("nameZh")]:
                alias = clean_text(alias)
                if alias and alias not in entry["aliases"]:
                    entry["aliases"].append(alias)
            if conf_id not in entry["confIds"]:
                entry["confIds"].append(conf_id)

            for alias in [name, exhibitor.get("nameEn"), exhibitor.get("nameZh")]:
                reg_key = normalize_name(alias or "")
                reg_hit = registry.get(reg_key)
                if not reg_hit:
                    continue
                if reg_hit.get("pitch") and (not e.get("pitch") or len(reg_hit["pitch"]) > len(e["pitch"])):
                    e["pitch"] = reg_hit["pitch"]
                    e["pitchSource"] = e.get("pitchSource") or reg_hit.get("pitchSource") or "registry"
                if reg_hit.get("pitchVerified"):
                    e["pitchVerified"] = True
                if reg_hit.get("url") and not e.get("url"):
                    e["url"] = reg_hit["url"]
                if reg_hit.get("countryZh") and not e.get("countryZh"):
                    e["countryZh"] = reg_hit["countryZh"]
                    e["country"] = reg_hit.get("country", e.get("country"))
                if reg_hit.get("cats"):
                    e["cats"] = sorted(set((e.get("cats") or []) + (reg_hit.get("cats") or [])))

    out: List[Dict[str, Any]] = []
    for entry in company_map.values():
        confs = [conf_by_id[cid] for cid in entry["confIds"] if cid in conf_by_id]
        out.append(
            {
                "e": entry["e"],
                "confIds": entry["confIds"],
                "aliases": entry["aliases"],
                "searchText": build_company_search_text(entry["e"], confs, entry["aliases"]),
            }
        )
    out.sort(key=lambda x: normalize_name(x["e"].get("name", "")))
    return out


def bump_build_version(version: str) -> None:
    html = INDEX_PATH.read_text(encoding="utf-8")
    html = re.sub(r"const APP_BUILD = '.*?';", f"const APP_BUILD = '{version}';", html, count=1)
    html = re.sub(
        r'(<link rel="preload" href="exhibitor-data/conferences-lite\.json\?build=)[^"]+(" as="fetch" crossorigin>)',
        rf"\g<1>{version}\2",
        html,
        count=1,
    )
    INDEX_PATH.write_text(html, encoding="utf-8")

    if README_PATH.exists():
        readme = README_PATH.read_text(encoding="utf-8")
        readme = re.sub(r"(\*\*当前版本：\*\* )v[^\s]+", rf"\g<1>{version}", readme, count=1)
        README_PATH.write_text(readme, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", default="", help="Explicit build version, e.g. v2026.06.24.1700")
    args = parser.parse_args()

    conferences = read_json(CONF_PATH)
    registry_raw = read_json(REGISTRY_PATH) if REGISTRY_PATH.exists() else {}
    registry = {normalize_name(k): v for k, v in registry_raw.items()}

    for conf in conferences:
        conf["searchText"] = build_conference_search_text(conf)
        bulk_path = DATA_DIR / f"{conf.get('id')}.json"
        if bulk_path.exists():
            try:
                conf["bulkExhibitorCount"] = len(read_json(bulk_path).get("exhibitors") or [])
            except Exception:
                pass
    write_json(CONF_PATH, conferences)
    write_json(CONF_LITE_PATH, [conference_lite(conf) for conf in conferences])

    company_index = build_company_index(conferences, registry)
    write_json(COMPANY_INDEX_PATH, company_index)
    total_records = sum(int(conf.get("bulkExhibitorCount") or 0) for conf in conferences)
    write_json(
        COMPANY_META_PATH,
        {
            "uniqueCompanyCount": len(company_index),
            "exhibitorRecordCount": total_records,
        },
    )

    version = args.build or datetime.now(timezone.utc).strftime("v%Y.%m.%d.%H%M")
    bump_build_version(version)
    print(f"conferences: {len(conferences)}")
    print(f"company-search-index: {len(company_index)}")
    print(f"build: {version}")


if __name__ == "__main__":
    main()
