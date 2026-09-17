"""Generate a Markdown report from execution_environment_details.json.

Produces a per-image doc summarizing ansible-core/python/jinja versions and
the full list of installed collections (in a code block, one per line), so
developers have a quick reference without needing to pull the images
themselves. If pip package data was collected (see aap-ee-inspect
--pip-list), it is rendered in a second code block per image.

Usage:
    aap-ee-report
    aap-ee-report --only "amfam_default:1.21,vmware_env:*"
    aap-ee-report --input outputs/20260101T120000_execution_environment_details.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from aap_ee_inspector.app_config import AppConfig, current_timestamp, load_config
from aap_ee_inspector.filters import matches_any, parse_csv_patterns
from aap_ee_inspector.models import ExecutionEnvironmentDetails


def resolve_input_file(config: AppConfig, explicit_path: str | None) -> Path:
    """Resolve which execution_environment_details.json to read.

    Uses `explicit_path` if given, otherwise the most recently generated
    timestamped file in the output directory.
    """
    if explicit_path is not None:
        path = Path(explicit_path)
        if not path.exists():
            raise FileNotFoundError(f"{path} not found.")
        return path

    latest = config.latest_details_output_file()
    if latest is None:
        raise FileNotFoundError(
            f"No execution_environment_details.json found in {config.output.dir}. "
            "Run `aap-ee-inspect` first."
        )
    return latest


def load_details(
    input_file: Path, only: list[str] | None = None
) -> list[ExecutionEnvironmentDetails]:
    """Load and validate `input_file`.

    If `only` is given, results are narrowed to entries where at least one
    associated EE name matches one of the glob patterns.
    """
    raw = json.loads(input_file.read_text())
    all_details = [ExecutionEnvironmentDetails.model_validate(item) for item in raw]

    if only is None:
        return all_details

    return [d for d in all_details if any(matches_any(name, only) for name in d.names)]


def render_entry(details: ExecutionEnvironmentDetails) -> str:
    """Render a single image's details as a Markdown section."""
    heading = " / ".join(details.names)
    lines = [f"## {heading}", "", f"- **Image**: `{details.image}`"]

    if details.error:
        # Collapse multi-line subprocess error output to keep the bullet on one line.
        error_text = details.error.replace("\n", " ").strip()
        lines.append(f"- **Status**: :warning: FAILED - {error_text}")
        lines.append("")
        return "\n".join(lines)

    lines.append("- **Status**: OK")
    lines.append(f"- **ansible-core version**: `{details.ansible_core_version or 'unknown'}`")
    lines.append(f"- **Python version**: `{details.python_version or 'unknown'}`")
    lines.append(f"- **jinja version**: `{details.jinja_version or 'unknown'}`")
    lines.append(f"- **Collections installed**: {len(details.collections)}")
    lines.append("")

    if details.collections:
        lines.append("```")
        lines.extend(f"{name} {details.collections[name]}" for name in sorted(details.collections))
        lines.append("```")
    else:
        lines.append("_No collections found._")

    lines.append("")

    if details.python_packages:
        lines.append(f"- **Python packages installed (pip list)**: {len(details.python_packages)}")
        lines.append("")
        lines.append("```")
        lines.extend(
            f"{name} {details.python_packages[name]}" for name in sorted(details.python_packages)
        )
        lines.append("```")
        lines.append("")

    return "\n".join(lines)


def render_report(all_details: list[ExecutionEnvironmentDetails]) -> str:
    """Render the full Markdown report: successful entries, then failed ones."""
    ok = [d for d in all_details if not d.error]
    failed = [d for d in all_details if d.error]

    summary = (
        f"Generated from {len(all_details)} unique execution environment image(s): "
        f"{len(ok)} inspected successfully, {len(failed)} failed."
    )
    sections = [
        "# Execution Environment Report",
        "",
        summary,
        "",
        "---",
        "",
    ]

    sections.extend(render_entry(d) for d in sorted(ok, key=lambda d: d.names[0].lower()))

    if failed:
        sections.append("---")
        sections.append("")
        sections.append("# Failed / Skipped Images")
        sections.append("")
        sections.extend(render_entry(d) for d in sorted(failed, key=lambda d: d.names[0].lower()))

    return "\n".join(sections)


def save_report(markdown: str, config: AppConfig) -> Path:
    """Write the rendered Markdown to a new timestamped file. Returns the path written to."""
    config.output.dir.mkdir(parents=True, exist_ok=True)
    report_file = config.new_report_output_file(current_timestamp())
    report_file.write_text(markdown)
    print(f"Saved report to {report_file}")
    return report_file


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--only",
        metavar="PATTERN[,PATTERN...]",
        help=(
            "Comma-separated glob pattern(s) matched against EE names. "
            "Only images with at least one matching EE name are included "
            'in the report. Example: --only "amfam_default:1.21,vmware_env:*"'
        ),
    )
    parser.add_argument(
        "--input",
        metavar="PATH",
        help=(
            "Path to a specific execution_environment_details.json to read. "
            "Defaults to the most recently generated file in the output directory."
        ),
    )
    return parser.parse_args()


def main() -> None:
    """Entry point: load details, render Markdown, and save the report."""
    args = parse_args()
    only = parse_csv_patterns(args.only)

    config = load_config()
    input_file = resolve_input_file(config, args.input)
    print(f"Reading execution environment details from {input_file}")

    all_details = load_details(input_file, only=only)
    markdown = render_report(all_details)
    save_report(markdown, config)


if __name__ == "__main__":
    main()
