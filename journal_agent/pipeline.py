"""Run one harvest: official journals first, then WeChat, with a shared cache."""

from __future__ import annotations

import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

from journal_agent.common import Article, ArticleCache, Http, MAX_WORKERS, cutoff_date, setup_logging
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
    kept, dismissed = ranker.select(journal, pending)
    for article in dismissed:
        cache.save(article, "dismissed")
    chosen = ready + kept
    if not chosen:
        return []

    def _summarize_one(article: Article) -> Article:
        if not article.summary:
            article.summary = ranker.summarize(article)
        return article

    summarized: list[Article] = []
    workers = min(MAX_WORKERS, max(1, len(chosen)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for article in pool.map(_summarize_one, chosen):
            cache.save(article, "summarized")
            summarized.append(article)
            logger.info("已整理 %s | %s", journal, article.title[:80])
    return summarized


def _fetch_official(label: str, fetcher) -> tuple[str, list[Article]]:
    http = Http()
    return label, fetcher(http)


def _merge_for_report(cache: ArticleCache, kept: list[Article]) -> list[Article]:
    """Daily HTML lists all summarized papers in the lookback window, not only this run."""
    cutoff = cutoff_date()
    merged: dict[str, Article] = {a.dedupe_key: a for a in cache.summarized_in_window(cutoff)}
    for article in kept:
        merged[article.dedupe_key] = article
    return list(merged.values())


def run() -> None:
    setup_logging()
    logger.info("开始本轮抓取，回溯起点 %s，并行线程数 %d", date.today().isoformat(), MAX_WORKERS)
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
    with ThreadPoolExecutor(max_workers=min(3, MAX_WORKERS)) as pool:
        futures = [pool.submit(_fetch_official, label, fn) for label, fn in fetchers]
        for future in as_completed(futures):
            try:
                label, found = future.result()
            except Exception as exc:
                logger.error("官方源抓取失败: %s", exc, exc_info=True)
                continue
            fresh = _new_articles(cache, found, stats)
            for article in fresh:
                official_by_journal[article.journal].append(article)

    for journal, articles in official_by_journal.items():
        kept.extend(_judge(ranker, cache, journal, articles))

    try:
        wechat = fetch_wechat(Http())
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
    report_articles = _merge_for_report(cache, kept)
    grouped: dict[str, list[Article]] = defaultdict(list)
    for article in report_articles:
        grouped[article.journal].append(article)

    def _trend(job: tuple[str, list[Article]]) -> tuple[str, str]:
        journal, articles = job
        return journal, ranker.trends(journal, articles)

    jobs = list(grouped.items())
    if jobs:
        workers = min(MAX_WORKERS, len(jobs))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for journal, text in pool.map(_trend, jobs):
                trends[journal] = text

    write_report(report_articles, trends, stats)
    logger.info(
        "完成。抓取 %d，缓存跳过 %d，重复跳过 %d，页面 %d 篇（本轮新整理 %d）",
        stats["fetched"], stats["cached"], stats["duplicate"], len(report_articles), len(kept),
    )
