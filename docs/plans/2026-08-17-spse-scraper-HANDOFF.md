# Handoff: spse.py implementation, session 1

Date: 2026-08-17
Branch: `feature/spse-gui`
Worktree: `D:\ssa_ai\ssa_agentic_lpse\.worktrees\spse-gui`

Session 1 ended at the user's request (usage limit), gracefully, with no work in
a half-finished state. This document is what a new session needs to continue.

## Status: 3 of 20 tasks complete

| Task | Status | Commits |
|---|---|---|
| 1. Test scaffolding | DONE | `b2d878c`, `600db37` |
| 2. Value cleaners | DONE | `d02fb41`, `68cb2ae`, `5fa892a` |
| 3. Tab discovery | DONE | `3200571`, `b640609` |
| 4. `parse_detail` label/value fields | NOT STARTED | |
| 5. `parse_detail` named sub-tables | NOT STARTED | |
| 6. Category configuration table | NOT STARTED | |
| 7. Agency list from CSV | NOT STARTED | |
| 8. HTTP session layer | NOT STARTED | |
| 9. DataTables body builder | NOT STARTED | |
| 10. Phase 2, list JSON pagination | NOT STARTED | |
| 11. Package IDs and year filter | NOT STARTED | |
| 12. Phase 3, concurrent HTML download | NOT STARTED | |
| 13. LABEL_MAP and row assembly | NOT STARTED | |
| 14. Phase 4, CSV export | NOT STARTED | |
| 15. Run orchestration and output layout | NOT STARTED | |
| 16. CLI | NOT STARTED | |
| 17. Tkinter GUI | NOT STARTED | |
| 18. Live smoke test | NOT STARTED | |
| 19. Documentation | NOT STARTED | |
| 20. Final verification | NOT STARTED | |

Tasks 4 through 20 have not been touched at all. **Resume at Task 4.**

Every completed task passed a spec-compliance review and a code-quality review,
and every issue either found or raised was resolved before moving on. Nothing is
left open.

## What exists right now

`spse.py` contains, in order: module docstring, a win32 UTF-8 stream fix,
`_BULAN`, three compiled regexes, `clean_text`, `parse_rupiah`, `parse_tanggal`,
`from html.parser import HTMLParser`, `_TabParser`, `find_tabs`. Nothing else —
no `CATEGORIES`, no HTTP code, no CLI, no GUI.

Tests: `tests/conftest.py` (the `load_fixture` fixture), `tests/test_fixtures.py`,
`tests/test_clean.py`, `tests/test_parse_tabs.py`.

Verify the baseline before starting:

```bash
cd D:\ssa_ai\ssa_agentic_lpse\.worktrees\spse-gui
uv run pytest -q          # expect 36 passed
git log --oneline main..HEAD
```

## How to continue

1. Read `docs/plans/2026-08-17-spse-scraper-gui-plan.md` — the task-by-task plan.
   **It has been amended during this session** (see corrections below), so trust
   the file over any memory of the original.
2. Read `docs/plans/2026-08-17-spse-scraper-gui-design.md` for the site contract
   and design rationale.
3. Resume at Task 4 using `superpowers:subagent-driven-development`: one
   implementer subagent per task, then a spec-compliance review, then a
   code-quality review, fixing everything each review raises before moving on.
   That loop earned its cost in session 1 — see below.

## Environment gotchas that cost time in session 1

- **Always use `uv run`**, never bare `python`. The shell's `VIRTUAL_ENV` points
  at the *main* checkout's `.venv`, not the worktree's, so bare `python -m pytest`
  finds no pytest. `uv` prints a mismatch warning and correctly ignores the stale
  variable.
- `output/` is gitignored, so the worktree needed its own copy of
  `output/all_lpse_urls.csv`. It is already there. A fresh worktree would need it
  copied again.
- The six `html_examples/*.htm` fixtures are now tracked in git; their `*_files/`
  asset directories (7.2 MB of duplicated CSS/JS) are gitignored.
- Fixture filenames contain spaces. Use `Path` rather than shell quoting.

## Corrections made to the plan during session 1

These were real defects in the plan as originally written, found by
implementation or review. The plan file has been amended for all of them, but a
new session should know they exist rather than rediscovering them.

1. **The Windows UTF-8 workaround in the plan breaks pytest entirely.**
   `sys.stdout = io.TextIOWrapper(sys.stdout.buffer, ...)` takes ownership of a
   buffer it did not create; when garbage-collected it closes pytest's capture
   tempfile, producing `ValueError: I/O operation on closed file` and **zero
   tests collected**. Replaced with `reconfigure(encoding="utf-8",
   errors="replace")` behind a `getattr` guard. The same anti-pattern exists in
   `spse_pipeline.py` and the `scrape_*_batch.py` scripts — harmless there only
   because nothing imports them under pytest.
2. **`parse_rupiah` accepted any digit-bearing string.** It stripped all
   non-`[0-9.,]` characters, so `"APBN 2026"` became `2026.0` and `"Peserta 3"`
   became `3.0` — 19 of 101 real fixture cells. Now anchored on
   `^(?:Rp\.?\s*)?([\d.,]+)$`. **The `Rp` prefix must stay optional**: the
   fixtures' winner tables are all empty, so it is unknown whether real
   `Harga Kontrak` cells carry the prefix, and rejecting bare numbers would
   silently blank every contract price during the live scrape. Do not "tighten"
   this later; the reason is recorded in a comment above the regex.
3. **`parse_tanggal` emitted impossible dates.** `"31 Februari 2026"` returned
   `"2026-02-31"`. Now validated through `date(...).isoformat()`.
4. **Task 13's `build_rows` would destroy legitimate zeros.**
   `parse_rupiah(...) or ""` collapses `0.0` to `""`, and `Rp. 0,00` is 4 of the
   7 distinct money values in the fixtures — a genuine zero pagu becomes
   indistinguishable from an unparseable cell. Amended to
   `"" if value is None else value`. Task 18's smoke-test diagnostic was reworded
   too: as originally written it fired on every legitimate zero and would have
   sent someone to re-loosen `parse_rupiah`.
5. **`pythonpath` is now explicit.** `import spse` from `tests/` originally
   worked only as a side effect of an empty `tests/__init__.py` existing. Since
   the project has no `[build-system]`, uv treats it as a virtual project and
   never installs it, so `sys.path` insertion was the only mechanism.
   `[tool.pytest.ini_options] pythonpath = ["."]` now declares it.
6. **Task 12's comment claiming tabs are "deduplicated" was wrong** — only the
   *writes* are, via the `_is_complete(path)` skip.
7. **The design doc's "horizontal header row" case does not exist.** An earlier
   tag-skeleton dump hid attribute-free `<th>` tags, making six ordinary
   label/value rows look like a six-column header. Verified across all six
   fixtures: no `<tr>` ever contains more than one `th.bgwarning`. Sub-tables are
   a nested `<table>` inside a `<td>`, with plain `<th>` headers. Task 4 and 5
   depend on this being right.

## Site facts verified live, which the plan depends on

- **`Referer` is mandatory.** A cookie-warmed session still gets
  `403 Akses Ditolak!` on a detail page without it. Send the category listing
  page as `Referer` on every detail request.
- `authenticityToken` is camelCase. The snake_case form returns 403.
- `recordsTotal` is always `2147483647` (Java `Integer.MAX_VALUE`), never a real
  count. Paginate until an empty or short page.
- Tab sets vary per package: an unawarded tender has no `evaluasi/*` tabs, so a
  403 or 404 on a discovered tab is normal, not an error.
- The non-tender pengumuman slug is `pengumumanpl`. `CLAUDE.md` documents it as
  `pengumumapl`, which is a typo — Task 19 fixes the doc.
- No fixture exhibits a **Jadwal** tab even though live pages have one, so its
  markup is unverified. `find_tabs` now requires an absolute `http(s)` href, so a
  Bootstrap-style `href="#tab-jadwal"` would be skipped rather than producing a
  malformed request and a colliding `index.html` filename.

## Two open questions for later tasks

Neither blocks Task 4; both were raised during Task 3 and should be resolved when
the relevant task lands.

1. **Is the live Jadwal tab actually reachable?** Because `find_tabs` now demands
   an absolute href, a Jadwal rendered as an in-page Bootstrap tab would be
   silently skipped with no signal. Confirm against a live page during Task 18's
   smoke test, and if it is in-page, decide deliberately whether to fetch it.
2. **`find_tabs` returning `[]` means failure, but that is documented, not
   enforced.** `find_tabs` cannot raise without knowing the caller's retry
   policy, so Task 12's `scrape_package_html` must honour the contract — treat an
   empty tab list as a failed fetch, not as a package with no tabs. Check this
   when Task 12 lands.

## Why the review loop is worth keeping

In three tasks the two-stage review caught: pytest being unable to run at all,
money parsing that turned `"APBN 2026"` into 2026 rupiah, dates like
`"2026-02-31"`, a zero-collapse bug latent in a task seven steps ahead, and a
tab-discovery branch that silently dropped a tab on malformed markup. Each would
have surfaced much later as corrupted CSV output rather than as a test failure.
