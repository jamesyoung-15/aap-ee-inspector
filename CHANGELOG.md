# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
- **Timestamped outputs**: every run writes a new
  `outputs/<timestamp>_<filename>` file rather than overwriting the last;
  `aap-ee-inspect`/`aap-ee-report` auto-select the most recent matching
  input file by default, or `--input PATH` to target a specific past run.
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
