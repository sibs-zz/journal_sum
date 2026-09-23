#!/usr/bin/env python3
"""Crop-science literature radar.

Official journal pages (Nature family, Cell, Science) plus a small set of
WeChat public accounts. A local cache skips papers that were already summarized.
"""

from journal_agent.pipeline import run


if __name__ == "__main__":
    run()
