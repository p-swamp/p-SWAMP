"""The contract comparison (line endings ignored) and the check's file walk and syntax gate."""

from pswamp_tools import contract
from pswamp_tools.commands import check


def write(path, data: bytes):
    path.write_bytes(data)
    return path


def test_crlf_and_lf_copies_are_the_same_contract(tmp_path):
    committed = write(tmp_path / "a.ts", b"export interface A {\r\n  x: number;\r\n}\r\n")
    fresh = write(tmp_path / "b.ts", b"export interface A {\n  x: number;\n}\n")
    assert contract.stale_diff(committed, fresh, "schema.ts") is None


def test_a_real_change_is_a_unified_diff(tmp_path):
    committed = write(tmp_path / "a.ts", b"line 1\r\nline 2\r\n")
    fresh = write(tmp_path / "b.ts", b"line 1\nline two\n")
    diff = contract.stale_diff(committed, fresh, "schema.ts")
    assert diff is not None
    assert "-line 2" in diff and "+line two" in diff
    assert diff[0].startswith("--- schema.ts (committed)")


def test_a_long_diff_is_cut_short(tmp_path):
    committed = write(tmp_path / "a.txt", "".join(f"{i}\n" for i in range(200)).encode())
    fresh = write(tmp_path / "b.txt", "".join(f"x{i}\n" for i in range(200)).encode())
    diff = contract.stale_diff(committed, fresh, "f", limit=10)
    assert len(diff) == 11 and diff[-1].startswith("... (")


def test_the_walk_skips_caches_venvs_and_node_modules(tmp_path):
    for rel in ("app/a.py", "app/__pycache__/b.py", "app/.venv/c.py", "app/web/node_modules/d.py", "app/e.txt"):
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x = 1\n", encoding="utf-8")
    found = [p.relative_to(tmp_path).as_posix() for p in check.python_files(tmp_path, ("app", "missing"))]
    assert found == ["app/a.py"]


def test_a_syntax_error_names_the_file_and_line(tmp_path):
    good = write(tmp_path / "good.py", b"x = 1\n")
    bad = write(tmp_path / "bad.py", b"x = 1\ndef broken(:\n")
    errors = check.syntax_errors([good, bad], tmp_path)
    assert len(errors) == 1 and errors[0].startswith("bad.py:2: SyntaxError")
    assert not (tmp_path / "__pycache__").exists()  # read-only: nothing compiled to disk
