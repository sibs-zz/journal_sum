#!/usr/bin/env bash
cd "$(dirname "$0")"
set -euo pipefail
python journal_summarizer_v4.py
python sync_to_github.py
