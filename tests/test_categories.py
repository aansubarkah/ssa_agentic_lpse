from spse import CATEGORIES, entry_tab_url, list_api_url


def test_five_categories_are_defined():
    assert set(CATEGORIES) == {"tender", "nontender", "pencatatan", "swakelola", "darurat"}


def test_tender_list_url_includes_tahun():
    url = list_api_url("https://spse.inaproc.id/kemkes", "tender", 2025)
    assert url == "https://spse.inaproc.id/kemkes/dt/lelang?rekanan=&tahun=2025&instansiId="


def test_swakelola_list_url_has_no_tahun():
    # The endpoint ignores tahun; filtering happens client-side.
    url = list_api_url("https://spse.inaproc.id/kemkes", "swakelola", 2025)
    assert url == "https://spse.inaproc.id/kemkes/dt/swakelola"
    assert CATEGORIES["swakelola"]["accepts_tahun"] is False


def test_darurat_list_url():
    assert list_api_url("https://spse.inaproc.id/kemkes", "darurat", 2025) == \
        "https://spse.inaproc.id/kemkes/dt/darurat-list"


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
