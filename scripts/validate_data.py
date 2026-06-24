#!/usr/bin/env python3
"""Basic validation for generated exhibitor/site data."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "exhibitor-data"

REQUIRED_FILES = [
    DATA_DIR / "conferences.json",
    DATA_DIR / "conferences-lite.json",
    DATA_DIR / "company-registry.json",
    DATA_DIR / "company-search-index.json",
    DATA_DIR / "company-search-meta.json",
]


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def validate_bulk_file(path: Path) -> None:
    payload = read_json(path)
    require(isinstance(payload, dict), f"{path.name}: must be an object")
    require(isinstance(payload.get("exhibitors"), list), f"{path.name}: exhibitors must be a list")
    require(payload.get("count") == len(payload.get("exhibitors") or []), f"{path.name}: count mismatch")
    for idx, item in enumerate(payload["exhibitors"][:10]):
        require(isinstance(item, dict), f"{path.name}: exhibitor {idx} must be object")
        require(bool(str(item.get("name") or "").strip()), f"{path.name}: exhibitor {idx} missing name")


def main() -> None:
    for path in REQUIRED_FILES:
        require(path.exists(), f"Missing required file: {path}")
        read_json(path)

    conferences = read_json(DATA_DIR / "conferences.json")
    require(isinstance(conferences, list) and conferences, "conferences.json must be a non-empty array")
    conferences_lite = read_json(DATA_DIR / "conferences-lite.json")
    require(isinstance(conferences_lite, list) and conferences_lite, "conferences-lite.json must be a non-empty array")
    require(len(conferences_lite) == len(conferences), "conferences-lite.json count mismatch")

    company_index = read_json(DATA_DIR / "company-search-index.json")
    require(isinstance(company_index, list) and company_index, "company-search-index.json must be a non-empty array")
    company_meta = read_json(DATA_DIR / "company-search-meta.json")
    require(company_meta.get("uniqueCompanyCount") == len(company_index), "company-search-meta uniqueCompanyCount mismatch")

    conf_ids = {c.get("id") for c in conferences if c.get("id")}
    for conf in conferences:
        require(bool(conf.get("name")), f"conference missing name: {conf.get('id')}")
        require(bool(conf.get("searchText")), f"conference missing searchText: {conf.get('id')}")
        bulk_path = DATA_DIR / f"{conf.get('id')}.json"
        if bulk_path.exists():
            validate_bulk_file(bulk_path)

    for idx, item in enumerate(company_index[:50]):
        require(isinstance(item, dict), f"company index entry {idx} must be object")
        require(bool((item.get("e") or {}).get("name")), f"company index entry {idx} missing name")
        require(isinstance(item.get("confIds"), list), f"company index entry {idx} confIds must be list")
        require(all(cid in conf_ids for cid in item["confIds"]), f"company index entry {idx} references unknown conference")
        require(bool(item.get("searchText")), f"company index entry {idx} missing searchText")

    print(f"Validated {len(conferences)} conferences and {len(company_index)} company index entries.")


if __name__ == "__main__":
    main()
