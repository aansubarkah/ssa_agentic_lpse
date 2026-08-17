"""Tab discovery: read a package's real detail tabs out of the nav bar."""

from spse import find_tabs


def test_finds_five_tender_tabs(load_fixture):
    tabs = find_tabs(load_fixture("tender_pemenang"))
    assert len(tabs) == 5
    assert tabs[0]["url"].endswith("/lelang/10102453000/pengumumanlelang")
    assert tabs[-1]["url"].endswith("/evaluasi/10102453000/pemenangberkontrak")


def test_marks_the_active_tab(load_fixture):
    tabs = find_tabs(load_fixture("tender_pemenang"))
    active = [t for t in tabs if t["active"]]
    assert len(active) == 1
    assert active[0]["url"].endswith("pemenangberkontrak")


def test_unawarded_tender_has_only_two_tabs(load_fixture):
    # Package 10158661000 has no evaluasi tabs; that is valid, not an error.
    tabs = find_tabs(load_fixture("tender_peserta"))
    assert len(tabs) == 2
    assert [t["label"] for t in tabs] == ["Pengumuman", "Peserta"]


def test_query_string_tab_urls_are_preserved(load_fixture):
    tabs = find_tabs(load_fixture("pencatatan_pengumuman"))
    assert len(tabs) == 2
    assert tabs[-1]["url"].endswith("pengumumannonspkpemenang?id=11024357000")


def test_swakelola_tab_labels(load_fixture):
    tabs = find_tabs(load_fixture("swakelola_pelaksana"))
    assert [t["label"] for t in tabs] == ["Pengumuman", "Pelaksana Swakelola"]
