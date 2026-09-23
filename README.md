# Journal Agent

面向作物科学、育种和功能基因组学的文献雷达。每次运行只回看最近半个月，从 Nature 系、Cell、Science 抓取生物学研究论文，并用本地缓存跳过已经整理过的文章。

## 为什么改成这样

原先用期刊 RSS 和 PubMed 补摘要。RSS 条目少，也经常混进新闻和评论；PubMed 对刚上网的论文覆盖不及时。所以这一版不再走这两条检索链。

五个期刊改成直接打开官网列表，再逐篇进入文章页读取题目和摘要：

- Nature：官网检索里限定 research，学科为 biological sciences
- Nature Genetics、Nature Plants：官网 Research articles 列表
- Cell：ScienceDirect / cell.com 文章页常被反爬拦截。Cell 正文改从 **PubMed** 同期 `Cell[Journal]` 条目读取题目与摘要（可选 `ncbi_key.txt` 提高频率）；PubMed 为空时才尝试 ScienceDirect 在线列表（通常只有标题）
- Science：官网目录页经常被 Cloudflare 拦截。脚本会尝试打开文章页；打不开时使用该刊已登记的题录和摘要，并只保留生命科学相关条目

单次运行的日期窗口是 15 天，含当天。更早的论文不会进入本轮。**数量上只受时间窗和缓存约束**，不再按分数或每个来源篇数封顶。

## 关注什么

筛选标准与原先脚本一致，仍然从作物研究是否受启发来判断是否保留：

- 育种和遗传改良（产量、品质、抗逆、抗病）
- 作物功能基因组、关键基因和 QTL
- 组学与生物信息方法（GWAS、eQTL、网络、多组学）
- 可迁移的新技术（基因编辑、单细胞、空间组学、表型、计算方法）
- 模式生物、动物或微生物里对作物思路有用的机制工作

新闻、社论、更正、招聘广告、培训和会议通知会被丢掉。模型仍会给出相关度分数供页面展示，但**不设分数下限，也不限制每个来源最多几篇**。

## 缓存

缓存是本地 SQLite（`cache/articles.sqlite`）。一篇文章用 DOI 或规范化标题做键。

- 已经写过中文总结的，下次直接跳过
- 已经判定为与作物方向无关的，下次也不再送去打分

## 页面

- `site/index_YYYY-MM-DD.html`：当日摘要（顶栏含返回目录；正文区展示 `soybean.jpg`）
- `site/index.html`：**日期目录**（卡片列表，不自跳转到当天）；最新日期标红并带 ★

仅重建 HTML、不重新抓取时：

```bash
python journal_summarizer_v4.py --rebuild-page
```

## 运行

```bash
pip install -r requirements.txt
echo "your-deepseek-api-key" > key.txt
python journal_summarizer_v4.py
```

或：

```bash
./run.sh
```

密钥也可以放在环境变量 `DEEPSEEK_API_KEY`。输出在 `site/index_YYYY-MM-DD.html`；根目录 `site/index.html` 为日期索引（见上文「页面」）。

可选环境变量：

| 变量 | 含义 | 默认 |
| --- | --- | --- |
| `LOOKBACK_DAYS` | 回溯天数 | 15 |
| `DEEPSEEK_MODEL` | 模型 | deepseek-v4-flash |
| `DEEPSEEK_MAX_TOKENS` | 单次输出上限 | 8192 |
| `MAX_WORKERS` | 并行线程数（抓取 / 筛选 / 总结） | 10 |
| `JOURNAL_OUTPUT_DIR` | 页面输出目录 | `./site` |
| `JOURNAL_CACHE_PATH` | 缓存文件 | `./cache/articles.sqlite` |

## 目录

```text
journal_summarizer_v4.py    入口
journal_agent/sources.py    期刊官网抓取
journal_agent/rank.py       作物视角筛选和中文总结
journal_agent/common.py     缓存与 HTTP
journal_agent/render.py     每日页面
site/                       生成的 HTML
cache/                      文献缓存（不提交）
key.txt                     DeepSeek 密钥（不提交）
```
