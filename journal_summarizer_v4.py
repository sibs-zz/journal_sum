#!/usr/bin/env python3
"""Crop-science literature radar (Nature family, Cell, Science)."""

import argparse

from journal_agent.pipeline import rebuild_page_from_cache, run


def main() -> None:
    parser = argparse.ArgumentParser(description="Journal Agent v4")
    parser.add_argument(
        "--rebuild-page",
        action="store_true",
        help="从缓存重建今日 HTML（不抓取、不调模型），并清除公众号缓存",
    )
    args = parser.parse_args()
    if args.rebuild_page:
        rebuild_page_from_cache()
    else:
        run()


if __name__ == "__main__":
    main()
