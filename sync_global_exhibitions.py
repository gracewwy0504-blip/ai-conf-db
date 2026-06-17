#!/usr/bin/env python3
"""Refresh global exhibition metadata and bulk exhibitor counts in index.html."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
INDEX = ROOT / "index.html"
BULK = {
    "CES2026": ROOT / "exhibitor-data" / "CES2026.json",
    "GITEX2025": ROOT / "exhibitor-data" / "GITEX2025.json",
}


def load_counts() -> dict[str, int]:
    out = {}
    for conf_id, path in BULK.items():
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        ex = data.get("exhibitors") or []
        out[conf_id] = len(ex)
    return out


def patch_intro(html: str, conf_id: str, count: int) -> str:
    if conf_id == "CES2026":
        old = r"(CES 2026于1月6–9日在美国拉斯维加斯举办[^']*?)4,112家参展商"
        new = rf"\1{count:,}家参展商"
        return re.sub(old, new, html, count=1)
    if conf_id == "GITEX2025":
        marker = "id:'GITEX2025'"
        idx = html.find(marker)
        if idx < 0:
            return html
        chunk = html[idx : idx + 4000]
        patched = re.sub(
            r"intro:'([^']*?)'",
            lambda m: (
                "intro:'"
                + m.group(1).split("。")[0]
                + f"。官方名录已同步 {count:,} 家参展商数据。'"
            )
            if "intro:'" in m.group(0)
            else m.group(0),
            chunk,
            count=1,
        )
        return html[:idx] + patched + html[idx + 4000 :]
    return html


def main() -> None:
    counts = load_counts()
    html = INDEX.read_text(encoding="utf-8")
    for conf_id, count in counts.items():
        html = patch_intro(html, conf_id, count)
    synced = datetime.now().strftime("%Y-%m-%d")
    html = re.sub(
        r"最后更新：\d{4}年\d{1,2}月\d{1,2}日",
        f"最后更新：{datetime.now().strftime('%Y年%-m月%-d日')}",
        html,
        count=1,
    )
    INDEX.write_text(html, encoding="utf-8")
    print("synced global exhibitions:", counts, "on", synced)


if __name__ == "__main__":
    main()
