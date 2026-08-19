# SPSE Scraper (`spse.py`)

Scraper untuk portal SPSE (Sistem Pengadaan Secara Elektronik) pemerintah
Indonesia: **tender, non tender, pencatatan, swakelola, dan pengadaan
darurat**, untuk **instansi dan tahun anggaran apapun**, lengkap dengan export
CSV pipe-delimited (dan Excel opsional).

## File yang perlu dipakai

Hanya dua file di repo ini yang perlu dipakai dan dibaca:

| File | Peran |
|---|---|
| `spse.py` | Satu-satunya script yang perlu dijalankan. GUI (Tkinter) + CLI, semua instansi, semua tahun, semua kategori, scrape + CSV/Excel. |
| `all_lpse_urls.csv` | Katalog URL **seluruh LPSE pemerintah Indonesia**: semua kementerian/lembaga (K/L) dan pemerintah daerah (pemda). 735 baris, 600 LPSE unik (banyak K/L berbagi satu LPSE). Kolom: `name` (nama instansi), `url` (SPSE aktif, `https://spse.inaproc.id/<slug>`), `old_url` (domain `lpse.*.go.id` lama). Dipakai `spse.py` untuk resolve `--agency` (slug atau nama) dan mengisi dropdown GUI. |

Detail teknis `spse.py`: baca `SPSE_SCRAPER.md`.

Folder lain tidak perlu disentuh:

| Folder | Isi |
|---|---|
| `legacy_code/` | Script Python lama, sudah digantikan penuh oleh `spse.py`. Referensi saja. |
| `legacy_js/` | Script Node.js lama dengan fungsi yang sama. Referensi saja. |
| `docs/` | Catatan desain dan rencana historis. |

### Aset ikon aplikasi

Empat file ikon di root untuk shortcut/aplikasi di desktop:
`app_icon.ico` (Windows), `app_icon.icns` (macOS), `app_icon.png` dan
`app_icon.svg` (sumber/pratinjau). Agent AI yang memasang shortcut untuk GUI
`spse.py` cukup memakai format sesuai OS.

## Quick Start

```bash
# Install satu-satunya dependency
uv sync            # atau: pip install requests

# GUI: dropdown instansi, tipe, tahun, progress bar
python spse.py

# CLI: scrape + CSV
python spse.py --agency kemkes --tipe tender --tahun 2025

# Uji coba kecil: 5 paket saja
python spse.py --agency kemkes --tipe tender --tahun 2025 --limit 5

# Cek jumlah paket tanpa download
python spse.py --agency jakarta --tipe swakelola --tahun 2026 --dry

# Daftar semua instansi (slug + nama)
python spse.py --list-agencies

# Re-export CSV/Excel dari data yang sudah ada (tanpa network)
python spse.py --agency kemkes --tipe tender --tahun 2025 --skip-json --skip-html

# Sekalian export Excel (.xlsx)
python spse.py --agency kemkes --tipe tender --tahun 2025 --excel
```

### Lokasi daftar instansi

`spse.py` membaca `all_lpse_urls.csv` dari folder yang sama dengan script-nya
(repo root, file yang di-track git), jadi clone baru langsung jalan tanpa langkah
tambahan. Katalog ini memuat URL LPSE seluruh kementerian, lembaga, dan pemda
Indonesia, jadi `--agency` bisa dipakai untuk instansi mana pun. Pakai flag
`--csv` untuk memakai katalog lain:

```bash
python spse.py --csv katalog_lain.csv --list-agencies
```

## Command Options

| Flag | Deskripsi |
|---|---|
| `--agency A` | Slug LPSE atau nama instansi, mis. `jakarta` atau `kemkes` |
| `--tipe T` | `tender`, `nontender`, `pencatatan`, `swakelola`, atau `darurat` |
| `--tahun Y` | Tahun anggaran (default: tahun berjalan) |
| `--limit N` | Batasi N paket (untuk testing) |
| `--workers N` | Paralel download HTML (default: 8) |
| `--excel` | Sekalian tulis file `.xlsx` |
| `--skip-json` | Skip scrape daftar paket, pakai `list.json` yang ada |
| `--skip-html` | Skip download HTML, pakai file yang ada |
| `--skip-csv` | Skip export CSV |
| `--csv PATH` | Path katalog instansi (default: `all_lpse_urls.csv` di samping `spse.py`) |
| `--out DIR` | Root output (default: `output/`) |
| `--dry` | Cek jumlah paket tanpa download |
| `--list-agencies` | Cetak semua slug + nama instansi |

Tanpa argumen apa pun, `spse.py` membuka GUI.

## Kategori

| Kategori | `--tipe` | Listing page | DataTables endpoint (POST) | Kolom | Tab awal per paket |
|---|---|---|---|---|---|
| Tender | `tender` | `/lelang?tahun=Y` | `/dt/lelang` | 16 | `/lelang/{id}/pengumumanlelang` |
| Non Tender | `nontender` | `/nontender?tahun=Y` | `/dt/pl` | 12 | `/nontender/{id}/pengumumanpl` |
| Pencatatan Non Tender | `pencatatan` | `/pencatatan?tahun=Y` | `/dt/nonspk` | 9 | `/pencatatan/pengumumannonspk?id={id}` |
| Pencatatan Swakelola | `swakelola` | `/swakelola?tahun=Y` | `/dt/swakelola` | 5 | `/swakelola/{id}/pengumuman` |
| Pencatatan Pengadaan Darurat | `darurat` | `/darurat?tahun=Y` | `/dt/darurat-list` | 5 | `/darurat/pengumumandarurat?id={id}` |

Semua kategori difilter **server-side** lewat parameter `tahun`, jadi `--tahun`
selalu berlaku. Kalau sebuah kategori mengembalikan `0 paket`, biasanya tahun
itu memang kosong untuk instansi tersebut, bukan scraper-nya rusak. Contoh:
Kemkes tidak punya paket `swakelola` maupun `darurat` di 2025/2026, sedangkan
jakarta punya ribuan paket `swakelola` di 2026.

Dari tab awal, scraper membaca nav bar halaman untuk menemukan tab lain
(peserta/pemenang, pengumuman, RUP, realisasi) lalu mengunduh semuanya.

## Output

```
output/
└── <slug>/                        # mis. kemkes
    └── <tahun>/                   # mis. 2025
        ├── <kategori>/            # tender | nontender | pencatatan | swakelola | darurat
        │   ├── list.json          # daftar paket (cache; dipakai ulang oleh --skip-json)
        │   ├── meta.json          # info run
        │   ├── failed.json        # paket yang gagal (kalau ada)
        │   └── <kode_paket>/      # HTML per tab untuk tiap paket
        └── <slug>_<tahun>_<kategori>.csv
```

CSV: pipe-delimited (`|`), 35 kolom (`slug`, `nama_instansi`, `kategori`,
`tahun`, `kode_paket`, `nama_paket`, ..., `nama_pemenang`, `npwp`,
`harga_kontrak`, `sumber_url`, `extra_json`), UTF-8 dengan BOM agar langsung
terbuka benar di Excel. Satu paket di-expand menjadi satu baris per
peserta/pemenang.

## Cara Kerja & Gotchas

1. **CSRF**: GET halaman listing untuk token; kirim sebagai
   `authenticityToken` (camelCase, bukan `authenticity_token`). Server
   membalas 403 kalau salah.
2. **Paginasi**: POST ke endpoint DataTables, 10000 baris per halaman. Berhenti
   saat halaman kosong, bukan saat `recordsTotal`, karena `recordsTotal`
   selalu `2147483647` (`Integer.MAX_VALUE`), bukan jumlah asli.
3. **Rate limiting**: jeda 0.6 detik antar halaman list. Retry otomatis
   sampai 3 kali dengan backoff.
4. **Smart resume**: file HTML di bawah 200 byte dianggap halaman error dan
   di-fetch ulang; yang sudah benar di-skip. Aman dihentikan dan dilanjutkan.
5. **Sesi segar per kategori**: setiap kategori mulai dengan GET baru ke
   halaman listing agar token CSRF masih valid.
6. Beberapa halaman peserta memang gagal (403/redirect), biasanya paket batal.

## Environment

- Python >= 3.14, satu dependency: `requests` (`uv sync`)
- Tidak butuh Node.js; semua script Node.js lama ada di `legacy_js/` dan tidak
  dipakai lagi
- Windows: script sudah memaksa UTF-8 di stdout/stderr (workaround cp1252)

<!-- AI AGENT CONTEXT: informasi teknis untuk agent AI yang mengerjakan repo ini -->

## [AGENT CONTEXT] Technical Reference

> Mulai dari `spse.py` dan `all_lpse_urls.csv`. Semua endpoint dan pola URL di
> bawah sudah diparameterisasi penuh oleh `spse.py` (dict `CATEGORIES`).
> Folder `legacy_code/` dan `legacy_js/` hanya referensi historis.

### Target Server
- Base URL: `https://spse.inaproc.id/<slug>`, contoh `kemkes`, `jakarta`
- Backend: Phoenix (Elixir), server-side rendered, tidak perlu browser
- CSRF: token di-embed di JS variable `authenticityToken = '...'` pada HTML
  halaman listing
- Cookie session: `SPSE_SESSION` berisi `___AT`, `___TS`, `___ID`

### Authentication Flow
```
1. GET /<slug>/{listing}?tahun=2025
   -> HTML berisi: authenticityToken = 'TOKEN_HERE'
2. POST /<slug>/dt/{endpoint}?tahun=2025
   -> Body: authenticityToken=TOKEN_HERE&draw=1&start=0&length=10000&...
   -> Headers: X-Requested-With: XMLHttpRequest, Cookie: SPSE_SESSION=...
   -> Response: {"draw":"1","recordsTotal":2147483647,"data":[[...],...]}
```

### Key Decisions (jangan diubah tanpa pemahaman penuh)
- `authenticityToken` camelCase; snake_case = 403
- Page size 10000, stop pada halaman kosong (bukan `recordsTotal`)
- Delay 0.6 detik antar halaman list
- `--tahun` dikirim server-side untuk SEMUA kategori, termasuk swakelola dan
  darurat (diverifikasi live; memfilter di sisi client membuat paket yang
  hanya *bernama* "Tahun 2026" ikut bocor ke hasil 2026)
- Threshold resume: file HTML > 200 byte dianggap selesai
- CSV delimiter `|`, encoding `utf-8-sig`
