from spse import clean_text, parse_rupiah, parse_tanggal


def test_clean_text_collapses_whitespace_and_nbsp():
    assert clean_text("  APBN 2026\xa0\xa0\n ") == "APBN 2026"


def test_clean_text_handles_empty():
    assert clean_text("") == ""
    assert clean_text(None) == ""


def test_parse_rupiah_indonesian_format():
    assert parse_rupiah("Rp. 787.406.000,00") == 787406000.00
    assert parse_rupiah("Rp. 663.823.912.000,00") == 663823912000.00
    assert parse_rupiah("Rp. 0,00") == 0.0


def test_parse_rupiah_returns_none_when_unparseable():
    assert parse_rupiah("") is None
    assert parse_rupiah("-") is None
    assert parse_rupiah("Lumsum") is None


def test_parse_tanggal_indonesian_month_names():
    assert parse_tanggal("11 Agustus 2026") == "2026-08-11"
    assert parse_tanggal("6 Agustus 2026") == "2026-08-06"
    assert parse_tanggal("10 September 2021") == "2021-09-10"
    assert parse_tanggal("12 Maret 2024") == "2024-03-12"


def test_parse_tanggal_returns_none_when_unparseable():
    assert parse_tanggal("") is None
    assert parse_tanggal("Paket Sudah Selesai") is None
