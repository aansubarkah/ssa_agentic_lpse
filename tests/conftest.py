"""Shared test fixtures: paths to the saved SPSE detail pages."""

from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "html_examples"

FIXTURES = {
    "tender_pemenang": "LPSE - Informasi Tender.htm",
    "tender_peserta": "LPSE - Informasi Tender2.htm",
    "nontender_pengumuman": "LPSE - Informasi Paket.htm",
    "pencatatan_pengumuman": "LPSE - Informasi Paket2.htm",
    "swakelola_pelaksana": "LPSE - Informasi Swakelola.htm",
    "darurat_pemenang": "LPSE - Informasi Pengadaan Darurat.htm",
}


@pytest.fixture
def load_fixture():
    """Return a function that reads a saved detail page by short name."""

    def _load(name: str) -> str:
        path = FIXTURE_DIR / FIXTURES[name]
        return path.read_text(encoding="utf-8", errors="replace")

    return _load
