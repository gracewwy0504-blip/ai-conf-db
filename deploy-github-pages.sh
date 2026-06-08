#!/bin/bash
set -eo pipefail
REPO="ai-conf-db"
ROOT="$(cd "$(dirname "$0")" && pwd)"
GITHUB_TOKEN="$(printf '%s' "${GITHUB_TOKEN:-}" | tr -d '\r\n' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"

if [[ -z "$GITHUB_TOKEN" ]]; then
  echo "❌ 请先: export GITHUB_TOKEN=ghp_xxxxxxxx"
  exit 1
fi

echo "🔐 验证 Token..."
USER_JSON=$(curl -sS -H "Authorization: token $GITHUB_TOKEN" -H "Accept: application/vnd.github+json" "https://api.github.com/user")
if echo "$USER_JSON" | grep -q '"Bad credentials"'; then
  echo "❌ Token 无效"; exit 1
fi
OWNER=$(python3 -c "import json,sys; print(json.load(sys.stdin)['login'])" <<<"$USER_JSON")
echo "   ✅ 账号: $OWNER"

bash "$HOME/Desktop/pack-public-site.sh" >/dev/null
cd "$ROOT"

if [[ ! -d .git ]]; then
  git init && git branch -M main
fi
git add -A
git diff --cached --quiet || git commit -m "Publish AI conference database"

HTTP_CODE=$(curl -sS -o /tmp/gh-create.json -w "%{http_code}" \
  -X POST -H "Authorization: token $GITHUB_TOKEN" -H "Accept: application/vnd.github+json" \
  "https://api.github.com/user/repos" \
  -d "{\"name\":\"$REPO\",\"description\":\"AI conference database\",\"private\":false}" || echo "000")
[[ "$HTTP_CODE" == "201" || "$HTTP_CODE" == "422" ]] || { cat /tmp/gh-create.json; exit 1; }

git remote remove origin 2>/dev/null || true
git remote add origin "https://x-access-token:${GITHUB_TOKEN}@github.com/${OWNER}/${REPO}.git"
git push -u origin main
git remote set-url origin "https://github.com/${OWNER}/${REPO}.git"

curl -sS -X PUT -H "Authorization: token $GITHUB_TOKEN" -H "Accept: application/vnd.github+json" \
  "https://api.github.com/repos/${OWNER}/${REPO}/pages" \
  -d '{"build_type":"legacy","source":{"branch":"main","path":"/"}}' >/dev/null || true

echo ""
echo "✅ 完成！"
echo "   https://github.com/${OWNER}/${REPO}"
echo "   https://${OWNER}.github.io/${REPO}/"
