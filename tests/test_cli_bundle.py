"""End-to-end tests for the `pf bundle` subcommand.

Strategy: drive the CLI as a subprocess so stdout/stderr/exit code are
all exercised, but point `LIMEZU_ASSETS_ROOT` at a synthetic fixture
directory so we don't depend on the user's purchased LimeZu pack.

Pipe 3 (action sheets) now runs a full AI pipeline per variant, so the
tests have to feed it a backend. They use the `stub` backend plus a
synthetic "raw output" template whose dimensions match what the chop
action's grid extractor expects (10 × 4 × 64px). Every test in this
file uses `chop` only — the chop prompt is the first one we tune in
the smoke path — and pre-seeds a fake portrait.png into every target
bundle directory so the portrait-ordering guard lets actions proceed
without triggering real Gemini calls from `--skip-portrait`.

A separate test verifies the portrait-ordering guard itself: running
actions without a portrait must fail fast, before any filesystem side
effects.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from PIL import Image

from pixel_forge.actions import FARMER_ACTIONS, load_limezu_action_sheet


def _write_minimal_project(projects_root: Path, name: str = "bundle-smoke") -> Path:
    project_dir = projects_root / name
    (project_dir / "style" / "reference").mkdir(parents=True)
    (project_dir / "style" / "palette.hex").write_text(
        Path("tests/fixtures/palette-4.hex").read_text()
    )
    (project_dir / "style" / "prose.md").write_text("bundle smoke.\n")
    (project_dir / "style" / "reference" / "hero.png").write_bytes(
        Path("tests/fixtures/good-tile.png").read_bytes()
    )
    (project_dir / "project.toml").write_text(
        """
[project]
name = "bundle-smoke"
tile_size = 16
output_root = "out"

[style]
palette = "style/palette.hex"
prose = "style/prose.md"
hero_reference = "style/reference/hero.png"
extra_references = []

[generation]
backend = "stub"
variants_per_prompt = 1

[validation]
max_off_palette_pixels = 0
"""
    )
    return project_dir


def _make_fake_limezu_action_pngs(limezu_root: Path) -> None:
    """Produce fixture PNGs that mimic the LimeZu farmer action file layout.

    Each file has the exact total_frames * cell_w width and cell_h + 4
    loop-strip height that the real pack uses, so the loader succeeds
    end-to-end. Content is opaque solid color (alpha 255) so the reshape
    copies something non-trivial and the output file size is > 0.
    """
    dest_dir = limezu_root / "Modern_Farm_v1.2" / "32x32" / "Characters_32x32"
    dest_dir.mkdir(parents=True, exist_ok=True)
    for profile in FARMER_ACTIONS.values():
        src_w = profile.total_frames * profile.cell_w
        # Add 4 fake Loop strip rows to ensure the crop_y logic is exercised
        src_h = profile.cell_h + 4
        img = Image.new("RGBA", (src_w, src_h), (0, 0, 0, 0))
        # Paint each cell a different color band inside the content rows
        px = img.load()
        for c in range(profile.total_frames):
            r = (c * 7) % 256
            for x in range(c * profile.cell_w + 2, (c + 1) * profile.cell_w - 2):
                for y in range(2, profile.cell_h - 2):
                    px[x, y] = (r, 128, 200, 255)
        # Bright-white strip to mimic the Loop___ annotation
        for x in range(src_w):
            for y in range(profile.cell_h, src_h):
                px[x, y] = (255, 255, 255, 255)
        dest_path = dest_dir / Path(profile.limezu_rel_path).name
        img.save(dest_path)


def _make_chop_stub_template(limezu_root: Path, dest: Path) -> Path:
    """Produce a PNG shaped like a valid "raw Gemini output" for chop.

    `extract_sheet` expects to detect a 10-col × 4-row grid of 64×64
    cells, so the template must be 640×256 (or a clean multiple). We
    reuse the same synthetic LimeZu fake the other helper wrote, then
    call the real `load_limezu_action_sheet` reshape on it — the result
    is exactly the target canvas shape with distinct per-cell coloring,
    which satisfies both the grid detector and the background detector.
    """
    chop_profile = FARMER_ACTIONS["chop"]
    limezu_src = limezu_root / chop_profile.limezu_rel_path
    reshaped = load_limezu_action_sheet(chop_profile, src_path=limezu_src)
    dest.parent.mkdir(parents=True, exist_ok=True)
    reshaped.save(dest)
    return dest


def _preseed_portrait(bundle_dir: Path) -> Path:
    """Write a placeholder portrait.png so the portrait-ordering guard
    accepts `--skip-portrait`. Contents are arbitrary — the guard only
    checks existence and the stub backend ignores the portrait's pixels."""
    bundle_dir.mkdir(parents=True, exist_ok=True)
    portrait = bundle_dir / "portrait.png"
    Image.new("RGBA", (16, 16), (200, 100, 50, 255)).save(portrait)
    return portrait


def test_cli_bundle_actions_only_chop(tmp_path: Path) -> None:
    """Actions-only smoke test with a pre-seeded portrait + stub backend.

    Covers the "regenerate my chop sheet, reuse the existing portrait"
    workflow: we pre-seed portrait.png in the target bundle dir so
    --skip-portrait is legal, then exercise pipe 3 through the stub
    backend. Confirms the manifest is written with the chop grid
    contract and that the clean action PNG has the expected shape.
    """
    projects_root = tmp_path / "projects"
    projects_root.mkdir()
    project_dir = _write_minimal_project(projects_root)

    limezu_root = tmp_path / "fake-limezu"
    _make_fake_limezu_action_pngs(limezu_root)
    stub_template = _make_chop_stub_template(
        limezu_root, tmp_path / "stub-chop.png"
    )

    # Pre-seed portrait.png so the guard accepts --skip-portrait.
    slug = "testy-mctestface"
    bundle_dir_preseed = (
        project_dir / "out" / "characters" / "bundles" / slug
    )
    _preseed_portrait(bundle_dir_preseed)

    env = {**os.environ, "LIMEZU_ASSETS_ROOT": str(limezu_root)}
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pixel_forge",
            "bundle",
            "--projects-root",
            str(projects_root),
            "--project",
            "bundle-smoke",
            "--slug",
            slug,
            "--prompt",
            "a farmer who tests bundles all day",
            "--actions",
            "chop",
            "--skip-portrait",
            "--skip-walking",
            "--backend",
            "stub",
            "--stub-template",
            str(stub_template),
        ],
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["slug"] == slug
    assert payload["errors"] == []
    bundle_dir_path = Path(payload["bundle_dir"])
    assert bundle_dir_path.is_dir()
    assert (bundle_dir_path / "bundle.json").is_file()
    assert (bundle_dir_path / "actions" / "chop.png").is_file()

    # Portrait should still be the pre-seeded one (not regenerated).
    assert (bundle_dir_path / "portrait.png").is_file()
    assert not (bundle_dir_path / "walking.png").exists()

    manifest = json.loads((bundle_dir_path / "bundle.json").read_text())
    # Portrait is re-declared because we reused the pre-seeded one.
    assert manifest["portrait"] == "portrait.png"
    assert manifest["walking"] is None
    assert set(manifest["actions"].keys()) == {"chop"}
    assert manifest["actions"]["chop"]["profile_id"] == "farmer-chop"
    assert manifest["actions"]["chop"]["cell"] == [64, 64]

    chop_img = Image.open(bundle_dir_path / "actions" / "chop.png")
    assert chop_img.size == (10 * 64, 4 * 64)


def test_cli_bundle_errors_without_portrait(tmp_path: Path) -> None:
    """Actions without a portrait (neither generated nor pre-seeded)
    must fail fast with a clear error and no bundle directory side
    effects."""
    projects_root = tmp_path / "projects"
    projects_root.mkdir()
    _write_minimal_project(projects_root)
    limezu_root = tmp_path / "fake-limezu"
    _make_fake_limezu_action_pngs(limezu_root)

    env = {**os.environ, "LIMEZU_ASSETS_ROOT": str(limezu_root)}
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pixel_forge",
            "bundle",
            "--projects-root",
            str(projects_root),
            "--project",
            "bundle-smoke",
            "--slug",
            "no-portrait",
            "--prompt",
            "anything",
            "--actions",
            "chop",
            "--skip-portrait",
            "--skip-walking",
        ],
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 2, result.stdout
    err = json.loads(result.stderr)
    assert "portrait" in err["error"].lower()
    assert "identity anchor" in err["error"]

    # No filesystem side effects when the guard trips.
    projects_out = (
        projects_root / "bundle-smoke" / "out" / "characters" / "bundles"
    )
    if projects_out.exists():
        assert not any(projects_out.iterdir()), (
            "bundle dir created despite ordering guard"
        )


def test_cli_bundle_rejects_unknown_action(tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    projects_root.mkdir()
    _write_minimal_project(projects_root)
    limezu_root = tmp_path / "fake-limezu"
    _make_fake_limezu_action_pngs(limezu_root)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pixel_forge",
            "bundle",
            "--projects-root",
            str(projects_root),
            "--project",
            "bundle-smoke",
            "--slug",
            "anyslug",
            "--prompt",
            "anything",
            "--actions",
            "chop,nonexistent-action",
            "--skip-portrait",
            "--skip-walking",
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "LIMEZU_ASSETS_ROOT": str(limezu_root)},
    )

    assert result.returncode == 2, result.stdout
    err = json.loads(result.stderr)
    assert "nonexistent-action" in err["error"]
    # The bundle directory MUST NOT exist — unknown-action rejection must
    # happen before any filesystem side effect.
    projects_out = projects_root / "bundle-smoke" / "out" / "characters" / "bundles"
    if projects_out.exists():
        assert not any(projects_out.iterdir()), "dir created despite error"


def test_cli_bundle_rejects_unsafe_slug(tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    projects_root.mkdir()
    _write_minimal_project(projects_root)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pixel_forge",
            "bundle",
            "--projects-root",
            str(projects_root),
            "--project",
            "bundle-smoke",
            "--slug",
            "../escape-attempt",
            "--prompt",
            "anything",
            "--skip-portrait",
            "--skip-walking",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    err = json.loads(result.stderr)
    assert "slug" in err["error"].lower()


def test_cli_bundle_variants_produces_sibling_dirs(tmp_path: Path) -> None:
    """--variants N produces N sibling directories with -v1..vN suffixes.

    Pipe 3 now AI-generates action sheets per variant (no more shared
    cache), so each variant dir contains its own actions/chop.png. The
    stub backend keeps outputs deterministic across the run (the same
    raw template is copied every call), so under stub the three chop
    PNGs are still byte-identical — but this is a stub artifact, not a
    design invariant. The assertion below documents the stub behavior
    rather than any cross-variant sharing contract.
    """
    projects_root = tmp_path / "projects"
    projects_root.mkdir()
    project_dir = _write_minimal_project(projects_root)
    limezu_root = tmp_path / "fake-limezu"
    _make_fake_limezu_action_pngs(limezu_root)
    stub_template = _make_chop_stub_template(
        limezu_root, tmp_path / "stub-chop.png"
    )

    slug = "multi-variant"
    for i in range(1, 4):
        _preseed_portrait(
            project_dir / "out" / "characters" / "bundles" / f"{slug}-v{i}"
        )

    env = {**os.environ, "LIMEZU_ASSETS_ROOT": str(limezu_root)}
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pixel_forge",
            "bundle",
            "--projects-root",
            str(projects_root),
            "--project",
            "bundle-smoke",
            "--slug",
            slug,
            "--prompt",
            "a farmer rendered three ways",
            "--actions",
            "chop",
            "--skip-portrait",
            "--skip-walking",
            "--variants",
            "3",
            "--backend",
            "stub",
            "--stub-template",
            str(stub_template),
        ],
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)

    # New bundles array with 3 entries
    assert "bundles" in payload
    assert len(payload["bundles"]) == 3

    # Top-level back-compat: equals bundles[0]
    assert payload["slug"] == payload["bundles"][0]["slug"]
    assert payload["bundle_dir"] == payload["bundles"][0]["bundle_dir"]

    # Per-variant: slugs are multi-variant-v1, -v2, -v3 and dirs exist
    for i, b in enumerate(payload["bundles"], start=1):
        assert b["slug"] == f"multi-variant-v{i}"
        bdir = Path(b["bundle_dir"])
        assert bdir.is_dir()
        assert bdir.name == f"multi-variant-v{i}"
        # Each variant has its own bundle.json with its own slug
        manifest = json.loads((bdir / "bundle.json").read_text())
        assert manifest["slug"] == f"multi-variant-v{i}"
        # Per-variant generation: each variant gets its own chop.png
        assert (bdir / "actions" / "chop.png").is_file()

    # Under the stub backend, the raw Gemini output is deterministic
    # (same template file copied every call) and the extractor is a
    # pure function, so the per-variant outputs end up byte-identical.
    # This is a side effect of using a stub, not a cross-variant
    # sharing contract.
    chop_bytes = [
        (Path(b["bundle_dir"]) / "actions" / "chop.png").read_bytes()
        for b in payload["bundles"]
    ]
    assert chop_bytes[0] == chop_bytes[1] == chop_bytes[2]


def test_cli_bundle_variants_rejects_out_of_range(tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    projects_root.mkdir()
    _write_minimal_project(projects_root)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pixel_forge",
            "bundle",
            "--projects-root",
            str(projects_root),
            "--project",
            "bundle-smoke",
            "--slug",
            "anyslug",
            "--prompt",
            "anything",
            "--skip-portrait",
            "--skip-walking",
            "--variants",
            "0",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    err = json.loads(result.stderr)
    assert "variants" in err["error"].lower()


def test_cli_bundle_animal_reports_empty_catalog(tmp_path: Path) -> None:
    """--asset-type animal + any --actions should report that the animal
    catalog is not yet registered. The plumbing is in place (CLI
    accepts the flag), but the dict is intentionally empty until the
    animal state schema is designed."""
    projects_root = tmp_path / "projects"
    projects_root.mkdir()
    _write_minimal_project(projects_root)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pixel_forge",
            "bundle",
            "--projects-root",
            str(projects_root),
            "--project",
            "bundle-smoke",
            "--slug",
            "some-cow",
            "--prompt",
            "a cow",
            "--actions",
            "idle",
            "--asset-type",
            "animal",
            "--skip-portrait",
            "--skip-walking",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2, result.stdout
    err = json.loads(result.stderr)
    assert "animal" in err["error"]
    assert "catalog" in err["error"].lower()

    # No filesystem side effects when the catalog check trips.
    projects_out = projects_root / "bundle-smoke" / "out" / "characters" / "bundles"
    if projects_out.exists():
        assert not any(projects_out.iterdir()), "dir created despite catalog error"


def test_cli_bundle_decoration_reports_empty_catalog(tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    projects_root.mkdir()
    _write_minimal_project(projects_root)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pixel_forge",
            "bundle",
            "--projects-root",
            str(projects_root),
            "--project",
            "bundle-smoke",
            "--slug",
            "wooden-chest",
            "--prompt",
            "a chest",
            "--actions",
            "open",
            "--asset-type",
            "decoration",
            "--skip-portrait",
            "--skip-walking",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2, result.stdout
    err = json.loads(result.stderr)
    assert "decoration" in err["error"]


def test_cli_bundle_rejects_unknown_asset_type(tmp_path: Path) -> None:
    """argparse `choices` should surface an unknown asset type as a
    hard failure before any bundle work runs."""
    projects_root = tmp_path / "projects"
    projects_root.mkdir()
    _write_minimal_project(projects_root)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pixel_forge",
            "bundle",
            "--projects-root",
            str(projects_root),
            "--project",
            "bundle-smoke",
            "--slug",
            "whatever",
            "--prompt",
            "anything",
            "--asset-type",
            "vehicle",
            "--skip-portrait",
            "--skip-walking",
        ],
        capture_output=True,
        text=True,
    )
    # argparse writes its own error to stderr and exits with code 2.
    assert result.returncode == 2
    assert "asset-type" in result.stderr or "choices" in result.stderr.lower()


def test_cli_bundle_explicit_person_asset_type_matches_default(tmp_path: Path) -> None:
    """Passing --asset-type person explicitly must produce the same output
    as omitting the flag (the person path is the default)."""
    projects_root = tmp_path / "projects"
    projects_root.mkdir()
    project_dir = _write_minimal_project(projects_root)
    limezu_root = tmp_path / "fake-limezu"
    _make_fake_limezu_action_pngs(limezu_root)
    stub_template = _make_chop_stub_template(
        limezu_root, tmp_path / "stub-chop.png"
    )

    slug = "explicit-person"
    _preseed_portrait(
        project_dir / "out" / "characters" / "bundles" / slug
    )

    env = {**os.environ, "LIMEZU_ASSETS_ROOT": str(limezu_root)}
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pixel_forge",
            "bundle",
            "--projects-root",
            str(projects_root),
            "--project",
            "bundle-smoke",
            "--slug",
            slug,
            "--prompt",
            "a farmer",
            "--asset-type",
            "person",
            "--actions",
            "chop",
            "--skip-portrait",
            "--skip-walking",
            "--backend",
            "stub",
            "--stub-template",
            str(stub_template),
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["pipes"]["actions"]["chop"]["ok"] is True


def test_cli_bundle_handles_missing_limezu_source(tmp_path: Path) -> None:
    """If LIMEZU_ASSETS_ROOT points at a directory without the expected
    files, pipe 3 should record a per-action error but still save the
    manifest (with errors) instead of crashing the whole command. With
    the new AI pipeline the LimeZu source is still the layout
    reference, so a missing source trips the same pre-check.
    """
    projects_root = tmp_path / "projects"
    projects_root.mkdir()
    project_dir = _write_minimal_project(projects_root)
    empty_limezu = tmp_path / "empty-limezu"
    empty_limezu.mkdir()

    slug = "missing-sources"
    _preseed_portrait(
        project_dir / "out" / "characters" / "bundles" / slug
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pixel_forge",
            "bundle",
            "--projects-root",
            str(projects_root),
            "--project",
            "bundle-smoke",
            "--slug",
            slug,
            "--prompt",
            "anything",
            "--actions",
            "chop",
            "--skip-portrait",
            "--skip-walking",
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "LIMEZU_ASSETS_ROOT": str(empty_limezu)},
    )

    # Exit code 3 = "ran, but at least one pipe reported errors"
    assert result.returncode == 3, result.stderr
    payload = json.loads(result.stdout)
    assert payload["pipes"]["actions"]["chop"]["ok"] is False
    assert payload["errors"]
    assert Path(payload["manifest_path"]).is_file()
