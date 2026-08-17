from pathlib import Path

from spse import scrape_package_html, tab_filename


def test_tab_filename_from_url():
    assert tab_filename("https://x/kemkes/lelang/1/peserta") == "peserta.html"
    assert tab_filename("https://x/kemkes/pencatatan/pengumumannonspk?id=7") == \
        "pengumumannonspk.html"


def test_downloads_entry_tab_then_discovered_tabs(tmp_path, load_fixture):
    pages = {
        "https://x/kemkes/lelang/10158661000/pengumumanlelang": load_fixture("tender_peserta"),
        "https://x/kemkes/lelang/10158661000/peserta": load_fixture("tender_peserta"),
        # find_tabs returns the fixture's real absolute hrefs; the discovered
        # tab resolves to the spse.inaproc.id host, not the fake base.
        "https://spse.inaproc.id/kemkes/lelang/10158661000/peserta": load_fixture("tender_peserta"),
    }
    fetched = []

    def fake_fetch(session, url, referer, **kwargs):
        fetched.append(url)
        return pages.get(url)

    count = scrape_package_html(
        None, "https://x/kemkes", "tender", "10158661000", tmp_path,
        referer="https://x/kemkes/lelang?tahun=2025",
        fetch=fake_fetch, log=lambda *a: None,
    )
    # Entry tab plus the one further tab its nav bar advertises. Tabs are
    # not deduplicated; the repeated write is skipped by _is_complete(path).
    assert fetched[0].endswith("/pengumumanlelang")
    assert count == 2
    assert (tmp_path / "10158661000" / "peserta.html").exists()


def test_skips_files_already_on_disk(tmp_path, load_fixture):
    target = tmp_path / "10158661000"
    target.mkdir()
    (target / "pengumumanlelang.html").write_text("x" * 500, encoding="utf-8")
    (target / "peserta.html").write_text("x" * 500, encoding="utf-8")

    def fake_fetch(session, url, referer, **kwargs):
        raise AssertionError("must not fetch when files already exist")

    count = scrape_package_html(
        None, "https://x/kemkes", "tender", "10158661000", tmp_path,
        referer="https://x", fetch=fake_fetch, log=lambda *a: None,
    )
    assert count == 0


def test_refetches_truncated_error_pages(tmp_path, load_fixture):
    target = tmp_path / "10158661000"
    target.mkdir()
    (target / "pengumumanlelang.html").write_text("403", encoding="utf-8")
    calls = []

    def fake_fetch(session, url, referer, **kwargs):
        calls.append(url)
        return load_fixture("tender_peserta")

    scrape_package_html(
        None, "https://x/kemkes", "tender", "10158661000", tmp_path,
        referer="https://x", fetch=fake_fetch, log=lambda *a: None,
    )
    assert any(url.endswith("pengumumanlelang") for url in calls)


def test_missing_entry_tab_returns_zero(tmp_path):
    count = scrape_package_html(
        None, "https://x/kemkes", "tender", "999", tmp_path, referer="https://x",
        fetch=lambda *a, **k: None, log=lambda *a: None,
    )
    assert count == 0


def test_resolves_site_root_relative_tab_hrefs(tmp_path):
    # The live site renders its nav links as relative paths ('/kemkes/...');
    # the fetcher must resolve them against the origin before requesting.
    entry = (
        '<div class="content">'
        '<ul class="nav-tabs">'
        '<a class="nav-link active" href="/kemkes/lelang/1/pengumumanlelang">Pengumuman</a>'
        '<a class="nav-link" href="/kemkes/lelang/1/peserta">Peserta</a>'
        "</ul></div>"
    )
    fetched = []

    def fake_fetch(session, url, referer, **kwargs):
        fetched.append(url)
        return entry

    count = scrape_package_html(
        None, "https://spse.inaproc.id/kemkes", "tender", "1", tmp_path,
        referer="https://spse.inaproc.id/kemkes/lelang?tahun=2025",
        fetch=fake_fetch, log=lambda *a: None,
    )
    assert fetched[0] == "https://spse.inaproc.id/kemkes/lelang/1/pengumumanlelang"
    assert "https://spse.inaproc.id/kemkes/lelang/1/peserta" in fetched
    assert (tmp_path / "1" / "pengumumanlelang.html").exists()
    assert (tmp_path / "1" / "peserta.html").exists()
    assert count == 2
