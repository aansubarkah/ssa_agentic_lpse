# AGENTS.md

SPSE scraper (Indonesia gov e-procurement). Scrapes tender/nontender/pencatatan for any agency+year → pipe-delimited CSV.

## One command to rule them all

```bash
python spse_pipeline.py --url https://spse.inaproc.id/<agency> --tahun <year>
uv run python spse_pipeline.py --url https://spse.inaproc.id/kemkes --tahun 2024 --limit 5  # test
```

## Only edit these files

| File | Role |
|---|---|
| `spse_pipeline.py` | **Primary script** — scrape + CSV, any agency/year |
| `scrape_all.py`, `scrape_all.js`, `convert_to_csv.js` | **Legacy** — Kemkes 2025 hardcoded, touch only for old output |

Everything else is helper/config scaffolding. `main.py` is a stub.

## Environment

- **Python**: uv-managed, >=3.14, single dep `requests` (`uv sync` to install)
- **Node.js**: v22, zero runtime deps; `npm install` pulls dev-only `exceljs`
- No tests, no linter, no typechecker

## Critical gotchas

| Gotcha | Detail |
|---|---|
| `authenticityToken` | camelCase; server 403s on snake_case |
| Pagination | Stop on **empty page**, not `recordsTotal` (which is `Integer.MAX_VALUE`) |
| Rate limiting | 600ms delay (`DELAY_S`), page size 300 (`PAGE_SIZE`) |
| Smart resume | HTML files >200B are skipped; smaller = error page, re-fetched |
| Windows | Scripts force UTF-8 on stdout/stderr (cp1252 workaround) |
| Session | Fresh `GET` to listing page before each category for new CSRF token |

## Output layout

```
output/<agency>/<tahun>/
├── tender_<tahun>.json, non_tender_<tahun>.json, pencatatan_non_tender_<tahun>.json
├── html/{tender,non_tender,pencatatan}/{peserta|pemenang,pengumuman}/
└── <agency>_<tahun>.csv   # pipe-delimited, 28 cols, 1 row per participant
```

## CSV structure

28 pipe-delimited columns: `kategori` + JSON fields (varies by category) + 9 pengumuman + 5 peserta fields. Each package expands to N rows (one per participant).

## API endpoints

| Category | DataTables endpoint | Cols | Peserta URL | Pengumuman URL |
|---|---|---|
| Tender | `POST /<agency>/dt/lelang` | 16 | `/lelang/{kode}/peserta` | `/lelang/{kode}/pengumumanlelang` |
| Non Tender | `POST /<agency>/dt/pl` | 12 | `/nontender/{kode}/peserta` | `/nontender/{kode}/pengumumanpl` |
| Pencatatan | `POST /<agency>/dt/nonspk` | 9 | `/pencatatan/pengumumannonspkpemenang?id={kode}` | `/pencatatan/pengumumannonspk?id={kode}` |

## Command flags (`spse_pipeline.py`)

`--url` (required), `--tahun`, `--categories`, `--limit`, `--skip-json`, `--skip-peserta`, `--skip-pengumuman`, `--skip-csv`, `--dry`

## Conventions

Never use emoji in any file or communication in this repo (especially README.md). Only use emojis if the user explicitly requests them.
