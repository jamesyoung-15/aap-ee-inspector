# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `aap-ee-publish` (`publish_confluence_report.py`): new CLI entry that reads
  the latest `execution_environment_details.json` and publishes a full-page
  Confluence update using Confluence storage-format XHTML with native
  code-block macros (no lossy Markdown conversion). Includes a static
  hand-written intro from `templates/confluence_intro.md` (Jinja2 + Markdown
  → HTML) and an excluded-EE footnote from `config.toml`'s
  `[exclusions].name_patterns`. Configured via `CONFLUENCE_BASE_URL`,
  `CONFLUENCE_EMAIL`, `CONFLUENCE_API_TOKEN` in `.env` and
  `[confluence].page_id` in `config.toml`. Supports `--only` and `--input`.
  Verified end-to-end against a live Confluence page.
- `confluence_report.py`: Confluence storage-format XHTML renderer mirroring
  the existing Markdown renderer in `generate_report.py`, rendering
  collections and pip packages as native `<ac:structured-macro ac:name="code">`
  macros (language: none, CDATA bodies).
- `templates/confluence_intro.md`: version-controlled, hand-editable source
  for the static intro section of the Confluence page.
- `[confluence].page_id` in `config.toml`: non-secret Confluence page target.
- `ConfluenceSettings` in `config.py`: pydantic-settings class loading
  Confluence auth from `.env`.

## [0.1.0] - 2026-09-17

First release. A CLI pipeline to fetch every execution environment (EE)
from an AAP controller, pull and inspect each unique image locally with
podman or docker, and generate a Markdown report of what's installed in
each - Ansible collections, `ansible-core`/Python/jinja versions, and
optionally pip packages.

### Features

- **Three-stage pipeline** (`aap-ee-fetch` -> `aap-ee-inspect` -> `aap-ee-report`),
  each independently runnable via `uv run task <fetch|inspect|report|all>`.
- **AAP API fetch**: pages through `GET /api/controller/v2/execution_environments/`,
  handling pagination and TLS-verification-disabled internal registries.
- **Local image inspection** via podman or docker (`[container].engine` in
  `config.toml`): pulls each unique image, runs `ansible --version` and
  `ansible-galaxy collection list --format json` inside a throwaway
  container, then removes the image to reclaim disk space.
- **Markdown report generation**: one section per EE image with
  ansible-core/Python/jinja versions and the full collection list in a
  fenced code block (one collection per line, sorted).
- **Per-run output directories**: every `aap-ee-fetch` run creates a new
  `outputs/<timestamp>/` directory; `aap-ee-inspect` and `aap-ee-report`
  write their output into that same directory, so all files belonging to
  one end-to-end run live together. Auto-selects the most recently
  generated run by default, or `--input PATH` (run directory or a file
  inside one) to target a specific past run.
- **Config-driven exclusions**: `[exclusions]` in `config.toml` skips known
  unreachable/unsupported images (glob patterns for both image references
  and EE names).
- **Ad-hoc filtering**: `--only "PATTERN[,PATTERN...]"` on `aap-ee-inspect`/
  `aap-ee-report` to target specific EEs for a single run without editing
  config.
- **Opt-in pip package listing**: `[output].include_pip_packages` or
  `--pip-list` also captures every Python package installed per image
  (off by default — can be large).
- **Cache retention control**: `[cache]` section (`keep_all`, `images`,
  `name_patterns`) or `--keep-cache` to keep pulled images cached locally
  instead of removing them after inspection, speeding up repeat runs.
  `images` patterns (both `[exclusions]` and `[cache]`) support glob
  matching against the full image reference, not just exact strings.
- **Config split**: secrets (`AAP_API_TOKEN`, `AAP_BASE_URL`) live in
  `.env` (never committed); everything else lives in committed
  `config.toml`.
- Unit test suite (pytest) covering config loading, filtering/exclusion
  logic, and report rendering; `ruff` + `pyright` clean.
