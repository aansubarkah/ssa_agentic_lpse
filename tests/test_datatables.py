from urllib.parse import parse_qs

from spse import build_dt_body


def test_body_uses_camelcase_token():
    body = build_dt_body("tok", "tender", start=0, length=10000)
    parsed = parse_qs(body, keep_blank_values=True)
    assert parsed["authenticityToken"] == ["tok"]
    assert "authenticity_token" not in parsed


def test_body_declares_the_right_column_count():
    body = build_dt_body("tok", "tender", start=0, length=10000)
    parsed = parse_qs(body, keep_blank_values=True)
    assert "columns[15][data]" in parsed
    assert "columns[16][data]" not in parsed


def test_body_carries_start_and_length():
    body = build_dt_body("tok", "swakelola", start=300, length=100)
    parsed = parse_qs(body, keep_blank_values=True)
    assert parsed["start"] == ["300"]
    assert parsed["length"] == ["100"]
    assert parsed["draw"] == ["1"]


def test_body_order_column_matches_category():
    parsed = parse_qs(build_dt_body("tok", "tender", 0, 10), keep_blank_values=True)
    assert parsed["order[0][column]"] == ["5"]
    assert parsed["order[0][dir]"] == ["desc"]
