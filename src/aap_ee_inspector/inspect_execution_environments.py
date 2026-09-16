"""Inspect AAP execution environment images locally with podman.

For each unique image referenced in the latest execution_environments.json
(excluding any matched by config.toml's [exclusions] section, and further
narrowed by --only if given), pulls the image, runs `ansible --version` and
`ansible-galaxy collection list --format json` inside a throwaway
container, parses out the ansible-core/python/jinja versions and the
installed collection versions, then removes the image again to reclaim
disk space.

Requires:
    - a <timestamp>_execution_environments.json to already exist in the
      output directory (run `aap-ee-fetch` first)
    - podman installed and able to pull the referenced images

Usage:
    aap-ee-inspect
    aap-ee-inspect --only "amfam_default:1.21,vmware_env:*"
    aap-ee-inspect --input outputs/20260101T120000_execution_environments.json
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections import defaultdict
from pathlib import Path

from aap_ee_inspector.app_config import AppConfig, ExclusionsConfig, current_timestamp, load_config
from aap_ee_inspector.filters import matches_any, parse_csv_patterns
from aap_ee_inspector.models import ExecutionEnvironmentDetails

ANSIBLE_VERSION_SEPARATOR = "---SEP---"

CORE_VERSION_RE = re.compile(r"ansible \[core ([\d.]+)\]")
PYTHON_VERSION_RE = re.compile(r"python version = ([\d.]+)")
JINJA_VERSION_RE = re.compile(r"jinja version = ([\d.]+)")


def resolve_input_file(config: AppConfig, explicit_path: str | None) -> Path:
    """Resolve which execution_environments.json to read.

    Uses `explicit_path` if given, otherwise the most recently generated
    timestamped file in the output directory.
    """
    if explicit_path is not None:
        path = Path(explicit_path)
        if not path.exists():
            raise FileNotFoundError(f"{path} not found.")
        return path

    latest = config.latest_output_file()
    if latest is None:
        raise FileNotFoundError(
            f"No execution_environments.json found in {config.output.dir}. "
            "Run `aap-ee-fetch` first to fetch the execution environment list from AAP."
        )
    return latest


def load_images(
    input_file: Path, config: AppConfig, only: list[str] | None = None
) -> dict[str, list[str]]:
    """Load `input_file` and group EE names by image.

    Images excluded via config.toml's [exclusions] section (either by exact
    image reference or by a matching EE name glob pattern) are always
    skipped. If `only` is given, results are further narrowed to just the EE
    names matching one of those glob patterns.
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
    return image in exclusions.images or matches_any(name, exclusions.name_patterns)


def pull_image(image: str) -> None:
    """Pull `image` with podman; raises RuntimeError on failure."""
    result = subprocess.run(
        ["podman", "pull", image],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "podman pull failed")


def remove_image(image: str) -> None:
    """Remove `image` from local podman storage. Best-effort; never raises."""
    subprocess.run(["podman", "rmi", image], capture_output=True, text=True, check=False)


def run_in_container(image: str) -> str:
    """Run the version/collection-listing commands inside a throwaway container.

    Returns combined stdout containing both the `ansible --version` output
    and the `ansible-galaxy collection list --format json` output, separated
    by ANSIBLE_VERSION_SEPARATOR.
    """
    command = (
        f"ansible --version; echo '{ANSIBLE_VERSION_SEPARATOR}'; "
        "ansible-galaxy collection list --format json"
    )
    result = subprocess.run(
        ["podman", "run", "--rm", image, "sh", "-c", command],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "podman run failed")
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


def inspect_image(image: str) -> tuple[str | None, str | None, str | None, dict[str, str]]:
    """Pull-independent inspection step: run version/collection commands and parse them."""
    output = run_in_container(image)
    ansible_block, _, collections_block = output.partition(ANSIBLE_VERSION_SEPARATOR)

    core_version, python_version, jinja_version = parse_ansible_version_block(ansible_block)
    collections = parse_collections_block(collections_block)

    return core_version, python_version, jinja_version, collections


def inspect_all_images(
    images_to_names: dict[str, list[str]],
) -> list[ExecutionEnvironmentDetails]:
    """Pull, inspect, and clean up each image, collecting results as we go.

    Failures (pull or inspect) for a single image are recorded on that
    image's result rather than aborting the whole batch.
    """
    details: list[ExecutionEnvironmentDetails] = []
    total = len(images_to_names)

    for i, (image, names) in enumerate(images_to_names.items(), start=1):
        print(f"[{i}/{total}] {image}")

        try:
            print("  pulling...")
            pull_image(image)
        except RuntimeError as exc:
            print(f"  FAILED to pull: {exc}")
            details.append(
                ExecutionEnvironmentDetails(names=names, image=image, error=f"pull failed: {exc}")
            )
            continue

        try:
            print("  inspecting...")
            core_version, python_version, jinja_version, collections = inspect_image(image)
            details.append(
                ExecutionEnvironmentDetails(
                    names=names,
                    image=image,
                    ansible_core_version=core_version,
                    python_version=python_version,
                    jinja_version=jinja_version,
                    collections=collections,
                )
            )
            print(
                f"  ok: ansible-core={core_version}, python={python_version}, "
                f"{len(collections)} collections"
            )
        except (RuntimeError, json.JSONDecodeError) as exc:
            print(f"  FAILED to inspect: {exc}")
            details.append(
                ExecutionEnvironmentDetails(
                    names=names, image=image, error=f"inspect failed: {exc}"
                )
            )
        finally:
            print("  removing local image...")
            remove_image(image)

    return details


def save_details(details: list[ExecutionEnvironmentDetails], config: AppConfig) -> Path:
    """Write the details list to a new timestamped file as pretty-printed JSON.

    Returns the path written to.
    """
    config.output.dir.mkdir(parents=True, exist_ok=True)
    details_file = config.new_details_output_file(current_timestamp())
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
            "Path to a specific execution_environments.json to read. "
            "Defaults to the most recently generated file in the output directory."
        ),
    )
    return parser.parse_args()


def main() -> None:
    """Entry point: inspect every unique (non-excluded) EE image and save the results."""
    args = parse_args()
    only = parse_csv_patterns(args.only)

    config = load_config()
    input_file = resolve_input_file(config, args.input)
    print(f"Reading execution environments from {input_file}")

    images_to_names = load_images(input_file, config, only=only)
    print(f"Found {len(images_to_names)} unique images across the execution environment list.")
    details = inspect_all_images(images_to_names)
    save_details(details, config)


if __name__ == "__main__":
    main()
