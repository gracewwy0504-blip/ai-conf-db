# 全球 AI 展会 & 公司产品数据库

**线上地址：** https://gracewwy0504-blip.github.io/ai-conf-db/  
**当前版本：** v2.8.5

## 仓库结构（便于整库提取）

```
index.html                 # 前端页面（筛选、搜索、展示逻辑）
exhibitor-data/
  conferences.json         # 104 场展会主数据（由 index 异步加载）
  company-registry.json    # 公司主库（688+ 条目，含 pitch/product/总部等）
  CES2026.json             # CES 2026 全量参展商 (~4190)
  GITEX2025.json           # GITEX 2025 全量参展商 (~2291)
  hq-cache.json            # 公司总部爬取缓存（6500+ 域名）
  conf-focus-cache.json    # 展会 focus 标签抓取缓存
  name-translation-cache.json
  product-translation-cache.json
enrich_conf_focus.py       # 更新展会 focus 标签
enrich_company_pitch.py    # 清洗公司 intro/product，写入 pitch
scrape_company_hq.py       # 爬取并更新公司总部
sync_global_exhibitions.py # 同步 bulk 展会参展商数量到页面文案
migrate_prod_cats.py       # 产品类别迁移工具
```

## 常用维护命令

```bash
# 清洗公司介绍与产品字段
python3 enrich_company_pitch.py --scope all

# 更新公司总部（registry + CES/GITEX）
python3 scrape_company_hq.py --scope all

# 更新展会 focus 标签
python3 enrich_conf_focus.py

# 本地预览
python3 -m http.server 8877
# 打开 http://localhost:8877/
```

## 数据字段说明

### 展会 `conferences.json`
`id`, `year`, `month`, `name`, `dates`, `city`, `country`, `types[]`, `focus[]`, `detail{intro,themes,speakers,exhibitors}`

### 公司 registry
`nameZh`, `nameEn`, `url`, `stage`, `cats[]`, `productZh`, `pitch`, `pitchVerified`, `pitchSource`, `country`, `countryZh`

### 参展商 bulk（CES/GITEX）
`name`, `nameEn`, `nameZh`, `booth`, `url`, `stage`, `cats[]`, `product`, `productZh`, `pitch`, `exhibitProduct`, `exhibitProductZh`, `country`, `countryZh`

## 部署

本仓库通过 **GitHub Pages** 发布（分支 `main`，根目录）。

```bash
git add -A
git commit -m "Publish v2.8.5"
git push origin main
```

推送后约 1–3 分钟生效：https://gracewwy0504-blip.github.io/ai-conf-db/
