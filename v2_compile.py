#!/usr/bin/env python3
"""
Legacy compile script — prefer `python scan.py` for live scanning.

This script re-processes v2-*.json files using the improved compile pipeline.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from scanner.compile import compile_records, print_summary, save_compiled
from scanner.config import load_config

logging.basicConfig(level=logging.INFO, format="%(message)s")

if __name__ == "__main__":
    config = load_config()
    final, stats = compile_records([], include_legacy=True, config=config)
    save_compiled(final)
    print_summary(final, stats)
