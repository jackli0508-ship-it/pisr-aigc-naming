---
name: pisr-aigc-naming
description: "Create authoritative product-based delivery metadata for PISR AIGC image and video outputs. Use when Codex must name paired 1:1 and 9:16 images from exact product names, prevent filename collisions, validate renamed pairs, or write one look- and clip-grouped product TXT manifest per delivered video scene group without forcing long product names into video filenames."
---

# PISR AIGC Naming

Create delivery metadata from the products actually used in each generated
look. For images, rename completed ratio-adjustment outputs. For videos, write
an authoritative product manifest while keeping video filenames concise. Derive
both outputs from structured generation metadata, never from visual guesses.

## Task-folder boundary

This skill never creates or renames the total task folder. It receives an
existing completed task directory and operates in place. Preserve its upstream
`YYYY-MM-DD-<Title-Kebab-Case>` folder name exactly.

- For image jobs, control only image filenames and keep every image flat in the
  single `results/` directory.
- For video jobs, leave video filenames unchanged and control only the
  per-scene-group product TXT manifests in `results/`.

Never create ratio or naming subfolders in a new run.

## Choose an output mode

- Use **image filename mode** for completed 1:1 and 9:16 image pairs.
- Use **video scene-group manifest mode** when `pisr-aigc-video` hands off one
  or more final scene groups. Write one TXT per delivered scene group. Do not
  apply the image filename contract to `.mp4` files.

## Naming contract

- Name a 1:1 file `<product 1>_<product 2>[_<product n>].<ext>`.
- Name its 9:16 counterpart `<same 1:1 base>_vertical.<ext>`.
- Preserve authoritative product spelling, capitalization, and product order.
- Preserve the existing file extension. Naming does not convert PNG to JPG or
  change image contents.
- For an identical product combination, leave the first base unchanged and add
  `2`, `3`, and so on to later bases before `_vertical` or the extension.
- Include only product names and the required duplicate/vertical suffixes. Do
  not include batch IDs, image IDs, model names, scene names, ratio labels, or
  words such as `photoshop`.

Example pair:

```text
1997 POSTOFFICE Distressed Tribal Graphics T-Shirt_DND4DES Star Graffiti Patchwork Cartoon Denim Oversized Shorts.png
1997 POSTOFFICE Distressed Tribal Graphics T-Shirt_DND4DES Star Graffiti Patchwork Cartoon Denim Oversized Shorts_vertical.png
```

## Video scene-group manifest contract

Write exactly one UTF-8 text file for every delivered scene group at:

```text
<video-task>/results/<scene-group-delivery-stem>-Video-Products.txt
```

- Use the authoritative user-facing `scene_group_delivery_stem` handed off by
  `pisr-aigc-video`; for example, `Ssequence-B07-S06` produces
  `Ssequence-B07-S06-Video-Products.txt`.
- Keep looks in final clip order and number them `Look 01`, `Look 02`, and so
  on.
- Write the exact final clip filename under its Look.
- List every product actually used in each look, including accessories, using
  exact authoritative spelling and capitalization.
- Preserve the official product order supplied by the look or generation plan.
- Repeat a product under every look where it appears; do not deduplicate across
  looks or scenes.
- Keep full names in the text manifest. Do not abbreviate names to fit a video
  filename and do not rename the final `.mp4` from the full product list.
- Make the TXT count match the delivered scene-group count and the Look count
  in each TXT match that group's final clip count. Stop if a product ID cannot
  be resolved, a final clip lacks authoritative lineage, or a delivery stem is
  missing.
- Rewrite each scene-group TXT atomically when its approved clip or look order
  changes; do not create numbered copies of the text file.

Use this structure:

```text
Ssequence Batch 07 — Scene 06 Video Products
Source Group: Ssequence-B07-S06-Quartet-Review

Look 01
Clip: Ssequence-B07-S06-L01-Kling3-3s.mp4
Products:
- <official product name>
- <official product name>

Look 02
Clip: Ssequence-B07-S06-L02-Kling3-3s.mp4
Products:
- <official product name>
```

## Authoritative inputs

For image filename mode, use the completed ratio task directory. The tool reads:

```text
<ratio-task>/run/ratio-plan.json
<generation-task>/run/plan.json
<generation-task>/run/current-assets.json
```

Infer the generation task from `ratio-plan.json.source_dir`. Pass
`--generation-task-dir` only when the source task moved. Stop if a product ID
cannot be resolved to its official `name`, a ratio pair is incomplete, or the
metadata disagrees with the files. Do not invent or shorten a product name.

For video scene-group manifest mode, read the final `scene-groups.json`,
`video-plan.json`, or equivalent authoritative video state plus the upstream
product catalog or `current-assets.json`. Require the video handoff to provide
each `scene_group_delivery_stem` and ordered final clip filenames. Use the
ordered scene groups, variants, and clip lineage recorded there. Do not infer
products from rendered stills or video frames.

## Image filename workflow

1. Create a naming plan. This hashes every current asset, assigns duplicate
   suffixes by image order, checks filename length, and rejects collisions.
2. Read `run/naming-plan.json`. Confirm that every 1:1 and 9:16 pair uses the
   same base and that `_vertical` appears only on 9:16 files.
3. Apply the plan. The tool uses staged atomic renames, never overwrites a
   destination, flattens legacy ratio-subfolder files into `results/`, and
   updates `run/ratio-plan.json` only after all renames succeed.
4. Validate hashes, filenames, pair completeness, file counts, and ratio-plan
   paths. Report the single results folder and any warnings.

```bash
NAMING_TOOL="$HOME/.codex/skills/pisr-aigc-naming/scripts/naming_batch.py"
TASK_DIR="/Users/tianyuli/Codex Projects/AIGC/YYYY-MM-DD-<completed-ratio-task>"

python3 "$NAMING_TOOL" plan --task-dir "$TASK_DIR"
python3 "$NAMING_TOOL" apply --plan "$TASK_DIR/run/naming-plan.json"
python3 "$NAMING_TOOL" validate --plan "$TASK_DIR/run/naming-plan.json"
```

If metadata lives elsewhere:

```bash
python3 "$NAMING_TOOL" plan \
  --task-dir "$TASK_DIR" \
  --generation-task-dir "/absolute/generation-task"
```

Use `--output-plan /absolute/path.json` for a non-mutating dry-run outside the
task directory.

## Video scene-group manifest workflow

1. Resolve the final user-approved scene scope and ordered clip list.
2. Resolve every variant's product IDs to official product names from the
   authoritative product catalog.
3. For each delivered scene group, build
   `<scene-group-delivery-stem>-Video-Products.txt` in a temporary file using
   the required Look, Clip, and Products structure.
4. Confirm that the TXT count, per-group Look count, exact clip filenames, clip
   order, and product lists match the final video plan.
5. Atomically replace every scene-group TXT and report all of them alongside
   the final video delivery.

## Safety and acceptance

- Always run `plan` before `apply`; do not rename ad hoc with a guessed mapping.
- Never overwrite an existing target. Resolve the conflict or duplicate logic
  first.
- Keep the numeric duplicate suffix synchronized across the 1:1 and 9:16 pair.
- Determine ratio identity from `ratio-plan.json`, never from a parent folder.
- Keep final 1:1 and 9:16 files together directly under `results/`.
- Accept an already-named batch idempotently when filenames and hashes match.
- Require `validate` to report zero failures and zero unmanaged image files.
- Preserve the original assets byte-for-byte; successful validation requires
  every post-rename SHA-256 hash to match its pre-rename hash.
- In video scene-group manifest mode, never rename or modify the video assets.
- Require every listed product name to resolve from authoritative metadata and
  every delivered scene group, final clip, and look to appear exactly once
  across the TXT set.
