from spse import extract_ids, filter_rows_by_year


def test_extract_ids_uses_the_configured_column():
    rows = [["10102453000", "Paket A"], ["10158661000", "Paket B"]]
    assert extract_ids(rows, "tender") == ["10102453000", "10158661000"]


def test_extract_ids_strips_html_from_the_cell():
    rows = [['<a href="/x">2047</a>', "Paket"]]
    assert extract_ids(rows, "darurat") == ["2047"]


def test_extract_ids_skips_blank_cells():
    assert extract_ids([["", "Paket"], ["7", "Paket"]], "tender") == ["7"]


def test_filter_rows_by_year_matches_any_cell():
    rows = [["1", "Paket A", "12 Maret 2024"], ["2", "Paket B", "30 Oktober 2025"]]
    assert filter_rows_by_year(rows, 2025) == [["2", "Paket B", "30 Oktober 2025"]]


def test_filter_rows_by_year_keeps_rows_with_no_date():
    # Better to keep an undated row than to silently drop real data.
    rows = [["1", "Paket tanpa tanggal"]]
    assert filter_rows_by_year(rows, 2025) == rows
