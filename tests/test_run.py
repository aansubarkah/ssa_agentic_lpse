"""Run orchestration: the folder layout one run owns."""

from spse import run_dir


def test_output_layout(tmp_path):
    path = run_dir("kemkes", 2025, "tender", root=tmp_path)
    assert path == tmp_path / "kemkes" / "2025" / "tender"


def test_layout_is_stable_across_categories(tmp_path):
    a = run_dir("jakarta", 2026, "swakelola", root=tmp_path)
    b = run_dir("jakarta", 2026, "darurat", root=tmp_path)
    assert a != b
    assert a.parent == b.parent
