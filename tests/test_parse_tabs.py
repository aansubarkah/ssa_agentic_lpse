"""Tab discovery: read a package's real detail tabs out of the nav bar."""

import pytest

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


# Every saved page, not just the five above: pins the tab count and the
# invariants the rest of the pipeline relies on -- exactly one active tab, and
# an absolute URL for every tab, since callers fetch these without rewriting.
@pytest.mark.parametrize(
    ("fixture", "expected_count"),
    [
        ("tender_pemenang", 5),
        ("tender_peserta", 2),
        ("nontender_pengumuman", 5),
        ("pencatatan_pengumuman", 2),
        ("swakelola_pelaksana", 2),
        ("darurat_pemenang", 2),
    ],
)
def test_every_fixture_yields_sane_tabs(load_fixture, fixture, expected_count):
    tabs = find_tabs(load_fixture(fixture))
    assert len(tabs) == expected_count
    assert sum(1 for t in tabs if t["active"]) == 1
    assert all(t["url"].startswith("https://") for t in tabs)
    assert all(t["label"] for t in tabs)


def test_class_attribute_is_matched_token_wise():
    # SPSE really emits this irregular spacing; a substring test would also
    # match a hypothetical 'nav-link-disabled' or 'inactive'.
    html = '<a class="nav-link  active " href="https://x/a">Peserta</a>'
    assert find_tabs(html) == [
        {"url": "https://x/a", "label": "Peserta", "active": True}
    ]


def test_anchor_without_href_is_skipped():
    assert find_tabs('<a class="nav-link">Peserta</a>') == []


def test_anchor_without_nav_link_class_is_skipped():
    # The page's navbar close button is a classless <a>; it must not be a tab.
    assert find_tabs('<a href="https://x/a">Tutup</a>') == []
    assert find_tabs('<a class="navbar-brand" href="https://x/a">X</a>') == []


def test_fragment_and_relative_hrefs_are_skipped():
    # A Bootstrap-style in-page tab would become the filename 'index.html' for
    # every such tab, so it is dropped rather than fetched.
    assert find_tabs('<a class="nav-link" href="#tab-jadwal">Jadwal</a>') == []
    assert find_tabs('<a class="nav-link" href="/kemkes/x">Jadwal</a>') == []


def test_entities_in_labels_are_decoded():
    html = '<a class="nav-link" href="https://x/a">Pemenang &amp; Kontrak</a>'
    assert find_tabs(html)[0]["label"] == "Pemenang & Kontrak"


def test_nested_markup_in_a_label_is_flattened():
    html = (
        '<a class="nav-link" href="https://x/a">'
        '<i class="fa fa-list"> </i> Hasil<br>  Evaluasi</a>'
    )
    assert find_tabs(html)[0]["label"] == "Hasil Evaluasi"


def test_unterminated_anchor_does_not_discard_the_previous_tab():
    # A missing '</a>' must not silently cost a whole tab download.
    html = (
        '<a class="nav-link" href="https://x/a">Pengumuman'
        '<a class="nav-link" href="https://x/b">Peserta</a>'
    )
    assert [(t["url"], t["label"]) for t in find_tabs(html)] == [
        ("https://x/a", "Pengumuman"),
        ("https://x/b", "Peserta"),
    ]


def test_empty_input_yields_no_tabs():
    assert find_tabs("") == []
