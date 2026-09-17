"""Publish the latest execution environment report to Confluence.

Reads the most recently generated execution_environment_details.json (same
resolution logic as aap-ee-report), renders it into Confluence storage
format, and updates the configured Confluence page (config.toml's
[confluence].page_id), replacing everything below a static hand-written
intro (templates/confluence_intro.md) with the fresh report and an
excluded-EE footnote sourced from config.toml's [exclusions].name_patterns.

This does a full-page replace on every run rather than trying to
diff/patch the live page, since the report itself is a full re-dump each
time and the intro is sourced locally (not scraped from Confluence),
avoiding the fragile "find where the auto-generated section starts on the
live page" problem entirely.

Requires (in .env): CONFLUENCE_BASE_URL, CONFLUENCE_EMAIL, CONFLUENCE_API_TOKEN.
Requires (in config.toml): [confluence].page_id.

Usage:
    aap-ee-publish
    aap-ee-publish --input outputs/20260101T120000
"""

from __future__ import annotations

import argparse
from pathlib import Path

import httpx
import markdown
from jinja2 import Environment, FileSystemLoader, select_autoescape

from aap_ee_inspector.app_config import AppConfig, load_config
from aap_ee_inspector.config import ConfluenceSettings
from aap_ee_inspector.confluence_report import (
    render_exclusions_footnote_storage,
    render_report_storage,
)
from aap_ee_inspector.filters import parse_csv_patterns
from aap_ee_inspector.generate_report import load_details, resolve_input_file
from aap_ee_inspector.models import ExecutionEnvironmentDetails

TEMPLATES_DIR = Path("templates")
INTRO_TEMPLATE_NAME = "confluence_intro.md"


def render_intro_html() -> str:
    """Render templates/confluence_intro.md (via Jinja2) into an HTML fragment.

    Returns an empty string if the file doesn't exist — the intro is
    optional. Copy templates/confluence_intro.md.example to
    templates/confluence_intro.md and edit it to add an intro to the page.
    The file is gitignored so local edits are never accidentally committed.

    The template has no variables today, but is rendered through Jinja2
    rather than read as a plain string so it's trivial to add e.g. a
    generated-at timestamp later without restructuring this function.
    """
    intro_path = TEMPLATES_DIR / INTRO_TEMPLATE_NAME
    if not intro_path.exists():
        return ""

    env = Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        autoescape=select_autoescape(disabled_extensions=(".md",)),
    )
    template = env.get_template(INTRO_TEMPLATE_NAME)
    intro_markdown = template.render()
    return markdown.markdown(intro_markdown)


def build_page_body(
    all_details: list[ExecutionEnvironmentDetails], exclusions_name_patterns: list[str]
) -> str:
    """Assemble the full Confluence storage-format page body."""
    intro_html = render_intro_html()
    report_html = render_report_storage(all_details)
    footnote_html = render_exclusions_footnote_storage(exclusions_name_patterns)
    return intro_html + report_html + footnote_html


def get_current_version(client: httpx.Client, base_url: str, page_id: str) -> tuple[int, str]:
    """Fetch the current page version number and title.

    Confluence's update API requires the exact next version number for its
    optimistic-concurrency check, so this GET is necessary before the PUT.
    """
    response = client.get(
        f"{base_url}/api/v2/pages/{page_id}",
        params={"body-format": "storage"},
    )
    response.raise_for_status()
    data = response.json()
    return data["version"]["number"], data["title"]


def update_page(
    client: httpx.Client,
    base_url: str,
    page_id: str,
    title: str,
    next_version: int,
    body_storage: str,
) -> tuple[int, str]:
    """PUT the updated page content. Returns (new version number, webui path)."""
    response = client.put(
        f"{base_url}/api/v2/pages/{page_id}",
        json={
            "id": page_id,
            "status": "current",
            "title": title,
            "body": {
                "representation": "storage",
                "value": body_storage,
            },
            "version": {
                "number": next_version,
                "message": "Auto-updated by aap-ee-publish",
            },
        },
    )
    response.raise_for_status()
    data = response.json()
    return data["version"]["number"], data.get("_links", {}).get("webui", "")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--only",
        metavar="PATTERN[,PATTERN...]",
        help=(
            "Comma-separated glob pattern(s) matched against EE names. "
            "Only images with at least one matching EE name are included "
            'in the published report. Example: --only "amfam_default:1.21,vmware_env:*"'
        ),
    )
    parser.add_argument(
        "--input",
        metavar="PATH",
        help=(
            "Path to a specific run directory (outputs/<timestamp>/) or "
            "execution_environment_details.json file to read. Defaults to "
            "the most recently generated run that has one."
        ),
    )
    return parser.parse_args()


def main() -> None:
    """Entry point: render the latest report and publish it to Confluence."""
    args = parse_args()
    only = parse_csv_patterns(args.only)

    config: AppConfig = load_config()
    if not config.confluence.page_id:
        raise SystemExit(
            "config.toml is missing [confluence].page_id. Set it to the "
            "Confluence page ID to publish to."
        )

    # Confluence secrets are loaded from the environment / .env file at
    # runtime by pydantic-settings; pyright can't see that, hence the ignore.
    settings = ConfluenceSettings()  # pyright: ignore[reportCallIssue]

    input_file = resolve_input_file(config, args.input)
    print(f"Reading execution environment details from {input_file}")
    all_details = load_details(input_file, only=only)

    body = build_page_body(all_details, config.exclusions.name_patterns)

    base_url = settings.confluence_base_url.rstrip("/")
    with httpx.Client(auth=(settings.confluence_email, settings.confluence_api_token)) as client:
        current_version, title = get_current_version(client, base_url, config.confluence.page_id)
        print(f"Current page version: {current_version} (title: {title!r})")

        new_version, webui_path = update_page(
            client,
            base_url,
            config.confluence.page_id,
            title,
            current_version + 1,
            body,
        )

    print(f"Published. New version: {new_version}")
    print(f"Page: {base_url}{webui_path}")


if __name__ == "__main__":
    main()
