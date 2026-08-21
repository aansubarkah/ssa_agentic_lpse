import pytest

from spse import build_parser, resolve_tahun


def test_default_tahun_is_current_year():
    import datetime
    assert resolve_tahun(None) == datetime.date.today().year
    assert resolve_tahun(2019) == 2019


def test_parses_a_typical_agent_invocation():
    args = build_parser().parse_args(
        ["--agency", "jakarta", "--tipe", "tender", "--tahun", "2025"])
    assert args.agency == "jakarta"
    assert args.tipe == "tender"
    assert args.tahun == 2025


def test_rejects_an_unknown_tipe():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--agency", "x", "--tipe", "lelangan"])


def test_phase_skip_flags_default_to_running_everything():
    args = build_parser().parse_args(["--agency", "x", "--tipe", "tender"])
    assert not args.skip_json and not args.skip_html and not args.skip_csv


def test_excel_is_on_by_default_and_can_be_turned_off():
    parser = build_parser()
    assert parser.parse_args(["--agency", "x", "--tipe", "tender"]).excel
    assert parser.parse_args(["--agency", "x", "--tipe", "tender", "--excel"]).excel
    assert not parser.parse_args(
        ["--agency", "x", "--tipe", "tender", "--no-excel"]).excel
