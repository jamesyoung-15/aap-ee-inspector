"""Fetch all AAP execution environments (paginating through results) and
dump them to outputs/execution_environments.json for downstream analysis.

Usage:
    python main.py
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urljoin

import httpx

from aap_ee_inspector.app_config import AppConfig, current_timestamp, load_config
from aap_ee_inspector.config import Settings
from aap_ee_inspector.models import (
    ExecutionEnvironment,
    ExecutionEnvironmentListResponse,
)


def fetch_all_execution_environments(
    settings: Settings, config: AppConfig
) -> list[ExecutionEnvironment]:
    """Page through the AAP execution environments API and return all results."""
    base_url = f"https://{settings.aap_base_url}"
    next_url: str | None = urljoin(base_url, config.api.execution_environments_path)

    headers = {"Authorization": f"Bearer {settings.aap_api_token}"}
    results: list[ExecutionEnvironment] = []

    with httpx.Client(verify=False, headers=headers) as client:
        page = 1
        while next_url:
            response = client.get(next_url)
            response.raise_for_status()

            page_data = ExecutionEnvironmentListResponse.model_validate(response.json())
            results.extend(page_data.results)

            print(
                f"Fetched page {page}: {len(page_data.results)} results "
                f"({len(results)}/{page_data.count} total)"
            )

            next_url = urljoin(base_url, page_data.next) if page_data.next else None
            page += 1

    return results


def save_results(results: list[ExecutionEnvironment], config: AppConfig) -> Path:
    """Write results to a new timestamped file, limited to config.output_fields.

    Returns the path written to.
    """
    config.output.dir.mkdir(parents=True, exist_ok=True)
    output_file = config.new_output_file(current_timestamp())
    payload = [ee.model_dump(mode="json", include=config.output_fields) for ee in results]
    output_file.write_text(json.dumps(payload, indent=2))
    print(f"Saved {len(results)} execution environments to {output_file}")
    return output_file


def main() -> None:
    """Entry point: fetch all execution environments from AAP and save them."""
    config = load_config()
    # Fields are loaded from the environment / .env file at runtime by
    # pydantic-settings; pyright can't see that, hence the ignore.
    settings = Settings()  # pyright: ignore[reportCallIssue]
    results = fetch_all_execution_environments(settings, config)
    save_results(results, config)


if __name__ == "__main__":
    main()
