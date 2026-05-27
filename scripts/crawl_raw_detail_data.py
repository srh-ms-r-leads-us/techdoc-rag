from bs4 import BeautifulSoup
from urllib.parse import urljoin
from pathlib import Path
from loguru import logger

from techdoc_rag.config.constants import PROJECT_ROOT

import json
import re


BASE_URL = "https://unece.org"


# =========================================================
# helpers
# =========================================================

def clean_text(text):
    if not text:
        return None

    text = re.sub(r"\s+", " ", text)

    return text.strip()


# =========================================================
# format detection
# =========================================================

def is_publication_page(soup):
    """
    Format A

    Features:
    - "Document Title"
    - "Click icon to download pdf"
    """

    text = soup.get_text(" ", strip=True)

    return (
        "Document Title" in text
        and "Click icon to download pdf" in text
    )


def is_chapter_pdf_page(soup):
    """
    Format B

    Features:
    - chapter-style pdf listing
    - ENG/FRE/RUS links
    """

    pdf_links = soup.select('a[href*=".pdf"]')

    if len(pdf_links) < 2:
        return False

    for a in pdf_links:
        text = clean_text(a.get_text())

        if text in {"ENG", "FRE", "RUS", "SPA"}:
            return True

    return False


def is_download_publication_page(soup):
    """
    Format C

    Features:
    - "Download this publication"
    """

    for a in soup.select("a[href]"):
        text = clean_text(a.get_text(" ", strip=True))

        if not text:
            continue

        if "Download this publication" not in text:
            continue

        href = a.get("href", "")

        if ".pdf" in href.lower():
            return True

    return False


def is_final_publication_pdf_page(soup):
    """
    Format D

    Features:
    - multiple pdf links
    - final/main publication pdf is the last pdf on page
    """

    pdf_links = soup.select('a[href*=".pdf"]')

    return len(pdf_links) >= 1


# =========================================================
# common extractors
# =========================================================

def extract_title(soup):
    h1 = soup.select_one("h1")

    if h1:
        return clean_text(h1.get_text())

    title = soup.select_one("title")

    if title:
        return clean_text(title.get_text())

    return None


def extract_breadcrumbs(soup):
    results = []

    for a in soup.select("div.breadlist a"):
        text = clean_text(a.get_text())

        if text:
            results.append(text)

    return results


def extract_publish_date(soup):
    selectors = [
        "time",
        ".published",
        ".date",
        ".field--name-field-date",
    ]

    for sel in selectors:
        el = soup.select_one(sel)

        if not el:
            continue

        value = clean_text(el.get_text())

        if value:
            return value

    return None


def extract_summary(soup):
    div = soup.select_one("div.text_with_summary")

    if not div:
        return None

    return clean_text(div.get_text(" ", strip=True))


# =========================================================
# pdf extractors
# =========================================================

def extract_pdfs_format_a(soup):
    """
    Example:

    EXECUTIVE SUMMARY | [pdf icon]
    """

    results = []
    seen = set()

    for a in soup.select("a[href]"):
        href = a.get("href", "").strip()

        if ".pdf" not in href.lower():
            continue

        pdf_url = urljoin(BASE_URL, href)

        title = None

        pdf_td = a.find_parent("td")

        if pdf_td:
            prev_td = pdf_td.find_previous_sibling("td")

            if prev_td:
                title = clean_text(
                    prev_td.get_text(" ", strip=True)
                )

        if not title:
            title = Path(href).stem

        item = {
            "title": title,
            "pdf_url": pdf_url,
        }

        key = (title, pdf_url)

        if key in seen:
            continue

        seen.add(key)

        results.append(item)

    return results


def extract_pdfs_format_b(soup):
    """
    Example:

    CHAPTER 1
    SAMPLE DESIGN GUIDELINES
    Michelle Simard, Sarah Franklin
    """

    results = []
    seen = set()

    for a in soup.select("a[href]"):
        href = a.get("href", "").strip()

        if ".pdf" not in href.lower():
            continue

        pdf_url = urljoin(BASE_URL, href)

        title = None

        pdf_td = a.find_parent("td")

        if pdf_td:
            prev_td = pdf_td.find_previous_sibling("td")

            if prev_td:
                title = clean_text(
                    prev_td.get_text("\n", strip=True)
                )

        if not title:
            title = Path(href).stem

        item = {
            "title": title,
            "pdf_url": pdf_url,
        }

        key = (title, pdf_url)

        if key in seen:
            continue

        seen.add(key)

        results.append(item)

    return results


def extract_pdfs_format_c(soup):
    """
    Example:

    Download this publication
    """

    results = []
    seen = set()

    for a in soup.select("a[href]"):
        text = clean_text(a.get_text(" ", strip=True))

        if not text:
            continue

        if "Download this publication" not in text:
            continue

        href = a.get("href", "").strip()

        if ".pdf" not in href.lower():
            continue

        pdf_url = urljoin(BASE_URL, href)

        title = extract_title(soup)

        item = {
            "title": title,
            "pdf_url": pdf_url,
        }

        key = (title, pdf_url)

        if key in seen:
            continue

        seen.add(key)

        results.append(item)

    return results


def extract_pdfs_format_d(soup):
    """
    Extract only the final/main publication PDF.
    """

    pdf_links = soup.select('a[href*=".pdf"]')

    if not pdf_links:
        return []

    a = pdf_links[-1]

    href = a.get("href", "").strip()

    pdf_url = urljoin(BASE_URL, href)

    title = extract_title(soup)

    return [
        {
            "title": title,
            "pdf_url": pdf_url,
        }
    ]


# =========================================================
# main parser
# =========================================================

def parse_html_file(html_path):
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()

    soup = BeautifulSoup(html, "lxml")

    data = {
        "source_file": str(html_path),
        "title": extract_title(soup),
        "breadcrumb": extract_breadcrumbs(soup),
        "publish_date": extract_publish_date(soup),
        "summary": extract_summary(soup),
        "page_type": "unknown",
        "pdfs": [],
    }

    # =====================================================
    # routing
    # =====================================================

    if is_publication_page(soup):
        data["page_type"] = "publication_page"
        data["pdfs"] = extract_pdfs_format_a(soup)

    elif is_chapter_pdf_page(soup):
        data["page_type"] = "chapter_pdf_page"
        data["pdfs"] = extract_pdfs_format_b(soup)

    elif is_download_publication_page(soup):
        data["page_type"] = "download_publication_page"
        data["pdfs"] = extract_pdfs_format_c(soup)

    elif is_final_publication_pdf_page(soup):
        data["page_type"] = "final_publication_pdf_page"
        data["pdfs"] = extract_pdfs_format_d(soup)

    return data


# =========================================================
# batch processing
# =========================================================

def process_folder(input_dir, output_jsonl):
    input_dir = Path(input_dir)

    html_files = list(input_dir.rglob("*.html"))

    results = []

    with open(output_jsonl, "w", encoding="utf-8") as fout:

        for html_file in html_files:
            try:
                data = parse_html_file(html_file)

                # ============================================
                # skip unknown page type
                # ============================================

                if data["page_type"] == "unknown":
                    logger.warning(
                        f"[SKIP] {html_file} -> unknown_page_type"
                    )
                    continue

                # ============================================
                # skip empty pdf extraction
                # ============================================

                if not data["pdfs"]:
                    logger.warning(
                        f"[SKIP] {html_file} -> no_pdfs_extracted ({data['page_type']})"
                    )
                    continue

                # ============================================
                # write output
                # ============================================

                fout.write(
                    json.dumps(data, ensure_ascii=False) + "\n"
                )

                results.append(data)

                logger.info(
                    f"[OK] {html_file} -> {data['page_type']} ({len(data['pdfs'])} pdfs)"
                )

            except Exception as e:
                logger.exception(
                    f"[ERROR] {html_file}: {e}"
                )

    logger.info(f"Done. Total parsed: {len(results)}")

    return results


# =========================================================
# main
# =========================================================

if __name__ == "__main__":
    process_folder(
        input_dir=PROJECT_ROOT /"data" / "raw" / "raw_detail_page",
        output_jsonl=PROJECT_ROOT /"data" / "raw" / "unece_publications_detail.jsonl",
    )