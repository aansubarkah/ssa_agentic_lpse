from spse import parse_detail


def test_tender_fields(load_fixture):
    result = parse_detail(load_fixture("tender_pemenang"))
    fields = result["fields"]
    assert len(fields) == 6
    assert fields["Nama Tender"].startswith("Paket Jasa Lainnya Pertemuan")
    assert fields["Jenis Pengadaan"] == "Jasa Lainnya"
    assert fields["K/L/PD/Instansi Lainnya"] == "Kementerian Kesehatan"
    assert fields["Satuan Kerja"] == "SEKRETARIAT BADAN KEBIJAKAN PEMBANGUNAN KESEHATAN"
    assert fields["Pagu"] == "Rp. 787.406.000,00"
    assert fields["HPS"] == "Rp. 750.939.420,00"


def test_nontender_fields(load_fixture):
    fields = parse_detail(load_fixture("nontender_pengumuman"))["fields"]
    assert len(fields) == 20  # 18 labels + 2 "[url]" companion keys (Uraian Singkat Pekerjaan, Tahap Paket Saat Ini)
    assert fields["Kode Paket"] == "11002302000"
    assert fields["Tahap Paket Saat Ini"] == "Paket Sudah Selesai"
    assert fields["Tanggal Pembuatan"] == "11 Agustus 2026"
    assert fields["Tahun Anggaran"] == "APBN 2026"      # nbsp stripped
    assert fields["Jenis Kontrak"] == "Lumsum"


def test_pencatatan_fields(load_fixture):
    fields = parse_detail(load_fixture("pencatatan_pengumuman"))["fields"]
    assert len(fields) == 10
    assert fields["Kode Paket"] == "11024357000"
    assert fields["Nilai Pagu Paket"] == "Rp. 124.126.000,00"


def test_swakelola_fields(load_fixture):
    fields = parse_detail(load_fixture("swakelola_pelaksana"))["fields"]
    assert len(fields) == 7
    assert fields["Tipe Pelaksana"] == "K/L/PD Penanggung Jawab Anggaran"
    assert fields["Nilai Pagu Paket"] == "Rp. 1.000.000.000,00"
    assert fields["Tanggal Paket Selesai"] == "30 Oktober 2025"


def test_darurat_fields(load_fixture):
    fields = parse_detail(load_fixture("darurat_pemenang"))["fields"]
    assert len(fields) == 9
    assert "COVID-19" in fields["Nama Paket"]
    assert fields["Metode Pengadaan"] == "Darurat"
    assert fields["Nilai Pagu Paket"] == "Rp. 663.823.912.000,00"


def test_peserta_page_has_no_label_value_fields(load_fixture):
    # The tender peserta tab renders only a participant table.
    assert parse_detail(load_fixture("tender_peserta"))["fields"] == {}


def test_tabs_are_included_in_the_result(load_fixture):
    assert len(parse_detail(load_fixture("tender_pemenang"))["tabs"]) == 5
