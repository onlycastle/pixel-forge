import subprocess
import sys
from pathlib import Path


def test_cli_promote_moves_siblings_to_rejected(tmp_path: Path) -> None:
    tiles = tmp_path / "out" / "tiles"
    rejected = tiles / "_rejected"
    tiles.mkdir(parents=True)
    rejected.mkdir()

    base = "grass-20260412-100000"
    (tiles / f"{base}-v1.png").write_bytes(b"v1")
    (tiles / f"{base}-v2.png").write_bytes(b"v2")
    (tiles / f"{base}-v3.png").write_bytes(b"v3")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pixel_forge",
            "promote",
            "--path",
            str(tiles / f"{base}-v2.png"),
            "--canonical-name",
            "grass",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert (tiles / "grass.png").exists()
    assert (tiles / "grass.png").read_bytes() == b"v2"
    assert not (tiles / f"{base}-v1.png").exists()
    assert not (tiles / f"{base}-v2.png").exists()
    assert not (tiles / f"{base}-v3.png").exists()

    rejected_children = list(rejected.rglob("*.png"))
    assert len(rejected_children) == 2
