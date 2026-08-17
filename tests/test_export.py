"""Phase 4: walk saved HTML and write the combined pipe-delimited CSV."""

from spse import export_csv


def test_writes_pipe_delimited_csv_with_header(tmp_path, load_fixture):
    packages = tmp_path / "html"
    target = packages / "10102453000"
    target.mkdir(parents=True)
    (target / "pemenangberkontrak.html").write_text(
        load_fixture("tender_pemenang"), encoding="utf-8")

    out = tmp_path / "kemkes_2025_tender.csv"
    count = export_csv(packages, out, slug="kemkes",
                       nama_instansi="Kementerian Kesehatan",
                       kategori="tender", tahun=2025,
                       base="https://spse.inaproc.id/kemkes",
                       log=lambda *a: None)
    assert count == 1
    text = out.read_text(encoding="utf-8-sig")
    header = text.splitlines()[0]
    assert header.startswith("slug|nama_instansi|kategori|tahun|")
    assert "Rp. 787.406.000,00" in text


def test_merges_all_tabs_of_one_package(tmp_path, load_fixture):
    packages = tmp_path / "html"
    target = packages / "10158661000"
    target.mkdir(parents=True)
    (target / "pengumumanlelang.html").write_text(
        load_fixture("tender_pemenang"), encoding="utf-8")
    (target / "peserta.html").write_text(
        load_fixture("tender_peserta"), encoding="utf-8")

    out = tmp_path / "out.csv"
    count = export_csv(packages, out, slug="kemkes", nama_instansi="",
                       kategori="tender", tahun=2025,
                       base="https://spse.inaproc.id/kemkes", log=lambda *a: None)
    # Fields from the pengumuman tab, five rows from the peserta table.
    assert count == 5
    text = out.read_text(encoding="utf-8-sig")
    assert "Peserta 1" in text
    assert "SEKRETARIAT BADAN KEBIJAKAN PEMBANGUNAN KESEHATAN" in text


def test_skips_directories_with_no_html(tmp_path):
    packages = tmp_path / "html"
    (packages / "empty").mkdir(parents=True)
    out = tmp_path / "out.csv"
    count = export_csv(packages, out, slug="k", nama_instansi="", kategori="tender",
                       tahun=2025, base="https://x", log=lambda *a: None)
    assert count == 0
