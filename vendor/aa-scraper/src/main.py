#!/usr/bin/env python3
"""
Main entry point for the Artificial Analysis Leaderboard Scraper.

This module orchestrates the scraping process by coordinating the scraper,
parser, and formatter components to extract and process leaderboard data
from the Artificial Analysis website.

Usage:
    python src/main.py
"""
import os
import sys
import logging
from pathlib import Path

if __package__:
    from .components.config import load_config
    from .components.formatter import write_to_csv
    from .components.logger import setup_logger
    from .components.parser import parse_leaderboard
    from .components.scraper import fetch_html, fetch_html_with_playwright
    from .components.snapshot import normalize_model_url, record_local_snapshot, validate_model_table
else:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from components.config import load_config
    from components.formatter import write_to_csv
    from components.logger import setup_logger
    from components.parser import parse_leaderboard
    from components.scraper import fetch_html, fetch_html_with_playwright
    from components.snapshot import normalize_model_url, record_local_snapshot, validate_model_table


def main() -> int:
    """
    Main function that orchestrates the scraping process.

    This function coordinates all components to fetch, parse, and format
    the leaderboard data.
    """
    # Initialize the logger
    setup_logger()
    logger = logging.getLogger("web_scraper")

    # Load configuration
    config = load_config()

    # Log the start of the scraping process
    logger.info("Starting leaderboard scraping process")

    # Fetch HTML content from the target URL
    url = config.get("target_url")
    if not url:
        logger.error("Target URL not found in configuration")
        return 1
    url = normalize_model_url(url)

    html_content = fetch_html(url)
    if not html_content:
        logger.error("Failed to fetch HTML content from the target URL")
        return 1

    # Parse the leaderboard data from HTML
    leaderboard_data = parse_leaderboard(html_content)
    if not leaderboard_data:
        logger.info(
            "No table found in initial HTML, attempting to render with Playwright"
        )
        # Try fetching with Playwright
        html_content = fetch_html_with_playwright(url)
        if html_content:
            leaderboard_data = parse_leaderboard(html_content)

    if not leaderboard_data:
        logger.error("Failed to parse leaderboard data from HTML")
        return 1

    # Write the parsed data to CSV
    output_path = config.get("output_csv_path")
    if not output_path:
        logger.error("Output CSV path not found in configuration")
        return 1

    add_timestamp = config.get("output_add_timestamp", True)
    localize_numbers = config.get("output_localize_numbers", True)
    output_locale = config.get("output_locale", "el_GR")

    # Diagnostic logging to trace filename path
    logger.debug(
        f"Configured output_csv_path={output_path!r}, exists={os.path.exists(output_path)}, is_dir={os.path.isdir(output_path)}"
    )

    try:
        if config.get("output_manifest", False):
            validate_model_table(leaderboard_data)
            if add_timestamp or localize_numbers:
                raise ValueError("manifest output requires stable filename and unlocalized numbers")
        write_to_csv(
            leaderboard_data,
            output_path,
            add_timestamp=add_timestamp,
            localize_numbers=localize_numbers,
            locale_name=output_locale,
        )
        if config.get("output_manifest", False):
            record_local_snapshot(Path(output_path), url, html_content, leaderboard_data)
        logger.info("Leaderboard scraping process completed successfully")
        return 0
    except (OSError, ValueError) as e:
        logger.error(f"Failed to write data to CSV: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
