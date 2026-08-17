from spse import CATEGORIES, entry_tab_url, list_api_url


def test_five_categories_are_defined():
    assert set(CATEGORIES) == {"tender", "nontender", "pencatatan", "swakelola", "darurat"}


def test_tender_list_url_includes_tahun():
    url = list_api_url("https://spse.inaproc.id/kemkes", "tender", 2025)
    assert url == "https://spse.inaproc.id/kemkes/dt/lelang?rekanan=&tahun=2025&instansiId="


def test_swakelola_list_url_includes_tahun():
    # Verified live 2026-08-17: the endpoint filters by tahun server-side, so
    # the year must be sent. Omitting it returns every year at once and leaves
    # selection to filter_rows_by_year(), which over-matches on package names.
    url = list_api_url("https://spse.inaproc.id/kemkes", "swakelola", 2025)
    assert url == "https://spse.inaproc.id/kemkes/dt/swakelola?tahun=2025"
    assert CATEGORIES["swakelola"]["accepts_tahun"] is True


def test_darurat_list_url_includes_tahun():
    assert list_api_url("https://spse.inaproc.id/kemkes", "darurat", 2025) == \
        "https://spse.inaproc.id/kemkes/dt/darurat-list?tahun=2025"
    assert CATEGORIES["darurat"]["accepts_tahun"] is True


def test_every_category_filters_by_year_server_side():
    # All five endpoints honour tahun, so no category should fall back to the
    # client-side year filter. A new category defaulting to False would
    # silently download every year.
    assert all(cfg["accepts_tahun"] for cfg in CATEGORIES.values())


def test_entry_tab_urls_per_category():
    base = "https://spse.inaproc.id/kemkes"
    assert entry_tab_url(base, "tender", "10102453000") == \
        f"{base}/lelang/10102453000/pengumumanlelang"
    assert entry_tab_url(base, "nontender", "11002302000") == \
        f"{base}/nontender/11002302000/pengumumanpl"
    assert entry_tab_url(base, "pencatatan", "11024357000") == \
        f"{base}/pencatatan/pengumumannonspk?id=11024357000"
    assert entry_tab_url(base, "swakelola", "1176047") == \
        f"{base}/swakelola/1176047/pengumuman"
    assert entry_tab_url(base, "darurat", "2047") == \
        f"{base}/darurat/pengumumandarurat?id=2047"
