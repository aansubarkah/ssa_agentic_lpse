def test_all_fixtures_load(load_fixture):
    for name in ["tender_pemenang", "tender_peserta", "nontender_pengumuman",
                 "pencatatan_pengumuman", "swakelola_pelaksana", "darurat_pemenang"]:
        assert "nav-tabs" in load_fixture(name)
