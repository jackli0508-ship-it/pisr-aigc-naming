#!/usr/bin/env python3
"""Plan, apply, and validate deterministic PISR AIGC delivery filenames."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}
REQUIRED_RATIOS = ("1x1", "9x16")
ROLE_ORDER = (
    "top",
    "outerwear",
    "bottom",
    "dress",
    "footwear",
    "headwear",
    "glasses",
    "necklace",
    "bracelet",
    "bag",
    "accessory",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Required metadata file is missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def extract_image_id(job_id: str) -> str:
    match = re.search(r"-(\d{3})-", job_id)
    if not match:
        raise ValueError(f"Cannot extract a three-digit image ID from job: {job_id}")
    return match.group(1)


def image_sort_key(image_id: str) -> tuple[int, str]:
    try:
        return int(image_id), image_id
    except ValueError:
        return sys.maxsize, image_id


def clean_product_name(name: str) -> str:
    value = re.sub(r"\s+", " ", name).strip()
    value = value.replace("/", "-").replace(":", "-")
    value = value.rstrip(". ")
    if not value:
        raise ValueError("An authoritative product name became empty after filename cleanup")
    return value


def flatten_product_ids(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(flatten_product_ids(item))
        return result
    if isinstance(value, dict) and isinstance(value.get("id"), str):
        return [value["id"]]
    raise ValueError(f"Unsupported product reference in look.items: {value!r}")


def ordered_product_ids(items: dict[str, Any]) -> list[str]:
    ordered_roles = [role for role in ROLE_ORDER if role in items]
    ordered_roles.extend(role for role in items if role not in ordered_roles)
    result: list[str] = []
    for role in ordered_roles:
        result.extend(flatten_product_ids(items[role]))
    if not result:
        raise ValueError("A look has no product IDs in look.items")
    return result


def resolve_generation_dir(
    ratio_plan: dict[str, Any], explicit: Path | None
) -> Path:
    if explicit:
        return explicit.resolve()
    source_dir = ratio_plan.get("source_dir")
    if not isinstance(source_dir, str) or not source_dir:
        raise ValueError(
            "ratio-plan.json has no source_dir; pass --generation-task-dir"
        )
    source_path = Path(source_dir).resolve()
    return source_path.parent if source_path.name == "results" else source_path


def product_name_map(assets: dict[str, Any]) -> dict[str, str]:
    products = assets.get("products")
    if not isinstance(products, list):
        raise ValueError("current-assets.json must contain a products array")
    result: dict[str, str] = {}
    for product in products:
        if not isinstance(product, dict):
            continue
        product_id = product.get("id")
        name = product.get("name")
        if isinstance(product_id, str) and isinstance(name, str):
            result[product_id] = clean_product_name(name)
    return result


def build_job_map(generation_plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    jobs = generation_plan.get("jobs")
    if not isinstance(jobs, list):
        raise ValueError("Generation plan must contain a jobs array")
    result: dict[str, dict[str, Any]] = {}
    for job in jobs:
        if not isinstance(job, dict) or not isinstance(job.get("job_id"), str):
            continue
        image_id = extract_image_id(job["job_id"])
        if image_id in result:
            raise ValueError(f"Generation plan has duplicate image ID {image_id}")
        result[image_id] = job
    return result


def ensure_filename_fits(filename: str) -> None:
    if len(filename.encode("utf-8")) > 255:
        raise ValueError(
            f"Filename exceeds the 255-byte filesystem limit; do not silently shorten "
            f"an official product name: {filename}"
        )


def create_plan(args: argparse.Namespace) -> dict[str, Any]:
    task_dir = Path(args.task_dir).resolve()
    ratio_plan_path = (
        Path(args.ratio_plan).resolve()
        if args.ratio_plan
        else task_dir / "run" / "ratio-plan.json"
    )
    ratio_plan = load_json(ratio_plan_path)
    generation_dir = resolve_generation_dir(
        ratio_plan,
        Path(args.generation_task_dir) if args.generation_task_dir else None,
    )
    generation_plan_path = generation_dir / "run" / "plan.json"
    assets_path = generation_dir / "run" / "current-assets.json"
    generation_plan = load_json(generation_plan_path)
    assets = load_json(assets_path)
    names = product_name_map(assets)
    generation_jobs = build_job_map(generation_plan)

    ratio_jobs_raw = ratio_plan.get("jobs")
    if not isinstance(ratio_jobs_raw, list):
        raise ValueError("ratio-plan.json must contain a jobs array")
    ratio_jobs: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for job in ratio_jobs_raw:
        if not isinstance(job, dict):
            continue
        image_id = str(job.get("image_id", ""))
        ratio = str(job.get("ratio", ""))
        if ratio not in REQUIRED_RATIOS:
            continue
        if ratio in ratio_jobs[image_id]:
            raise ValueError(f"Duplicate ratio job for image {image_id}, ratio {ratio}")
        ratio_jobs[image_id][ratio] = job

    if not ratio_jobs:
        raise ValueError("No 1x1 or 9x16 jobs were found in ratio-plan.json")

    seen_combinations: dict[tuple[str, ...], int] = defaultdict(int)
    planned_files: list[dict[str, Any]] = []
    target_paths: set[str] = set()

    for image_id in sorted(ratio_jobs, key=image_sort_key):
        pair = ratio_jobs[image_id]
        missing = [ratio for ratio in REQUIRED_RATIOS if ratio not in pair]
        if missing:
            raise ValueError(f"Image {image_id} is missing ratio(s): {', '.join(missing)}")
        generation_job = generation_jobs.get(image_id)
        if not generation_job:
            raise ValueError(f"No generation job matches ratio image ID {image_id}")
        look = generation_job.get("look")
        items = look.get("items") if isinstance(look, dict) else None
        if not isinstance(items, dict):
            raise ValueError(f"Generation job {image_id} has no look.items mapping")

        product_ids = ordered_product_ids(items)
        unresolved = [product_id for product_id in product_ids if product_id not in names]
        if unresolved:
            raise ValueError(
                f"Image {image_id} has product IDs without official names: "
                + ", ".join(unresolved)
            )
        product_names = [names[product_id] for product_id in product_ids]
        combination = tuple(product_names)
        seen_combinations[combination] += 1
        occurrence = seen_combinations[combination]
        base_name = "_".join(product_names) + (str(occurrence) if occurrence > 1 else "")

        for ratio in REQUIRED_RATIOS:
            ratio_job = pair[ratio]
            output = ratio_job.get("output")
            job_id = ratio_job.get("id")
            if not isinstance(output, str) or not isinstance(job_id, str):
                raise ValueError(f"Ratio job {image_id}-{ratio} lacks id or output")
            planned_output = Path(output).resolve()
            suffix = planned_output.suffix
            if suffix.lower() not in IMAGE_SUFFIXES:
                raise ValueError(f"Unsupported or missing image extension: {planned_output}")
            filename = base_name + ("_vertical" if ratio == "9x16" else "") + suffix
            ensure_filename_fits(filename)
            target = planned_output.with_name(filename)

            if planned_output.exists():
                current = planned_output
            elif target.exists():
                current = target
            else:
                raise ValueError(
                    f"Neither the ratio-plan output nor its intended target exists: "
                    f"{planned_output} -> {target}"
                )
            if target.exists() and current != target:
                raise ValueError(f"Refusing to overwrite existing target: {target}")
            target_key = str(target)
            if target_key in target_paths:
                raise ValueError(f"Two assets resolve to the same target: {target}")
            target_paths.add(target_key)

            planned_files.append(
                {
                    "job_id": job_id,
                    "image_id": image_id,
                    "ratio": ratio,
                    "product_ids": product_ids,
                    "product_names": product_names,
                    "combination_occurrence": occurrence,
                    "base_name": base_name,
                    "source_path": str(current),
                    "target_path": str(target),
                    "extension": suffix,
                    "sha256": sha256(current),
                    "bytes": current.stat().st_size,
                    "status": "already_named" if current == target else "planned",
                }
            )

    output_plan = (
        Path(args.output_plan).resolve()
        if args.output_plan
        else task_dir / "run" / "naming-plan.json"
    )
    plan = {
        "version": 1,
        "created_at": now_iso(),
        "task_dir": str(task_dir),
        "ratio_plan": str(ratio_plan_path),
        "generation_task_dir": str(generation_dir),
        "generation_plan": str(generation_plan_path),
        "assets_manifest": str(assets_path),
        "rules": {
            "square": "<product names joined by underscores><duplicate number>.<ext>",
            "vertical": "<square base>_vertical.<ext>",
            "preserve_extension": True,
        },
        "files": planned_files,
    }
    atomic_write_json(output_plan, plan)
    return {
        "plan": str(output_plan),
        "files": len(planned_files),
        "pairs": len(planned_files) // 2,
        "planned_renames": sum(item["status"] == "planned" for item in planned_files),
        "already_named": sum(
            item["status"] == "already_named" for item in planned_files
        ),
    }


def load_naming_plan(path_arg: str) -> tuple[Path, dict[str, Any]]:
    path = Path(path_arg).resolve()
    plan = load_json(path)
    files = plan.get("files")
    if plan.get("version") != 1 or not isinstance(files, list):
        raise ValueError(f"Unsupported naming plan: {path}")
    return path, plan


def verify_hash(path: Path, expected: str) -> None:
    actual = sha256(path)
    if actual != expected:
        raise ValueError(f"Hash mismatch for {path}: expected {expected}, got {actual}")


def apply_plan(args: argparse.Namespace) -> dict[str, Any]:
    plan_path, plan = load_naming_plan(args.plan)
    files = plan["files"]
    actual_moves: list[dict[str, Any]] = []

    for item in files:
        source = Path(item["source_path"])
        target = Path(item["target_path"])
        expected_hash = item["sha256"]
        if source == target:
            if not target.is_file():
                raise ValueError(f"Already-named target is missing: {target}")
            verify_hash(target, expected_hash)
            continue
        if source.is_file():
            verify_hash(source, expected_hash)
            if target.exists():
                raise ValueError(f"Refusing to overwrite existing target: {target}")
            actual_moves.append(item)
            continue
        if target.is_file():
            verify_hash(target, expected_hash)
            continue
        raise ValueError(f"Rename source is missing: {source}")

    journal_path = plan_path.with_name("naming-journal.json")
    journal: dict[str, Any] = {
        "version": 1,
        "started_at": now_iso(),
        "status": "staging",
        "moves": [],
    }
    for index, item in enumerate(actual_moves):
        source = Path(item["source_path"])
        target = Path(item["target_path"])
        temp = source.with_name(
            f".pisr-naming-{uuid.uuid4().hex}-{index}{source.suffix}"
        )
        journal["moves"].append(
            {"source": str(source), "temp": str(temp), "target": str(target), "status": "pending"}
        )
    atomic_write_json(journal_path, journal)

    try:
        for move in journal["moves"]:
            os.replace(move["source"], move["temp"])
            move["status"] = "staged"
            atomic_write_json(journal_path, journal)
        journal["status"] = "committing"
        atomic_write_json(journal_path, journal)
        for move in journal["moves"]:
            if Path(move["target"]).exists():
                raise ValueError(f"Target appeared during rename: {move['target']}")
            os.replace(move["temp"], move["target"])
            move["status"] = "committed"
            atomic_write_json(journal_path, journal)
    except Exception:
        journal["status"] = "rolling_back"
        atomic_write_json(journal_path, journal)
        for move in reversed(journal["moves"]):
            source = Path(move["source"])
            temp = Path(move["temp"])
            target = Path(move["target"])
            if target.exists() and not source.exists():
                os.replace(target, source)
            elif temp.exists() and not source.exists():
                os.replace(temp, source)
            move["status"] = "rolled_back"
        journal["status"] = "rolled_back"
        atomic_write_json(journal_path, journal)
        raise

    target_by_job = {item["job_id"]: item["target_path"] for item in files}
    ratio_plan_path = Path(plan["ratio_plan"])
    ratio_plan = load_json(ratio_plan_path)
    ratio_jobs = ratio_plan.get("jobs")
    if not isinstance(ratio_jobs, list):
        raise ValueError("ratio-plan.json lost its jobs array after planning")
    updated_jobs = 0
    for job in ratio_jobs:
        job_id = job.get("id") if isinstance(job, dict) else None
        if job_id in target_by_job:
            job["output"] = target_by_job[job_id]
            updated_jobs += 1
    if updated_jobs != len(files):
        raise ValueError(
            f"Updated {updated_jobs} ratio jobs but expected {len(files)}; files were renamed, "
            "so inspect the naming journal before retrying"
        )
    atomic_write_json(ratio_plan_path, ratio_plan)

    for item in files:
        item["source_path"] = item["target_path"]
        item["status"] = "named"
    plan["applied_at"] = now_iso()
    atomic_write_json(plan_path, plan)
    journal["status"] = "complete"
    journal["completed_at"] = now_iso()
    atomic_write_json(journal_path, journal)
    return {
        "renamed": len(actual_moves),
        "already_named": len(files) - len(actual_moves),
        "ratio_plan_jobs_updated": updated_jobs,
        "journal": str(journal_path),
    }


def validate_plan(args: argparse.Namespace) -> dict[str, Any]:
    _, plan = load_naming_plan(args.plan)
    files = plan["files"]
    failures: list[str] = []
    expected_targets: set[Path] = set()
    pair_ratios: dict[str, set[str]] = defaultdict(set)
    pair_bases: dict[str, set[str]] = defaultdict(set)

    for item in files:
        target = Path(item["target_path"])
        expected_targets.add(target.resolve())
        image_id = str(item["image_id"])
        ratio = str(item["ratio"])
        base_name = str(item["base_name"])
        pair_ratios[image_id].add(ratio)
        pair_bases[image_id].add(base_name)
        expected_filename = base_name + ("_vertical" if ratio == "9x16" else "") + item["extension"]
        if target.name != expected_filename:
            failures.append(f"Unexpected filename for {item['job_id']}: {target.name}")
        if not target.is_file():
            failures.append(f"Missing target: {target}")
            continue
        if sha256(target) != item["sha256"]:
            failures.append(f"Content changed during rename: {target}")

    for image_id in sorted(pair_ratios, key=image_sort_key):
        if pair_ratios[image_id] != set(REQUIRED_RATIOS):
            failures.append(f"Incomplete ratio pair for image {image_id}")
        if len(pair_bases[image_id]) != 1:
            failures.append(f"1x1 and 9x16 bases disagree for image {image_id}")

    ratio_plan = load_json(Path(plan["ratio_plan"]))
    planned_by_job = {item["job_id"]: item["target_path"] for item in files}
    for job in ratio_plan.get("jobs", []):
        if isinstance(job, dict) and job.get("id") in planned_by_job:
            if job.get("output") != planned_by_job[job["id"]]:
                failures.append(f"ratio-plan output is stale for {job['id']}")

    unmanaged: list[str] = []
    task_dir = Path(plan["task_dir"])
    for ratio in REQUIRED_RATIOS:
        folder = task_dir / "results" / ratio
        if not folder.is_dir():
            failures.append(f"Missing results folder: {folder}")
            continue
        for path in folder.iterdir():
            if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES:
                if path.resolve() not in expected_targets:
                    unmanaged.append(str(path))
    if unmanaged:
        failures.extend(f"Unmanaged image file: {path}" for path in unmanaged)

    result = {
        "checked": len(files),
        "pairs": len(pair_ratios),
        "failures": len(failures),
        "unmanaged_files": len(unmanaged),
        "details": failures,
    }
    if failures:
        raise ValidationFailure(result)
    return result


class ValidationFailure(Exception):
    def __init__(self, result: dict[str, Any]):
        super().__init__(f"Validation failed with {result['failures']} issue(s)")
        self.result = result


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        description="Plan, apply, and validate PISR AIGC delivery filenames."
    )
    sub = root.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan", help="Create a collision-checked naming plan")
    plan.add_argument("--task-dir", required=True)
    plan.add_argument("--generation-task-dir")
    plan.add_argument("--ratio-plan")
    plan.add_argument("--output-plan")
    plan.set_defaults(handler=create_plan)

    apply_cmd = sub.add_parser("apply", help="Apply a reviewed naming plan")
    apply_cmd.add_argument("--plan", required=True)
    apply_cmd.set_defaults(handler=apply_plan)

    validate = sub.add_parser("validate", help="Validate names, hashes, and pairs")
    validate.add_argument("--plan", required=True)
    validate.set_defaults(handler=validate_plan)
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        result = args.handler(args)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except ValidationFailure as exc:
        print(json.dumps(exc.result, indent=2, ensure_ascii=False))
        return 2
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"error": str(exc)}, indent=2, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
