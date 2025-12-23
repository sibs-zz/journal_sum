#!/bin/bash
# 检查同步状态脚本

cd /tiandata2/zzh/journal-agent/github_repo

echo "=========================================="
echo "GitHub 同步状态检查"
echo "=========================================="

echo -e "\n1. Git 状态："
git status --short

echo -e "\n2. 本地最新提交："
git log --oneline -3

echo -e "\n3. 获取远程更新："
git fetch origin 2>&1 | grep -v "^$"

echo -e "\n4. 远程状态："
git status -sb

echo -e "\n5. 未推送的提交："
UNPUSHED=$(git log origin/main..HEAD --oneline)
if [ -z "$UNPUSHED" ]; then
    echo "  ✅ 所有提交已推送"
else
    echo "  ⚠️ 有以下未推送的提交："
    echo "$UNPUSHED"
    echo ""
    echo "  运行以下命令推送："
    echo "  git push origin main"
fi

echo -e "\n6. 远程仓库 URL："
git remote get-url origin | sed 's/\(github_pat_[^@]*\)@/***@/'

echo -e "\n=========================================="

