"""
spse_pipeline.py — SPSE scrape + CSV export in a single script.

Combines the logic of `scrape_all.py` (DataTables JSON + HTML download) and
`convert_to_csv.js` (HTML parsing → pipe-delimited CSV), but generalized so it
works for ANY SPSE agency URL and ANY year.

Examples:
    # Scrape Mahkamah Agung, tahun 2025, full pipeline → single CSV
    python spse_pipeline.py --url https://spse.inaproc.id/mahkamahagung --tahun 2025

    # Quick test: 5 paket per kategori
    python spse_pipeline.py --url https://spse.inaproc.id/kemkes --tahun 2024 --limit 5

    # Re-export CSV only (reuse already-scraped JSON + HTML)
    python spse_pipeline.py --url https://spse.inaproc.id/kemkes --tahun 2025 \
        --skip-json --skip-peserta --skip-pengumuman

    # Only tender category
    python spse_pipeline.py --url https://spse.inaproc.id/mahkamahagung --tahun 2025 \
        --categories tender

Output layout:
    output/<agency>/<tahun>/
        tender_<tahun>.json
        non_tender_<tahun>.json
        pencatatan_non_tender_<tahun>.json
        html/
            tender/{peserta,pengumuman}/
            non_tender/{peserta,pengumuman}/
            pencatatan/{pemenang,pengumuman}/
        <agency>_<tahun>.csv          ← single combined, pipe-delimited

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
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import requests

# Force UTF-8 on Windows console
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ============================================================
# Constants
# ============================================================
DELAY_S = 0.6        # 600ms between requests
PAGE_SIZE = 300      # DataTables page length
DELIM = "|"          # CSV field delimiter

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
}

# Field schema per category (positional index in DataTables row → field name)
TENDER_FIELDS = [
    "kode", "nama", "instansi", "status", "nilai_pagu", "kualifikasi",
    "metode_pemilihan", "evaluasi", "jenis_pengadaan", "jumlah_peserta",
    "nilai_kontrak",
]
NONTENDER_FIELDS = [
    "kode", "nama", "instansi", "status", "nilai_pagu",
    "metode", "jenis_pengadaan", "jumlah_peserta", "nilai_kontrak",
]
PENCATATAN_FIELDS = [
    "kode", "nama", "instansi", "nilai_pagu",
    "metode", "jenis_pengadaan", "tahun", "jumlah_peserta", "status",
]

# DataTables column counts (must match the agency's table layout)
DT_NUM_COLS = {"tender": 16, "nontender": 12, "pencatatan": 9}

# API endpoints per category (path under BASE)
DT_API = {
    "tender":     "/dt/lelang?tahun={tahun}",
    "nontender":  "/dt/pl?tahun={tahun}",
    "pencatatan": "/dt/nonspk?tahun={tahun}",
}
# Listing page (where the CSRF token lives) per category
LIST_PAGE = {
    "tender":     "/lelang?tahun={tahun}",
    "nontender":  "/nontender?tahun={tahun}",
    "pencatatan": "/pencatatan?tahun={tahun}",
}
# HTML detail endpoints per category
HTML_URL = {
    "tender": {
        "peserta":   lambda base, kode: f"{base}/lelang/{kode}/peserta",
        "pengumuman": lambda base, kode: f"{base}/lelang/{kode}/pengumumanlelang",
    },
    "nontender": {
        "peserta":   lambda base, kode: f"{base}/nontender/{kode}/peserta",
        "pengumuman": lambda base, kode: f"{base}/nontender/{kode}/pengumumanpl",
    },
    "pencatatan": {
        "pemenang":   lambda base, kode: f"{base}/pencatatan/pengumumannonspkpemenang?id={kode}",
        "pengumuman": lambda base, kode: f"{base}/pencatatan/pengumumannonspk?id={kode}",
    },
}
# Which HTML "detail" key each category uses for the participant/winner page
DETAIL_KEY = {"tender": "peserta", "nontender": "peserta", "pencatatan": "pemenang"}

# Pengumuman fields extracted from HTML
PENGUMUMAN_FIELDS = [
    "kode_rup", "nama_paket", "tanggal_pembuatan", "k_l_pd_instansi_lainnya",
    "satuan_kerja", "tahun_anggaran", "nilai_hps_paket", "jenis_kontrak",
    "lokasi_pekerjaan",
]
# Peserta/pemenang fields extracted from HTML
PESERTA_FIELDS = [
    "peserta_no", "peserta_nama", "peserta_npwp",
    "peserta_harga_penawaran", "peserta_harga_terkoreksi",
]

# Ordered superset of columns for the combined CSV
COMBINED_COLUMNS = [
    "kategori", "kode", "nama", "instansi", "status", "nilai_pagu",
    "kualifikasi", "metode_pemilihan", "evaluasi", "metode", "jenis_pengadaan",
    "tahun", "jumlah_peserta", "nilai_kontrak",
    *PENGUMUMAN_FIELDS,
    *PESERTA_FIELDS,
]


# ============================================================
# Config resolution
# ============================================================
def resolve_config(url: str, tahun: str) -> dict:
    """Derive BASE, agency slug, and output paths from a SPSE URL."""
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    parts = [p for p in parsed.path.split("/") if p]
    agency = parts[0] if parts else "spse"
    # If the URL already includes an agency subpath, keep the full path as BASE
    if parts:
        base = f"{base}/" + "/".join(parts)

    base = base.rstrip("/")
    root = Path(__file__).resolve().parent / "output" / agency / tahun
    config = {
        "base": base,
        "agency": agency,
        "tahun": tahun,
        "root": root,
        "json": {
            "tender":     root / f"tender_{tahun}.json",
            "nontender":  root / f"non_tender_{tahun}.json",
            "pencatatan": root / f"pencatatan_non_tender_{tahun}.json",
        },
        "html": {
            "tender":     {"peserta": root / "html" / "tender" / "peserta",
                           "pengumuman": root / "html" / "tender" / "pengumuman"},
            "nontender":  {"peserta": root / "html" / "non_tender" / "peserta",
                           "pengumuman": root / "html" / "non_tender" / "pengumuman"},
            "pencatatan": {"pemenang": root / "html" / "pencatatan" / "pemenang",
                           "pengumuman": root / "html" / "pencatatan" / "pengumuman"},
        },
        "csv": root / f"{agency}_{tahun}.csv",
    }
    return config


# ============================================================
# HTTP / scraping helpers
# ============================================================
def safe_name(raw: str) -> str:
    """Sanitize a package name for use as a filename."""
    s = raw or ""
    s = re.sub(r"<[^>]+>", "", s)
    s = s.replace("\t", " ").replace("\n", " ").replace("\r", " ")
    s = re.sub(r'[/\\:*?"<>|\0]', "-", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:80]


def init_session(base: str, tahun: str, cat: str) -> tuple[requests.Session, str | None]:
    """GET the listing page → extract CSRF authenticityToken + cookies."""
    sess = requests.Session()
    sess.headers.update(HTML_HEADERS)
    page_url = f"{base}{LIST_PAGE[cat].format(tahun=tahun)}"
    resp = sess.get(page_url, allow_redirects=True)
    resp.raise_for_status()
    m = re.search(r"authenticityToken\s*=\s*'([^']+)'", resp.text)
    token = m.group(1) if m else None
    return sess, token


def build_dt_body(token: str, draw: int, start: int, length: int, num_cols: int) -> str:
    """Build a DataTables server-side POST body (form-urlencoded)."""
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


def fetch_all_pages(sess: requests.Session, base: str, tahun: str, cat: str,
                    token: str) -> list[list]:
    """Fetch all paginated DataTables rows for a category."""
    api_url = f"{base}{DT_API[cat].format(tahun=tahun)}"
    referer = f"{base}{LIST_PAGE[cat].format(tahun=tahun)}"
    num_cols = DT_NUM_COLS[cat]
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
                headers={**AJAX_HEADERS, "Referer": referer,
                         "Origin": base,
                         "Cookie": sess.cookies.get_cookie_header()},
            )
            if resp.status_code != 200:
                print(f"HTTP {resp.status_code}")
                break
            rows = resp.json().get("data", [])
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
                resp = sess.post(api_url, data=body,
                                 headers={**AJAX_HEADERS, "Referer": referer})
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
    d = {}
    for i, field in enumerate(fields):
        d[field] = row[i] if i < len(row) else None
    return d


def download_pages(sess: requests.Session, base: str, tahun: str, cat: str,
                   kind: str, packages: list[dict], output_dir: Path,
                   label: str) -> dict:
    """Download HTML pages for each package. Skips existing files >200B."""
    output_dir.mkdir(parents=True, exist_ok=True)
    url_fn = HTML_URL[cat][kind]
    referer = f"{base}{LIST_PAGE[cat].format(tahun=tahun)}"
    ok = fail = skip = 0
    total = len(packages)
    print(f"\n  {label}: {total} paket")

    for i, pkg in enumerate(packages):
        kode = str(pkg["kode"])
        nama = safe_name(pkg.get("nama", "") or "")
        url = url_fn(base, kode)
        filepath = output_dir / f"{kode}_{nama}.html"

        if filepath.exists() and filepath.stat().st_size > 200:
            skip += 1
            continue

        print(f"    [{i + 1}/{total}] {kode} ... ", end="", flush=True)
        try:
            resp = sess.get(url, headers={**HTML_HEADERS, "Referer": referer})
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
# HTML parsing (ported from convert_to_csv.js)
# ============================================================
def clean_html(val: str) -> str:
    """Strip tags + decode common HTML entities, collapse whitespace."""
    if not val:
        return ""
    s = val
    s = re.sub(r"<[^>]*>", "", s)                 # strip tags
    s = re.sub(r"&nbsp;", " ", s, flags=re.IGNORECASE)
    s = re.sub(r"&amp;", "&", s, flags=re.IGNORECASE)
    s = re.sub(r"&lt;", "<", s, flags=re.IGNORECASE)
    s = re.sub(r"&gt;", ">", s, flags=re.IGNORECASE)
    s = re.sub(r"&quot;", '"', s, flags=re.IGNORECASE)
    s = re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _text_after_label(html: str, label: str) -> str:
    """Return cleaned text of the first <td> following a <th>label</th>."""
    m = re.search(
        rf"{re.escape(label)}</th>[\s\S]*?<td[^>]*>([\s\S]*?)</td>",
        html, re.IGNORECASE)
    return clean_html(m.group(1)) if m else ""


def parse_pengumuman(html: str) -> dict:
    """Extract pengumuman fields from an HTML detail page."""
    out = {k: "" for k in PENGUMUMAN_FIELDS}

    # Kode RUP + Nama Paket (live inside a sub-table)
    m = re.search(
        r"Kode RUP[\s\S]*?<td[^>]*>(\d+)</td>[\s\S]*?<td[^>]*>([\s\S]*?)</td>",
        html, re.IGNORECASE)
    if m:
        out["kode_rup"] = m.group(1).strip()
        out["nama_paket"] = clean_html(m.group(2))

    out["tanggal_pembuatan"] = _text_after_label(html, "Tanggal Pembuatan")
    out["k_l_pd_instansi_lainnya"] = _text_after_label(html, "K/L/PD/Instansi Lainnya")
    out["satuan_kerja"] = _text_after_label(html, "Satuan Kerja")
    out["tahun_anggaran"] = _text_after_label(html, "Tahun Anggaran")
    out["nilai_hps_paket"] = _text_after_label(html, "Nilai HPS Paket")
    out["jenis_kontrak"] = _text_after_label(html, "Jenis Kontrak")

    m = re.search(
        r"Lokasi Pekerjaan</th>[\s\S]*?<td[^>]*>([\s\S]*?)</td>",
        html, re.IGNORECASE)
    if m:
        li = re.search(r"<li>([\s\S]*?)</li>", m.group(1), re.IGNORECASE)
        out["lokasi_pekerjaan"] = clean_html(li.group(1) if li else m.group(1))
    return out


def parse_peserta(html: str) -> list[dict]:
    """Extract participant rows from a peserta/pemenang HTML table."""
    rows: list[dict] = []
    tbody = re.search(r"<tbody>([\s\S]*?)</tbody>", html, re.IGNORECASE)
    if not tbody:
        return rows
    for tr in re.finditer(r"<tr>([\s\S]*?)</tr>", tbody.group(1), re.IGNORECASE):
        tds = re.findall(r"<td[^>]*>([\s\S]*?)</td>", tr.group(1), re.IGNORECASE)
        if len(tds) >= 5:
            rows.append({
                "peserta_no": clean_html(tds[0]),
                "peserta_nama": clean_html(tds[1]),
                "peserta_npwp": clean_html(tds[2]),
                "peserta_harga_penawaran": clean_html(tds[3]),
                "peserta_harga_terkoreksi": clean_html(tds[4]),
            })
    return rows


def index_html_dir(directory: Path) -> dict[str, Path]:
    """Map kode → filepath for every *.html file in a directory."""
    index: dict[str, Path] = {}
    if not directory.exists():
        return index
    for f in directory.iterdir():
        if f.suffix == ".html":
            index[f.name.split("_")[0]] = f
    return index


# ============================================================
# CSV export
# ============================================================
def escape_field(val) -> str:
    s = "" if val is None else str(val)
    if DELIM in s or '"' in s or "\n" in s or "\r" in s:
        return '"' + s.replace('"', '""') + '"'
    return s


def build_rows_for_category(cat: str, packages: list[dict], cfg: dict) -> list[dict]:
    """Join JSON + pengumuman HTML + peserta/pemenang HTML into flat rows."""
    peng_idx = index_html_dir(cfg["html"][cat]["pengumuman"])
    det_key = DETAIL_KEY[cat]
    det_idx = index_html_dir(cfg["html"][cat][det_key])

    json_keys = {"tender": TENDER_FIELDS,
                 "nontender": NONTENDER_FIELDS,
                 "pencatatan": PENCATATAN_FIELDS}[cat]

    out_rows: list[dict] = []
    matched_peng = matched_det = total_det_rows = 0

    for pkg in packages:
        kode = str(pkg["kode"])
        base_row: dict[str, str] = {"kategori": cat}
        for key in json_keys:
            val = pkg.get(key, "") or ""
            if key == "nama":
                val = clean_html(val)
            base_row[key] = val

        # Pengumuman
        pf = peng_idx.get(kode)
        if pf:
            matched_peng += 1
            parsed = parse_pengumuman(pf.read_text(encoding="utf-8", errors="replace"))
            base_row.update(parsed)
        else:
            base_row.update({k: "" for k in PENGUMUMAN_FIELDS})

        # Peserta / pemenang detail
        df = det_idx.get(kode)
        detail_rows: list[dict] = []
        if df:
            matched_det += 1
            parsed = parse_peserta(df.read_text(encoding="utf-8", errors="replace"))
            for prow in parsed:
                row = {**base_row}
                row.update(prow)
                detail_rows.append(row)
                total_det_rows += 1

        if detail_rows:
            out_rows.extend(detail_rows)
        else:
            row = {**base_row}
            row.update({k: "" for k in PESERTA_FIELDS})
            out_rows.append(row)

    print(f"  [{cat}] matched pengumuman: {matched_peng}/{len(packages)}, "
          f"matched {det_key}: {matched_det}/{len(packages)}, "
          f"detail rows: {total_det_rows}, total csv rows: {len(out_rows)}")
    return out_rows


def write_combined_csv(rows: list[dict], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [DELIM.join(escape_field(c) for c in COMBINED_COLUMNS)]
    for row in rows:
        lines.append(DELIM.join(escape_field(row.get(c, "")) for c in COMBINED_COLUMNS))
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n  Written: {out_path} ({len(rows)} rows, {len(COMBINED_COLUMNS)} cols)")


# ============================================================
# MAIN
# ============================================================
def main():
    parser = argparse.ArgumentParser(
        description="SPSE scrape + CSV export (any agency, any year)")
    parser.add_argument("--url", required=True,
                        help="SPSE agency URL, e.g. https://spse.inaproc.id/mahkamahagung")
    parser.add_argument("--tahun", default=str(datetime.now().year),
                        help="Tahun anggaran (default: current year)")
    parser.add_argument("--categories", default="tender,nontender,pencatatan",
                        help="Comma-separated subset: tender,nontender,pencatatan")
    parser.add_argument("--limit", type=int, default=0,
                        help="Batas N paket per kategori (0=all)")
    parser.add_argument("--skip-json", action="store_true",
                        help="Skip JSON scrape, pakai file existing")
    parser.add_argument("--skip-peserta", action="store_true",
                        help="Skip HTML peserta/pemenang")
    parser.add_argument("--skip-pengumuman", action="store_true",
                        help="Skip HTML pengumuman")
    parser.add_argument("--skip-csv", action="store_true",
                        help="Skip export CSV")
    parser.add_argument("--dry", action="store_true",
                        help="Cek jumlah paket tanpa download")
    args = parser.parse_args()

    cfg = resolve_config(args.url, args.tahun)
    cats = [c.strip() for c in args.categories.split(",") if c.strip()]
    bad = [c for c in cats if c not in ("tender", "nontender", "pencatatan")]
    if bad:
        parser.error(f"Unknown categories: {bad}. Valid: tender,nontender,pencatatan")

    field_map = {"tender": TENDER_FIELDS,
                 "nontender": NONTENDER_FIELDS,
                 "pencatatan": PENCATATAN_FIELDS}

    t0 = time.time()
    print("=" * 64)
    print(f"SPSE Pipeline  —  {cfg['agency']}  /  tahun {cfg['tahun']}")
    print("=" * 64)
    print(f"Started : {datetime.now().isoformat()}")
    print(f"BASE    : {cfg['base']}")
    print(f"Output  : {cfg['root']}")
    print(f"Options : categories={cats}, limit={args.limit or 'ALL'}, "
          f"skip-json={args.skip_json}, skip-peserta={args.skip_peserta}, "
          f"skip-pengumuman={args.skip_pengumuman}, skip-csv={args.skip_csv}, "
          f"dry={args.dry}")

    # Ensure all output dirs exist
    for cat in cats:
        for d in cfg["html"][cat].values():
            d.mkdir(parents=True, exist_ok=True)

    # ----------------------------------------------------------------
    # PHASE 1: Scrape JSON (daftar pekerjaan)
    # ----------------------------------------------------------------
    data: dict[str, list[dict]] = {}
    if not args.skip_json:
        print("\n" + "=" * 64)
        print("PHASE 1: DAFTAR PEKERJAAN (JSON)")
        print("=" * 64)
        for cat in cats:
            print(f"\n[{cat}] {args.tahun}")
            sess, token = init_session(cfg["base"], args.tahun, cat)
            print(f"  Session OK (token: {token[:12] + '...' if token else 'NONE'})")
            raw = fetch_all_pages(sess, cfg["base"], args.tahun, cat, token)
            rows = [row_to_dict(r, field_map[cat]) for r in raw]
            cfg["json"][cat].write_text(
                json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"  Saved: {cfg['json'][cat]} ({len(rows)} items)")
            data[cat] = rows
    else:
        print("\nSkipping JSON scrape (loading from disk)...")
        for cat in cats:
            p = cfg["json"][cat]
            data[cat] = json.loads(p.read_text(encoding="utf-8")) if p.exists() else []
            print(f"  {cat}: {len(data[cat])} items")

    # Apply limit
    pkgs = {cat: (d[:args.limit] if args.limit else d) for cat, d in data.items()}

    if args.dry:
        print("\n[DRY RUN] Would download:")
        for cat in cats:
            print(f"  {cat}: {len(pkgs[cat])} paket")
        return

    # ----------------------------------------------------------------
    # PHASE 2: Download HTML — Peserta / Pemenang
    # ----------------------------------------------------------------
    if not args.skip_peserta:
        print("\n" + "=" * 64)
        print("PHASE 2: PESERTA / PEMENANG (HTML)")
        print("=" * 64)
        for cat in cats:
            det_key = DETAIL_KEY[cat]
            sess, _ = init_session(cfg["base"], args.tahun, cat)
            print(f"\n[{cat}] {det_key}")
            download_pages(sess, cfg["base"], args.tahun, cat, det_key,
                           pkgs[cat], cfg["html"][cat][det_key],
                           f"{cat} {det_key}".title())

    # ----------------------------------------------------------------
    # PHASE 3: Download HTML — Pengumuman
    # ----------------------------------------------------------------
    if not args.skip_pengumuman:
        print("\n" + "=" * 64)
        print("PHASE 3: PENGUMUMAN (HTML)")
        print("=" * 64)
        for cat in cats:
            sess, _ = init_session(cfg["base"], args.tahun, cat)
            print(f"\n[{cat}] pengumuman")
            download_pages(sess, cfg["base"], args.tahun, cat, "pengumuman",
                           pkgs[cat], cfg["html"][cat]["pengumuman"],
                           f"{cat} pengumuman".title())

    # ----------------------------------------------------------------
    # PHASE 4: Export → single combined CSV
    # ----------------------------------------------------------------
    if not args.skip_csv:
        print("\n" + "=" * 64)
        print("PHASE 4: EXPORT CSV (| delimiter)")
        print("=" * 64)
        all_rows: list[dict] = []
        for cat in cats:
            all_rows.extend(build_rows_for_category(cat, data[cat], cfg))
        write_combined_csv(all_rows, cfg["csv"])

    # ----------------------------------------------------------------
    # Summary
    # ----------------------------------------------------------------
    elapsed = f"{time.time() - t0:.1f}"
    print("\n" + "=" * 64)
    print(f"DONE in {elapsed}s")
    print("=" * 64)
    for cat in cats:
        print(f"  {cat:11s}: {len(data[cat])} items")
    if not args.skip_csv:
        print(f"\nCombined CSV: {cfg['csv']}")


if __name__ == "__main__":
    main()
