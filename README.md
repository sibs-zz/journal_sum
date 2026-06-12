# 📚 Journal Agent - 期刊自动摘要生成工具

<div align="center">

![Python](https://img.shields.io/badge/Python-3.7+-blue.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)
![Status](https://img.shields.io/badge/Status-Active-success.svg)

**面向作物科学 / 育种 / 功能基因组学研究的智能文献追踪与摘要系统**

[功能特性](#-功能特性) • [快速开始](#-快速开始) • [文章抓取流程](#-文章抓取流程) • [配置说明](#-配置说明)

</div>

---

## 📖 项目简介

Journal Agent 从 Nature、Science、Cell 等顶级期刊及主要植物学期刊的 RSS 源抓取最新论文，自动过滤 News / Editorial 等非 research 内容，通过 PubMed / CrossRef / PMC 补全摘要与开放获取正文，再使用 DeepSeek 大模型从**作物研究视角**筛选并生成中文摘要网页。

在线浏览：https://sibs-zz.github.io/journal_sum/

---

## ✨ 功能特性

### 🔬 智能筛选
- **元数据过滤**：Nature News DOI、Science `dc_type`、Cell `prism_section` 等规则剔除非 research 文章
- **摘要质量检测**：识别 RSS 模板导语、`No abstract` 等无效摘要
- **LLM 二次筛选**：DeepSeek 对候选文章打分（0–10），保留对作物研究最有启发的文章

### 📄 内容补全
- **PubMed**：通过 PMID / DOI 获取完整摘要
- **CrossRef**：Science 等 RSS 无摘要时，通过 DOI 补全
- **PMC 开放获取正文**：若文章在 PubMed Central 开放，自动抓取正文节选供 LLM 总结

### 📊 多期刊支持（19 个源）
- **综合顶刊**：Nature, Science, Cell, PNAS
- **Nature 子刊**：Genetics, Plants, Communications, Biotechnology, Ecology & Evolution
- **植物学期刊**（PubMed RSS）：Plant Cell, Plant Physiology, New Phytologist, Plant Journal, JIPB, PBJ
- **Cell 系**：Plant Communications, Molecular Plant
- **作物期刊**：The Crop Journal, Science Advances

### 🎨 输出
- 每日 HTML 摘要页（`index_YYYY-MM-DD.html`）+ 历史索引页
- 响应式界面：搜索、期刊导航、字号调节、研究方向趋势总结

---

## 🚀 快速开始

### 环境要求

- Python 3.7+
- DeepSeek API Key（LLM 筛选与摘要）
- NCBI API Key（推荐，加速 PubMed/PMC 补全；[免费申请](https://www.ncbi.nlm.nih.gov/account/settings/)）

### 安装

```bash
git clone https://github.com/sibs-zz/journal_sum.git
cd journal_sum
pip install -r requirements.txt
```

### 配置密钥

在项目根目录创建两个密钥文件（**不要提交到 Git**）：

```bash
echo "your-deepseek-api-key" > key.txt
echo "your-ncbi-api-key"     > ncbi_key.txt
```

也支持环境变量（优先级更高）：

```bash
export DEEPSEEK_API_KEY="your-deepseek-api-key"
export NCBI_API_KEY="your-ncbi-api-key"
```

密钥读取优先级（与 `post_gwas_gene_agent_v1.py` 一致）：

| 密钥 | 环境变量 | 文件（当前目录 → 脚本目录） |
|------|----------|------------------------------|
| DeepSeek | `DEEPSEEK_API_KEY` | `key.txt` |
| NCBI | `NCBI_API_KEY` | `ncbi_key.txt` |

### 运行

```bash
python journal_summarizer_advanced_v2.py
```

或使用一键脚本：

```bash
chmod +x run.sh
./run.sh
```

输出目录默认为 `site/`（可通过 `JOURNAL_OUTPUT_DIR` 修改）。

---

## 📡 文章抓取流程

脚本对每个期刊依次执行以下步骤（期刊之间并行）：

```
┌─────────────────────────────────────────────────────────────────┐
│  1. RSS 抓取                                                     │
│     feedparser 读取各期刊 RSS，提取：                               │
│     title, link, abstract, doi, pmid, pub_type, article_section  │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  2. 元数据过滤 (is_core_research)                                │
│     • Nature: 剔除 DOI 含 d41586 的 News/Feature                 │
│     • Science/PNAS: 仅保留 Research Article / Report / Letter  │
│     • Cell 系: 剔除 Commentary / Preview / Correction          │
│     • 标题黑名单: Author Correction, Editorial, World Cup 等     │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  3. 内容补全 (enrich_article_content)                            │
│     RSS 摘要不足时依次尝试：                                      │
│     PubMed efetch → CrossRef API → PMC 开放获取正文              │
│     补全后仍无有效内容的文章会被丢弃                                │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  4. LLM 筛选 (select_valuable_with_llm)                          │
│     DeepSeek 对每篇候选文章打分，选出对作物研究最有价值的 N 篇     │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  5. 中文摘要 (summarize)                                         │
│     基于摘要 + PMC 正文节选，生成结构化中文总结                    │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  6. 生成 HTML                                                    │
│     index_YYYY-MM-DD.html + index.html 历史索引                  │
└─────────────────────────────────────────────────────────────────┘
```

### 各数据源说明

| 来源 | 用途 | 说明 |
|------|------|------|
| **期刊 RSS** | 发现最新文章 | Nature/Science/Cell 官方 RSS；植物期刊使用 PubMed Journal RSS |
| **PubMed E-utilities** | 摘要补全 | 通过 PMID 或 DOI 查询完整摘要 |
| **CrossRef API** | 摘要补全 | Science RSS 常只有卷期信息，需 CrossRef 补摘要 |
| **PMC (NCBI)** | 开放获取正文 | 仅对 PMC 开放文章可读正文节选（默认最多 6000 字） |
| **DeepSeek API** | 筛选 + 总结 | 默认模型 `deepseek-v4-pro` |

### RSS 示例

期刊列表在脚本 `JOURNALS` 变量中配置，每条包含 `name`、`id`、`rss` 三个字段：

```python
{
    "name": "Nature Plants",
    "id": "nature_plants",
    "rss": "https://www.nature.com/nplants.rss",
},
{
    "name": "The Plant Cell (PubMed)",
    "id": "plant_cell_pubmed",
    "rss": "https://pubmed.ncbi.nlm.nih.gov/rss/journals/9208688/?limit=50&name=Plant%20Cell&utm_campaign=journals",
},
```

添加新期刊：找到对应 RSS 地址，追加到 `JOURNALS` 列表即可。

---

## ⚙️ 配置说明

### 环境变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥 | 读 `key.txt` |
| `NCBI_API_KEY` | NCBI E-utilities 密钥 | 读 `ncbi_key.txt` |
| `DEEPSEEK_MODEL` | LLM 模型 | `deepseek-v4-pro` |
| `DEEPSEEK_MAX_TOKENS` | LLM 最大输出 token | `4096` |
| `JOURNAL_OUTPUT_DIR` | HTML 输出目录 | `./site` |
| `JOURNAL_LOG_DIR` | 日志目录 | `./logs` |
| `MAX_ITEMS_PER_JOURNAL` | 每期刊 RSS 最大抓取数 | `50` |
| `TARGET_ARTICLES_PER_JOURNAL` | 每期刊 LLM 筛选保留数 | `15` |
| `MAX_WORKERS` | 并行线程数 | `10` |
| `MIN_ABSTRACT_CHARS` | 有效摘要最短字符数 | `80` |
| `FETCH_FULL_TEXT` | 是否尝试读 PMC 正文 | `true` |
| `MAX_FULL_TEXT_CHARS` | PMC 正文节选最大字符 | `6000` |

---

## 📁 项目结构

```
journal_sum/
├── journal_summarizer_advanced_v2.py  # 主脚本
├── run.sh                             # 一键运行
├── requirements.txt                   # Python 依赖
├── key.txt                            # DeepSeek Key（本地，不提交）
├── ncbi_key.txt                       # NCBI Key（本地，不提交）
├── docs/                              # GitHub Pages 静态页面
│   ├── index.html
│   └── index_YYYY-MM-DD.html
└── logs/                              # 运行日志（本地）
```

---

## 🐛 故障排查

| 问题 | 排查 |
|------|------|
| LLM 不可用 | 检查 `key.txt` 或 `DEEPSEEK_API_KEY` |
| 摘要补全慢 | 配置 `ncbi_key.txt`，限速从 3 req/s 提升到 10 req/s |
| 仍有 News 漏网 | 查看日志中「元数据过滤」计数；可在 `is_core_research()` 追加规则 |
| Science 摘要不完整 | 正常——脚本会自动走 CrossRef 补全，查看 `content_source` 字段 |
| 某篇被丢弃 | 可能 PubMed 也无摘要（Preview/Commentary 类），属预期行为 |

日志文件：`logs/journal_agent_YYYYMMDD.log`

---

## 🛠️ 技术栈

- **feedparser** — RSS 解析
- **requests** — PubMed / CrossRef / PMC API
- **BeautifulSoup4** — HTML 清理
- **OpenAI SDK** — DeepSeek Chat Completions
- **tenacity** — 网络请求重试
- **ThreadPoolExecutor** — 多期刊并行

---

## 📝 更新日志

### v2.1
- NCBI Key 支持 `ncbi_key.txt` 读取
- 元数据过滤 + PubMed/CrossRef/PMC 三级内容补全
- DeepSeek 模型升级至 `deepseek-v4-pro`
- 移除 GitHub 自动/手动同步说明，文档聚焦文章抓取流程

### v2.0
- 并行处理、重试机制、日志系统、类型提示

---

<div align="center">

**⭐ 如果这个项目对你有帮助，请给个 Star！**

Made with ❤️ for the crop science research community

</div>
