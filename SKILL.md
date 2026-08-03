---
name: pisr-aigc-naming
description: "Rename completed PISR AIGC fashion-ad batches from authoritative product metadata. Use when Codex must name paired 1:1 and 9:16 deliverables, join the exact product names with underscores, append numeric suffixes for repeated product combinations, add _vertical to 9:16 variants, preserve existing image formats, prevent filename collisions, update the ratio plan, and validate every renamed pair."
---

# PISR AIGC Naming

Name completed PISR ratio-adjustment outputs from the products actually used in
each generated look. Treat filenames as delivery metadata: derive them from the
generation plan, never from visual guesses.

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

## Authoritative inputs

Use the completed ratio task directory. The tool reads:

```text
<ratio-task>/run/ratio-plan.json
<generation-task>/run/plan.json
<generation-task>/run/current-assets.json
```

Infer the generation task from `ratio-plan.json.source_dir`. Pass
`--generation-task-dir` only when the source task moved. Stop if a product ID
cannot be resolved to its official `name`, a ratio pair is incomplete, or the
metadata disagrees with the files. Do not invent or shorten a product name.

## Workflow

1. Create a naming plan. This hashes every current asset, assigns duplicate
   suffixes by image order, checks filename length, and rejects collisions.
2. Read `run/naming-plan.json`. Confirm that every 1:1 and 9:16 pair uses the
   same base and that `_vertical` appears only on 9:16 files.
3. Apply the plan. The tool uses staged same-folder renames, never overwrites a
   destination, and updates `run/ratio-plan.json` only after all renames succeed.
4. Validate hashes, filenames, pair completeness, file counts, and ratio-plan
   paths. Report the two results folders and any warnings.

```bash
NAMING_TOOL="$HOME/.codex/skills/pisr-aigc-naming/scripts/naming_batch.py"
TASK_DIR="/Users/tianyuli/Codex Projects/AIGC/<completed-ratio-task>"

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

## Safety and acceptance

- Always run `plan` before `apply`; do not rename ad hoc with a guessed mapping.
- Never overwrite an existing target. Resolve the conflict or duplicate logic
  first.
- Keep the numeric duplicate suffix synchronized across the 1:1 and 9:16 pair.
- Accept an already-named batch idempotently when filenames and hashes match.
- Require `validate` to report zero failures and zero unmanaged image files.
- Preserve the original assets byte-for-byte; successful validation requires
  every post-rename SHA-256 hash to match its pre-rename hash.

