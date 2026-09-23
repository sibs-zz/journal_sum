"""Run one harvest: official journals first, then WeChat, with a shared cache."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date

from journal_agent.common import Article, ArticleCache, Http, setup_logging
from journal_agent.rank import Ranker
from journal_agent.render import write_report
from journal_agent.sources import fetch_cell, fetch_nature_family, fetch_science, fetch_wechat

logger = logging.getLogger("journal_agent")


def _new_articles(cache: ArticleCache, articles: list[Article], stats: dict[str, int]) -> list[Article]:
    fresh: list[Article] = []
    for article in articles:
        stats["fetched"] += 1
        if cache.is_finished(article):
            stats["cached"] += 1
            logger.info("缓存跳过 %s", article.title[:80])
            continue
        fresh.append(article)
    return fresh


def _judge(ranker: Ranker, cache: ArticleCache, journal: str, articles: list[Article]) -> list[Article]:
    pending = []
    ready: list[Article] = []
    for article in articles:
        row = cache.lookup(article)
        if row and row["status"] == "ranked" and row["summary"]:
            article.summary = row["summary"]
            article.score = row["score"] or 0
            article.reason = row["reason"] or ""
            ready.append(article)
            continue
        if row and row["status"] == "ranked":
            article.score = row["score"] or 0
            article.reason = row["reason"] or ""
            ready.append(article)
            continue
        pending.append(article)
    kept, dismissed, overflow = ranker.select(journal, pending)
    for article in dismissed:
        cache.save(article, "dismissed")
    for article in overflow:
        cache.save(article, "ranked")
    chosen = ready + kept
    summarized = []
    for article in chosen:
        if not article.summary:
            article.summary = ranker.summarize(article)
        cache.save(article, "summarized")
        summarized.append(article)
        logger.info("已整理 %s | %s", journal, article.title[:80])
    return summarized


def run() -> None:
    setup_logging()
    logger.info("开始本轮抓取，回溯起点 %s", date.today().isoformat())
    http = Http()
    cache = ArticleCache()
    ranker = Ranker()
    stats = {"fetched": 0, "cached": 0, "duplicate": 0}
    kept: list[Article] = []

    fetchers = [
        ("Nature 系", fetch_nature_family),
        ("Cell", fetch_cell),
        ("Science", fetch_science),
    ]
    official_by_journal: dict[str, list[Article]] = defaultdict(list)
    for label, fetcher in fetchers:
        try:
            found = fetcher(http)
        except Exception as exc:
            logger.error("%s 抓取失败: %s", label, exc, exc_info=True)
            continue
        fresh = _new_articles(cache, found, stats)
        for article in fresh:
            official_by_journal[article.journal].append(article)

    for journal, articles in official_by_journal.items():
        kept.extend(_judge(ranker, cache, journal, articles))

    try:
        wechat = fetch_wechat(http)
    except Exception as exc:
        logger.error("公众号抓取失败: %s", exc, exc_info=True)
        wechat = []
    wechat_by_journal: dict[str, list[Article]] = defaultdict(list)
    for article in wechat:
        stats["fetched"] += 1
        if cache.is_finished(article) or cache.overlaps_known(article):
            stats["duplicate" if cache.overlaps_known(article) and not cache.is_finished(article) else "cached"] += 1
            if not cache.is_finished(article):
                cache.save(article, "dismissed")
                article.reason = article.reason or "与已处理文献重复"
            logger.info("公众号跳过 %s", article.title[:80])
            continue
        wechat_by_journal[article.journal].append(article)
    for journal, articles in wechat_by_journal.items():
        kept.extend(_judge(ranker, cache, journal, articles))

    trends = {}
    grouped: dict[str, list[Article]] = defaultdict(list)
    for article in kept:
        grouped[article.journal].append(article)
    for journal, articles in grouped.items():
        trends[journal] = ranker.trends(journal, articles)
    write_report(kept, trends, stats)
    logger.info(
        "完成。抓取 %d，缓存跳过 %d，重复跳过 %d，保留 %d",
        stats["fetched"], stats["cached"], stats["duplicate"], len(kept),
    )
