"""
期刊自动摘要生成脚本 - 优化版本
功能：从多个期刊 RSS 抓取文章，使用 LLM 筛选和总结，生成 HTML 页面
"""
import os
import json
import logging
import datetime as dt
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import wraps
import time

import feedparser
from bs4 import BeautifulSoup
from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

# ================= 配置区 =================

# 输出网页的目录（自动创建）
OUTPUT_DIR = Path(os.getenv("JOURNAL_OUTPUT_DIR", "/tiandata2/zzh/journal-agent/site"))

# 日志配置
LOG_DIR = Path(os.getenv("JOURNAL_LOG_DIR", "/tiandata2/zzh/journal-agent/logs"))
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / f"journal_agent_{dt.datetime.now().strftime('%Y%m%d')}.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def load_api_key() -> Optional[str]:
    """
    加载 API Key，按优先级尝试：
    1. 环境变量 DEEPSEEK_API_KEY
    2. 当前目录的 key.txt 文件
    3. 脚本所在目录的 key.txt 文件
    """
    # 1. 优先从环境变量读取
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if api_key:
        logger.info("✅ 从环境变量读取 API Key")
        return api_key.strip()
    
    # 2. 尝试从当前工作目录的 key.txt 读取
    current_dir_key = Path("key.txt")
    if current_dir_key.exists():
        try:
            api_key = current_dir_key.read_text(encoding='utf-8').strip()
            if api_key:
                logger.info("✅ 从当前目录的 key.txt 读取 API Key")
                return api_key
        except Exception as e:
            logger.warning(f"⚠️ 读取当前目录 key.txt 失败: {e}")
    
    # 3. 尝试从脚本所在目录的 key.txt 读取
    script_dir = Path(__file__).parent
    script_dir_key = script_dir / "key.txt"
    if script_dir_key.exists():
        try:
            api_key = script_dir_key.read_text(encoding='utf-8').strip()
            if api_key:
                logger.info("✅ 从脚本目录的 key.txt 读取 API Key")
                return api_key
        except Exception as e:
            logger.warning(f"⚠️ 读取脚本目录 key.txt 失败: {e}")
    
    return None


# API Key 加载（支持环境变量和 key.txt 文件）
DEEPSEEK_API_KEY = load_api_key()
if not DEEPSEEK_API_KEY:
    logger.warning("⚠️ 未找到 API Key（环境变量 DEEPSEEK_API_KEY 或 key.txt 文件），LLM 功能将不可用")
    client = None
else:
    client = OpenAI(
        api_key=DEEPSEEK_API_KEY,
        base_url="https://api.deepseek.com",
    )
    logger.info("✅ DeepSeek API 客户端初始化成功")

# ====== 期刊列表：综合顶刊 + 作物/育种/组学 + 子刊 + 新增植物期刊 ======
# 每个条目：
#  - name: 显示在网页上的名字
#  - id:   内部用的短 id（不重复即可）
#  - rss:  RSS/Atom feed 地址（用于抓最新文章）

JOURNALS = [
    # --- 综合顶刊 ---
    {
        "name": "Nature",
        "id": "nature",
        "rss": "https://www.nature.com/nature.rss",
    },
    {
        "name": "Science",
        "id": "science",
        "rss": "https://www.science.org/action/showFeed?type=etoc&feed=rss&jc=science",
    },
    {
        "name": "Cell",
        "id": "cell",
        "rss": "https://www.cell.com/cell/current.rss",
    },

    # --- Nature 系重要子刊 ---
    {
        "name": "Nature Genetics",
        "id": "nature_genetics",
        "rss": "https://www.nature.com/ng.rss",
    },
    {
        "name": "Nature Plants",
        "id": "nature_plants",
        "rss": "https://www.nature.com/nplants.rss",
    },
    {
        "name": "Nature Communications",
        "id": "nature_communications",
        "rss": "https://www.nature.com/ncomms.rss",
    },
    {
        "name": "Nature Biotechnology",
        "id": "nature_biotechnology",
        "rss": "https://www.nature.com/nbt.rss",
    },
    {
        "name": "Nature Ecology & Evolution",
        "id": "nature_ecol_evol",
        "rss": "https://www.nature.com/natecolevol.rss",
    },

    # --- Science 系重要子刊 ---
    {
        "name": "Science Advances",
        "id": "science_advances",
        "rss": "https://www.science.org/action/showFeed?feed=rss&jc=sciadv&type=etoc",
    },

    # --- 植物/作物方向新增期刊 ---
    {
        "name": "The Plant Journal (PubMed)",
        "id": "plant_journal_pubmed",
        "rss": "https://pubmed.ncbi.nlm.nih.gov/rss/journals/9207397/?limit=50&name=Plant%20J&utm_campaign=journals",
    },
    {
        "name": "Journal of Integrative Plant Biology (PubMed)",
        "id": "jipb_pubmed",
        "rss": "https://pubmed.ncbi.nlm.nih.gov/rss/journals/101250502/?limit=50&name=J%20Integr%20Plant%20Biol&utm_campaign=journals",
    },
    {
        "name": "Plant Biotechnology Journal (PubMed)",
        "id": "pbj_pubmed",
        "rss": "https://pubmed.ncbi.nlm.nih.gov/rss/journals/101201889/?limit=50&name=Plant%20Biotechnol%20J&utm_campaign=journals",
    },
    {
        "name": "The Plant Cell (PubMed)",
        "id": "plant_cell_pubmed",
        "rss": "https://pubmed.ncbi.nlm.nih.gov/rss/journals/9208688/?limit=50&name=Plant%20Cell&utm_campaign=journals",
    },
    {
        "name": "Plant Physiology (PubMed)",
        "id": "plant_physiology_pubmed",
        "rss": "https://pubmed.ncbi.nlm.nih.gov/rss/journals/0401224/?limit=50&name=Plant%20Physiol&utm_campaign=journals",
    },
    {
        "name": "New Phytologist (PubMed)",
        "id": "new_phytologisty_pubmed",
        "rss": "https://pubmed.ncbi.nlm.nih.gov/rss/journals/9882884/?limit=50&name=New%20Phytol&utm_campaign=journals",
    },

    # --- Plant Communications / Molecular Plant（保留） ---
    {
        "name": "Plant Communications",
        "id": "plant_communications",
        "rss": "http://www.cell.com/plant-communications/current.rss",
    },
    {
        "name": "Molecular Plant",
        "id": "molecular_plant",
        "rss": "http://www.cell.com/molecular-plant/current.rss",
    },

    # --- PNAS ---
    {
        "name": "PNAS",
        "id": "pnas",
        "rss": "https://www.pnas.org/action/showFeed?type=etoc&feed=rss&jc=pnas",
    },

    # --- 作物科学 / 育种 / 品种改良 ---
    {
        "name": "The Crop Journal",
        "id": "crop_journal",
        "rss": "https://rss.sciencedirect.com/publication/science/22145141",
    },
]

# 配置常量
MAX_ITEMS_PER_JOURNAL = int(os.getenv("MAX_ITEMS_PER_JOURNAL", "50"))
TARGET_ARTICLES_PER_JOURNAL = int(os.getenv("TARGET_ARTICLES_PER_JOURNAL", "15"))
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "5"))  # 并行处理线程数
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))  # 重试次数

# ================= 工具函数 =================

def clean_text(html_text: str) -> str:
    """把 RSS 里的 HTML 标签去掉。"""
    if not html_text:
        return ""
    try:
        return BeautifulSoup(html_text, "html.parser").get_text().strip()
    except Exception as e:
        logger.warning(f"清理 HTML 文本时出错: {e}")
        return html_text.strip()


@retry(stop=stop_after_attempt(MAX_RETRIES), wait=wait_exponential(multiplier=1, min=2, max=10))
def fetch_rss_articles(journal: Dict[str, str], max_items: int = MAX_ITEMS_PER_JOURNAL) -> List[Dict[str, Any]]:
    """从 RSS 抓取最新若干篇文章（带重试机制）。"""
    logger.info(f"▶ 抓取 {journal['name']} ...")
    try:
        feed = feedparser.parse(journal["rss"])
        
        if feed.bozo and feed.bozo_exception:
            logger.warning(f"⚠️ {journal['name']} RSS 解析警告: {feed.bozo_exception}")

        articles = []
        for entry in feed.entries[:max_items]:
            title = (entry.get("title") or "").strip()
            link = (entry.get("link") or "").strip()

            if not title or not link:
                continue

            abstract_raw = entry.get("summary", "") or entry.get("description", "")
            abstract = clean_text(abstract_raw)

            if entry.get("published_parsed"):
                try:
                    pub_date = dt.date(*entry.published_parsed[:3]).isoformat()
                except (ValueError, TypeError):
                    pub_date = dt.date.today().isoformat()
            else:
                pub_date = dt.date.today().isoformat()

            articles.append({
                "journal": journal["name"],
                "journal_id": journal["id"],
                "title": title,
                "link": link,
                "abstract": abstract,
                "pub_date": pub_date,
            })

        logger.info(f"  找到 {len(articles)} 篇（未过滤）")
        return articles
    except Exception as e:
        logger.error(f"❌ 抓取 {journal['name']} 失败: {e}", exc_info=True)
        return []


# ---------- 基于标题+摘要的粗过滤：去掉非科研核心内容 ----------

EXCLUDE_KEYWORDS = [
    "news", "editorial", "perspective", "comment",
    "correspondence", "viewpoint", "opinion",
    "highlight", "policy", "correction", "erratum",
    "retraction", "protocol", "methods", "methodology",
    "in brief", "brief communication", "obituary",
    "news feature", "book review", "conference report",
    "in this issue", "research highlight", "research news",
    "technical report"
]


def is_core_research(entry: Dict[str, Any]) -> bool:
    """判断是否是科研核心文章（基于标题+摘要关键词排除非研究类内容）"""
    text = (entry.get("title", "") + " " + entry.get("abstract", "")).lower()
    return not any(kw in text for kw in EXCLUDE_KEYWORDS)


# ---------- 利用大模型挑选"对你有价值"的文章 ----------

@retry(stop=stop_after_attempt(MAX_RETRIES), wait=wait_exponential(multiplier=1, min=2, max=10))
def select_valuable_with_llm(journal_name: str, articles: List[Dict[str, Any]], target_n: int = TARGET_ARTICLES_PER_JOURNAL) -> List[Dict[str, Any]]:
    """
    让大模型根据你的研究兴趣，在该期刊候选文章中挑选最有"借鉴意义"的若干篇。
    返回：一个子列表（最多 target_n 篇）。
    """
    if client is None or not articles:
        logger.warning(f"⚠️ LLM 客户端不可用或文章列表为空，返回前 {target_n} 篇")
        return articles[:target_n]

    # 为了 prompt 不爆炸，摘要按 800 字符截断
    items_for_llm = []
    for idx, art in enumerate(articles):
        abs_trim = (art.get("abstract") or "").replace("\n", " ")
        if len(abs_trim) > 800:
            abs_trim = abs_trim[:800] + "..."
        items_for_llm.append({
            "id": idx,
            "title": art["title"],
            "abstract": abs_trim,
            "pub_date": art["pub_date"],
        })

    prompt = f"""
你是一名作物科学/育种/功能基因组学方向的科研助理，帮我从该期刊最新论文中挑出【对作物研究有启发价值】的文章。

我的长期关注点包括：
- 育种策略与遗传改良（产量、品质、抗逆、抗病）
- 作物功能基因组学（关键基因/QTL 的解析与验证）
- 组学整合与生物信息学方法（多组学关联、GWAS、eQTL、网络分析等）
- 新技术/新方法（基因编辑、单细胞/空间组学、高通量表型、AI/计算方法等）
- 可迁移到作物上的机制工作（模式生物、人类/小鼠/微生物，只要对作物思路有启发，也可以保留）

请注意：尽量排除非 research article 的内容，例如 News、Comment、Perspective、Research highlight、人物纪念、编辑部文章、撤稿、勘误等。仅在标题与摘要明显属于科研文章（有明确实验/分析/方法/数据）时才予以保留。

下面是该期刊的若干候选文章（title+abstract 摘要节选）：

{json.dumps(items_for_llm, ensure_ascii=False, indent=2)}

请你完成两件事：
1）为每篇文章打一个 0–10 的分数，表示"对作物育种/作物功能基因组学/组学分析是否有启发"；
2）从中选择【最多 {target_n} 篇】你认为最值得关注的文章。

请只输出 JSON，不要任何解释性文字，格式为：

[
  {{
    "id": 0,
    "score": 0-10 的数字,
    "keep": true 或 false,
    "reason": "用1句话解释为什么对作物方向有启发（中文）"
  }},
  ...
]

要求：
- 不要捏造内容，只根据给出的标题和摘要推断。
- 如果难以判断，就给中等分数（比如 5-6），但不要完全乱猜。
"""

    try:
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "You are a helpful assistant"},
                {"role": "user", "content": prompt},
            ],
            stream=False,
            temperature=0.2,
        )
        raw = resp.choices[0].message.content.strip()

        # 容错：找到第一个 '[' 开始解析 JSON
        start = raw.find("[")
        end = raw.rfind("]")
        if start == -1 or end == -1:
            raise ValueError("LLM 输出中未找到 JSON 列表")
        json_text = raw[start:end + 1]

        data = json.loads(json_text)
        scored = []
        for item in data:
            try:
                idx = int(item.get("id"))
                score = float(item.get("score", 0))
                keep = bool(item.get("keep", True))
                if 0 <= idx < len(articles):
                    scored.append({"idx": idx, "score": score, "keep": keep})
            except (ValueError, TypeError) as e:
                logger.debug(f"解析评分项失败: {e}")
                continue

        # 过滤 keep=True，再按分数从高到低排序
        kept = [x for x in scored if x["keep"]]
        if not kept:
            kept = scored  # 如果一个 keep 都没有，就退而选最高分

        kept.sort(key=lambda x: x["score"], reverse=True)
        selected_idx = [x["idx"] for x in kept[:target_n]]

        selected = [articles[i] for i in selected_idx]
        logger.info(f"  ▶ {journal_name}：模型筛选出 {len(selected)} 篇有价值文章。")
        return selected

    except Exception as e:
        logger.error(f"❌ 选择有价值文章时解析失败，采用降级策略：{e}", exc_info=True)
        return articles[:target_n]


@retry(stop=stop_after_attempt(MAX_RETRIES), wait=wait_exponential(multiplier=1, min=2, max=10))
def summarize(title: str, abstract: str, journal: str) -> str:
    """调用 DeepSeek 生成中文精炼总结（带重试机制）。"""
    if client is None:
        return (
            "核心：尚未配置 DEEPSEEK_API_KEY，暂无法生成自动摘要。\n"
            f"- 要点1：标题为「{title}」，期刊：{journal}。\n"
            "- 要点2：请点击下方原文链接查看详细内容。\n"
        )

    if not abstract:
        abstract = "（该条目未提供摘要，请仅基于标题做一个非常简短的介绍。）"

    prompt = f"""
你是一名严谨的中文科研助理，负责从论文标题与摘要中提取高质量信息。请严格按照以下要求生成总结：

1.专业、精炼地翻译论文标题和摘要（分别以"标题：""摘要："开头；要求忠实、完整、无删减，无字数限制）。
2.用四句话概括论文的核心科学发现或主要贡献（以"核心："开头，并按 1、2、3、4 分条列出；不超过 500 字）。
3.所有内容必须完全基于原文标题与摘要，不得加入外部知识、推测、虚构信息或未出现的细节。
4.语言要求清晰、客观、专业，不包含与论文无关的内容。

期刊：{journal}
标题：{title}
摘要：{abstract}
"""

    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "You are a helpful assistant"},
                {"role": "user", "content": prompt},
            ],
            stream=False,
            temperature=0.2,
        )
        summary = response.choices[0].message.content.strip()
        return summary
    except Exception as e:
        logger.error(f"❌ DeepSeek 调用失败：{e}", exc_info=True)
        return (
            "核心：自动生成摘要失败，请参考原文标题与摘要理解内容。\n"
            f"- 要点1：标题为「{title}」。\n"
            "- 要点2：可点击下方原文链接查看详细研究。\n"
        )


@retry(stop=stop_after_attempt(MAX_RETRIES), wait=wait_exponential(multiplier=1, min=2, max=10))
def summarize_journal_trends(journal_name: str, articles_for_this_journal: List[Dict[str, Any]]) -> str:
    """
    在已经选出的"有价值文章"基础上，让模型总结该期刊最近值得你关注的研究方向。
    """
    if client is None or not articles_for_this_journal:
        return ""

    items = []
    for a in articles_for_this_journal:
        s = a.get("summary", "").strip()
        if len(s) > 600:
            s = s[:600] + "..."
        items.append({
            "title": a["title"],
            "summary": s,
            "pub_date": a["pub_date"],
        })

    prompt = f"""
你是一名长期跟踪 {journal_name} 的作物/植物科学 PI，请根据下面这些"已筛选过、与作物研究相关"的论文，归纳该期刊最近值得关注的研究方向。

下面是该期刊近期若干篇代表性论文（已经过筛选，标题+简要总结）：
{json.dumps(items, ensure_ascii=False, indent=2)}

请输出：
- 先用 1 句话整体评价该期刊最近的研究趋势（1 行）。
- 然后列出 3–5 个你认为对"作物育种、作物改良、功能基因组学、组学分析、新技术应用"特别有启发的研究方向，每个方向一行，以"- "开头，语言尽量具体（可以点出关键技术、思路或材料类型），但不要超过 60 字。

只输出中文文本，不要额外解释。
"""

    try:
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "You are a helpful assistant"},
                {"role": "user", "content": prompt},
            ],
            stream=False,
            temperature=0.3,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        logger.warning(f"⚠️ 期刊趋势总结失败（{journal_name}）：{e}", exc_info=True)
        return ""


# ================= HTML 模板生成函数 =================

def get_html_styles() -> str:
    """返回 HTML 样式 CSS"""
    return """<style>
body {
  font-family: -apple-system,BlinkMacSystemFont,'Segoe UI','Microsoft YaHei',sans-serif;
  background: #e5f6e8;
  margin: 0;
  padding: 0;
}
header {
  background: #14532d;
  color: #fff;
  padding: 16px 24px;
}
.header-inner {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
header h1 {
  margin: 0;
  font-size: 20px;
}
header p {
  margin: 4px 0 0;
  font-size: 12px;
  opacity: 0.9;
}
.lab-name {
  font-size: 24px;
  font-weight: 700;
  letter-spacing: 1px;
  font-family: 'Microsoft YaHei','SimHei','Segoe UI',sans-serif;
  color: #ffffff;
}

.hero {
  margin: 16px auto 0;
  max-width: 1200px;
  padding: 0 16px 8px;
}
.hero-inner {
  background: linear-gradient(135deg, rgba(34,197,94,0.18), rgba(22,163,74,0.05));
  border-radius: 16px;
  padding: 12px 16px;
  display: flex;
  align-items: center;
  gap: 16px;
}
.hero img {
  display: block;
  max-height: 120px;
  border-radius: 12px;
  object-fit: cover;
}
.hero-text-title {
  font-size: 16px;
  font-weight: 600;
  color: #064e3b;
  margin-bottom: 4px;
}
.hero-text-sub {
  font-size: 12px;
  color: #166534;
}

.container {
  max-width: 1200px;
  margin: 16px auto 32px;
  padding: 0 16px 16px;
  display: flex;
  gap: 16px;
  align-items: flex-start;
}
.nav {
  flex: 0 0 220px;
  background: #ecfdf3;
  border-radius: 16px;
  padding: 12px 12px 14px;
  box-shadow: 0 1px 4px rgba(0,0,0,0.05);
  border: 1px solid rgba(22,163,74,0.18);
  position: sticky;
  top: 20px;
  max-height: calc(100vh - 40px);
  overflow-y: auto;
}
.nav-title {
  font-size: 13px;
  font-weight: 600;
  color: #065f46;
  margin-bottom: 8px;
}
.nav a {
  display: block;
  font-size: 13px;
  padding: 5px 8px;
  border-radius: 8px;
  color: #065f46;
  text-decoration: none;
  margin-bottom: 2px;
}
.nav a:hover {
  background: rgba(22,163,74,0.1);
}
.nav a.active {
  background: #16a34a;
  color: #ecfdf3;
}

.main {
  flex: 1 1 auto;
}

/* 顶部控制区：左侧搜索 + 右侧字号控制 */
.controls {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  font-size: 12px;
  color: #4b5563;
  flex-wrap: wrap;
}
.search-box {
  flex: 1 1 260px;
}
.search-box input {
  width: 100%;
  padding: 4px 8px;
  border-radius: 999px;
  border: 1px solid #d1d5db;
  font-size: 12px;
  outline: none;
}
.search-box input:focus {
  border-color: #16a34a;
  box-shadow: 0 0 0 1px rgba(22,163,74,0.4);
  background: #f0fdf4;
}
.font-controls {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}
.font-controls button {
  border: 1px solid #d1d5db;
  background: #f9fafb;
  border-radius: 999px;
  padding: 2px 8px;
  cursor: pointer;
  font-size: 11px;
}
.font-controls button:hover {
  background: #e5e7eb;
}

.journal-block {
  margin-top: 24px;
}
.journal-header {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 8px;
}
.journal-header h2 {
  margin: 0;
  font-size: 18px;
  color: #064e3b;
}
.journal-trends {
  font-size: 12px;
  color: #166534;
  white-space: pre-wrap;
  margin-bottom: 8px;
  background: rgba(22,163,74,0.06);
  border-left: 3px solid #16a34a;
  padding: 6px 10px;
  border-radius: 8px;
}

.card {
  background: #ffffff;
  padding: 16px;
  border-radius: 12px;
  margin-bottom: 14px;
  box-shadow: 0 1px 4px rgba(0,0,0,0.08);
  border: 1px solid rgba(22,163,74,0.08);
}
.title {
  font-weight: 600;
  font-size: 15px;
}
.meta {
  color: #6b7280;
  font-size: 12px;
  margin-top: 4px;
}
.toggle-btn {
  margin-top: 8px;
  border-radius: 999px;
  border: 1px solid #d1d5db;
  background: #f9fafb;
  font-size: 11px;
  padding: 2px 8px;
  cursor: pointer;
  color: #374151;
}
.toggle-btn:hover {
  background: #e5e7eb;
}

.card-body {
  margin-top: 8px;
}
.abstract-label {
  margin-top: 4px;
  font-size: 12px;
  font-weight: 600;
  color: #065f46;
}
.abstract {
  margin-top: 4px;
  color: #374151;
  font-size: 13px;
  white-space: pre-wrap;
  line-height: 1.5;
}
.summary {
  margin-top: 10px;
  font-size: 13px;
  white-space: pre-wrap;
  border-top: 1px dashed #e5e7eb;
  padding-top: 8px;
}
a {
  color: #2563eb;
  text-decoration: none;
  word-break: break-all;
  font-size: 12px;
}
a:hover {
  text-decoration: underline;
}
.footer {
  text-align: center;
  font-size: 11px;
  color: #6b7280;
  padding: 12px 0 24px;
}

.scroll-top {
  position: fixed;
  right: 20px;
  bottom: 20px;
  padding: 6px 10px;
  font-size: 12px;
  border-radius: 999px;
  border: none;
  background: #16a34a;
  color: #ecfdf3;
  cursor: pointer;
  box-shadow: 0 1px 4px rgba(0,0,0,0.2);
  display: none;
  z-index: 50;
}
.scroll-top.show {
  display: block;
}

@media (max-width: 900px) {
  .container {
    flex-direction: column;
  }
  .nav {
    position: static;
    max-height: none;
    width: 100%;
  }
}
</style>"""


def get_html_scripts() -> str:
    """返回 HTML JavaScript 代码"""
    return """<script>
  // 简单的字号调整
  let baseSize = 13;
  function applyFontSize() {
    document.querySelectorAll('.abstract, .summary, .card .meta').forEach(el => {
      el.style.fontSize = baseSize + 'px';
    });
  }
  function changeFontSize(delta) {
    baseSize = Math.max(11, Math.min(18, baseSize + delta));
    applyFontSize();
  }
  function resetFontSize() {
    baseSize = 13;
    applyFontSize();
  }
  applyFontSize();

  // 展开 / 收起详情
  function toggleCardBody(btn) {
    const body = btn.nextElementSibling;
    if (!body) return;
    const isHidden = body.style.display === '' || body.style.display === 'none';
    if (isHidden) {
      body.style.display = 'block';
      btn.textContent = '收起详情';
    } else {
      body.style.display = 'none';
      btn.textContent = '展开详情';
    }
  }
  
  // 默认全部展开
  document.querySelectorAll('.card-body').forEach(b => {
    b.style.display = 'block';
  });
  document.querySelectorAll('.toggle-btn').forEach(btn => {
    btn.textContent = '收起详情';
  });

  // 导航高亮 & 返回顶部按钮
  const navLinks = document.querySelectorAll('.nav a');
  const sections = Array.from(document.querySelectorAll('.journal-block'));
  const scrollBtn = document.getElementById('scrollTopBtn');

  function onScroll() {
    const fromTop = window.scrollY + 80;
    let currentId = null;
    for (const sec of sections) {
      if (sec.offsetTop <= fromTop) {
        currentId = sec.id;
      }
    }
    navLinks.forEach(link => {
      const href = link.getAttribute('href') || '';
      const id = href.startsWith('#') ? href.slice(1) : null;
      if (id === currentId) {
        link.classList.add('active');
      } else {
        link.classList.remove('active');
      }
    });

    if (window.scrollY > 300) {
      scrollBtn.classList.add('show');
    } else {
      scrollBtn.classList.remove('show');
    }
  }
  window.addEventListener('scroll', onScroll);
  onScroll();

  // 搜索栏：在标题 / 摘要 / 总结里检索关键词
  const searchInput = document.getElementById('searchInput');
  if (searchInput) {
    searchInput.addEventListener('input', function() {
      const q = this.value.trim().toLowerCase();
      const cards = document.querySelectorAll('.card');
      cards.forEach(card => {
        const text = card.innerText.toLowerCase();
        if (!q || text.indexOf(q) !== -1) {
          card.style.display = '';
        } else {
          card.style.display = 'none';
        }
      });
    });
  }
</script>"""


def generate_archive_index_html(pages: List[Dict[str, str]], generated_at: str) -> str:
    """生成索引页面的 HTML"""
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>期刊每日摘要索引</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body {{
  font-family: -apple-system,BlinkMacSystemFont,'Segoe UI','Microsoft YaHei',sans-serif;
  background: #e5f6e8;
  margin: 0;
  padding: 0;
}}
header {{
  background: #14532d;
  color: #fff;
  padding: 16px 24px;
}}
.header-inner {{
  display: flex;
  justify-content: space-between;
  align-items: center;
}}
header h1 {{
  margin: 0;
  font-size: 20px;
}}
header p {{
  margin: 4px 0 0;
  font-size: 12px;
  opacity: 0.9;
}}
.lab-name {{
  font-size: 24px;
  font-weight: 700;
  letter-spacing: 1px;
  font-family: 'Microsoft YaHei','SimHei','Segoe UI',sans-serif;
  color: #ffffff;
}}
.container {{
  max-width: 900px;
  margin: 20px auto 40px;
  padding: 0 16px;
}}
.box {{
  background: #ffffff;
  border-radius: 16px;
  box-shadow: 0 1px 4px rgba(0,0,0,0.08);
  padding: 16px 20px;
  border: 1px solid rgba(22,163,74,0.15);
}}
.box h2 {{
  margin-top: 0;
  font-size: 18px;
  color: #064e3b;
}}
.desc {{
  font-size: 13px;
  color: #4b5563;
  margin-bottom: 10px;
}}
ul.archive {{
  list-style: none;
  padding-left: 0;
  margin: 0;
}}
ul.archive li {{
  padding: 6px 4px;
  border-bottom: 1px dashed #e5e7eb;
  font-size: 13px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}}
ul.archive li:last-child {{
  border-bottom: none;
}}
ul.archive a {{
  color: #2563eb;
  text-decoration: none;
}}
ul.archive a:hover {{
  text-decoration: underline;
}}
.tag-latest {{
  font-size: 11px;
  color: #f97316;
  margin-left: 8px;
}}
.footer {{
  text-align: center;
  font-size: 11px;
  color: #6b7280;
  padding: 12px 0 24px;
}}
</style>
</head>
<body>
<header>
  <div class="header-inner">
    <div>
      <h1>期刊自动摘要 · 索引</h1>
      <p>最新更新：{generated_at}</p>
    </div>
    <div class="lab-name">Sweet Home</div>
  </div>
</header>

<div class="container">
  <div class="box">
    <h2>历史日期页面</h2>
    <div class="desc">
      这里列出了所有已生成的每日摘要页面，点击日期即可打开对应版本。
      最新的一天会标记为「最新」。
    </div>
    <ul class="archive">
"""
    
    for i, page in enumerate(pages):
        label = page["date"]
        filename = page["filename"]
        latest_tag = ' <span class="tag-latest">最新</span>' if i == 0 else ""
        html += f'      <li><a href="{filename}">{label}</a>{latest_tag}</li>\n'
    
    html += """    </ul>
  </div>
</div>

<div class="footer">
  本索引页由实验室内部脚本自动生成。如遇问题，请联系维护者。
</div>
</body>
</html>
"""
    return html


def generate_daily_html(grouped: Dict[str, List[Dict[str, Any]]], journal_trends: Dict[str, str], 
                        date_tag: str, generated_at: str) -> str:
    """生成每日内容页面的 HTML"""
    journal_order = sorted(grouped.keys())
    
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>期刊每日自动摘要 · {date_tag}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
{get_html_styles()}
</head>
<body>
<header>
  <div class="header-inner">
    <div>
      <h1>期刊自动摘要 · 作物视角</h1>
      <p>当前页面日期：{date_tag}　|　生成时间：{generated_at}</p>
    </div>
    <div class="lab-name">Sweet Home</div>
  </div>
</header>

<div class="hero">
  <div class="hero-inner">
    <!-- soybean.jpg 与本页面同目录 -->
    <img src="soybean.jpg" alt="Soybean plant" onerror="this.style.display='none'">
    <div>
      <div class="hero-text-title">面向育种与作物改良的每日文献雷达</div>
      <div class="hero-text-sub">
        自动抓取 Nature / Science / Cell 及主要植物期刊最新论文，由大模型从"作物视角"筛选、总结与归纳方向。
      </div>
    </div>
  </div>
</div>

<div class="container">
  <nav class="nav">
    <div class="nav-title">期刊导航</div>
"""
    
    # 左侧导航
    for journal in journal_order:
        anchor = journal.replace(" ", "_").replace("&", "and")
        count = len(grouped[journal])
        label = f"{journal}（{count}）"
        html += f'    <a href="#{anchor}">{label}</a>\n'
    
    html += """  </nav>
  <main class="main">
    <div class="controls">
      <div class="search-box">
        <input id="searchInput" type="text" placeholder="在标题 / 摘要 / 总结中搜索关键词...">
      </div>
      <div class="font-controls">
        <span>字号：</span>
        <button type="button" onclick="changeFontSize(1)">A+</button>
        <button type="button" onclick="changeFontSize(-1)">A-</button>
        <button type="button" onclick="resetFontSize()">重置</button>
      </div>
    </div>
"""
    
    # 右侧各期刊内容
    for journal in journal_order:
        arts = grouped[journal]
        anchor = journal.replace(" ", "_").replace("&", "and")
        trends = journal_trends.get(journal, "").strip()
        
        html += f'    <section class="journal-block" id="{anchor}">\n'
        html += '      <div class="journal-header">\n'
        html += f'        <h2>{journal}</h2>\n'
        html += '      </div>\n'
        if trends:
            html += f'      <div class="journal-trends">{trends}</div>\n'
        
        for a in arts:
            full_abs = (a.get("abstract") or "").strip()
            meta_line = f"发表日期：{a['pub_date']}，期刊：{a['journal']}"
            html += f"""
      <div class="card" data-journal="{a['journal']}">
        <div class="title">{a['title']}</div>
        <div class="meta">{meta_line}</div>
        <button type="button" class="toggle-btn" onclick="toggleCardBody(this)">收起详情</button>
        <div class="card-body">
"""
            if full_abs:
                html += f"""          <div class="abstract-label">原始摘要：</div>
          <div class="abstract">{full_abs}</div>
"""
            html += f"""          <div class="summary">{a['summary']}</div>
          <div style="margin-top:8px;"><a href="{a['link']}" target="_blank" rel="noopener noreferrer">原文链接</a></div>
        </div>
      </div>
"""
        
        html += "    </section>\n"
    
    html += """  </main>
</div>

<button class="scroll-top" id="scrollTopBtn" onclick="window.scrollTo({top:0, behavior:'smooth'});">返回顶部</button>

<div class="footer">
  本页由实验室内部脚本自动生成（DeepSeek + Python）。如遇摘要异常，请以原文为准。<br>
  历史版本请访问根目录索引页（GitHub Pages 环境下为仓库首页）。
</div>

"""
    html += get_html_scripts()
    html += "</body>\n</html>"
    
    return html


def build_archive_index():
    """
    构建一个总目录页面 index.html：
    - 自动扫描 OUTPUT_DIR 下所有 index_YYYY-MM-DD.html
    - 按日期从新到旧列出
    - 点击每一条跳转到对应日期页面
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 找到所有带日期的页面，比如 index_2025-12-06.html
    dated_files = sorted(
        OUTPUT_DIR.glob("index_*.html"),
        reverse=True  # 字符串排序对 YYYY-MM-DD 正好是新到旧
    )

    if not dated_files:
        logger.warning("⚠️ 暂无历史页面，跳过目录页生成。")
        return

    # 提取日期与文件名
    pages = []
    for p in dated_files:
        name = p.name  # index_2025-12-06.html
        try:
            date_str = name.replace("index_", "").replace(".html", "")
        except Exception:
            continue
        pages.append({"filename": name, "date": date_str})

    generated_at = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    html = generate_archive_index_html(pages, generated_at)

    index_path = OUTPUT_DIR / "index.html"
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(html)

    logger.info(f"✅ 索引页已更新：{index_path}")


def generate_html(articles: List[Dict[str, Any]], journal_trends: Dict[str, str]):
    """
    生成每天的完整页面 + 更新总目录页：
    - 每日内容页：index_YYYY-MM-DD.html
    - 总目录页：index.html（列出所有日期的链接）
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 按期刊分组
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for a in articles:
        grouped.setdefault(a["journal"], []).append(a)

    # 每个期刊内部按日期排序（新 → 旧）
    for arts in grouped.values():
        arts.sort(key=lambda x: x["pub_date"], reverse=True)

    # 当前时间（用于显示）和日期（用于文件名）
    generated_at = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    date_tag = dt.datetime.now().strftime("%Y-%m-%d")

    # 生成每日内容页 HTML
    html = generate_daily_html(grouped, journal_trends, date_tag, generated_at)

    # 写入带日期的每日页面，例如 index_2025-12-06.html
    dated_filename = f"index_{date_tag}.html"
    dated_path = OUTPUT_DIR / dated_filename

    with open(dated_path, "w", encoding="utf-8") as f:
        f.write(html)

    logger.info(f"✅ 网页生成成功（带日期）：{dated_path}")

    # 更新总目录页 index.html
    build_archive_index()


# ================= 并行处理辅助函数 =================

def process_journal(journal: Dict[str, str]) -> Tuple[Dict[str, str], List[Dict[str, Any]], str]:
    """
    处理单个期刊：抓取、过滤、筛选、生成摘要、总结趋势
    返回：(journal, articles, trends_text)
    """
    try:
        # 1. 抓取文章
        items = fetch_rss_articles(journal, max_items=MAX_ITEMS_PER_JOURNAL)
        
        # 2. 过滤非科研核心内容
        items = [a for a in items if is_core_research(a)]
        
        if not items:
            logger.warning(f"⚠️ {journal['name']} 过滤后无有效文章，跳过。")
            return (journal, [], "")
        
        # 3. 利用大模型从该期刊中挑选"对你有启发的"文章
        valuable = select_valuable_with_llm(
            journal_name=journal["name"], 
            articles=items, 
            target_n=TARGET_ARTICLES_PER_JOURNAL
        )
        
        # 4. 对挑出的文章生成中文摘要
        for art in valuable:
            logger.info(f"▶ 生成摘要：{art['title']}")
            art["summary"] = summarize(
                title=art["title"],
                abstract=art["abstract"],
                journal=art["journal"],
            )
        
        # 5. 总结该期刊最近研究方向
        trends_text = ""
        if valuable:
            trends_text = summarize_journal_trends(
                journal_name=journal["name"],
                articles_for_this_journal=valuable,
            )
        
        return (journal, valuable, trends_text)
    except Exception as e:
        logger.error(f"❌ 处理期刊 {journal['name']} 时出错: {e}", exc_info=True)
        return (journal, [], "")


# ================= 主流程 =================

def main():
    """主函数：并行处理所有期刊"""
    logger.info("=" * 60)
    logger.info("开始处理期刊摘要生成任务")
    logger.info(f"共 {len(JOURNALS)} 个期刊，并行线程数: {MAX_WORKERS}")
    logger.info("=" * 60)
    
    all_articles: List[Dict[str, Any]] = []
    journal_trends: Dict[str, str] = {}
    
    start_time = time.time()
    
    # 使用线程池并行处理期刊
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # 提交所有任务
        future_to_journal = {
            executor.submit(process_journal, journal): journal 
            for journal in JOURNALS
        }
        
        # 收集结果
        completed = 0
        for future in as_completed(future_to_journal):
            completed += 1
            journal = future_to_journal[future]
            try:
                j, articles, trends = future.result()
                all_articles.extend(articles)
                if trends:
                    journal_trends[j["name"]] = trends
                logger.info(f"✅ [{completed}/{len(JOURNALS)}] {j['name']} 处理完成，获得 {len(articles)} 篇文章")
            except Exception as e:
                logger.error(f"❌ 处理 {journal['name']} 时发生异常: {e}", exc_info=True)
    
    elapsed_time = time.time() - start_time
    
    if not all_articles:
        logger.warning("⚠️ 没有抓到任何文章，请检查 RSS 链接或网络。")
        return
    
    logger.info(f"✅ 所有期刊处理完成，共获得 {len(all_articles)} 篇文章，耗时 {elapsed_time:.2f} 秒")
    logger.info("开始生成 HTML 页面...")
    
    generate_html(all_articles, journal_trends)
    
    # 可选：自动同步到 GitHub
    if os.getenv("AUTO_SYNC_GITHUB", "false").lower() == "true":
        logger.info("=" * 60)
        logger.info("开始自动同步到 GitHub...")
        try:
            # 动态导入同步模块，避免循环依赖
            import sys
            sync_script = Path(__file__).parent / "sync_to_github.py"
            if sync_script.exists():
                import importlib.util
                spec = importlib.util.spec_from_file_location("sync_to_github", sync_script)
                sync_module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(sync_module)
                sync_module.main()
            else:
                logger.warning("⚠️ 未找到 sync_to_github.py，跳过自动同步")
        except Exception as e:
            logger.error(f"❌ 自动同步失败: {e}", exc_info=True)
    
    logger.info("=" * 60)
    logger.info("任务完成！")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
