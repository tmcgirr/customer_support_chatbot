"""_write_output creates parent dirs and never raises — an I/O error must not flip the
gate's exit code (it is reported, not raised)."""

from pathlib import Path

from eval.run import _write_output


def test_write_creates_parent_dirs(tmp_path: Path) -> None:
    target = tmp_path / "reports" / "nested" / "out.html"
    msg = _write_output(str(target), lambda: "<html>ok</html>")
    assert target.read_text() == "<html>ok</html>"
    assert msg == f"wrote {target}"


def test_write_failure_is_reported_not_raised(tmp_path: Path) -> None:
    # Parent path is a FILE, so mkdir/write fails — must return a warning, not raise.
    blocker = tmp_path / "afile"
    blocker.write_text("x")
    msg = _write_output(str(blocker / "child.html"), lambda: "data")
    assert msg.startswith("WARNING: could not write")


def test_render_failure_is_reported_not_raised(tmp_path: Path) -> None:
    # A RENDER crash (not just a write error) must also be caught, so an artifact problem
    # can never flip the gate's exit code.
    def _boom() -> str:
        raise ValueError("render blew up")

    msg = _write_output(str(tmp_path / "out.html"), _boom)
    assert msg.startswith("WARNING: could not write") and "ValueError" in msg
