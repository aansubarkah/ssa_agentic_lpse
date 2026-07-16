"""
scrape_all.py — SPSE Kemkes 2025: Daftar Pekerjaan + Peserta/Pemenang + Pengumuman

Salinan 1:1 dari scrape_all.js, menggunakan requests (tanpa Selenium).

Usage:
    python scrape_all.py                    # full scrape (semua paket)
    python scrape_all.py --limit 5          # test: hanya 5 paket per kategori
    python scrape_all.py --skip-json        # skip scraping JSON, hanya HTML
    python scrape_all.py --skip-peserta     # skip HTML peserta/pemenang
    python scrape_all.py --skip-pengumuman  # skip HTML pengumuman
    python scrape_all.py --dry              # cek saja, tidak download

Dependencies:
    pip install requests
"""

import argparse
import io
import json
import os
import re
import sys
import time

# Force UTF-8 on Windows console
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
from datetime import datetime
from pathlib import Path

import requests

# ============================================================
# Config
# ============================================================
BASE = "https://spse.inaproc.id/kemkes"
ROOT = Path(__file__).resolve().parent / "output"
JSON_DIR = ROOT
HTML_ROOT = ROOT / "html"
DELAY_S = 0.6  # 600ms
PAGE_SIZE = 300

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) "
    "Gecko/20100101 Firefox/133.0"
)

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
    "Origin": "https://spse.inaproc.id",
}

# Output directories
DIRS = {
    "tender_peserta":      HTML_ROOT / "tender" / "peserta",
    "nontender_peserta":    HTML_ROOT / "non_tender" / "peserta",
    "pencatatan_pemenang":  HTML_ROOT / "pencatatan" / "pemenang",
    "tender_pengumuman":    HTML_ROOT / "tender" / "pengumuman",
    "nontender_pengumuman": HTML_ROOT / "non_tender" / "pengumuman",
    "pencatatan_pengumuman": HTML_ROOT / "pencatatan" / "pengumuman",
}

JSON_FILES = {
    "tender":     JSON_DIR / "tender_2025.json",
    "nontender":  JSON_DIR / "non_tender_2025.json",
    "pencatatan": JSON_DIR / "pencatatan_non_tender_2025.json",
}

# Field mapping per kategori (index dalam array → nama field)
TENDER_FIELDS = [
    "kode", "nama", "instansi", "status", "nilai_pagu", "kualifikasi",
    "metode_pemilihan", "evaluasi", "jenis_pengadaan", "peserta", "nilai_kontrak",
]
NONTENDER_FIELDS = [
    "kode", "nama", "instansi", "status", "nilai_pagu",
    "metode", "jenis_pengadaan", "peserta", "nilai_kontrak",
]
PENCATATAN_FIELDS = [
    "kode", "nama", "instansi", "nilai_pagu",
    "metode", "jenis_pengadaan", "tahun", "peserta", "status",
]


# ============================================================
# Helpers
# ============================================================
def safe_name(raw: str) -> str:
    """Sanitize package name for use as filename."""
    s = (raw or "")
    s = re.sub(r"<[^>]+>", "", s)       # strip HTML tags
    s = s.replace("\t", " ").replace("\n", " ").replace("\r", " ")
    s = re.sub(r'[/\\:*?"<>|\0]', "-", s)  # invalid filename chars
    s = re.sub(r"\s+", " ", s).strip()
    return s[:80]


def init_session(page_url: str) -> tuple[requests.Session, str | None]:
    """GET main page → extract CSRF authenticityToken + cookies.

    Phoenix app embeds token in JS: authenticityToken = '...'
    """
    sess = requests.Session()
    sess.headers.update(HTML_HEADERS)

    resp = sess.get(page_url, allow_redirects=True)
    resp.raise_for_status()

    m = re.search(r"authenticityToken\s*=\s*'([^']+)'", resp.text)
    token = m.group(1) if m else None
    return sess, token


def build_dt_body(token: str, draw: int, start: int, length: int, num_cols: int) -> str:
    """Build DataTables server-side POST body (form-urlencoded)."""
    parts: list[str] = []

    def add(key: str, val: str):
        parts.append(f"{key}={val}")

    add("draw", str(draw))
    add("start", str(start))
    add("length", str(length))
    add("search[value]", "")
    add("search[regex]", "false")
    add("authenticityToken", token)

    for i in range(num_cols):
        add(f"columns[{i}][data]", str(i))
        add(f"columns[{i}][name]", "")
        add(f"columns[{i}][searchable]", "true")
        add(f"columns[{i}][orderable]", "true")
        add(f"columns[{i}][search][value]", "")
        add(f"columns[{i}][search][regex]", "false")

    add("order[0][column]", "0")
    add("order[0][dir]", "asc")

    return "&".join(parts)


def fetch_all_pages(
    sess: requests.Session,
    api_url: str,
    referer_url: str,
    token: str,
    num_cols: int,
) -> list[list]:
    """Fetch all paginated DataTables rows."""
    print(f"  API: {api_url}")
    all_data: list[list] = []
    draw = 1
    start = 0
    has_more = True

    while has_more:
        body = build_dt_body(token, draw, start, PAGE_SIZE, num_cols)
        print(f"    page draw={draw} start={start} ... ", end="", flush=True)

        try:
            resp = sess.post(
                api_url,
                data=body,
                headers={**AJAX_HEADERS, "Referer": referer_url, "Cookie": sess.cookies.get_cookie_header()},
            )
            if resp.status_code != 200:
                print(f"HTTP {resp.status_code}")
                break

            payload = resp.json()
            rows = payload.get("data", [])
            print(f"{len(rows)} rows")

            if not rows:
                has_more = False
            else:
                all_data.extend(rows)
                start += len(rows)
                draw += 1
                if len(rows) < PAGE_SIZE:
                    has_more = False
                time.sleep(DELAY_S)

        except Exception as err:
            print(f"ERROR: {err}")
            time.sleep(5)
            try:
                resp = sess.post(
                    api_url,
                    data=body,
                    headers={**AJAX_HEADERS, "Referer": referer_url},
                )
                rows = resp.json().get("data", [])
                print(f"    retry → {len(rows)} rows")
                if not rows:
                    has_more = False
                else:
                    all_data.extend(rows)
                    start += len(rows)
                    draw += 1
                    if len(rows) < PAGE_SIZE:
                        has_more = False
            except Exception:
                print("    retry failed")
                has_more = False

    print(f"  Total: {len(all_data)} rows")
    return all_data


def row_to_dict(row: list, fields: list[str]) -> dict:
    """Map a DataTables row (positional array) to a named dict."""
    d = {}
    for i, field in enumerate(fields):
        d[field] = row[i] if i < len(row) else None
    return d


def download_pages(
    sess: requests.Session,
    packages: list[dict],
    url_fn,
    output_dir: Path,
    label: str,
) -> dict:
    """Download HTML pages for each package. Skips existing files >200B."""
    output_dir.mkdir(parents=True, exist_ok=True)
    ok = fail = skip = 0

    total = len(packages)
    print(f"\n  {label}: {total} paket")

    for i, pkg in enumerate(packages):
        kode = pkg["kode"]
        nama = safe_name(pkg.get("nama", ""))
        url = url_fn(kode)
        filepath = output_dir / f"{kode}_{nama}.html"

        # Smart resume: skip existing files >200 bytes
        if filepath.exists() and filepath.stat().st_size > 200:
            skip += 1
            continue

        print(f"    [{i + 1}/{total}] {kode} ... ", end="", flush=True)

        try:
            resp = sess.get(url, headers={**HTML_HEADERS, "Referer": f"{BASE}/lelang?tahun=2025"})
            if resp.status_code == 200 and len(resp.text) > 200:
                filepath.write_text(resp.text, encoding="utf-8")
                ok += 1
                print("OK")
            else:
                fail += 1
                print(f"HTTP {resp.status_code} ({len(resp.text)}b)")
        except Exception as err:
            fail += 1
            print(f"FAIL: {err}")

        time.sleep(DELAY_S)

    print(f"  → {ok} ok, {fail} fail, {skip} skipped")
    return {"ok": ok, "fail": fail, "skip": skip}


# ============================================================
# MAIN
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="SPSE Kemkes 2025 Full Scraper")
    parser.add_argument("--limit", type=int, default=0, help="Batas N paket per kategori (0=all)")
    parser.add_argument("--skip-json", action="store_true", help="Skip scrape JSON, pakai file existing")
    parser.add_argument("--skip-peserta", action="store_true", help="Skip HTML peserta/pemenang")
    parser.add_argument("--skip-pengumuman", action="store_true", help="Skip HTML pengumuman")
    parser.add_argument("--dry", action="store_true", help="Cek jumlah paket tanpa download")
    args = parser.parse_args()

    limit = args.limit
    t0 = time.time()

    print("=" * 60)
    print("SPSE Kemkes 2025 — Full Scraper (Python)")
    print("=" * 60)
    print(f"Started: {datetime.now().isoformat()}")
    print(f"Options: limit={limit or 'ALL'}, skip-json={args.skip_json}, "
          f"skip-peserta={args.skip_peserta}, skip-pengumuman={args.skip_pengumuman}, "
          f"dry={args.dry}")

    # Create all output dirs
    for d in DIRS.values():
        d.mkdir(parents=True, exist_ok=True)

    # ----------------------------------------------------------------
    # PHASE 1: Scrape JSON (daftar pekerjaan)
    # ----------------------------------------------------------------
    tender_data: list[dict] = []
    nontender_data: list[dict] = []
    pencatatan_data: list[dict] = []

    if not args.skip_json:
        print("\n" + "=" * 60)
        print("PHASE 1: DAFTAR PEKERJAAN (JSON)")
        print("=" * 60)

        # --- 1a. Tender ---
        print("\n1a. Tender 2025")
        sess1, token1 = init_session(f"{BASE}/lelang?tahun=2025")
        print(f"  Session OK (token: {token1[:12] + '...' if token1 else 'NONE'})")
        raw = fetch_all_pages(sess1, f"{BASE}/dt/lelang?tahun=2025",
                              f"{BASE}/lelang?tahun=2025", token1, 16)
        tender_data = [row_to_dict(r, TENDER_FIELDS) for r in raw]
        JSON_FILES["tender"].write_text(json.dumps(tender_data, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  Saved: {JSON_FILES['tender']} ({len(tender_data)} items)")

        # --- 1b. Non Tender ---
        print("\n1b. Non Tender 2025")
        sess2, token2 = init_session(f"{BASE}/nontender?tahun=2025")
        print("  Session OK")
        raw = fetch_all_pages(sess2, f"{BASE}/dt/pl?tahun=2025",
                              f"{BASE}/nontender?tahun=2025", token2, 12)
        nontender_data = [row_to_dict(r, NONTENDER_FIELDS) for r in raw]
        JSON_FILES["nontender"].write_text(json.dumps(nontender_data, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  Saved: {JSON_FILES['nontender']} ({len(nontender_data)} items)")

        # --- 1c. Pencatatan Non Tender ---
        print("\n1c. Pencatatan Non Tender 2025")
        sess3, token3 = init_session(f"{BASE}/pencatatan?tahun=2025")
        print("  Session OK")
        raw = fetch_all_pages(sess3, f"{BASE}/dt/nonspk?tahun=2025",
                              f"{BASE}/pencatatan?tahun=2025", token3, 9)
        pencatatan_data = [row_to_dict(r, PENCATATAN_FIELDS) for r in raw]
        JSON_FILES["pencatatan"].write_text(json.dumps(pencatatan_data, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  Saved: {JSON_FILES['pencatatan']} ({len(pencatatan_data)} items)")
    else:
        print("\nSkipping JSON (loading from disk)...")
        tender_data = json.loads(JSON_FILES["tender"].read_text(encoding="utf-8"))
        nontender_data = json.loads(JSON_FILES["nontender"].read_text(encoding="utf-8"))
        pencatatan_data = json.loads(JSON_FILES["pencatatan"].read_text(encoding="utf-8"))
        print(f"  Loaded: {len(tender_data)} tender, {len(nontender_data)} non-tender, "
              f"{len(pencatatan_data)} pencatatan")

    # Apply limit
    t_pkgs = tender_data[:limit] if limit else tender_data
    nt_pkgs = nontender_data[:limit] if limit else nontender_data
    pc_pkgs = pencatatan_data[:limit] if limit else pencatatan_data

    if args.dry:
        print("\n[DRY RUN] Would download:")
        print(f"  Tender:     {len(t_pkgs)} paket")
        print(f"  Non Tender: {len(nt_pkgs)} paket")
        print(f"  Pencatatan: {len(pc_pkgs)} paket")
        return

    # ----------------------------------------------------------------
    # PHASE 2: Download HTML — Peserta / Pemenang
    # ----------------------------------------------------------------
    if not args.skip_peserta:
        print("\n" + "=" * 60)
        print("PHASE 2: PESERTA / PEMENANG (HTML)")
        print("=" * 60)

        sess4, _ = init_session(f"{BASE}/lelang?tahun=2025")
        print("2a. Tender — Peserta")
        download_pages(sess4, t_pkgs,
                       lambda kode: f"{BASE}/lelang/{kode}/peserta",
                       DIRS["tender_peserta"], "Tender Peserta")

        sess5, _ = init_session(f"{BASE}/nontender?tahun=2025")
        print("2b. Non Tender — Peserta")
        download_pages(sess5, nt_pkgs,
                       lambda kode: f"{BASE}/nontender/{kode}/peserta",
                       DIRS["nontender_peserta"], "Non Tender Peserta")

        sess6, _ = init_session(f"{BASE}/pencatatan?tahun=2025")
        print("2c. Pencatatan — Pemenang")
        download_pages(sess6, pc_pkgs,
                       lambda kode: f"{BASE}/pencatatan/pengumumannonspkpemenang?id={kode}",
                       DIRS["pencatatan_pemenang"], "Pencatatan Pemenang")

    # ----------------------------------------------------------------
    # PHASE 3: Download HTML — Pengumuman
    # ----------------------------------------------------------------
    if not args.skip_pengumuman:
        print("\n" + "=" * 60)
        print("PHASE 3: PENGUMUMAN (HTML)")
        print("=" * 60)

        sess7, _ = init_session(f"{BASE}/lelang?tahun=2025")
        print("3a. Tender — Pengumuman")
        download_pages(sess7, t_pkgs,
                       lambda kode: f"{BASE}/lelang/{kode}/pengumumanlelang",
                       DIRS["tender_pengumuman"], "Tender Pengumuman")

        sess8, _ = init_session(f"{BASE}/nontender?tahun=2025")
        print("3b. Non Tender — Pengumuman")
        download_pages(sess8, nt_pkgs,
                       lambda kode: f"{BASE}/nontender/{kode}/pengumumanpl",
                       DIRS["nontender_pengumuman"], "Non Tender Pengumuman")

        sess9, _ = init_session(f"{BASE}/pencatatan?tahun=2025")
        print("3c. Pencatatan — Pengumuman")
        download_pages(sess9, pc_pkgs,
                       lambda kode: f"{BASE}/pencatatan/pengumumannonspk?id={kode}",
                       DIRS["pencatatan_pengumuman"], "Pencatatan Pengumuman")

    # ----------------------------------------------------------------
    # Summary
    # ----------------------------------------------------------------
    elapsed = f"{time.time() - t0:.1f}"
    print("\n" + "=" * 60)
    print(f"DONE in {elapsed}s")
    print("=" * 60)
    print(f"\nJSON files:")
    print(f"  tender_2025.json:                 {len(tender_data)} items")
    print(f"  non_tender_2025.json:             {len(nontender_data)} items")
    print(f"  pencatatan_non_tender_2025.json:  {len(pencatatan_data)} items")
    print(f"\nHTML directories (under output/html/):")
    print(f"  tender/peserta/          non_tender/peserta/        pencatatan/pemenang/")
    print(f"  tender/pengumuman/       non_tender/pengumuman/     pencatatan/pengumuman/")


if __name__ == "__main__":
    main()
