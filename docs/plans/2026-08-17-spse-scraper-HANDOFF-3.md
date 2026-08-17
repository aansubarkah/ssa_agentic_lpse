# Handoff: spse.py implementation, session 3

Date: 2026-08-17
Branch: `feature/spse-gui`
Worktree: `D:\ssa_ai\ssa_agentic_lpse\.worktrees\spse-gui`
Supersedes: `docs/plans/2026-08-17-spse-scraper-HANDOFF-2.md` (session 2)

Session 3 was a short, budget-constrained session: the user was at a usage limit
and asked for one task at a time, so tasks 13 and 14 were implemented directly by
the controller rather than through the subagent-driven-development dispatch loop.
Both are brief-faithful, test-first, and committed. **Neither has been through a
review agent** — that is the one process step this session skipped, and it is
recorded in the ledger.

## Status: 14 of 20 tasks complete

| Task | Status | Commits |
|---|---|---|
| 1. Test scaffolding | DONE (session 1) | `b2d878c`, `600db37` |
| 2. Value cleaners | DONE (session 1) | `d02fb41`, `68cb2ae`, `5fa892a` |
| 3. Tab discovery | DONE (session 1) | `3200571`, `b640609` |
| 4. parse_detail label/value | DONE (session 2) | `0e7f848` |
| 5. parse_detail named sub-tables | DONE (session 2) | `6623639` |
| 6. Category configuration table | DONE (session 2) | `738bdb0` |
| 7. Agency list from CSV | DONE (session 2) | `27c6339` |
| 8. HTTP session layer | DONE (session 2) | `bf65b40` |
| 9. DataTables body builder | DONE (session 2) | `bbfb39e` |
| 10. List JSON pagination | DONE (session 2) | `d0a12a7`, `9133ffc` |
| 11. Package IDs + year filter | DONE (session 2) | `f39a777` |
| 12. Concurrent HTML download | DONE (session 2) | `3e2c582` |
| 13. LABEL_MAP and row assembly | DONE, UNREVIEWED | `a1a1fdd` |
| 14. Phase 4 CSV export | DONE, UNREVIEWED | `a1cedb4` |
| 15. Run orchestration/output layout | NOT STARTED | |
| 16. CLI | NOT STARTED | |
| 17. Tkinter GUI | NOT STARTED | |
| 18. Live smoke test | NOT STARTED | |
| 19. Documentation | NOT STARTED | |
| 20. Final verification | NOT STARTED | |

**Resume at Task 15.** No brief exists for 15 yet; generate it (command below).

## Verify the baseline before starting

```bash
cd D:\ssa_ai\ssa_agentic_lpse\.worktrees\spse-gui
uv run pytest -q          # expect 92 passed
git log --oneline main..HEAD
```

92 = 83 (session 2) + 6 (test_rows.py) + 3 (test_export.py).

## What session 3 added to spse.py

Appended after `scrape_html`, in phase order:

- `LABEL_MAP` — Indonesian detail labels to snake_case columns, 23 entries with
  per-category synonyms collapsed (`Nama Paket`/`Nama Tender`/`Nama Swakelola`
  all map to `nama_paket`).
- `MONEY_COLUMNS`, `DATE_COLUMNS`, `CSV_COLUMNS` (35 columns, `slug` first,
  `extra_json` last).
- `build_rows(detail, slug, nama_instansi, kategori, tahun, paket_id, sumber_url)`
  — one row per participant, a single blank-participant row when there is none,
  `*_num` / `*_iso` companions alongside the raw values, everything unmapped
  serialised into `extra_json`.
- `merge_package_detail(package_dir)` — folds every saved tab of one package into
  one detail dict. Fields are first-wins (pengumuman stays authoritative);
  named tables are last-populated-wins.
- `export_csv(...)` — `csv.DictWriter`, `delimiter="|"`, `utf-8-sig`,
  `extrasaction="ignore"`; returns the row count.
- `export_excel(csv_path)` — lazy `openpyxl` import, returns None with a log line
  when the package is absent (which is the current state of the env).

## Rulings applied this session

Both were pre-authorized in session 2's ledger; session 3 executed them.

- **Ruling 1 (T13):** the plan's duplicated
  `elif not label.endswith("[url]")` / `else` branches collapsed into one `else`.
  Pure simplification, `[url]` companion keys still reach `extra_json`.
- **Ruling 2 (T13):** `tables.get("pemenang") or tables.get("peserta")` replaced
  with a loop that picks the first table which actually **has rows**. Confirmed
  correct by T14's merge test: the merged detail for `10158661000` carries an
  empty pemenang table from the pengumuman tab beside a populated peserta table,
  and the old expression would have yielded 1 row where the spec wants 5.

No new rulings were needed; nothing was escalated.

## Open items the next session must carry

Carried forward from session 2, still open:

- **T4 deferred minor:** the plan and handoff-1 correction #7 still claim "no row
  holds more than one bgwarning" — factually wrong (`LPSE - Informasi Paket.htm`
  has a Pagu/HPS row with two). Amend both docs in Task 19.
- **T12 minors:** `scrape_html` has no direct test (fold into T15 wiring tests);
  pooled workers silence the empty-tabs log — collecting zero-tab ids into
  `stats` is a T15+ decision; unused `Path` import in `tests/test_scrape_html.py`.
- **T10 minors:** non-atomic `list.json` write; `scrape_json` untested directly;
  `FakeDtSession.headers` dead state.
- **T18 watch items:** confirm the live Jadwal tab href is absolute (fetchable)
  rather than an in-page Bootstrap anchor (which `find_tabs` silently skips);
  Task 18 also adjudicates Ruling 5's `CATEGORIES` column/order values against
  the live server.
- **Doc fixes are all Task 19**, including `pengumumapl` -> `pengumumanpl` in
  `CLAUDE.md`.

New from session 3:

- **Tasks 13 and 14 are unreviewed.** Either dispatch a spec+quality review over
  `3e2c582..a1cedb4` at the start of session 4, or explicitly fold them into the
  Task 20 whole-branch review and note that choice in the ledger.
- **T13 minors:** RUP contributes only its first row (multi-RUP packages lose
  rows 2+); `nilai_pdn` / `nilai_umk` have no `_num` companions; every
  participant row of a package repeats the same `extra_json` blob.
- **T14 minors:** `export_csv` calls `packages_dir.iterdir()` unguarded, so a
  missing html dir raises `FileNotFoundError` — Task 15 should decide whether to
  guard it or let it abort; `export_excel` is untested; the CSV write is
  non-atomic.

## Where things live

- Plan (amended, authoritative): `docs/plans/2026-08-17-spse-scraper-gui-plan.md`
- Design: `docs/plans/2026-08-17-spse-scraper-gui-design.md`
- SDD workspace: `.superpowers/sdd/2026-08-17-spse-scraper-gui-plan/`
  - `progress.md` — the LEDGER: task log, rulings 1-8, watch items, deferred
    minors. Read it first; it is the recovery map.
  - `task-N-brief.md` / `task-N-report.md` — briefs 4-14 present; reports 4-12
    only (13 and 14 were controller-implemented, their outcome is in the ledger).
  - `review-<base>..<head>.diff` — review packages
- Skill: superpowers:subagent-driven-development
- Skill dir:
  `C:/Users/aansubarkah/.pi/agent/git/github.com/obra/superpowers/skills/subagent-driven-development`

```bash
# generate the Task 15 brief
bash "<skill-dir>/scripts/task-brief" docs/plans/2026-08-17-spse-scraper-gui-plan.md 15
# build a review package
bash "<skill-dir>/scripts/review-package" docs/plans/2026-08-17-spse-scraper-gui-plan.md 3e2c582 a1cedb4
```

## Environment gotchas (unchanged)

- Always `uv run`, never bare `python`. A stale `VIRTUAL_ENV` points at the main
  checkout's venv; uv prints a warning and ignores it, which is fine.
- `output/` is gitignored; the worktree has its own `output/all_lpse_urls.csv`.
  Real scraped JSONs live only in the MAIN checkout at `output/data/1/*.json`
  and `output/{tender,non_tender,pencatatan_non_tender}_2025.json`.
- Fixture filenames contain spaces; use `Path`, not shell quoting.
- Never use emoji in any file or communication in this repo.

## What spse.py contains now, top to bottom

Docstring; win32 UTF-8 reconfigure; `_BULAN`; regexes; `clean_text`,
`parse_rupiah`, `parse_tanggal`; `Tab`, `_TabParser`, `find_tabs`;
`_DetailParser`, `parse_detail`; `TABLE_SIGNATURES`, `name_tables`; CONFIG
constants + `CATEGORIES` + `list_api_url`/`listing_url`/`entry_tab_url`;
agencies (`slug_from_url`, `load_agencies`, `match_agency`); HTTP (`UA`,
headers, `TOKEN_RE`, `extract_token`, `open_session`, `fetch_html`);
`build_dt_body`; `strip_tags`, `extract_ids`, `filter_rows_by_year`;
`paginate_list`, `scrape_json`; `tab_filename`, `_is_complete`,
`scrape_package_html`, `scrape_html`; `LABEL_MAP`, `MONEY_COLUMNS`,
`DATE_COLUMNS`, `CSV_COLUMNS`, `build_rows`; `merge_package_detail`,
`export_csv`, `export_excel`.

Still missing: `run_pipeline` (T15), the argparse CLI (T16), the Tkinter GUI
(T17). Tasks 15-20 build exactly those, then smoke-test, document, and verify.
