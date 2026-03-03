from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import urljoin
from uuid import uuid4

from playwright.sync_api import sync_playwright


def _scrape(url: str, include_preview: bool) -> Tuple[List[str], Optional[str]]:
    urls = set()
    preview_filename = None
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, wait_until="networkidle")
        if include_preview:
            preview_filename = f"{uuid4().hex}.jpg"
            preview_path = Path("previews") / preview_filename
            page.screenshot(path=str(preview_path), full_page=True)
        src_values = page.eval_on_selector_all(
            "img",
            "els => els.map(e => e.getAttribute('src')).filter(Boolean)",
        )
        browser.close()

    for src in src_values:
        full_url = urljoin(url, src)
        urls.add(full_url)

    return list(urls), preview_filename


def scrape_images_with_preview(url: str) -> Tuple[List[str], Optional[str]]:
    return _scrape(url, include_preview=True)


def scrape_images(url: str) -> List[str]:
    image_urls, _ = _scrape(url, include_preview=False)
    return image_urls
