from pathlib import Path

from pixel_forge.backends.base import ImageBackend
from pixel_forge.backends.stub import StubBackend


def test_stub_backend_generates_n_copies_with_absolute_paths(tmp_path: Path) -> None:
    """Behavioral conformance test.

    The `backend: ImageBackend` annotation is static-only (erased at runtime);
    structural compatibility is verified by the type checker, not pytest.
    This test pins the observable contract: N files, each absolute, each
    byte-identical to the template.
    """
    fixture = Path("tests/fixtures/good-tile.png")
    backend: ImageBackend = StubBackend(template_path=fixture, output_dir=tmp_path)

    paths = backend.generate(prompt="anything", refs=[], n=3)

    assert len(paths) == 3
    for p in paths:
        assert p.exists()
        assert p.is_absolute()
        assert p.read_bytes() == fixture.read_bytes()
