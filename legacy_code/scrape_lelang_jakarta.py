"""
scrape_lelang_jakarta.py — paginated scrape of `/dt/pl` (non tender) JSON for
a single agency, saving the merged rows to output/data/<no>/non_tender.json.

Default target: no=70, Provinsi DKI Jakarta -> https://spse.inaproc.id/jakarta
(which exceeded the single-request 10000-row cap).

Paginates the DataTables server-side endpoint (start += PAGE_SIZE) until an
empty page or the total cap (default 100000 rows per user request) is reached.
Replicates the exact request shape the SPSE front-end sends (Firefox UA,
form-urlencoded, order col 5 desc, tahun=2026) and follows repo conventions:
fresh GET to the listing page for the CSRF authenticityToken, 600ms delay,
retry on failure, smart resume (existing output >MIN_FILE_SIZE is skipped).

Usage:
    python scrape_lelang_jakarta.py [--no 70] [--tahun 2026] [--cap 100000]
                                    [--page-size 10000] [--force]
"""

import argparse
import csv
import io
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) "
      "Gecko/20100101 Firefox/133.0")

HTML_HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

AJAX_HEADERS = {
    "User-Agent": UA,
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.5",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest",
}

DELAY_S = 0.6
MAX_RETRIES = 3
MIN_FILE_SIZE = 200  # bytes; smaller-than-this = error page, re-fetch

TOKEN_RE = re.compile(r"authenticityToken\s*=\s*'([^']+)'")


def build_dt_body(token: str, start: int, length: int) -> str:
    """DataTables server-side POST body — exact shape captured from the site."""
    parts: list[str] = []

    def add(key: str, val: str = ""):
        parts.append(f"{key}={val}")

    add("draw", "1")
    for i in range(6):
        add(f"columns[{i}][data]", str(i))
        add(f"columns[{i}][name]")
        add(f"columns[{i}][searchable]", "true" if i != 3 else "false")
        add(f"columns[{i}][orderable]", "true" if i != 3 else "false")
        add(f"columns[{i}][search][value]")
        add(f"columns[{i}][search][regex]", "false")
    add("order[0][column]", "5")
    add("order[0][dir]", "desc")
    add("start", str(start))
    add("length", str(length))
    add("search[value]")
    add("search[regex]", "false")
    add("authenticityToken", token)
    return "&".join(parts)


def scrape_page(sess: requests.Session, base: str, tahun: str, token: str,
                start: int, length: int) -> dict:
    """POST one DataTables page over the session; return parsed JSON (or raise)."""
    api = f"{base}/dt/pl?tahun={tahun}"
    listing = (f"{base}/nontender?kategoriId=&tahun={tahun}&instansiId="
               f"&rekanan=&kontrak_status=&kontrak_tipe=")
    parsed = urlparse(base)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    body = build_dt_body(token, start, length)
    resp = sess.post(
        api,
        data=body,
        headers={**AJAX_HEADERS, "Referer": listing, "Origin": origin},
        timeout=120,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}")
    data = resp.json()
    if not isinstance(data, dict) or "data" not in data:
        raise RuntimeError(f"unexpected response shape: {str(data)[:120]}")
    return data


def init_session(base: str, tahun: str) -> tuple[requests.Session, str]:
    """GET listing page -> CSRF authenticityToken + session cookies."""
    listing = (f"{base}/nontender?kategoriId=&tahun={tahun}&instansiId="
               f"&rekanan=&kontrak_status=&kontrak_tipe=")
    sess = requests.Session()
    sess.headers.update(HTML_HEADERS)
    resp = sess.get(listing, allow_redirects=True, timeout=60)
    resp.raise_for_status()
    m = TOKEN_RE.search(resp.text)
    if not m:
        raise RuntimeError("authenticityToken not found on listing page")
    return sess, m.group(1)


def find_target(csv_path: Path, no: int) -> str:
    """Return the URL for the row with the given 'no' column."""
    with open(csv_path, encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for rec in reader:
            if rec.get("no", "") == str(no):
                url = (rec.get("url") or "").strip()
                if url:
                    return url
    raise SystemExit(f"no={no} not found in {csv_path}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--csv",
                        default="output/dedup_kl_lpse_urls_dedup_url.csv")
    parser.add_argument("--no", type=int, default=70,
                        help="Nomor baris (folder) tujuan, default 70 (DKI Jakarta)")
    parser.add_argument("--tahun", default="2026")
    parser.add_argument("--out", default="output/data")
    parser.add_argument("--cap", type=int, default=100000,
                        help="Batas maksimum total baris (default 100000)")
    parser.add_argument("--page-size", type=int, default=10000,
                        help="Baris per request DataTables (default 10000)")
    parser.add_argument("--force", action="store_true",
                        help="Re-scrape walaupun non_tender.json sudah ada")
    args = parser.parse_args()

    base_url = find_target(Path(args.csv), args.no).rstrip("/")
    out_file = Path(args.out) / str(args.no) / "non_tender.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)

    if out_file.exists() and out_file.stat().st_size > MIN_FILE_SIZE and not args.force:
        print(f"no={args.no} {base_url} -> skipped (non_tender.json already exists)")
        return

    print(f"Scraping no={args.no} {base_url} (tahun {args.tahun}, cap={args.cap})")
    sess, token = init_session(base_url, args.tahun)
    all_rows: list = []
    start = 0
    while len(all_rows) < args.cap:
        n_before = len(all_rows)
        page_rows: list = []
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                data = scrape_page(sess, base_url, args.tahun, token, start,
                                   args.page_size)
                page_rows = data.get("data", [])
                break
            except Exception as err:
                print(f"  start={start} attempt {attempt}/{MAX_RETRIES} "
                      f"FAILED: {err}")
                time.sleep(5 * attempt)
        if not page_rows:
            print(f"  start={start} -> empty page, stopping")
            break
        all_rows.extend(page_rows)
        print(f"  start={start} -> +{len(page_rows)} (total {len(all_rows)})")
        if len(page_rows) < args.page_size:
            print("  last page (< page_size), stopping")
            break
        start += len(page_rows)
        time.sleep(DELAY_S)
        if len(all_rows) == n_before:
            print("  no progress, stopping")
            break

    out = {"draw": 1, "recordsTotal": len(all_rows),
           "recordsFiltered": len(all_rows), "data": all_rows}
    out_file.write_text(json.dumps(out, indent=2, ensure_ascii=False),
                        encoding="utf-8")
    print(f"-> saved {len(all_rows)} rows -> {out_file}")


if __name__ == "__main__":
    main()
