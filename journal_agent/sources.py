"""Fetch recent biology articles from journal sites and WeChat (Sogou search)."""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from typing import Iterable, Optional
from urllib.parse import quote, urljoin
from xml.etree import ElementTree as ET

import requests
from bs4 import BeautifulSoup

from journal_agent.common import (
    Article,
    Http,
    MAX_WORKERS,
    UA,
    clean_text,
    cutoff_date,
    extract_doi,
    load_ncbi_api_key,
)

logger = logging.getLogger("journal_agent")

NATURE_SOURCES = [
    {
        "name": "Nature",
        "url": "https://www.nature.com/search",
        "params": {
            "journal": "nature",
            "article_type": "research",
            "subject": "biological-sciences",
            "order": "date_desc",
        },
    },
    {
        "name": "Nature Genetics",
        "url": "https://www.nature.com/ng/research-articles",
        "params": {},
    },
    {
        "name": "Nature Plants",
        "url": "https://www.nature.com/nplants/research-articles",
        "params": {},
    },
]

DROP_TYPE_WORDS = (
    "news",
    "editorial",
    "correction",
    "career",
    "amendment",
    "obituary",
    "comment",
    "world view",
    "where i work",
    "technology feature",
    "outlook",
    "perspective",
    "books",
)

BIO_WORDS = (
    "gene", "genome", "protein", "cell", "plant", "crop", "animal", "neuron",
    "bacteria", "virus", "ecology", "species", "tissue", "immune", "metabol",
    "rna", "dna", "crispr", "chromosome", "evolution", "organism", "microb",
    "photosynth", "hormone", "allele", "qtl", "breed", "arabidopsis", "rice",
    "wheat", "maize", "soybean", "mouse", "human", "cancer", "stem",
    "chloroplast", "mitochond", "enzyme", "receptor", "transcription", "epigen",
    "pathogen", "fung", "insect", "root", "leaf", "seed", "flower", "embryo",
    "neuron", "brain", "antibody", "vaccine", "microbiome", "symbio",
)

NONBIO_WORDS = (
    "qubit", "superconduct", "lithograph", "perovskite", "telescope",
    "exoplanet", "gravitational wave", "battery cathode", "quantum comput",
)

WECHAT_COLUMNS = [
    ("植物科学最前沿", "https://www.jintiankansha.com/column/fKqbycyq1p"),
    ("BioArt植物", "https://www.jintiankansha.com/column/Yyk5kJ9xFa"),
    ("BioArt", "https://www.jintiankansha.com/column/uRbAcCYKay"),
    ("iPlants", "https://www.jintiankansha.com/column/jCtqG2JMxy"),
]

WECHAT_NOISE = (
    "招聘", "直播", "培训", "博士后", "征稿", "优惠券", "购买", "广告",
    "基金委", "拟资助", "会议通知", "倒计时", "报名", "采购", "课程",
    "年会", "预算", "仪器", "黑客", "签约", "实操", "通知", "特价",
    "做不出来", "搞定", "国自然", "申报", "项目指南",
)

REL_DATE = re.compile(
    r"(刚刚|\d+\s*分钟前|\d+\s*小时前|昨天|前天|\d+\s*天前|\d+\s*周前|\d+\s*月前|\d+\s*年前)"
)


def _parse_iso(value: str) -> Optional[date]:
    value = (value or "")[:10]
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _keep_type(article_type: str) -> bool:
    text = (article_type or "").casefold()
    if not text:
        return True
    return not any(word in text for word in DROP_TYPE_WORDS)


def _has_term(blob: str, word: str) -> bool:
    return re.search(rf"(?<![a-z]){re.escape(word)}s?(?![a-z])", blob) is not None


def looks_biological(title: str, abstract: str) -> bool:
    blob = f"{title} {abstract}".casefold()
    bio = any(_has_term(blob, word) for word in BIO_WORDS)
    nonbio = any(_has_term(blob, word) for word in NONBIO_WORDS)
    if nonbio and not bio:
        return False
    return bio


def _fill_nature_one(article: Article) -> Article:
    http = Http()
    try:
        _fill_nature_abstract(http, article)
    except Exception as exc:
        logger.warning("打开 Nature 文章失败 %s: %s", article.url, exc)
    return article


def fetch_nature_family(http: Http, today: Optional[date] = None) -> list[Article]:
    today = today or date.today()
    cutoff = cutoff_date(today)
    found: list[Article] = []
    for source in NATURE_SOURCES:
        journal_items = _nature_listing(http, source, cutoff)
        logger.info("%s 列表 %d 篇（%s 之后）", source["name"], len(journal_items), cutoff)
        if not journal_items:
            continue
        workers = min(MAX_WORKERS, max(1, len(journal_items)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            filled = list(pool.map(_fill_nature_one, journal_items))
        for item in filled:
            if item.abstract or item.title:
                found.append(item)
    return found


def _nature_listing(http: Http, source: dict, cutoff: date) -> list[Article]:
    articles: list[Article] = []
    seen_urls: set[str] = set()
    for page in range(1, 9):
        params = dict(source["params"])
        params["page"] = page
        html = http.get(source["url"], params=params)
        soup = BeautifulSoup(html, "html.parser")
        cards = soup.select("article")
        if not cards:
            break
        page_dates: list[date] = []
        for card in cards:
            link = card.select_one("h3 a[href*='/articles/']")
            stamp = card.select_one("time")
            if not link or not stamp:
                continue
            published = _parse_iso(stamp.get("datetime") or "")
            if not published:
                continue
            page_dates.append(published)
            if published < cutoff:
                continue
            kind_el = card.select_one("[data-test='article.type']")
            kind = kind_el.get_text(" ", strip=True) if kind_el else "Article"
            if not _keep_type(kind):
                continue
            href = urljoin("https://www.nature.com", link.get("href", ""))
            if href in seen_urls:
                continue
            seen_urls.add(href)
            doi = ""
            slug = re.search(r"/articles/([^/?#]+)", href)
            if slug and slug.group(1).startswith("s"):
                doi = "10.1038/" + slug.group(1)
            articles.append(
                Article(
                    journal=source["name"],
                    title=link.get_text(" ", strip=True),
                    url=href,
                    pub_date=published.isoformat(),
                    doi=doi,
                    article_type=kind,
                    source="official",
                    content_source="nature.com",
                )
            )
        if page_dates and max(page_dates) < cutoff:
            break
        if page_dates and min(page_dates) < cutoff:
            break
    return articles


def _format_author_list(names: list[str]) -> str:
    cleaned = [n for n in names if n]
    return "; ".join(cleaned)


def _format_crossref_authors(work: dict) -> str:
    names: list[str] = []
    for author in work.get("author") or []:
        family = (author.get("family") or "").strip()
        given = (author.get("given") or "").strip()
        if not family and not given:
            continue
        names.append(f"{given} {family}".strip() if given else family)
    return _format_author_list(names)


def _pubmed_authors(node: ET.Element) -> str:
    names: list[str] = []
    for au in node.findall(".//Author"):
        last = (au.findtext("LastName") or "").strip()
        fore = (au.findtext("ForeName") or "").strip()
        if last:
            names.append(f"{fore} {last}".strip() if fore else last)
    return _format_author_list(names)


def fetch_authors_by_doi(doi: str) -> str:
    import json

    if not doi:
        return ""
    url = f"https://api.crossref.org/works/{quote(doi, safe='')}"
    raw = Http().get(url)
    work = json.loads(raw).get("message", {})
    return _format_crossref_authors(work)


def backfill_authors(articles: list[Article]) -> None:
    pending = [
        a
        for a in articles
        if a.doi and (not a.authors or " et al." in a.authors)
    ]
    if not pending:
        return

    def fill(article: Article) -> None:
        try:
            article.authors = fetch_authors_by_doi(article.doi)
        except Exception as exc:
            logger.debug("Crossref 作者补全失败 %s: %s", article.doi, exc)

    workers = min(MAX_WORKERS, max(1, len(pending)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pool.map(fill, pending)
    logger.info("已补全 %d 篇文献作者信息", sum(1 for a in pending if a.authors))


def _fill_nature_abstract(http: Http, article: Article) -> None:
    html = http.get(article.url)
    soup = BeautifulSoup(html, "html.parser")
    node = soup.select_one("#Abs1-content")
    if node:
        article.abstract = clean_text(node.get_text(" ", strip=True))
    doi_meta = soup.select_one('meta[name="citation_doi"]')
    if doi_meta and doi_meta.get("content"):
        article.doi = doi_meta["content"].strip()
    if not article.doi:
        article.doi = extract_doi(html)
    author_metas = soup.select('meta[name="citation_author"]')
    if author_metas:
        article.authors = _format_author_list(
            [m.get("content", "").strip() for m in author_metas if m.get("content")]
        )


def fetch_cell(http: Http, today: Optional[date] = None) -> list[Article]:
    """Cell 文章页 / ScienceDirect 常被反爬拦截，摘要用 PubMed 同期条目补全。"""
    today = today or date.today()
    cutoff = cutoff_date(today)
    articles = _fetch_cell_from_pubmed(cutoff, today)
    if not articles:
        logger.warning("PubMed 未返回 Cell 条目，尝试 ScienceDirect 仅抓标题列表")
        articles = _fetch_cell_sciencedirect_titles(http, cutoff)
    logger.info("Cell %d 篇（%s 之后，摘要来源 pubmed/sciencedirect）", len(articles), cutoff)
    return articles


def _pubmed_params(extra: dict) -> dict:
    params = dict(extra)
    key = load_ncbi_api_key()
    if key:
        params["api_key"] = key
    return params


def _pubmed_article_date(node: ET.Element, fallback: date) -> date:
    for tag in ("PubDate", "ArticleDate", "DateRevised"):
        dnode = node.find(f".//JournalIssue/{tag}") or node.find(f".//{tag}")
        if dnode is None:
            continue
        parsed = _ymd_to_date(
            dnode.findtext("Year"),
            dnode.findtext("Month"),
            dnode.findtext("Day"),
        )
        if parsed:
            return parsed
    return fallback


def _ymd_to_date(year: Optional[str], month: Optional[str], day: Optional[str]) -> Optional[date]:
    if not year or not str(year).isdigit():
        return None
    m = (month or "1").strip()
    d = (day or "1").strip()
    if not str(d).isdigit():
        d = "1"
    if str(m).isdigit():
        month_num = int(m)
    else:
        try:
            month_num = datetime.strptime(m[:3], "%b").month
        except ValueError:
            try:
                month_num = datetime.strptime(m, "%B").month
            except ValueError:
                month_num = 1
    try:
        return date(int(year), month_num, int(d))
    except ValueError:
        return None


def _fetch_cell_from_pubmed(cutoff: date, today: date) -> list[Article]:
    term = (
        f"Cell[Journal] AND {cutoff.strftime('%Y/%m/%d')}:{today.strftime('%Y/%m/%d')}[PDAT]"
    )
    search = requests.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
        params=_pubmed_params({"db": "pubmed", "term": term, "retmax": 200, "retmode": "json"}),
        timeout=60,
        headers={"User-Agent": "journal-agent/1.0 (mailto:journal-agent@local)"},
    )
    search.raise_for_status()
    ids = search.json().get("esearchresult", {}).get("idlist") or []
    if not ids:
        return []
    fetch = requests.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
        params=_pubmed_params({"db": "pubmed", "id": ",".join(ids), "retmode": "xml"}),
        timeout=120,
        headers={"User-Agent": "journal-agent/1.0 (mailto:journal-agent@local)"},
    )
    fetch.raise_for_status()
    root = ET.fromstring(fetch.content)
    articles: list[Article] = []
    for node in root.findall(".//PubmedArticle"):
        title = clean_text("".join(node.find(".//ArticleTitle").itertext()) if node.find(".//ArticleTitle") is not None else "")
        if not title:
            continue
        abs_parts = [
            clean_text("".join(el.itertext()))
            for el in node.findall(".//Abstract/AbstractText")
        ]
        abstract = clean_text(" ".join(p for p in abs_parts if p))
        doi = ""
        for aid in node.findall(".//ArticleId"):
            if aid.get("IdType") == "doi" and aid.text:
                doi = aid.text.strip()
                break
        pub_date = _pubmed_article_date(node, cutoff)
        if pub_date < cutoff:
            continue
        pmid_el = node.find(".//PMID")
        pmid = (pmid_el.text or "").strip() if pmid_el is not None else ""
        url = f"https://doi.org/{doi}" if doi else f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
        authors = _pubmed_authors(node)
        articles.append(
            Article(
                journal="Cell",
                title=title,
                url=url,
                pub_date=pub_date.isoformat(),
                abstract=abstract,
                doi=doi,
                authors=authors,
                article_type="Research article",
                source="official",
                content_source="pubmed",
            )
        )
    return articles


def _fetch_cell_sciencedirect_titles(http: Http, cutoff: date) -> list[Article]:
    articles: list[Article] = []
    seen: set[str] = set()
    try:
        html = http.get(
            "https://www.sciencedirect.com/journal/cell/articles-in-press",
            impersonate=True,
        )
        soup = BeautifulSoup(html, "html.parser")
        for item in soup.select("li.js-article-list-item"):
            article = _parse_sciencedirect_item(item, cutoff)
            if not article or article.doi in seen:
                continue
            seen.add(article.doi or article.url)
            articles.append(article)
    except Exception as exc:
        logger.warning("ScienceDirect 列表不可用: %s", exc)
    return articles


def _parse_sciencedirect_item(item, cutoff: date) -> Optional[Article]:
    text = item.get_text("\n", strip=True)
    doi_match = re.search(r"10\.1016/j\.cell\.[0-9A-Za-z.()]+", text)
    date_match = re.search(
        r"(?:Available online|Published online)\s+(\d{1,2}\s+[A-Za-z]+\s+\d{4})",
        text,
    )
    if not date_match:
        return None
    try:
        published = datetime.strptime(date_match.group(1), "%d %B %Y").date()
    except ValueError:
        return None
    if published < cutoff:
        return None
    title = ""
    url = ""
    for link in item.select("a[href*='/science/article/pii/']"):
        href = link.get("href") or ""
        label = link.get_text(" ", strip=True)
        if "pdfft" in href or label.lower().startswith("view pdf"):
            continue
        if len(label) < 20:
            continue
        title = label
        url = urljoin("https://www.sciencedirect.com", href.split("?")[0])
        break
    if not title:
        return None
    kind = "Research article"
    first = text.split("\n", 1)[0]
    if first:
        kind = first
    if not _keep_type(kind):
        return None
    doi = doi_match.group(0) if doi_match else extract_doi(text)
    return Article(
        journal="Cell",
        title=title,
        url=url or (f"https://doi.org/{doi}" if doi else ""),
        pub_date=published.isoformat(),
        doi=doi,
        article_type=kind,
        source="official",
        content_source="sciencedirect.com",
    )


def _science_work_to_article(
    work: dict,
    cutoff: date,
    *,
    try_official: bool,
) -> Optional[Article]:
    title = clean_text((work.get("title") or [""])[0])
    abstract = clean_text(work.get("abstract") or "")
    if not looks_biological(title, abstract):
        return None
    doi = (work.get("DOI") or "").strip()
    published = _crossref_date(work) or cutoff
    if published < cutoff:
        return None
    url = f"https://www.science.org/doi/{doi}" if doi else work.get("URL") or ""
    content_source = "crossref"
    if doi and try_official:
        try:
            page_abstract = _science_page_abstract(Http(), url)
            if page_abstract:
                abstract = page_abstract
                content_source = "science.org"
        except Exception:
            pass
    if not title:
        return None
    return Article(
        journal="Science",
        title=title,
        url=url,
        pub_date=published.isoformat(),
        abstract=abstract,
        doi=doi,
        authors=_format_crossref_authors(work),
        article_type="journal-article",
        source="official",
        content_source=content_source,
    )


def fetch_science(http: Http, today: Optional[date] = None) -> list[Article]:
    """Science 目录页经常被 Cloudflare 拦住，先打开 DOI 页，失败再用期刊登记摘要。"""
    today = today or date.today()
    cutoff = cutoff_date(today)
    works = _crossref_works("0036-8075", cutoff)
    candidates = [
        work
        for work in works
        if looks_biological(
            clean_text((work.get("title") or [""])[0]),
            clean_text(work.get("abstract") or ""),
        )
    ]
    articles: list[Article] = []
    official_pages_ok: Optional[bool] = None
    if candidates:
        probe = _science_work_to_article(candidates[0], cutoff, try_official=True)
        if probe and probe.content_source == "science.org":
            official_pages_ok = True
        else:
            official_pages_ok = False
            logger.info("Science 官网页面被拦截，本批使用期刊登记摘要")
    try_official = official_pages_ok is not False
    workers = min(MAX_WORKERS, max(1, len(candidates)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(_science_work_to_article, work, cutoff, try_official=try_official)
            for work in candidates
        ]
        for future in as_completed(futures):
            article = future.result()
            if article:
                articles.append(article)
    logger.info("Science 生物学相关 %d 篇（%s 之后）", len(articles), cutoff)
    return articles


def _science_page_abstract(http: Http, url: str) -> str:
    html = http.get(url, impersonate=True)
    soup = BeautifulSoup(html, "html.parser")
    node = soup.select_one("section#abstract, div.abstract, meta[name='citation_abstract']")
    if node and node.name == "meta":
        return clean_text(node.get("content") or "")
    if node:
        return clean_text(node.get_text(" ", strip=True))
    return ""


def _sogou_wechat_fetch(args: tuple[str, str, date, date]) -> tuple[str, list[Article]]:
    name, column_url, today, cutoff = args
    try:
        http = Http()
        batch = _wechat_column(http, name, column_url, today, cutoff)
        return name, batch
    except Exception as exc:
        logger.warning("公众号栏目抓取失败 %s: %s", name, exc)
        return name, []


def fetch_wechat(http: Http, today: Optional[date] = None) -> list[Article]:
    """近窗文章来自今天看啥栏目；正文摘要用搜狗微信按标题检索的 txt-info 摘要。"""
    today = today or date.today()
    cutoff = cutoff_date(today)
    articles: list[Article] = []
    seen: set[str] = set()
    jobs = [(name, url, today, cutoff) for name, url in WECHAT_COLUMNS]
    workers = min(MAX_WORKERS, len(jobs))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for name, batch in pool.map(_sogou_wechat_fetch, jobs):
            logger.info("公众号 %s 近窗 %d 篇（含搜狗摘要）", name, len(batch))
            for article in batch:
                key = article.dedupe_key
                if key in seen:
                    continue
                seen.add(key)
                articles.append(article)
    return articles


def _wechat_column(http: Http, name: str, column_url: str, today: date, cutoff: date) -> list[Article]:
    html = http.get(column_url)
    soup = BeautifulSoup(html, "html.parser")
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": UA,
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
    )
    articles: list[Article] = []
    for row in soup.select("tr"):
        link = row.select_one("a[href*='/t/']")
        if not link:
            continue
        title = clean_text(link.get_text(" ", strip=True))
        if not title or any(word in title for word in WECHAT_NOISE):
            continue
        published = _relative_date(row.get_text(" ", strip=True), today)
        if not published or published < cutoff:
            continue
        href = link.get("href") or ""
        if href.startswith("/"):
            href = urljoin("https://www.jintiankansha.com", href)
        abstract = _sogou_wechat_blurb(session, title) or title
        articles.append(
            Article(
                journal=name,
                title=title,
                url=href,
                pub_date=published.isoformat(),
                abstract=abstract,
                doi=extract_doi(title + " " + abstract),
                article_type="wechat",
                source="wechat",
                content_source="jintiankansha+sogou",
            )
        )
    return articles


def _sogou_wechat_blurb(session: requests.Session, title: str) -> str:
    query = title if len(title) <= 96 else title[:96]
    try:
        resp = session.get(
            "https://weixin.sogou.com/weixin",
            params={"type": "2", "query": query, "ie": "utf8"},
            timeout=25,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        needle = title[:28]
        for box in soup.select(".txt-box"):
            head = box.select_one("h3 a")
            if not head:
                continue
            hit = clean_text(head.get_text(" ", strip=True))
            if needle not in hit and hit[:28] not in title:
                continue
            info = box.select_one(".txt-info")
            if info:
                text = clean_text(info.get_text(" ", strip=True))
                if len(text) >= 40:
                    return text
        info = soup.select_one(".txt-box .txt-info")
        if info:
            return clean_text(info.get_text(" ", strip=True))
    except Exception as exc:
        logger.debug("搜狗摘要检索失败 %s: %s", title[:40], exc)
    return ""


def _relative_date(text: str, today: date) -> Optional[date]:
    match = REL_DATE.search(text.replace("\xa0", " "))
    if not match:
        return None
    token = re.sub(r"\s+", "", match.group(1))
    if token in {"刚刚"} or token.endswith("分钟前") or token.endswith("小时前"):
        return today
    if token == "昨天":
        return today.fromordinal(today.toordinal() - 1)
    if token == "前天":
        return today.fromordinal(today.toordinal() - 2)
    days = re.match(r"(\d+)天前", token)
    if days:
        return today.fromordinal(today.toordinal() - int(days.group(1)))
    weeks = re.match(r"(\d+)周前", token)
    if weeks:
        return today.fromordinal(today.toordinal() - 7 * int(weeks.group(1)))
    months = re.match(r"(\d+)月前", token)
    if months:
        return today - timedelta(days=30 * int(months.group(1)))
    return None


def _crossref_works(issn: str, cutoff: date) -> list[dict]:
    url = f"https://api.crossref.org/journals/{issn}/works"
    params = {
        "filter": f"from-pub-date:{cutoff.isoformat()},type:journal-article",
        "rows": 200,
        "select": "DOI,title,abstract,URL,published-online,published-print,published,type,author",
        "mailto": "journal-agent@local",
    }
    http = Http()
    raw = http.get(url, params=params)
    import json

    payload = json.loads(raw)
    return payload.get("message", {}).get("items", [])


def _crossref_date(work: dict) -> Optional[date]:
    for key in ("published-online", "published-print", "published"):
        parts = (work.get(key) or {}).get("date-parts") or []
        if not parts or not parts[0]:
            continue
        year, month, day = (parts[0] + [1, 1])[:3]
        try:
            return date(int(year), int(month), int(day))
        except ValueError:
            continue
    return None


def iter_official(http: Http) -> Iterable[tuple[str, list[Article]]]:
    yield "Nature 系", fetch_nature_family(http)
    yield "Cell", fetch_cell(http)
    yield "Science", fetch_science(http)
