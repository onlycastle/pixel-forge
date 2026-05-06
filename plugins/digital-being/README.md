# Digital Being Assetgen 사용 가이드

`digital-being-assetgen`은 Sunny Street용 Digital Being 에셋을 만드는
Codex 스킬입니다. 이 repo에서는 `plugins/digital-being/` 폴더가
플러그인이고, 실제 사용 단위는 아래 스킬 파일입니다.

```text
plugins/digital-being/skills/digital-being-assetgen/SKILL.md
```

## 1. 최신 코드 받기

먼저 `pixel-forge` 최신 `main`을 받습니다.

```bash
git pull origin main
```

Codex에서는 `pixel-forge` repo root를 작업 폴더로 열어야 합니다. 그래야
스킬이 이 repo 안의 참조 파일과 Pixel Forge 도구를 같이 읽을 수 있습니다.

## 2. Codex에서 바로 사용하기

Codex에 이렇게 요청하면 됩니다.

```text
plugins/digital-being/skills/digital-being-assetgen/SKILL.md를 읽고,
digital-being-assetgen 워크플로로 Sunny Street placeable 나무 에셋을 하나 만들어줘.
```

더 명확하게 쓰려면 target, slug, prompt를 같이 줍니다.

```text
digital-being-assetgen --sunny-type placeable --slug sunny-farm-tree --prompt "Sunny Street 농장 맵에 놓을 수 있는 작은 나무 placeable"
```

## 3. `$digital-being-assetgen` 바로가기 등록하기

매번 긴 경로를 말하고 싶지 않다면 개인 Codex skill alias를 추가합니다.

```text
~/.codex/skills/digital-being-assetgen/SKILL.md
```

파일 내용:

````markdown
---
name: digital-being-assetgen
description: Explicit alias for the Sunny Street Digital Being asset authoring workflow.
---

# Digital Being Assetgen Alias

When used inside `pixel-forge`, the canonical project skill body lives at:

```text
plugins/digital-being/skills/digital-being-assetgen/SKILL.md
```

Before executing in `pixel-forge`, read that file and:

```text
plugins/digital-being/references/sunny-street-targets.md
```
````

등록 후에는 Codex에 이렇게 말하면 됩니다.

```text
$digital-being-assetgen --sunny-type placeable --slug sunny-farm-tree --prompt "Sunny Street 농장 맵에 놓을 수 있는 작은 나무 placeable"
```

## 4. 자주 쓰는 target

- `placeable`: 나무, 제단, 가구, 장식물 같은 정적 월드 오브젝트
- `npc-premade`: Sunny Street NPC처럼 움직이는 캐릭터
- `ground-tileset`: 바닥 타일셋
- `object-tileset`: 오브젝트 레이어 타일셋
- `map`: Sunny Street 호환 Tiled `.tmj` 맵
- `concept-only`: 런타임 준비가 아닌 시각 콘셉트

나무나 장식물을 만들 때는 보통 `placeable`을 사용합니다.

## 5. 결과물 위치

기본 출력 위치는 아래 형태입니다.

```text
out/digital-beings/<slug>/
```

생성 run에는 보통 다음 파일이 포함됩니다.

- `prompts.md`
- `learnings.md`
- `capability-matrix.json`
- `run-summary.json`
- 생성된 PNG와 `.meta.json` sidecar

`placeable`은 PNG와 sidecar가 준비되면 `adapter-ready`입니다. Sunny Street
runtime에 바로 등록된 상태를 의미하는 `runtime-ready`는 별도 export가
끝났을 때만 사용합니다.

## 6. Sunny Street runtime까지 내보내기

Sunny Street repo까지 바로 반영하려면 요청에 `--export-ready`와 Sunny Street
repo 경로를 같이 줍니다.

```text
$digital-being-assetgen --sunny-type placeable --slug sunny-farm-tree --export-ready --prompt "Sunny Street 농장 맵에 놓을 수 있는 작은 나무 placeable" --to /path/to/sunny-street
```

이 경우 검증 후 아래 명령 경로를 사용합니다.

```bash
pf being export-sunny --run-dir out/digital-beings/<slug> --to /path/to/sunny-street
```

`runtime-ready`라고 말할 수 있으려면 Sunny Street의 placeables manifest와
Tiled collection 등록까지 완료되어야 합니다.
