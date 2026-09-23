#!/bin/bash
# 快速同步脚本 - 将 site 目录同步到 GitHub

# 配置
LOCAL_SITE_DIR="/tiandata2/zzh/journal-agent/site"
GITHUB_REPO_URL="git@github.com:sibs-zz/journal_sum.git"
GITHUB_REPO_DIR="/tiandata2/zzh/journal-agent/github_repo"
GITHUB_DOCS_DIR="$GITHUB_REPO_DIR/docs"

echo "=========================================="
echo "开始同步到 GitHub"
echo "=========================================="

# 1. 克隆或更新仓库
if [ -d "$GITHUB_REPO_DIR" ]; then
    echo "📥 更新 GitHub 仓库..."
    cd "$GITHUB_REPO_DIR"
    # 确保使用 SSH URL
    CURRENT_URL=$(git remote get-url origin 2>/dev/null)
    if [[ "$CURRENT_URL" == https://* ]]; then
        echo "🔄 切换为 SSH URL..."
        git remote set-url origin "$GITHUB_REPO_URL"
    fi
    git pull origin main || git fetch && git reset --hard origin/main
else
    echo "📥 克隆 GitHub 仓库（使用 SSH）..."
    git clone "$GITHUB_REPO_URL" "$GITHUB_REPO_DIR"
fi

# 2. 同步文件
echo "📋 同步文件..."
mkdir -p "$GITHUB_DOCS_DIR"
rsync -av --delete --exclude='.git' "$LOCAL_SITE_DIR/" "$GITHUB_DOCS_DIR/"

# 3. 提交并推送
cd "$GITHUB_REPO_DIR"
if [ -n "$(git status --porcelain docs/)" ]; then
    echo "📝 提交更改..."
    git add docs/
    git commit -m "自动同步: $(date '+%Y-%m-%d %H:%M:%S')"
    echo "🚀 推送到 GitHub..."
    git push origin main
    echo "✅ 同步完成！"
else
    echo "✅ 没有更改，无需提交"
fi

echo "=========================================="

