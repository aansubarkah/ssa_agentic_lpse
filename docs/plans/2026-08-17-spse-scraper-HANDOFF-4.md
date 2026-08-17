# Handoff: spse.py implementation, session 3 (final state)

Date: 2026-08-17
Branch: `feature/spse-gui`
Worktree: `D:\ssa_ai\ssa_agentic_lpse\.worktrees\spse-gui`
Supersedes: `docs/plans/2026-08-17-spse-scraper-HANDOFF-3.md`, which was written
mid-session after Task 14 and is now stale.

Session 3 ran in two halves. Tasks 13, 14 and 15 were implemented directly by the
controller because the user was at a usage limit and asked to walk one task at a
time — test-first and brief-faithful, but with **no review agents dispatched**.
The user then invoked the subagent-driven-development skill, so Task 16 went
through the full loop: implementer subagent, spec-compliance review, code-quality
review.

## Status: 16 of 20 tasks complete

| Task | Status | Commits |
|---|---|---|
| 1. Test scaffolding | DONE (s1) | `b2d878c`, `600db37` |
| 2. Value cleaners | DONE (s1) | `d02fb41`, `68cb2ae`, `5fa892a` |
| 3. Tab discovery | DONE (s1) | `3200571`, `b640609` |
| 4. parse_detail label/value | DONE (s2) | `0e7f848` |
| 5. parse_detail named sub-tables | DONE (s2) | `6623639` |
| 6. Category configuration table | DONE (s2) | `738bdb0` |
| 7. Agency list from CSV | DONE (s2) | `27c6339` |
| 8. HTTP session layer | DONE (s2) | `bf65b40` |
| 9. DataTables body builder | DONE (s2) | `bbfb39e` |
| 10. List JSON pagination | DONE (s2) | `d0a12a7`, `9133ffc` |
| 11. Package IDs + year filter | DONE (s2) | `f39a777` |
| 12. Concurrent HTML download | DONE (s2) | `3e2c582` |
| 13. LABEL_MAP and row assembly | DONE, UNREVIEWED | `a1a1fdd` |
| 14. Phase 4 CSV export | DONE, UNREVIEWED | `a1cedb4` |
| 15. Run orchestration/output layout | DONE, UNREVIEWED | `06c7e19` |
| 16. CLI | DONE, spec review CLEAN, quality review PENDING | `4a9d6b4` |
| 17. Tkinter GUI | NOT STARTED | |
| 18. Live smoke test | NOT STARTED | |
| 19. Documentation | NOT STARTED | |
| 20. Final verification | NOT STARTED | |

**Resume at Task 17** (Tkinter GUI), after closing the review debt below.

## Verify the baseline before starting

```bash
cd D:\ssa_ai\ssa_agentic_lpse\.worktrees\spse-gui
uv run pytest -q          # expect 98 passed
git log --oneline main..HEAD
uv run python spse.py --help
uv run python spse.py --list-agencies | head -5
```

98 = 83 (session 2) + 6 test_rows + 3 test_export + 2 test_run + 4 test_cli.

## Review debt — deal with this first

1. **Tasks 13, 14, 15 were never reviewed.** No spec-compliance and no
   code-quality agent saw them. Either dispatch a review over
   `3e2c582..06c7e19` at the start of session 4, or make an explicit, ledgered
   decision to fold them into the Task 20 whole-branch review.
2. **Task 16's code-quality review was dispatched but had not reported when the
   session ended.** Re-run it (`06c7e19..4a9d6b4`) before treating Task 16 as
   closed. Its spec review is already clean and independently verified.

## What sessions 3 added to spse.py

Appended in phase order after `scrape_html`:

- `LABEL_MAP` (23 Indonesian labels to snake_case, per-category synonyms
  collapsed), `MONEY_COLUMNS`, `DATE_COLUMNS`, `CSV_COLUMNS` (35 columns,
  `slug` first, `extra_json` last).
- `build_rows(...)` — one row per participant, a single blank-participant row
  when there is none, `*_num`/`*_iso` companions beside the raw values,
  everything unmapped serialised into `extra_json`.
- `merge_package_detail(package_dir)` — folds every saved tab of one package
  into one detail dict. Fields first-wins (pengumuman stays authoritative),
  named tables last-populated-wins.
- `export_csv(...)` — `csv.DictWriter`, `delimiter="|"`, `utf-8-sig`,
  `extrasaction="ignore"`; returns the row count.
- `export_excel(csv_path)` — lazy `openpyxl` import; returns None with a log
  line when absent, which is the current state of the env.
- `OUTPUT_ROOT`, `run_dir(slug, tahun, kategori, root)`, `run_pipeline(...)` —
  the four phases wired together, each skippable and resumable.
- `launch_gui()` stub, `resolve_tahun`, `build_parser`, `run_cli`, `main`, and
  the `if __name__ == "__main__"` guard.

## Rulings applied in session 3

- **Ruling 1 (T13, pre-authorized in s2):** the duplicated
  `elif not label.endswith("[url]")` / `else` branches collapsed into one
  `else`. Pure simplification; `[url]` companion keys still reach `extra_json`.
- **Ruling 2 (T13, pre-authorized in s2):** participant-table selection now
  loops `("pemenang", "peserta")` and picks the first table that actually HAS
  rows, replacing `tables.get("pemenang") or tables.get("peserta")`. Confirmed
  correct by T14's merge test: the merged detail for `10158661000` carries an
  empty pemenang table beside a populated peserta table, and the old expression
  would have written 1 row where the spec wants 5.
- **Ruling 9 (T16, new):** the plan wrote `import datetime` /
  `datetime.date.today().year`, but `spse.py` already has
  `from datetime import date`, so the literal form would add a redundant second
  import of the same module. Authorized `date.today().year`. The plan's test
  keeps its function-local `import datetime` verbatim, so the assertion is
  unchanged.

## Open items the next session must carry

Older, still open:

- **T4:** the plan and handoff-1 correction #7 still claim "no row holds more
  than one bgwarning" — factually wrong (`LPSE - Informasi Paket.htm` has a
  Pagu/HPS row with two). Amend both in Task 19.
- **T10:** non-atomic `list.json` write; `scrape_json` untested directly;
  `FakeDtSession.headers` dead state.
- **T12:** `scrape_html` has no direct test; pooled workers silence the
  empty-tabs log (collecting zero-tab ids into `stats` is a T15+ decision, still
  undecided); unused `Path` import in `tests/test_scrape_html.py`.
- **T18 watch items:** confirm the live Jadwal tab href is absolute (fetchable)
  rather than an in-page Bootstrap anchor, which `find_tabs` silently skips;
  Task 18 also adjudicates Ruling 5's `CATEGORIES` column/order values against
  the live server.

New in session 3:

- **T13:** RUP contributes only its first row, so multi-RUP packages lose rows
  2+; `nilai_pdn`/`nilai_umk` have no `_num` companions; every participant row
  of a package repeats the same `extra_json` blob.
- **T14:** `export_csv` calls `packages_dir.iterdir()` unguarded, so a direct
  call on a missing html dir raises `FileNotFoundError`. `run_pipeline` guards
  it with `html_dir.exists()`, so the pipeline path is safe; a direct caller is
  not. `export_excel` is untested; the CSV write is non-atomic.
- **T15:** the plan writes the CSV to `out_dir.parent /
  "<slug>_<tahun>_<kategori>.csv"` (that is `output/<slug>/<tahun>/`), while the
  DESIGN doc says `output/<slug>/<tahun>/<kategori>.csv`. The plan was followed
  as the authoritative document; **Task 19 must reconcile the design doc.**
  `run_pipeline` itself has no direct test — only `run_dir` is covered.
- **T16:** `--dry`'s help says "download nothing" but `scrape_json` writes
  `list.json`; counting requires the list, so the behavior is intended and only
  the wording is loose. Fix the wording in Task 19.
- **Doc fixes remain Task 19**, including `pengumumapl` -> `pengumumanpl` in
  `CLAUDE.md`.

## Where things live

- Plan (amended, authoritative): `docs/plans/2026-08-17-spse-scraper-gui-plan.md`
- Design: `docs/plans/2026-08-17-spse-scraper-gui-design.md`
- SDD workspace: `.superpowers/sdd/2026-08-17-spse-scraper-gui-plan/`
  - `progress.md` — the LEDGER: task log, rulings 1-9, watch items, deferred
    minors. Read it first; it is the recovery map.
  - `task-N-brief.md` / `task-N-report.md` — briefs 4-14; reports 4-12. Tasks
    13-15 were controller-implemented with no brief or report, and Task 16 was
    dispatched from task text pasted straight out of the plan, so for 13-16 the
    ledger is the only record.
- Skill: superpowers:subagent-driven-development, at
  `C:\Users\aansubarkah\.claude\plugins\cache\superpowers-marketplace\superpowers\4.1.1\skills\subagent-driven-development`
  (note: this path moved since session 2, which pointed at a `.pi/agent/git`
  checkout). Prompt templates: `implementer-prompt.md`,
  `spec-reviewer-prompt.md`, `code-quality-reviewer-prompt.md`.

Dispatching that worked in session 3: paste the task's full text from the plan
into a `general-purpose` implementer, then a `general-purpose` spec reviewer with
the same task text plus an explicit "do not trust the report, re-run everything
yourself" instruction and a list of already-authorized deviations, then a
`superpowers:code-reviewer` for quality with BASE_SHA/HEAD_SHA. Telling each
reviewer which findings are already known and accepted keeps their reports short
and on-target.

## Environment gotchas

- Always `uv run`, never bare `python`. A stale `VIRTUAL_ENV` points at the main
  checkout's venv; uv prints a warning and ignores it, which is expected.
- `output/` is gitignored; the worktree has its own `output/all_lpse_urls.csv`
  (600 agencies after grouping by slug). Real scraped JSONs live only in the MAIN
  checkout at `output/data/1/*.json` and
  `output/{tender,non_tender,pencatatan_non_tender}_2025.json`.
- Fixture filenames contain spaces; use `Path`, not shell quoting.
- `openpyxl` is not installed, so the `--excel` path currently logs and skips.
- Never use emoji in any file or communication in this repo.

## What remains

Task 17 replaces the `launch_gui()` stub with the real Tkinter window (combobox
with typeahead over the agency list, worker thread, `queue.Queue` drained by a
100 ms `root.after` poll, Mulai/Batal/Tutup, progress bar). Task 18 is the first
live network run — `--dry` per category, then `--limit 5` — and it is the
adjudicator for the `CATEGORIES` column/order values and the Jadwal tab question.
Task 19 is documentation, carrying every doc fix listed above. Task 20 is final
verification, then superpowers:finishing-a-development-branch.
