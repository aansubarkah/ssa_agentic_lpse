"""Phase 4 row assembly: detail fields -> stable CSV columns."""

import json

from spse import CSV_COLUMNS, build_rows, parse_detail


def test_core_columns_are_present_and_ordered():
    assert CSV_COLUMNS[:4] == ["slug", "nama_instansi", "kategori", "tahun"]
    assert "extra_json" == CSV_COLUMNS[-1]


def test_maps_labels_to_stable_columns(load_fixture):
    detail = parse_detail(load_fixture("tender_pemenang"))
    rows = build_rows(detail, slug="kemkes", nama_instansi="Kementerian Kesehatan",
                      kategori="tender", tahun=2025, paket_id="10102453000",
                      sumber_url="https://x")
    row = rows[0]
    assert row["nama_paket"].startswith("Paket Jasa Lainnya")
    assert row["satuan_kerja"] == "SEKRETARIAT BADAN KEBIJAKAN PEMBANGUNAN KESEHATAN"
    assert row["pagu"] == "Rp. 787.406.000,00"
    assert row["pagu_num"] == 787406000.0
    assert row["kode_paket"] == "10102453000"


def test_unmapped_labels_land_in_extra_json(load_fixture):
    detail = parse_detail(load_fixture("nontender_pengumuman"))
    rows = build_rows(detail, slug="kemkes", nama_instansi="", kategori="nontender",
                      tahun=2026, paket_id="11002302000", sumber_url="https://x")
    extra = json.loads(rows[0]["extra_json"])
    # 'Jenis Kontrak' is not promoted to a column but must not be lost.
    assert extra["Jenis Kontrak"] == "Lumsum"


def test_dates_are_normalised(load_fixture):
    detail = parse_detail(load_fixture("nontender_pengumuman"))
    rows = build_rows(detail, slug="kemkes", nama_instansi="", kategori="nontender",
                      tahun=2026, paket_id="11002302000", sumber_url="https://x")
    assert rows[0]["tanggal_pembuatan"] == "11 Agustus 2026"
    assert rows[0]["tanggal_pembuatan_iso"] == "2026-08-11"


def test_one_row_per_participant(load_fixture):
    detail = parse_detail(load_fixture("tender_peserta"))
    rows = build_rows(detail, slug="kemkes", nama_instansi="", kategori="tender",
                      tahun=2025, paket_id="10158661000", sumber_url="https://x")
    assert len(rows) == 5
    assert rows[0]["nama_pemenang"] == "Peserta 1"


def test_single_row_when_there_are_no_participants(load_fixture):
    # The package must still appear in the CSV even with an empty winner table.
    detail = parse_detail(load_fixture("tender_pemenang"))
    rows = build_rows(detail, slug="kemkes", nama_instansi="", kategori="tender",
                      tahun=2025, paket_id="10102453000", sumber_url="https://x")
    assert len(rows) == 1
    assert rows[0]["nama_pemenang"] == ""
