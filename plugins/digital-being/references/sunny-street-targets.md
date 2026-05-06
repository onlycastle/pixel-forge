# Sunny Street Target Contracts

Use these target flags before generating assets. If a user wants something
"usable in Sunny Street", choose a target and record it in `prompts.md` and
`asset-index.json`.

## Skill Flags

Recommended invocation shape:

```text
digital-being-assetgen --sunny-type <target> --slug <slug> --prompt "<prompt>"
```

Optional target-specific flags:

- `--sheet CxR`
- `--footprint WxH`
- `--frame-size WxH`
- `--animation idle|walk|idle-walk|action`
- `--export-ready`
- `--concept-only`

When `--export-ready` is requested for a completed run, use:

```text
pf being export-sunny --run-dir out/digital-beings/<slug> --to <sunny-street-root>
```

Use `--dry-run` first when the Sunny Street repo is not writable from the
current session. The command scans sidecar-backed PNGs in the run directory and
exports the supported runtime targets.

## Targets

| `--sunny-type` | Use for | Runtime contract |
| --- | --- | --- |
| `npc-premade` | Named NPC or Digital Being that moves like an NPC | `32x64` frames, `56` columns, at least top 3 rows: preview, idle, walk. Idle/walk use 6 frames per direction in `right, up, left, down` order. |
| `player-farmer` | Player/farmer style character | `32x64` frames, `24` columns, top 3 rows: preview, idle, walk. |
| `animal-livestock24` | Small animal-like being | `32x32` frames, `24` columns, 4 rows, livestock-style layout. |
| `placeable` | Static or lightly animated world object | PNG plus sidecar, `kind=placeable`, `layer_target=placeables`, footprint required or inferred. Exports to Sunny Street placeables manifest. |
| `ground-tileset` | Ground terrain | Grid sheet, `kind=ground-tileset`, `layer_target=ground`, sheet dimensions required. |
| `object-tileset` | Object-layer tile sheet | Grid sheet, `kind=object-tileset`, `layer_target=object`, sheet dimensions required. |
| `map` | Full map composition | Editable Sunny Street-compatible Tiled `.tmj` from `pf mapgen`; registered world patches are opt-in and must include registry/preload tasks. |
| `concept-only` | Mood, identity, or exploration art | Not runtime-ready until promoted to one of the concrete targets above. |

## Routing Rules

- If the user asks for a Sunny Street character or NPC and does not specify a
  type, default to `npc-premade`.
- If the being is a small non-human companion but must run in the current Sunny
  Street runtime, still use `npc-premade` unless the user explicitly accepts a
  new runtime loader.
- If the user asks for a decorative object, lantern, statue, portal, or shrine,
  use `placeable`.
- If the user asks for a map, room, street, or district, use `map`.
- If the user asks only for look exploration, use `concept-only` and do not
  claim runtime readiness.

## Readiness Labels

- `concept`: visual reference only.
- `prototype`: can be manually previewed or hacked into a scene.
- `adapter-ready`: matches a known pixel-forge/Sunny Street adapter contract.
- `runtime-ready`: copied or copyable into Sunny Street with required registry
  changes identified.

For `placeable`, `runtime-ready` specifically means:

- PNG copied to `public/placeables/generated/<textureKey>.png`.
- `src/phaser/data/placeable-asset-manifest.json` contains the same
  `textureKey`, `publicPath`, and provenance.
- `public/maps/placeables-collection.tsj` has a tile whose image points at the
  generated PNG.
- If the asset must be selectable in the custom TMJ editor, its manifest
  `category` must match an allowed editor category exactly, and the editor
  discovery pass must show the asset without creating a duplicate category
  label.

`pf being export-sunny` performs all three steps and writes
`sunny-street-export.json` plus run-summary updates. Character and tileset
exports are copied into public runtime folders, but current Sunny Street
character/map selection still has static registry surfaces, so do not claim
full runtime pickability for those targets unless the relevant registry is also
patched and tested.

For already-exported placeables, distinguish a new asset from an art-only
revision. Because generated texture keys include a content hash, repainting a
PNG and running export again can create a new manifest entry and tile ID. If
existing map placements should visually update in place, dry-run export first,
then overwrite the previously registered generated PNG path and preserve the
manifest / collection identity.

## Map Target Notes

`map` output defaults to an editable TMJ, not an automatic Sunny Street world
registry patch. A map can be called adapter-ready only when it has:

- `ground`, `object`, `collision`, `placeables`, and `markers` layers.
- `placeablesVisualOwner=runtime`.
- transition markers with `targetMap`, `targetSpawn`, `requiredFacing`, and
  `arrivalFacing`.
- placeable objects whose manifest/collection identity resolves without
  filename-stem guessing.

Registered Sunny Street map patches are stricter and must also account for
`src/domain/world/maps/world.ts`, region graph membership,
`tiled/sunny-street.tiled-project` enums, and Phaser preload/runtime texture
registration.
