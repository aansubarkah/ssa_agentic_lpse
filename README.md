# SPSE Scraper & CSV Exporter

Scraper otomatis untuk mengumpulkan data pengadaan (procurement) dari portal SPSE — bekerja untuk **agency & tahun apapun**, sekaligus export ke CSV pipe-delimited.

> **SPSE** = Sistem Pengadaan Secara Elektronik — platform e-procurement pemerintah Indonesia (Phoenix/Elixir).

## Script mana yang harus dijalankan?

| Skenario | Script |
|---|---|
| **Scrape agency/tahun apapun + export CSV (RECOMMENDED)** | `python spse_pipeline.py --url <URL> --tahun <TAHUN>` |
| Re-export CSV dari data yang sudah di-scrape (tanpa download) | `python spse_pipeline.py --url <URL> --tahun <TAHUN> --skip-json --skip-peserta --skip-pengumuman` |
| Legacy: scrape Kemkes 2025 saja (tanpa CSV) | `python scrape_all.py` atau `node scrape_all.js` |
| Legacy: convert HTML tender Kemkes 2025 → CSV | `node convert_to_csv.js` |

> **`spse_pipeline.py`** adalah script utama & paling lengkap: scrape + CSV dalam satu perintah, multi-agency, multi-tahun, semua kategori. Script lain (`scrape_all.py/js`, `convert_to_csv.js`) adalah versi lama yang hardcoded untuk **Kemkes 2025**.

## `spse.py` (RECOMMENDED — GUI + CLI)

`spse.py` adalah entrypoint terbaru: satu file Python yang bisa dipakai dua
cara — buka **GUI Tkinter** (jalankan tanpa argumen) untuk memilih instansi,
tipe, dan tahun lewat dropdown, atau pakai **CLI headless** untuk AI agent.
Ia menggantikan `spse_pipeline.py` dan mendukung lima kategori:
`tender`, `nontender`, `pencatatan`, `swakelola`, `darurat`.

```bash
# GUI (dropdown instansi, tipe, tahun, progress bar)
python spse.py

# CLI: scrape + CSV untuk satu agency/tipe/tahun
python spse.py --agency jakarta --tipe tender --tahun 2025

# Hitung jumlah paket saja (tidak download HTML/CSV)
python spse.py --agency jakarta --tipe tender --dry

# Daftar semua instansi (slug + nama)
python spse.py --list-agencies

# Re-export CSV dari data yang sudah ada (tanpa network)
python spse.py --agency kemkes --tipe tender --skip-json --skip-html

# Uji coba: 5 paket per kategori
python spse.py --agency kemkes --tipe tender --tahun 2025 --limit 5
```

Output: `output/<slug>/<tahun>/<kategori>/` (list.json + html per paket) dan
CSV pipe-delimited di `output/<slug>/<tahun>/<slug>_<tahun>_<kategori>.csv`.
Scraping aman di-resume: file yang sudah selesai (>200 byte) otomatis di-skip.
Untuk detail teknis, baca `SPSE_SCRAPER.md`.

## Data Apa yang Diambil?

| Kategori | Jumlah Paket | Sumber |
|---|---|---|
| **Tender** | ~301 | `/lelang?tahun=2025` |
| **Non Tender** | ~993 | `/nontender?tahun=2025` |
| **Pencatatan Non Tender** | ~55 | `/pencatatan?tahun=2025` |

Untuk setiap paket diambil:

1. **Daftar pekerjaan** → file JSON terstruktur
2. **Halaman peserta/pemenang** → HTML mentah
3. **Halaman pengumuman** → HTML mentah

## Quick Start

### `spse_pipeline.py` (RECOMMENDED — any agency, any year)

```bash
# Install dependency
pip install requests   # atau: uv sync

# Full pipeline: scrape + export single CSV
python spse_pipeline.py --url https://spse.inaproc.id/mahkamahagung --tahun 2025

# Test: 5 paket per kategori
python spse_pipeline.py --url https://spse.inaproc.id/kemkes --tahun 2024 --limit 5

# Tender saja
python spse_pipeline.py --url https://spse.inaproc.id/mahkamahagung --tahun 2025 --categories tender

# Re-export CSV dari data yang sudah di-scrape (tanpa download)
python spse_pipeline.py --url https://spse.inaproc.id/kemkes --tahun 2025 \
    --skip-json --skip-peserta --skip-pengumuman

# Cek jumlah paket tanpa download
python spse_pipeline.py --url https://spse.inaproc.id/mahkamahagung --tahun 2025 --dry
```

Output tunggal: `output/<agency>/<tahun>/<agency>_<tahun>.csv` (pipe `|` delimited, 28 kolom, semua kategori tergabung dengan kolom `kategori`).

### Legacy scripts (Kemkes 2025 hardcoded)

```bash
# Python — scrape JSON + HTML (tanpa CSV)
uv run python scrape_all.py --limit 5

# Node.js — scrape JSON + HTML
node scrape_all.js

# Convert HTML tender → CSV (pipe delimited)
node convert_to_csv.js
```

## Command Options

### `spse_pipeline.py`

| Flag | Deskripsi |
|---|---|
| `--url URL` | **(wajib)** URL agency SPSE, mis. `https://spse.inaproc.id/mahkamahagung` |
| `--tahun TAHUN` | Tahun anggaran (default: tahun berjalan) |
| `--categories C` | Subset: `tender,nontender,pencatatan` (default: semua) |
| `--limit N` | Batasi N paket per kategori (testing) |
| `--skip-json` | Skip scrape JSON, pakai file yang sudah ada |
| `--skip-peserta` | Skip download HTML peserta/pemenang |
| `--skip-pengumuman` | Skip download HTML pengumuman |
| `--skip-csv` | Skip export CSV (hanya scrape) |
| `--dry` | Cek jumlah paket tanpa download |

### Legacy (`scrape_all.py` / `scrape_all.js`)

| Flag | Deskripsi |
|---|---|
| *(tanpa flag)* | Full scrape: JSON + semua HTML |
| `--limit N` | Batasi N paket per kategori (untuk testing) |
| `--skip-json` | Skip scrape JSON, pakai file yang sudah ada di `output/` |
| `--skip-peserta` | Skip download HTML peserta/pemenang |
| `--skip-pengumuman` | Skip download HTML pengumuman |
| `--dry` | Cek jumlah paket tanpa download |

## Output

### `spse_pipeline.py` (per agency + tahun)

```
output/
└── <agency>/                         # mis. mahkamahagung, kemkes
    └── <tahun>/                      # mis. 2025
        ├── tender_<tahun>.json
        ├── non_tender_<tahun>.json
        ├── pencatatan_non_tender_<tahun>.json
        ├── html/
        │   ├── tender/{peserta,pengumuman}/
        │   ├── non_tender/{peserta,pengumuman}/
        │   └── pencatatan/{pemenang,pengumuman}/
        └── <agency>_<tahun>.csv      # single combined, pipe-delimited (28 kolom)
```

**Kolom CSV gabungan (28):** `kategori` + field JSON (kode, nama, instansi, status, nilai_pagu, …) + 9 field pengumuman (`kode_rup`, `nama_paket`, `nilai_hps_paket`, `lokasi_pekerjaan`, …) + 5 field peserta (`peserta_no`, `peserta_nama`, `peserta_npwp`, `peserta_harga_penawaran`, `peserta_harga_terkoreksi`). Tiap paket di-expand menjadi N baris (1 per peserta) — sama dengan logika `convert_to_csv.js`.

### Legacy (`scrape_all.py` — Kemkes 2025 flat)

```
output/
├── tender_2025.json                  # 301 paket tender
├── non_tender_2025.json              # 993 paket non tender
├── pencatatan_non_tender_2025.json    # 55 paket pencatatan
└── html/
    ├── tender/
    │   ├── peserta/                  # halaman daftar peserta tender
    │   └── pengumuman/                # halaman pengumuman lelang
    ├── non_tender/
    │   ├── peserta/                  # halaman daftar peserta non tender
    │   └── pengumuman/               # halaman pengumuman pl
    └── pencatatan/
        ├── pemenang/                 # halaman pemenang
        └── pengumuman/               # halaman pengumuman nonspk
```

### Format JSON

Setiap paket memiliki field-field berikut:

**Tender** (11 field):
`kode`, `nama`, `instansi`, `status`, `nilai_pagu`, `kualifikasi`, `metode_pemilihan`, `evaluasi`, `jenis_pengadaan`, `peserta`, `nilai_kontrak`

**Non Tender** (9 field):
`kode`, `nama`, `instansi`, `status`, `nilai_pagu`, `metode`, `jenis_pengadaan`, `peserta`, `nilai_kontrak`

**Pencatatan Non Tender** (9 field):
`kode`, `nama`, `instansi`, `nilai_pagu`, `metode`, `jenis_pengadaan`, `tahun`, `peserta`, `status`

### Format HTML

File HTML disimpan dengan format: `{KODE}_{nama_paket}.html`

Contoh: `10102584000_Penyediaan BMHP Skrining Gagal Ginjal Kronik Tahap II.html`

## Fitur

- **Smart resume** — file HTML yang sudah ada (>200 bytes) otomatis di-skip, aman di-run ulang
- **Rate limiting** — delay 600ms antar request untuk menghindari blokir server
- **Auto retry** — satu kali retry otomatis jika request gagal
- **No external dependencies** (Node.js) — murni `https` + `zlib` bawaan Node
- **Single dependency** (Python) — cukup `requests`

## Cara Kerja

1. **GET halaman utama** → ekstrak `authenticityToken` dari JS inline (Phoenix CSRF)
2. **POST DataTables API** → paginasi 300 baris/halaman, kumpulkan semua halaman
3. **GET halaman detail** → simpan HTML peserta/pemenang & pengumuman per paket

Token CSRF harus dikirim sebagai `authenticityToken` (camelCase) — bukan `authenticity_token`. Token di-refresh setiap kali ganti seksi scraping.

## Struktur Kode

```
spse_pipeline.py     # Script utama: scrape + CSV, multi-agency & multi-tahun (Python)
scrape_all.py        # Legacy: scrape Kemkes 2025 (Python) — salinan 1:1 dari scrape_all.js
scrape_all.js        # Legacy: scrape Kemkes 2025 (Node.js)
convert_to_csv.js    # Legacy: convert HTML tender Kemkes 2025 → CSV (Node.js, tender saja)
convert_no_html.js   # Convert JSON → CSV tanpa parsing HTML
scrape_spse.js       # Script lama: daftar pekerjaan + peserta (Node.js)
scrape_pengumuman.js # Script lama: pengumuman saja (Node.js)
scrape_info.md       # Referensi API: URL, headers, contoh response
```

## Keterbatasan

- `recordsTotal: 2147483647` = `Integer.MAX_VALUE` — bukan jumlah real, paginasi berhenti saat baris kosong
- Beberapa halaman peserta bisa gagal (403/redirect) — biasanya paket batal atau dibatalkan
- Script legacy (`scrape_all.py/js`, `convert_to_csv.js`) hardcoded untuk **Kemkes 2025** — gunakan `spse_pipeline.py` untuk agency/tahun lain
- `convert_to_csv.js` hanya memproses kategori **tender**; `spse_pipeline.py` memproses semua kategori sekaligus

---

<!-- AI AGENT CONTEXT — informasi teknis untuk agent AI yang mengerjakan repo ini -->

## [AGENT CONTEXT] Technical Reference

> **Mulai dari mana?** Untuk hampir semua kebutuhan, gunakan `spse_pipeline.py --url <URL> --tahun <TAHUN>`. Endpoint, column counts, dan HTML URL patterns di bawah sudah diparameterisasi penuh oleh script ini. Script legacy hanya relevant bila mempertahankan output Kemkes 2025 yang lama.

### Target Server
- **Base URL**: `https://spse.inaproc.id/<agency>` — agency = path segment pertama (mis. `kemkes`, `mahkamahagung`)
- **Backend**: Phoenix (Elixir) — server-side rendered, tidak perlu browser/JS runtime
- **CSRF**: Token di-embed di JS variable `authenticityToken = '...'` di HTML halaman utama
- **Cookie session**: `SPSE_SESSION` berisi `___AT` (auth token), `___TS` (timestamp), `___ID` (session ID)

### Authentication Flow
```
1. GET /kemkes/{section}?tahun=2025
   → Response HTML contains: authenticityToken = 'TOKEN_HERE'
2. POST /kemkes/dt/{endpoint}?tahun=2025
   → Body: authenticityToken=TOKEN_HERE&draw=1&start=0&length=300&...columns...
   → Headers: X-Requested-With: XMLHttpRequest, Cookie: SPSE_SESSION=...
   → Response: {"draw":"1","recordsTotal":2147483647,"data":[[col0,col1,...],...]}
```

### API Endpoints
| Endpoint | Method | Columns | Kategori |
|---|---|---|---|
| `/dt/lelang?tahun=2025` | POST | 16 | Tender |
| `/dt/pl?tahun=2025` | POST | 12 | Non Tender |
| `/dt/nonspk?tahun=2025` | POST | 9 | Pencatatan Non Tender |

### HTML Page Patterns
| Halaman | URL Pattern |
|---|---|
| Tender Peserta | `/lelang/{kode}/peserta` |
| Tender Pengumuman | `/lelang/{kode}/pengumumanlelang` |
| Non Tender Peserta | `/nontender/{kode}/peserta` |
| Non Tender Pengumuman | `/nontender/{kode}/pengumumanpl` |
| Pencatatan Pemenang | `/pencatatan/pengumumannonspkpemenang?id={kode}` |
| Pencatatan Pengumuman | `/pencatatan/pengumumannonspk?id={kode}` |

### Key Decisions (jangan diubah tanpa pemahaman penuh)
- **`authenticityToken`** (camelCase) — bukan snake_case. Server return 403 jika salah.
- **Page size 300** — max yang diizinkan DataTables server-side config
- **Delay 600ms** — antar request, untuk menghindari rate limiting
- **Session init per seksi** — GET halaman utama sebelum scrape setiap seksi untuk dapat token segar
- **File HTML > 200 bytes** — threshold untuk skip (file kecil kemungkinan error page)

### Python Environment
- Managed by **uv** — `uv sync` untuk install deps, `uv run python` untuk eksekusi
- Python >= 3.14, single dependency: `requests`
- Windows: UTF-8 console wrapper sudah di-handle di script (cp1252 issue)

### Node.js Environment
- Node.js v22.22.3
- Zero dependencies — native `https` + `zlib`
