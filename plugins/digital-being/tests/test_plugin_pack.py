from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PLUGIN_ROOT.parents[1]
EXAMPLE = PLUGIN_ROOT / "examples" / "minimal-being"
EXPECTED_SKILLS = {
    "digital-being-assetgen",
    "digital-being-init",
    "digital-being-runbook",
    "digital-being-spritegen",
    "digital-being-validation",
    "digital-being-worldgen",
}


def test_plugin_manifest_points_to_skills() -> None:
    manifest_path = PLUGIN_ROOT / ".codex-plugin" / "plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["name"] == "digital-being"
    assert manifest["skills"] == "./skills/"
    assert manifest["version"]
    assert "gpt-image-2" not in json.dumps(manifest).lower()


def test_skill_frontmatter_exists() -> None:
    skill_dirs = {path.name for path in (PLUGIN_ROOT / "skills").iterdir() if path.is_dir()}
    assert skill_dirs == EXPECTED_SKILLS
    for skill in sorted(EXPECTED_SKILLS):
        text = (PLUGIN_ROOT / "skills" / skill / "SKILL.md").read_text(
            encoding="utf-8"
        )
        assert text.startswith("---\n")
        assert f"name: {skill}" in text
        assert "description:" in text


def test_authoring_skills_route_to_imagegen_and_sprite_pipeline() -> None:
    assetgen = (PLUGIN_ROOT / "skills" / "digital-being-assetgen" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    spritegen = (PLUGIN_ROOT / "skills" / "digital-being-spritegen" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    worldgen = (PLUGIN_ROOT / "skills" / "digital-being-worldgen" / "SKILL.md").read_text(
        encoding="utf-8"
    )

    assert "imagegen" in assetgen
    assert "pixel-sprite-pipeline" in assetgen
    assert "imagegen" in spritegen
    assert "pixel-sprite-pipeline" in spritegen
    assert "imagegen" in worldgen
    assert "workspace" in worldgen


def test_authoring_skills_define_sunny_street_target_flags() -> None:
    reference = (PLUGIN_ROOT / "references" / "sunny-street-targets.md").read_text(
        encoding="utf-8"
    )
    assetgen = (PLUGIN_ROOT / "skills" / "digital-being-assetgen" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    spritegen = (PLUGIN_ROOT / "skills" / "digital-being-spritegen" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    worldgen = (PLUGIN_ROOT / "skills" / "digital-being-worldgen" / "SKILL.md").read_text(
        encoding="utf-8"
    )

    for target in (
        "npc-premade",
        "player-farmer",
        "animal-livestock24",
        "placeable",
        "ground-tileset",
        "object-tileset",
        "map",
        "concept-only",
    ):
        assert target in reference
        assert target in assetgen
    assert "--sunny-type" in reference
    assert "--sunny-type" in assetgen
    assert "npc-premade" in spritegen
    assert "animal-livestock24" in spritegen
    assert "placeable" in worldgen
    assert "ground-tileset" in worldgen


def test_validation_skill_stays_offline() -> None:
    text = (PLUGIN_ROOT / "skills" / "digital-being-validation" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "Do not call network services" in text
    assert "Do not generate assets" in text


def test_source_contract_metadata() -> None:
    payload = json.loads(
        (PLUGIN_ROOT / "references" / "source-contract.json").read_text(
            encoding="utf-8"
        )
    )
    assert payload["source_repo"] == "pixel-forge"
    assert payload["schema_version"] == 1
    assert payload["source_of_truth"] is True
    for rel in payload["canonical_paths"].values():
        assert (REPO_ROOT / rel).exists()


def test_example_passes_plugin_validators() -> None:
    commands = [
        [sys.executable, str(PLUGIN_ROOT / "scripts" / "check_artifacts.py"), str(EXAMPLE)],
        [
            sys.executable,
            str(PLUGIN_ROOT / "scripts" / "validate_manifest.py"),
            str(EXAMPLE / "being-manifest.json"),
            str(EXAMPLE),
        ],
        [sys.executable, str(PLUGIN_ROOT / "scripts" / "summarize_run.py"), str(EXAMPLE)],
    ]
    for command in commands:
        result = subprocess.run(command, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr


def test_validators_reject_missing_required_artifact(tmp_path: Path) -> None:
    broken = tmp_path / "broken"
    broken.mkdir()
    result = subprocess.run(
        [
            sys.executable,
            str(PLUGIN_ROOT / "scripts" / "check_artifacts.py"),
            str(broken),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "being-manifest.json" in result.stderr


def test_artifact_checker_rejects_escaped_path_like_keys(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    for name in (
        "spec.json",
        "identity.png",
        "walk.png",
        "walk-contact.png",
        "walk.gif",
        "walk-validation.json",
        "capability-matrix.json",
        "plan.md",
        "prompts.md",
        "learnings.md",
    ):
        (run_dir / name).write_text("{}", encoding="utf-8")
    (run_dir / "being-manifest.json").write_text(
        json.dumps(
            {
                "identity": "identity.png",
                "animations": {
                    "walk": {
                        "sheet": "walk.png",
                        "metadata": {
                            "contact_sheet": "../escape.png",
                            "preview_gif": "walk.gif",
                            "validation_report": "walk-validation.json",
                        },
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "pipeline-run.json").write_text(
        json.dumps({"spec_path": "spec.json"}),
        encoding="utf-8",
    )
    (run_dir / "run-summary.json").write_text(
        json.dumps({"capability_matrix": "capability-matrix.json"}),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(PLUGIN_ROOT / "scripts" / "check_artifacts.py"),
            str(run_dir),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "path escapes run directory: ../escape.png" in result.stderr
