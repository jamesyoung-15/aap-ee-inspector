# AAP EE Inspector

Fetches every execution environment (EE) available in Ansible Automation
Platform (AAP), then pulls each EE image locally with podman to inspect
what's actually installed inside it: `ansible-core` version, Python
version, `jinja` version, and every Ansible collection (with version)
baked into the image.

Output is written to `outputs/`, timestamped so each run gets its own file
rather than overwriting the last:

- `<timestamp>_execution_environments.json` — raw list of EEs from the AAP
  API (name, image, description).
- `<timestamp>_execution_environment_details.json` — per-image inspection
  results.
- `<timestamp>_execution_environment_report.md` — human-readable Markdown
  summary of the above, one section per image.

`aap-ee-inspect` and `aap-ee-report` automatically use the most recently
generated input file by default; pass `--input PATH` to target a specific
historical run instead. See [docs/README.md](docs/README.md) for a
breakdown of how the pipeline works internally.

## Requirements

- Python 3.13+ and [uv](https://docs.astral.sh/uv/)
- [podman](https://podman.io/), authenticated (`podman login`) against any
  registries the EE images live on
- An AAP controller API token

## Setup

Create a `.env` file in the project root (secrets, never committed):

```
AAP_API_TOKEN=<your-bearer-token>
AAP_BASE_URL=<aap-controller-hostname, no scheme>
```

Non-secret settings (output paths, output fields, and images/EE names to
skip during inspection) live in [`config.toml`](config.toml) — edit it
directly, no code changes needed. See
[docs/README.md](docs/README.md#configuration-app_configpy--configtoml)
for details.

Install dependencies:

```bash
uv sync
```

## Usage

Run the full pipeline (fetch, inspect, report):

```bash
uv run task all
```

Or run each stage individually:

```bash
uv run task fetch     # -> outputs/<timestamp>_execution_environments.json
uv run task inspect   # -> outputs/<timestamp>_execution_environment_details.json (slow: pulls every unique image)
uv run task report    # -> outputs/<timestamp>_execution_environment_report.md
```

Equivalent direct commands (without `task`):

```bash
uv run aap-ee-fetch
uv run aap-ee-inspect
uv run aap-ee-report
```

To limit inspection/reporting to specific EEs without editing
`config.toml`, pass `--only` with a comma-separated list of exact names or
glob patterns:

```bash
uv run aap-ee-inspect --only "amfam_default:1.21,vmware_env:*"
uv run aap-ee-report --only "amfam_default:1.21,vmware_env:*"

# via task (note the -- separator)
uv run task inspect -- --only "amfam_default:1.21,vmware_env:*"
uv run task report -- --only "amfam_default:1.21,vmware_env:*"
```

To re-run a stage against a specific past run's output instead of the
latest, pass `--input`:

```bash
uv run aap-ee-inspect --input outputs/20260101T120000_execution_environments.json
uv run aap-ee-report --input outputs/20260101T120000_execution_environment_details.json
```

## Development

```bash
uv run task lint      # ruff check
uv run task format    # ruff format
uv run task test      # pytest
```
