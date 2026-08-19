# Legacy Node.js scripts

Versi lama berbasis Node.js, sudah digantikan `spse.py` (Python) di root repo.
Tidak dipakai lagi; disimpan hanya sebagai referensi historis. `exceljs` masih
ada sebagai devDependency untuk `csv_to_excel.js`.

| File | Catatan |
|---|---|
| `scrape_all.js` | Hardcoded Kemkes 2025: JSON + HTML, tanpa CSV. |
| `scrape_spse.js` | Daftar pekerjaan + peserta. |
| `scrape_pengumuman.js` | Halaman pengumuman saja. |
| `convert_to_csv.js` | HTML tender Kemkes 2025 ke CSV (kategori tender saja). |
| `convert_no_html.js` | JSON ke CSV tanpa parsing HTML. |
| `csv_to_excel.js` | CSV ke Excel (memakai exceljs). |
