from spse import load_agencies, match_agency, slug_from_url

CSV = """name,url,old_url
"Badan Karantina Indonesia > LPSE Kementerian Pertanian","https://spse.inaproc.id/pertanian","https://lpse.pertanian.go.id"
"Kementerian Pertanian > LPSE Kementerian Pertanian","https://spse.inaproc.id/pertanian","https://lpse.pertanian.go.id"
"Provinsi DKI Jakarta > LPSE Provinsi Daerah Khusus Ibukota Jakarta","https://spse.inaproc.id/jakarta","https://lpse.jakarta.go.id"
"""


def test_slug_from_url():
    assert slug_from_url("https://spse.inaproc.id/kemkes") == "kemkes"
    assert slug_from_url("https://spse.inaproc.id/jakarta/") == "jakarta"


def test_load_agencies_groups_shared_lpse(tmp_path):
    path = tmp_path / "urls.csv"
    path.write_text(CSV, encoding="utf-8")
    agencies = load_agencies(path)
    # Two K/L share the pertanian LPSE, so it appears once.
    assert [a["slug"] for a in agencies] == ["jakarta", "pertanian"]
    pertanian = [a for a in agencies if a["slug"] == "pertanian"][0]
    assert len(pertanian["names"]) == 2
    assert pertanian["base"] == "https://spse.inaproc.id/pertanian"


def test_match_agency_by_slug(tmp_path):
    path = tmp_path / "urls.csv"
    path.write_text(CSV, encoding="utf-8")
    agencies = load_agencies(path)
    assert match_agency(agencies, "jakarta")["slug"] == "jakarta"


def test_match_agency_by_partial_name(tmp_path):
    path = tmp_path / "urls.csv"
    path.write_text(CSV, encoding="utf-8")
    agencies = load_agencies(path)
    # An agent may say "pemprov dki jakarta"; "dki jakarta" must resolve.
    assert match_agency(agencies, "dki jakarta")["slug"] == "jakarta"
    assert match_agency(agencies, "Kementerian Pertanian")["slug"] == "pertanian"


def test_match_agency_returns_none_when_unknown(tmp_path):
    path = tmp_path / "urls.csv"
    path.write_text(CSV, encoding="utf-8")
    assert match_agency(load_agencies(path), "kementerian antariksa") is None


def test_real_csv_loads(tmp_path):
    # The shipped file has 734 data rows across far fewer distinct LPSE hosts.
    agencies = load_agencies("output/all_lpse_urls.csv")
    assert len(agencies) > 100
    assert any(a["slug"] == "jakarta" for a in agencies)
