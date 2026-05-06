# Digital Being Artifact Contract

The plugin consumes the local `pixel-forge` Digital Being contract. It does not
define a new schema.

Required v1 run artifacts:

- `spec.json`
- `identity.png`
- `walk.png`
- `walk-contact.png`
- `walk.gif`
- `walk-validation.json`
- `being-manifest.json`
- `pipeline-run.json`
- `run-summary.json`
- `capability-matrix.json`
- `plan.md`
- `prompts.md`
- `learnings.md`

All paths referenced by `being-manifest.json`, `pipeline-run.json`, and
`run-summary.json` must resolve inside the run directory.

V1 provider state must be offline/stub-safe. Live image, video, and
background-removal providers are deferred.
