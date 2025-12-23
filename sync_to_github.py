"""
将 site 目录同步到 GitHub 仓库的 docs 目录
使用方法：
    python sync_to_github.py
"""
import os
import subprocess
import shutil
from pathlib import Path
from typing import Tuple
import logging

# 配置
LOCAL_SITE_DIR = Path("/tiandata2/zzh/journal-agent/site")
# 使用 SSH URL（更稳定，无需 token）
GITHUB_REPO_URL = "git@github.com:sibs-zz/journal_sum.git"
GITHUB_REPO_DIR = Path("/tiandata2/zzh/journal-agent/github_repo")
GITHUB_DOCS_DIR = GITHUB_REPO_DIR / "docs"

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def run_command(cmd: list, cwd: Path = None, check: bool = True, env: dict = None) -> Tuple[bool, str]:
    """执行 shell 命令"""
    try:
        cmd_env = os.environ.copy()
        if env:
            cmd_env.update(env)
        
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=check,
            env=cmd_env
        )
        return True, result.stdout
    except subprocess.CalledProcessError as e:
        return False, e.stderr


def check_git_config():
    """检查并配置 Git 用户信息"""
    # 检查全局配置
    success, email = run_command(["git", "config", "--global", "user.email"], check=False)
    success, name = run_command(["git", "config", "--global", "user.name"], check=False)
    
    if not email.strip() or not name.strip():
        logger.warning("⚠️ Git 用户信息未配置，使用默认值")
        # 设置本地仓库的 Git 配置（仅对当前仓库有效）
        run_command(["git", "config", "user.email", "journal-agent@local"], cwd=GITHUB_REPO_DIR, check=False)
        run_command(["git", "config", "user.name", "Journal Agent"], cwd=GITHUB_REPO_DIR, check=False)
        logger.info("✅ 已设置本地 Git 用户信息")


def ensure_ssh_remote():
    """确保远程仓库使用 SSH URL（如果当前是 HTTPS，则切换为 SSH）"""
    if not GITHUB_REPO_DIR.exists():
        return True
    
    success, current_url = run_command(
        ["git", "remote", "get-url", "origin"],
        cwd=GITHUB_REPO_DIR,
        check=False
    )
    
    if success and current_url.strip():
        current_url = current_url.strip()
        # 如果当前是 HTTPS URL，切换为 SSH
        if current_url.startswith("https://"):
            logger.info("🔄 检测到 HTTPS URL，切换为 SSH URL...")
            success, output = run_command(
                ["git", "remote", "set-url", "origin", GITHUB_REPO_URL],
                cwd=GITHUB_REPO_DIR,
                check=False
            )
            if success:
                logger.info("✅ 已切换为 SSH URL")
            else:
                logger.warning(f"⚠️ 切换 SSH URL 失败: {output}")
        elif current_url.startswith("git@github.com"):
            logger.debug("✅ 已使用 SSH URL")
        else:
            logger.warning(f"⚠️ 未知的远程 URL 格式: {current_url}")
    
    return True


def clone_or_update_repo():
    """克隆或更新 GitHub 仓库"""
    if GITHUB_REPO_DIR.exists():
        logger.info("📥 更新 GitHub 仓库...")
        # 确保使用 SSH URL
        ensure_ssh_remote()
        
        success, output = run_command(
            ["git", "pull", "origin", "main"],
            cwd=GITHUB_REPO_DIR,
            check=False
        )
        if not success:
            logger.warning(f"⚠️ 更新失败，尝试拉取: {output}")
            run_command(["git", "fetch"], cwd=GITHUB_REPO_DIR, check=False)
            run_command(["git", "reset", "--hard", "origin/main"], cwd=GITHUB_REPO_DIR, check=False)
        # 检查 Git 配置
        check_git_config()
    else:
        logger.info("📥 克隆 GitHub 仓库（使用 SSH）...")
        success, output = run_command(
            ["git", "clone", GITHUB_REPO_URL, str(GITHUB_REPO_DIR)],
            check=False
        )
        if not success:
            logger.error(f"❌ 克隆仓库失败: {output}")
            logger.info("💡 提示: 确保已配置 SSH 密钥并添加到 GitHub")
            return False
        # 检查 Git 配置
        check_git_config()
    return True


def sync_directories():
    """同步 site 目录到 docs 目录"""
    if not LOCAL_SITE_DIR.exists():
        logger.error(f"❌ 源目录不存在: {LOCAL_SITE_DIR}")
        return False
    
    # 确保 docs 目录存在
    GITHUB_DOCS_DIR.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"📋 同步 {LOCAL_SITE_DIR} -> {GITHUB_DOCS_DIR}")
    
    # 删除 docs 目录中的旧文件（保留 .git）
    for item in GITHUB_DOCS_DIR.iterdir():
        if item.name != ".git":
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
    
    # 复制所有文件
    for item in LOCAL_SITE_DIR.iterdir():
        dest = GITHUB_DOCS_DIR / item.name
        if item.is_dir():
            shutil.copytree(item, dest, dirs_exist_ok=True)
            logger.info(f"  ✅ 复制目录: {item.name}")
        else:
            shutil.copy2(item, dest)
            logger.info(f"  ✅ 复制文件: {item.name}")
    
    return True


def commit_and_push():
    """提交并推送到 GitHub"""
    logger.info("📝 检查更改...")
    
    # 检查是否有更改
    success, output = run_command(
        ["git", "status", "--porcelain"],
        cwd=GITHUB_REPO_DIR,
        check=False
    )
    
    if not output.strip():
        logger.info("✅ 没有更改，无需提交")
        return True
    
    logger.info("📝 添加更改...")
    success, output = run_command(
        ["git", "add", "docs/"],
        cwd=GITHUB_REPO_DIR
    )
    if not success:
        logger.error(f"❌ 添加文件失败: {output}")
        return False
    
    logger.info("💬 提交更改...")
    from datetime import datetime
    commit_message = f"自动同步: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    success, output = run_command(
        ["git", "commit", "-m", commit_message],
        cwd=GITHUB_REPO_DIR,
        check=False
    )
    
    if not success:
        if "nothing to commit" in output.lower():
            logger.info("✅ 没有需要提交的更改")
            return True
        logger.warning(f"⚠️ 提交失败: {output}")
        return False
    
    logger.info("🚀 推送到 GitHub（使用 SSH）...")
    # 确保使用 SSH URL
    ensure_ssh_remote()
    
    # 尝试推送，最多重试 3 次
    max_retries = 3
    for attempt in range(max_retries):
        success, output = run_command(
            ["git", "push", "origin", "main"],
            cwd=GITHUB_REPO_DIR,
            check=False
        )
        if success:
            logger.info("✅ 同步完成！")
            return True
        
        if attempt < max_retries - 1:
            logger.warning(f"⚠️ 推送失败（尝试 {attempt + 1}/{max_retries}），3秒后重试...")
            import time
            time.sleep(3)
        else:
            logger.error(f"❌ 推送失败（已重试 {max_retries} 次）: {output}")
            logger.info("💡 提示:")
            logger.info("   1. 检查网络连接")
            logger.info("   2. 验证 SSH 密钥是否已添加到 GitHub")
            logger.info("   3. 测试 SSH 连接: ssh -T git@github.com")
            logger.info("   4. 可以手动运行: cd github_repo && git push origin main")
            return False
    
    return False


def main():
    """主函数"""
    logger.info("=" * 60)
    logger.info("开始同步到 GitHub")
    logger.info("=" * 60)
    
    # 1. 克隆或更新仓库
    if not clone_or_update_repo():
        return
    
    # 2. 同步目录
    if not sync_directories():
        return
    
    # 3. 提交并推送
    commit_and_push()
    
    logger.info("=" * 60)
    logger.info("同步流程完成")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()

