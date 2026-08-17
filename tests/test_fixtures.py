import pytest

FIXTURE_NAMES = [
    "tender_pemenang",
    "tender_peserta",
    "nontender_pengumuman",
    "pencatatan_pengumuman",
    "swakelola_pelaksana",
    "darurat_pemenang",
]


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_fixture_loads(load_fixture, name):
    assert "nav-tabs" in load_fixture(name)
