from pathlib import Path

from pixel_forge.backends.base import ImageBackend
from pixel_forge.backends.stub import StubBackend


def test_stub_backend_implements_protocol(tmp_path: Path) -> None:
    fixture = Path("tests/fixtures/good-tile.png")
    backend: ImageBackend = StubBackend(template_path=fixture, output_dir=tmp_path)

    paths = backend.generate(prompt="anything", refs=[], n=3)

    assert len(paths) == 3
    for p in paths:
        assert p.exists()
        assert p.read_bytes() == fixture.read_bytes()
