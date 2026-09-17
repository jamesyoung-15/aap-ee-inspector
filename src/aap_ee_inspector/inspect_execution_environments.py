"""Inspect AAP execution environment images locally with podman or docker.

For each unique image referenced in the latest run's execution_environments.json
(excluding any matched by config.toml's [exclusions] section, and further
narrowed by --only if given), pulls the image, runs `ansible --version` and
`ansible-galaxy collection list --format json` (and, if enabled, `pip list
--format json`) inside a throwaway container, parses out the
ansible-core/python/jinja versions and the installed collection (and
optionally pip package) versions, then removes the image again to reclaim
disk space (unless kept per config.toml's [cache] section or --keep-cache).

Results are written to execution_environment_details.json in the same run
directory (outputs/<timestamp>/) the input file was read from.

Requires:
    - an outputs/<timestamp>/execution_environments.json run directory to
      already exist (run `aap-ee-fetch` first)
    - the configured container engine (config.toml's [container].engine,
      "podman" by default) installed and able to pull the referenced images

Usage:
    aap-ee-inspect
    aap-ee-inspect --only "amfam_default:1.21,vmware_env:*"
    aap-ee-inspect --input outputs/20260101T120000
    aap-ee-inspect --pip-list
    aap-ee-inspect --keep-cache
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections import defaultdict
from pathlib import Path

from aap_ee_inspector.app_config import (
    DETAILS_FILENAME,
    EXECUTION_ENVIRONMENTS_FILENAME,
    AppConfig,
    CacheConfig,
    ExclusionsConfig,
    load_config,
)
from aap_ee_inspector.filters import matches_any, parse_csv_patterns
from aap_ee_inspector.models import ExecutionEnvironmentDetails

ANSIBLE_VERSION_SEPARATOR = "---SEP---"
PIP_LIST_SEPARATOR = "---PIP-SEP---"

CORE_VERSION_RE = re.compile(r"ansible \[core ([\d.]+)\]")
PYTHON_VERSION_RE = re.compile(r"python version = ([\d.]+)")
JINJA_VERSION_RE = re.compile(r"jinja version = ([\d.]+)")


def resolve_input_file(config: AppConfig, explicit_path: str | None) -> Path:
    """Resolve which execution_environments.json to read.

    `explicit_path` may point at a run directory (outputs/<timestamp>/) or
    directly at an execution_environments.json file inside one. If not
    given, defaults to the file in the most recently generated run
    directory.
    """
    if explicit_path is not None:
        path = Path(explicit_path)
        if path.is_dir():
            path = path / EXECUTION_ENVIRONMENTS_FILENAME
        if not path.exists():
            raise FileNotFoundError(f"{path} not found.")
        return path

    latest = config.latest_output_file()
    if latest is None:
        raise FileNotFoundError(
            f"No execution_environments.json found under {config.output.dir}. "
            "Run `aap-ee-fetch` first to fetch the execution environment list from AAP."
        )
    return latest


def load_images(
    input_file: Path, config: AppConfig, only: list[str] | None = None
) -> dict[str, list[str]]:
    """Load `input_file` and group EE names by image.

    Images excluded via config.toml's [exclusions] section (either by a
    matching image glob pattern or a matching EE name glob pattern) are
    always skipped. If `only` is given, results are further narrowed to just
    the EE names matching one of those glob patterns.
    """
    records = json.loads(input_file.read_text())

    images_to_names: dict[str, list[str]] = defaultdict(list)
    skipped = 0
    for record in records:
        image, name = record["image"], record["name"]
        if is_excluded(image, name, config.exclusions):
            skipped += 1
            continue
        if only is not None and not matches_any(name, only):
            continue
        images_to_names[image].append(name)

    if skipped:
        print(f"Skipped {skipped} execution environment(s) via config.toml exclusions.")

    return images_to_names


def is_excluded(image: str, name: str, exclusions: ExclusionsConfig) -> bool:
    """Return True if `image`/`name` should be skipped per config exclusions."""
    return matches_any(image, exclusions.images) or matches_any(name, exclusions.name_patterns)


def pull_image(image: str, engine: str) -> None:
    """Pull `image` with the given container engine; raises RuntimeError on failure."""
    result = subprocess.run(
        [engine, "pull", image],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"{engine} pull failed")


def remove_image(image: str, engine: str) -> None:
    """Remove `image` from local engine storage. Best-effort; never raises."""
    subprocess.run([engine, "rmi", image], capture_output=True, text=True, check=False)


def run_in_container(image: str, engine: str, include_pip_packages: bool = False) -> str:
    """Run the version/collection-listing commands inside a throwaway container.

    Returns combined stdout containing the `ansible --version` output, the
    `ansible-galaxy collection list --format json` output (separated by
    ANSIBLE_VERSION_SEPARATOR), and, if `include_pip_packages` is set, the
    `pip list --format json` output (separated by PIP_LIST_SEPARATOR).
    """
    command = (
        f"ansible --version; echo '{ANSIBLE_VERSION_SEPARATOR}'; "
        "ansible-galaxy collection list --format json"
    )
    if include_pip_packages:
        command += f"; echo '{PIP_LIST_SEPARATOR}'; pip list --format json"

    result = subprocess.run(
        [engine, "run", "--rm", image, "sh", "-c", command],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"{engine} run failed")
    return result.stdout


def parse_ansible_version_block(text: str) -> tuple[str | None, str | None, str | None]:
    """Extract (ansible-core, python, jinja) versions from `ansible --version` output."""
    core_match = CORE_VERSION_RE.search(text)
    python_match = PYTHON_VERSION_RE.search(text)
    jinja_match = JINJA_VERSION_RE.search(text)
    return (
        core_match.group(1) if core_match else None,
        python_match.group(1) if python_match else None,
        jinja_match.group(1) if jinja_match else None,
    )


def parse_collections_block(text: str) -> dict[str, str]:
    """Flatten `ansible-galaxy collection list --format json` output.

    The JSON is keyed by collection search path (e.g. one entry per
    site-packages / system collections dir); we merge all paths into a
    single {name: version} dict since we only care about what's installed,
    not where.
    """
    # ansible-galaxy sometimes prints warnings before the JSON payload; find
    # the first '{' to isolate the actual JSON object.
    start = text.find("{")
    if start == -1:
        return {}

    data = json.loads(text[start:])

    collections: dict[str, str] = {}
    for entries in data.values():
        for name, info in entries.items():
            collections[name] = info.get("version", "")

    return collections


def parse_pip_list_block(text: str) -> dict[str, str]:
    """Flatten `pip list --format json` output ([{"name": ..., "version": ...}, ...])
    into a single {name: version} dict, matching the collections dict shape.
    """
    start = text.find("[")
    if start == -1:
        return {}

    data = json.loads(text[start:])
    return {entry["name"]: entry["version"] for entry in data}


def inspect_image(
    image: str, engine: str, include_pip_packages: bool = False
) -> tuple[str | None, str | None, str | None, dict[str, str], dict[str, str]]:
    """Pull-independent inspection step: run version/collection/pip commands and parse them."""
    output = run_in_container(image, engine, include_pip_packages=include_pip_packages)
    ansible_block, _, remainder = output.partition(ANSIBLE_VERSION_SEPARATOR)

    core_version, python_version, jinja_version = parse_ansible_version_block(ansible_block)

    if include_pip_packages:
        collections_block, _, pip_block = remainder.partition(PIP_LIST_SEPARATOR)
        python_packages = parse_pip_list_block(pip_block)
    else:
        collections_block = remainder
        python_packages = {}

    collections = parse_collections_block(collections_block)

    return core_version, python_version, jinja_version, collections, python_packages


def inspect_all_images(
    images_to_names: dict[str, list[str]],
    engine: str,
    include_pip_packages: bool = False,
    cache: CacheConfig | None = None,
) -> list[ExecutionEnvironmentDetails]:
    """Pull, inspect, and clean up each image, collecting results as we go.

    Failures (pull or inspect) for a single image are recorded on that
    image's result rather than aborting the whole batch. Images matched by
    `cache` (or `cache.keep_all`) are left in local storage instead of being
    removed after inspection.
    """
    cache = cache or CacheConfig()
    details: list[ExecutionEnvironmentDetails] = []
    total = len(images_to_names)

    for i, (image, names) in enumerate(images_to_names.items(), start=1):
        print(f"[{i}/{total}] {image}")

        try:
            print(f"  pulling ({engine})...")
            pull_image(image, engine)
        except RuntimeError as exc:
            print(f"  FAILED to pull: {exc}")
            details.append(
                ExecutionEnvironmentDetails(names=names, image=image, error=f"pull failed: {exc}")
            )
            continue

        try:
            print("  inspecting...")
            core_version, python_version, jinja_version, collections, python_packages = (
                inspect_image(image, engine, include_pip_packages=include_pip_packages)
            )
            details.append(
                ExecutionEnvironmentDetails(
                    names=names,
                    image=image,
                    ansible_core_version=core_version,
                    python_version=python_version,
                    jinja_version=jinja_version,
                    collections=collections,
                    python_packages=python_packages,
                )
            )
            summary = (
                f"  ok: ansible-core={core_version}, python={python_version}, "
                f"{len(collections)} collections"
            )
            if include_pip_packages:
                summary += f", {len(python_packages)} pip packages"
            print(summary)
        except (RuntimeError, json.JSONDecodeError) as exc:
            print(f"  FAILED to inspect: {exc}")
            details.append(
                ExecutionEnvironmentDetails(
                    names=names, image=image, error=f"inspect failed: {exc}"
                )
            )
        finally:
            if cache.should_keep(image, names):
                print("  keeping image cached (per [cache] config)")
            else:
                print("  removing local image...")
                remove_image(image, engine)

    return details


def save_details(details: list[ExecutionEnvironmentDetails], run_dir: Path) -> Path:
    """Write the details list into `run_dir` as pretty-printed JSON.

    Returns the path written to.
    """
    run_dir.mkdir(parents=True, exist_ok=True)
    details_file = run_dir / DETAILS_FILENAME
    payload = [d.model_dump(mode="json") for d in details]
    details_file.write_text(json.dumps(payload, indent=2))
    print(f"Saved {len(details)} execution environment details to {details_file}")
    return details_file


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--only",
        metavar="PATTERN[,PATTERN...]",
        help=(
            "Comma-separated glob pattern(s) matched against EE names. "
            "Only images with at least one matching EE name are inspected. "
            'Example: --only "amfam_default:1.21,vmware_env:*"'
        ),
    )
    parser.add_argument(
        "--input",
        metavar="PATH",
        help=(
            "Path to a specific run directory (outputs/<timestamp>/) or "
            "execution_environments.json file to read. Defaults to the "
            "most recently generated run."
        ),
    )
    parser.add_argument(
        "--pip-list",
        action="store_true",
        default=None,
        help=(
            "Also run `pip list` inside each EE image and record installed "
            "Python packages. Overrides config.toml's [output].include_pip_packages "
            "for this run. Warning: can significantly increase output size."
        ),
    )
    parser.add_argument(
        "--keep-cache",
        action="store_true",
        default=None,
        help=(
            "Keep every pulled image cached locally instead of removing it "
            "after inspection. Overrides config.toml's [cache].keep_all for "
            "this run. Speeds up subsequent runs at the cost of disk space."
        ),
    )
    return parser.parse_args()


def main() -> None:
    """Entry point: inspect every unique (non-excluded) EE image and save the results."""
    args = parse_args()
    only = parse_csv_patterns(args.only)

    config = load_config()
    include_pip_packages = (
        args.pip_list if args.pip_list is not None else config.output.include_pip_packages
    )
    cache = config.cache
    if args.keep_cache is not None:
        cache = CacheConfig(
            keep_all=args.keep_cache, images=cache.images, name_patterns=cache.name_patterns
        )

    input_file = resolve_input_file(config, args.input)
    run_dir = input_file.parent
    print(f"Reading execution environments from {input_file}")

    images_to_names = load_images(input_file, config, only=only)
    print(f"Found {len(images_to_names)} unique images across the execution environment list.")
    print(f"Using container engine: {config.container.engine}")
    if include_pip_packages:
        print("pip list collection: enabled")
    if cache.keep_all:
        print("Image caching: keeping ALL images after inspection")
    elif cache.images or cache.name_patterns:
        print("Image caching: keeping images matching [cache] config")
    details = inspect_all_images(
        images_to_names, config.container.engine, include_pip_packages, cache
    )
    save_details(details, run_dir)


if __name__ == "__main__":
    main()
