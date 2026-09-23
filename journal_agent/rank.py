"""Crop-science ranking and Chinese summaries. Interests match the previous v3 prompts."""

from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from journal_agent.common import (
    DEEPSEEK_MAX_TOKENS,
    DEEPSEEK_MODEL,
    MAX_WORKERS,
    RANK_BATCH,
    Article,
    load_api_key,
)

logger = logging.getLogger("journal_agent")

INTERESTS = """
我的长期关注点包括：
- 育种策略与遗传改良（产量、品质、抗逆、抗病）
- 作物功能基因组学（关键基因/QTL 的解析与验证）
- 组学整合与生物信息学方法（多组学关联、GWAS、eQTL、网络分析等）
- 新技术/新方法（基因编辑、单细胞/空间组学、高通量表型、AI/计算方法等）
- 可迁移到作物上的机制工作（模式生物、人类/小鼠/微生物，只要对作物思路有启发，也可以保留）
""".strip()


class Ranker:
    def __init__(self) -> None:
        key = load_api_key()
        self.client: Optional[OpenAI] = None
        if key:
            self.client = OpenAI(api_key=key, base_url="https://api.deepseek.com")
            logger.info("DeepSeek 客户端已就绪，模型 %s", DEEPSEEK_MODEL)
        else:
            logger.warning("未找到 DeepSeek API Key，只保留抓取结果，不生成摘要")

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=12))
    def _chat(self, system: str, user: str, temperature: float = 0.2) -> str:
        if self.client is None:
            raise RuntimeError("no client")
        resp = self.client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
            max_tokens=DEEPSEEK_MAX_TOKENS,
        )
        return (resp.choices[0].message.content or "").strip()

    def select(self, journal: str, articles: list[Article]) -> tuple[list[Article], list[Article]]:
        """Return (kept, dismissed). Only the 15-day window limits volume; no score or per-source cap."""
        if not articles:
            return [], []
        if self.client is None:
            return articles, []
        kept: list[Article] = []
        dismissed: list[Article] = []
        batches = [articles[i:i + RANK_BATCH] for i in range(0, len(articles), RANK_BATCH)]
        workers = min(MAX_WORKERS, max(1, len(batches)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(self._score_batch, journal, batch): batch
                for batch in batches
            }
            for future, batch in futures.items():
                judged = future.result()
                if judged is None:
                    kept.extend(batch)
                    continue
                seen = set()
                for item in judged:
                    idx = item["idx"]
                    seen.add(idx)
                    article = batch[idx]
                    article.score = item["score"]
                    article.reason = item["reason"]
                    if item["keep"]:
                        kept.append(article)
                    else:
                        dismissed.append(article)
                for idx, article in enumerate(batch):
                    if idx not in seen:
                        logger.info("模型未返回 %s，默认保留并总结", article.title[:60])
                        kept.append(article)
        kept.sort(key=lambda item: item.score, reverse=True)
        return kept, dismissed

    def _score_batch(self, journal: str, articles: list[Article]) -> Optional[list[dict]]:
        payload = []
        for idx, article in enumerate(articles):
            abstract = (article.abstract or "").replace("\n", " ")
            if len(abstract) > 1200:
                abstract = abstract[:1200] + "..."
            payload.append({
                "id": idx,
                "title": article.title,
                "abstract": abstract,
                "pub_date": article.pub_date,
                "article_type": article.article_type,
                "source": article.source,
            })
        prompt = f"""
你是一名作物科学/育种/功能基因组学方向的科研助理，帮我从候选文献中挑出【对作物研究有启发价值】的条目。

来源：{journal}
{INTERESTS}

请严格排除：
- News / News & Views / Research Highlights / Feature / Editorial / Perspective / Commentary / Preview
- 招聘、培训广告、会议通知、基金公示、书评、政策评论
- Author Correction / Erratum / Retraction
- 公众号只有标题时，可以依据标题判断；不要因为摘要短就一律丢弃，但广告和通知必须 keep=false

候选：
{json.dumps(payload, ensure_ascii=False, indent=2)}

只输出 JSON 数组，不要解释。每项格式：
{{"id": 0, "score": 0到10的数字, "keep": true或false, "reason": "一句话说明为何对作物方向有启发或为何排除"}}
分数表示对作物育种、作物功能基因组学或组学分析的启发程度。
"""
        try:
            raw = self._chat(
                "You are an expert assistant for plant science literature triage. Output JSON only.",
                prompt,
            )
            data = _parse_json_list(raw)
        except Exception as exc:
            logger.error("%s 筛选失败，本批不缓存: %s", journal, exc)
            return None
        parsed = []
        for item in data:
            try:
                idx = int(item.get("id"))
                if not 0 <= idx < len(articles):
                    continue
                parsed.append({
                    "idx": idx,
                    "score": float(item.get("score", 0)),
                    "keep": bool(item.get("keep", False)),
                    "reason": str(item.get("reason") or "").strip(),
                })
            except (TypeError, ValueError):
                continue
        return parsed

    def summarize(self, article: Article) -> str:
        if self.client is None:
            return f"标题：{article.title}\n核心：未配置 API Key，未生成摘要。"
        material = article.abstract or "（未取得摘要，仅有标题。）"
        note = ""
        if article.source == "wechat":
            note = "这是微信公众号条目。若材料只有标题，总结必须标明“仅依据公众号标题”，禁止编造实验细节。"
        prompt = f"""
你是一名严谨的中文科研助理。请完全依据给定材料总结，不得加入材料里没有的实验、数据或结论。
{note}

1. 翻译或转写标题，以“标题：”开头。
2. 若有摘要，完整翻译摘要，以“摘要：”开头。
3. 用不超过四句话概括核心发现，以“核心：”开头，按 1、2、3、4 分条。材料不足时少写，不要凑满四条。

期刊或栏目：{article.journal}
日期：{article.pub_date}
标题：{article.title}
材料：{material[:8000]}
"""
        try:
            return self._chat(
                "You are a helpful assistant for scientific literature summarization in Chinese.",
                prompt,
            )
        except Exception as exc:
            logger.error("摘要失败 %s: %s", article.title[:60], exc)
            return f"标题：{article.title}\n核心：自动摘要失败，请打开原文。"

    def trends(self, journal: str, articles: list[Article]) -> str:
        if self.client is None or not articles:
            return ""
        payload = [
            {
                "title": article.title,
                "summary": (article.summary or "")[:800],
                "pub_date": article.pub_date,
            }
            for article in articles
        ]
        prompt = f"""
你是一名长期跟踪 {journal} 的作物/植物科学 PI。下面这些论文已经按作物研究价值筛过。
请用 1 句话评价近期趋势，再列出 3–5 条对作物育种、功能基因组学、组学分析或新技术特别有启发的方向。
每条以“- ”开头，不超过 60 字。只输出中文。

{json.dumps(payload, ensure_ascii=False, indent=2)}
"""
        try:
            return self._chat(
                "You are a helpful assistant for plant science journal trend analysis.",
                prompt,
                temperature=0.3,
            )
        except Exception as exc:
            logger.warning("趋势总结失败 %s: %s", journal, exc)
            return ""


def _parse_json_list(raw: str) -> list:
    start = raw.find("[")
    end = raw.rfind("]")
    if start == -1 or end == -1:
        raise ValueError("no JSON list")
    text = raw[start:end + 1]
    text = re.sub(r",\s*]", "]", text)
    return json.loads(text)
