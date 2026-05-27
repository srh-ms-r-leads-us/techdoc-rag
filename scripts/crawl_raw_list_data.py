import csv
from pathlib import Path
from urllib.parse import urljoin
from loguru import logger

from bs4 import BeautifulSoup
from techdoc_rag.config.constants import PROJECT_ROOT

BASE_URL = "https://unece.org/"

OUTPUT_DIR = PROJECT_ROOT / "data" / "raw"
OUTPUT_CSV = OUTPUT_DIR / "unece_publications.csv"

results = []

# page_0.html ~ page_3.html
for page_no in range(4):

    html_dir = PROJECT_ROOT / "data" / "raw" / "raw_list_page"
    html_file = html_dir / f"page_{page_no}.html"

    logger.info(f"parsing {html_file}")

    html = Path(html_file).read_text(
        encoding="utf-8"
    )

    soup = BeautifulSoup(html, "lxml")

    # Find main container
    container = soup.select_one(
        "div.views-element-container"
    )

    if not container:
        logger.warning(
            f"container not found: {html_file}"
        )
        continue

    # Find all publication row
    rows = container.select("div.views-row")

    logger.info(
        f"found {len(rows)} rows in {html_file}"
    )

    for row in rows:

        # =========================
        # Title + Link
        # =========================
        title = ""
        title_link = ""

        title_div = row.select_one(
            "div.views-field-title"
        )

        if title_div:
            a = title_div.select_one("a")

            if a:
                title = a.get_text(strip=True)

                href = a.get("href", "")

                title_link = urljoin(
                    BASE_URL,
                    href,
                )

        # =========================
        # Publish date
        # =========================
        publish_date = ""

        meta_div = row.select_one(
            "div.views-field-field-publication-date-st"
        )

        if meta_div:

            time_tag = meta_div.select_one("time")

            if time_tag:
                publish_date = time_tag.get_text(
                    strip=True
                )

        if not title:
            continue

        results.append({
            "title": title,
            "title_link": title_link,
            "publish_date": publish_date,
        })

# =========================
# Deduplicate
# =========================
dedup = {}

for item in results:
    dedup[item["title_link"]] = item

final_results = list(dedup.values())

logger.info(
    f"total unique rows: {len(final_results)}"
)

# =========================
# Output CSV
# =========================
with open(
    OUTPUT_CSV,
    "w",
    newline="",
    encoding="utf-8",
) as f:

    writer = csv.DictWriter(
        f,
        fieldnames=[
            "title",
            "title_link",
            "publish_date",
        ],
        quoting=csv.QUOTE_ALL,
    )

    writer.writeheader()

    writer.writerows(final_results)

logger.info(
    f"saved csv -> {OUTPUT_CSV}"
)
