"""Shared types, HTTP, dates, and the article cache."""

from __future__ import annotations

import hashlib
import logging
import os
import re
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger("journal_agent")

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = Path(os.getenv("JOURNAL_OUTPUT_DIR", str(ROOT / "site")))
CACHE_PATH = Path(os.getenv("JOURNAL_CACHE_PATH", str(ROOT / "cache" / "articles.sqlite")))
LOG_DIR = Path(os.getenv("JOURNAL_LOG_DIR", str(ROOT / "logs")))
LOOKBACK_DAYS = int(os.getenv("LOOKBACK_DAYS", "15"))
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
DEEPSEEK_MAX_TOKENS = int(os.getenv("DEEPSEEK_MAX_TOKENS", "8192"))
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "10"))
RANK_BATCH = int(os.getenv("RANK_BATCH", "12"))

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"'<>]+", re.IGNORECASE)
TAG_RE = re.compile(r"<[^>]+>")


def setup_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(
                LOG_DIR / f"journal_agent_{datetime.now():%Y%m%d}.log",
                encoding="utf-8",
            ),
        ],
    )


def cutoff_date(today: Optional[date] = None) -> date:
    today = today or date.today()
    return today - timedelta(days=LOOKBACK_DAYS)


def clean_text(value: str) -> str:
    text = TAG_RE.sub(" ", value or "")
    text = text.replace("\xa0", " ").replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", text).strip()


def normalize_title(title: str) -> str:
    text = clean_text(title).casefold()
    text = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def extract_doi(text: str) -> str:
    match = DOI_RE.search(text or "")
    if not match:
        return ""
    return match.group(0).rstrip(".,;)")


def load_api_key() -> str:
    env = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if env:
        return env
    for path in (Path("key.txt"), ROOT / "key.txt"):
        if path.exists():
            key = path.read_text(encoding="utf-8").strip()
            if key:
                return key
    return ""


def load_ncbi_api_key() -> str:
    env = os.getenv("NCBI_API_KEY", "").strip()
    if env:
        return env
    for path in (Path("ncbi_key.txt"), ROOT / "ncbi_key.txt"):
        if not path.exists():
            continue
        raw = path.read_text(encoding="utf-8").strip()
        if not raw:
            continue
        match = re.search(r'NCBI_API_KEY\s*=\s*["\']?([^"\']+)["\']?', raw)
        if match:
            return match.group(1).strip()
        if "export" not in raw.casefold():
            return raw.split()[0]
    return ""


@dataclass
class Article:
    journal: str
    title: str
    url: str
    pub_date: str
    abstract: str = ""
    doi: str = ""
    article_type: str = ""
    source: str = "official"
    content_source: str = ""
    score: float = 0.0
    reason: str = ""
    summary: str = ""
    title_zh: str = ""
    authors: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def title_norm(self) -> str:
        return normalize_title(self.title)

    @property
    def dedupe_key(self) -> str:
        if self.doi:
            return "doi:" + self.doi.casefold()
        return "title:" + self.title_norm


class Http:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8"})
        self._cffi = None

    def get(self, url: str, *, params: Optional[dict] = None, timeout: int = 40, impersonate: bool = False) -> str:
        last_error: Optional[Exception] = None
        for attempt in range(3):
            try:
                if impersonate:
                    text, status = self._get_cffi(url, params=params, timeout=timeout)
                else:
                    resp = self.session.get(url, params=params, timeout=timeout)
                    text, status = resp.text, resp.status_code
                if status == 200 and "Just a moment" not in text[:800]:
                    return text
                last_error = RuntimeError(f"HTTP {status} for {url}")
            except Exception as exc:
                last_error = exc
            time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"请求失败 {url}: {last_error}")

    def _get_cffi(self, url: str, *, params: Optional[dict], timeout: int) -> tuple[str, int]:
        if self._cffi is None:
            from curl_cffi import requests as cffi_requests

            self._cffi = cffi_requests.Session(impersonate="chrome")
        resp = self._cffi.get(url, params=params, timeout=timeout)
        return resp.text, resp.status_code


class ArticleCache:
    """Skip articles that were already summarized or judged irrelevant."""

    def __init__(self, path: Path = CACHE_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS articles (
                dedupe_key TEXT PRIMARY KEY,
                doi TEXT,
                title TEXT,
                title_norm TEXT,
                title_zh TEXT,
                url TEXT,
                journal TEXT,
                source TEXT,
                pub_date TEXT,
                status TEXT,
                score REAL,
                reason TEXT,
                summary TEXT,
                updated_at TEXT
            )
            """
        )
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_articles_doi ON articles(doi)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_articles_title ON articles(title_norm)")
        cols = {row[1] for row in self.conn.execute("PRAGMA table_info(articles)").fetchall()}
        if "authors" not in cols:
            self.conn.execute("ALTER TABLE articles ADD COLUMN authors TEXT DEFAULT ''")
        self.conn.commit()

    def lookup(self, article: Article) -> Optional[sqlite3.Row]:
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM articles WHERE dedupe_key = ?",
                (article.dedupe_key,),
            ).fetchone()
            if row:
                return row
            if article.doi:
                row = self.conn.execute(
                    "SELECT * FROM articles WHERE doi = ? AND doi != ''",
                    (article.doi.casefold(),),
                ).fetchone()
                if row:
                    return row
            if article.title_norm:
                return self.conn.execute(
                    "SELECT * FROM articles WHERE title_norm = ? AND title_norm != ''",
                    (article.title_norm,),
                ).fetchone()
        return None

    def is_finished(self, article: Article) -> bool:
        row = self.lookup(article)
        return bool(row and row["status"] in {"summarized", "dismissed"})

    def overlaps_known(self, article: Article) -> bool:
        """True when a WeChat post is the same paper as something already handled."""
        if self.lookup(article):
            return True
        title = article.title
        norm = article.title_norm
        with self._lock:
            rows = self.conn.execute(
                "SELECT title, title_norm, title_zh, doi FROM articles "
                "WHERE status IN ('summarized', 'dismissed', 'ranked')"
            ).fetchall()
        for row in rows:
            known = row["title_norm"] or ""
            if known and len(known) >= 28 and (known in norm or norm in known):
                return True
            zh = (row["title_zh"] or "").strip()
            if zh and len(zh) >= 12 and (zh in title or title in zh):
                return True
        return False

    def save(self, article: Article, status: str) -> None:
        zh = article.title_zh
        if not zh and article.summary:
            match = re.search(r"标题[:：]\s*(.+)", article.summary)
            if match:
                zh = match.group(1).strip()
                article.title_zh = zh
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO articles (
                    dedupe_key, doi, title, title_norm, title_zh, url, journal, source,
                    pub_date, status, score, reason, summary, authors, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(dedupe_key) DO UPDATE SET
                    doi=excluded.doi,
                    title=excluded.title,
                    title_norm=excluded.title_norm,
                    title_zh=excluded.title_zh,
                    url=excluded.url,
                    journal=excluded.journal,
                    authors=CASE WHEN excluded.authors != '' THEN excluded.authors ELSE articles.authors END,
                    status=excluded.status,
                    score=excluded.score,
                    reason=excluded.reason,
                    summary=excluded.summary,
                    updated_at=excluded.updated_at
                """,
                (
                    article.dedupe_key,
                    article.doi.casefold(),
                    article.title,
                    article.title_norm,
                    zh,
                    article.url,
                    article.journal,
                    article.source,
                    article.pub_date,
                    status,
                    article.score,
                    article.reason,
                    article.summary,
                    article.authors or "",
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )
            self.conn.commit()

    def patch_authors(self, article: Article) -> None:
        if not article.authors:
            return
        with self._lock:
            self.conn.execute(
                "UPDATE articles SET authors = ? WHERE dedupe_key = ?",
                (article.authors, article.dedupe_key),
            )
            self.conn.commit()

    def purge_wechat(self) -> int:
        with self._lock:
            cur = self.conn.execute("DELETE FROM articles WHERE source = 'wechat'")
            self.conn.commit()
            return cur.rowcount

    def summarized_in_window(self, cutoff: date) -> list[Article]:
        with self._lock:
            rows = self.conn.execute(
                """
                SELECT * FROM articles
                WHERE status = 'summarized' AND pub_date >= ?
                ORDER BY pub_date DESC
                """,
                (cutoff.isoformat(),),
            ).fetchall()
        items: list[Article] = []
        for row in rows:
            authors = ""
            if "authors" in row.keys():
                authors = row["authors"] or ""
            items.append(
                Article(
                    journal=row["journal"] or "",
                    title=row["title"] or "",
                    url=row["url"] or "",
                    pub_date=row["pub_date"] or "",
                    doi=row["doi"] or "",
                    source=row["source"] or "",
                    summary=row["summary"] or "",
                    score=float(row["score"] or 0),
                    reason=row["reason"] or "",
                    title_zh=row["title_zh"] or "",
                    authors=authors,
                )
            )
        return items


def stable_id(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]
