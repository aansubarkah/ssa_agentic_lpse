# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Style rules

- **Never use emoji in any file**, especially `README.md`, unless the user explicitly asks for emoji in the prompt. This applies to docs, code comments, commit messages, and all generated output.

## What this repo does

A scraper for **SPSE** (Sistem Pengadaan Secara Elektronik — Indonesia's government e-procurement platform, Phoenix/Elixir backend). It downloads procurement data (tender / non-tender / pencatatan categories) for any agency and year, then exports a combined pipe-delimited CSV. The README is written in Indonesian and is the authoritative source of detail; read it for column lists and API reference.

## The one script that matters

**`spse_pipeline.py`** is the primary, fully-generalized script. It supersedes the legacy scripts (`scrape_all.py`, `scrape_all.js`, `convert_to_csv.js`, etc.), which are hardcoded to **Kemkes 2025** and should only be touched when maintaining that old output. Start any new work here.

```bash
# Full pipeline (scrape JSON + HTML + combined CSV)
python spse_pipeline.py --url https://spse.inaproc.id/<agency> --tahun <year>

# Test run: 5 paket per category
python spse_pipeline.py --url https://spse.inaproc.id/kemkes --tahun 2024 --limit 5

# Re-export CSV from already-scraped data (no network)
python spse_pipeline.py --url https://spse.inaproc.id/kemkes --tahun 2025 \
    --skip-json --skip-peserta --skip-pengumuman

# Just count packages
python spse_pipeline.py --url https://spse.inaproc.id/mahkamahagung --tahun 2025 --dry
```

There is no build step, no test suite, and no linter configured.

## Environment / commands

- **Python** (managed by `uv`, requires Python >=3.14): single dependency `requests`.
  - Install: `uv sync` (or `pip install requests`)
  - Run: `uv run python spse_pipeline.py ...` or plain `python spse_pipeline.py ...`
- **Node.js** v22, zero runtime deps (native `https` + `zlib`); `exceljs` is dev-only (used by `csv_to_excel.js`). `npm install` pulls dev deps.

## context-mode tools

context-mode is active. Prefer these MCP tools over inline `bash`/`cat` so large outputs stay out of the context window — only what you print (`console.log`) enters context. Hierarchy:

`ctx_batch_execute` > `ctx_execute` > `ctx_execute_file` > `ctx_search`

- Read/edit files → `ctx_execute_file`
- Multi-command research → `ctx_batch_execute`
- Web pages → `ctx_fetch_and_index`, then `ctx_search`
- Index docs → `ctx_index`
- Stats → `ctx_stats`; doctor → `ctx_doctor`; upgrade → `ctx_upgrade`; purge → `ctx_purge`

Run any Python via `uv run python` (uv-managed — see Environment).

## Architecture: the scrape → CSV pipeline

The data flow across the SPSE site is the key concept; it is implemented identically in `spse_pipeline.py` and the legacy `scrape_all.*`:

1. **Get CSRF token** — `GET /<agency>/{section}?tahun=<year>` returns server-rendered HTML containing an inline JS variable `authenticityToken = '...'`. The token is scraped via regex. A fresh token must be fetched (a new `GET` to the main page) before scraping each section.
2. **POST DataTables API** — `POST /<agency>/dt/{endpoint}?tahun=<year>` with body `authenticityToken=...&draw=1&start=0&length=300&...columns`. Server responds with `{draw, recordsTotal, data:[[...rows]]}`. Paginate in steps of 300 (the server-side max) until an empty page. **Stop condition is an empty page, not `recordsTotal`** — that field is hardcoded to `2147483647` (Java `Integer.MAX_VALUE`), not a real count.
3. **Download HTML detail pages** per package — peserta (participants/winners) and pengumuman (announcement) pages, saved as `{KODE}_{nama_paket}.html`. Files >200 bytes that already exist are skipped (smart resume); smaller files are treated as error pages and re-fetched.

Endpoints & HTML URL patterns (all parameterized by `spse_pipeline.py`):

| Category | DataTables endpoint | Cols | Peserta/HTML | Pengumuman/HTML |
|---|---|---|---|---|
| Tender | `/dt/lelang` | 16 | `/lelang/{kode}/peserta` | `/lelang/{kode}/pengumumanlelang` |
| Non Tender | `/dt/pl` | 12 | `/nontender/{kode}/peserta` | `/nontender/{kode}/pengumumapl` |
| Pencatatan | `/dt/nonspk` | 9 | `/pencatatan/pengumumannonspkpemenang?id={kode}` | `/pencatatan/pengumumannonspk?id={kode}` |

**CSV export** merges the JSON fields + parsed pengumuman fields (9) + peserta fields (5) into 28 pipe-delimited columns; each package expands to N rows (one per participant). `spse_pipeline.py` does all three categories; legacy `convert_to_csv.js` only does tender.

## Output layout

```
output/<agency>/<tahun>/
├── tender_<tahun>.json, non_tender_<tahun>.json, pencatatan_non_tender_<tahun>.json
├── html/{tender,non_tender,pencatatan}/{peserta|pemenang,pengumuman}/
└── <agency>_<tahun>.csv        # single combined, pipe-delimited, 28 cols
```

Legacy `scrape_all.py` writes a flat `output/` (Kemkes 2025 only, no CSV). Note `output/` is gitignored.

## Critical conventions (don't change without understanding)

- **`authenticityToken` is camelCase**, not `authenticity_token`. The server returns 403 on the wrong form.
- **Request delay 600ms** (`DELAY_S`) and **page size 300** (`PAGE_SIZE`) are tuned to avoid rate-limiting; don't bump them casually. One automatic retry is built in on failure.
- **Session cookie** `SPSE_SESSION` carries `___AT`/`___TS`/`___ID`; `requests.Session` (or Node's manual cookie jar) keeps it alive across the flow.
- On Windows the Python scripts force UTF-8 on stdout/stderr to work around the cp1252 console.
