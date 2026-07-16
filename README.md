# SPSE Kemkes 2025 Scraper

Scraper otomatis untuk mengumpulkan data pengadaan (procurement) dari portal SPSE Kementerian Kesehatan RI tahun 2025.

> **SPSE** = Sistem Pengadaan Secara Elektronik — platform e-procurement pemerintah Indonesia (Phoenix/Elixir).

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

### Python (rekomendasi)

```bash
# Install dependencies
uv sync

# Test: 5 paket per kategori
uv run python scrape_all.py --limit 5 --skip-json

# Full scrape
uv run python scrape_all.py

# Hanya HTML (skip JSON, pakai yang sudah ada)
uv run python scrape_all.py --skip-json

# Hanya JSON (skip HTML)
uv run python scrape_all.py --skip-peserta --skip-pengumuman
```

### Node.js

```bash
# Test
node scrape_all.js --limit 5 --skip-json

# Full scrape
node scrape_all.js
```

## Command Options

| Flag | Deskripsi |
|---|---|
| *(tanpa flag)* | Full scrape: JSON + semua HTML |
| `--limit N` | Batasi N paket per kategori (untuk testing) |
| `--skip-json` | Skip scrape JSON, pakai file yang sudah ada di `output/` |
| `--skip-peserta` | Skip download HTML peserta/pemenang |
| `--skip-pengumuman` | Skip download HTML pengumuman |
| `--dry` | Cek jumlah paket tanpa download |

## Output

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
scrape_all.py       # Script utama (Python) — salinan 1:1 dari scrape_all.js
scrape_all.js       # Script utama (Node.js)
scrape_spse.js      # Script lama: daftar pekerjaan + peserta (Node.js)
scrape_pengumuman.js # Script lama: pengumuman saja (Node.js)
scrape_info.md      # Referensi API: URL, headers, contoh response
```

## Keterbatasan

- `recordsTotal: 2147483647` = `Integer.MAX_VALUE` — bukan jumlah real, paginasi berhenti saat baris kosong
- Beberapa halaman peserta bisa gagal (403/redirect) — biasanya paket batal atau dibatalkan
- Data hanya tahun 2025 (hardcoded di URL API)

---

<!-- AI AGENT CONTEXT — informasi teknis untuk agent AI yang mengerjakan repo ini -->

## [AGENT CONTEXT] Technical Reference

### Target Server
- **Base URL**: `https://spse.inaproc.id/kemkes`
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
