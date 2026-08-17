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


def test_parse_rupiah_accepts_bare_numbers_without_the_rp_prefix():
    # The winner sub-tables (Harga Kontrak, Nilai PDN, Nilai UMK) are empty in
    # every fixture, so we do not know whether they carry the 'Rp' prefix.
    # Accept both shapes rather than risk blanking real contract prices.
    assert parse_rupiah("Rp 0,00") == 0.0
    assert parse_rupiah("1.000.000,00") == 1000000.00
    assert parse_rupiah("0,00") == 0.0
    assert parse_rupiah("165146000") == 165146000.0


def test_parse_rupiah_returns_none_when_unparseable():
    assert parse_rupiah("") is None
    assert parse_rupiah("-") is None
    assert parse_rupiah("Lumsum") is None


def test_parse_rupiah_rejects_non_money_values_seen_in_real_fixtures():
    # Every string below is a real cell value scraped from html_examples/.
    # Stripping non-digits made each one yield a bogus float, e.g.
    # 'APBN 2026' -> 2026.0 and '11 Agustus 2026' -> 112026.0.
    assert parse_rupiah("APBN 2026") is None
    assert parse_rupiah("11 Agustus 2026") is None
    assert parse_rupiah("Peserta 3") is None
    assert parse_rupiah("2 peserta") is None
    assert parse_rupiah("APOTEK KIMIA FARMA 103 SAMPIT") is None


def test_parse_tanggal_indonesian_month_names():
    assert parse_tanggal("11 Agustus 2026") == "2026-08-11"
    assert parse_tanggal("6 Agustus 2026") == "2026-08-06"
    assert parse_tanggal("10 September 2021") == "2021-09-10"
    assert parse_tanggal("12 Maret 2024") == "2024-03-12"


def test_parse_tanggal_returns_none_when_unparseable():
    assert parse_tanggal("") is None
    assert parse_tanggal("Paket Sudah Selesai") is None
