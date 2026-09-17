# AAP EE Inspector

Fetches every execution environment (EE) available in Ansible Automation
Platform (AAP), then pulls each EE image locally with podman or docker to
inspect what's actually installed inside it: `ansible-core` version, Python
version, `jinja` version, every Ansible collection (with version) baked
into the image, and optionally every pip-installed Python package.

Output is written to `outputs/<timestamp>/`, one directory per run, so all
files from a single end-to-end run live together instead of scattering
across separately-timestamped files:

- `outputs/<timestamp>/execution_environments.json` — raw list of EEs from
  the AAP API (name, image, description).
- `outputs/<timestamp>/execution_environment_details.json` — per-image
  inspection results.
- `outputs/<timestamp>/execution_environment_report.md` — human-readable
  Markdown summary of the above, one section per image.

`aap-ee-inspect` and `aap-ee-report` automatically use the most recently
generated run directory by default (writing their own output into that
same directory); pass `--input PATH` (a run directory or a file inside one)
to target a specific historical run instead. See
[docs/README.md](docs/README.md) for a breakdown of how the pipeline works
internally.

## Requirements

- Python 3.13+ and [uv](https://docs.astral.sh/uv/)
- [podman](https://podman.io/) (default) or [docker](https://www.docker.com/),
  authenticated (`podman login` / `docker login`) against any registries the
  EE images live on. Set `[container].engine` in `config.toml` to switch.
- An AAP controller API token

## Setup

Create a `.env` file in the project root (secrets, never committed):

```env
AAP_API_TOKEN=<your-bearer-token>
AAP_BASE_URL=<aap-controller-hostname, no scheme>

# Optional — only needed for `aap-ee-publish`
CONFLUENCE_BASE_URL=https://yourcompany.atlassian.net/wiki
CONFLUENCE_EMAIL=you@yourcompany.com
CONFLUENCE_API_TOKEN=<atlassian api token, see id.atlassian.com/manage-profile/security/api-tokens>
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
uv run task fetch     # -> outputs/<timestamp>/execution_environments.json
uv run task inspect   # -> outputs/<timestamp>/execution_environment_details.json (slow: pulls every unique image)
uv run task report    # -> outputs/<timestamp>/execution_environment_report.md
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
latest, pass `--input` with the run directory (or a file inside it):

```bash
uv run aap-ee-inspect --input outputs/20260101T120000
uv run aap-ee-report --input outputs/20260101T120000
```

To also capture every pip-installed Python package per EE image (off by
default — the package list can be large), pass `--pip-list` or set
`[output].include_pip_packages = true` in `config.toml`:

```bash
uv run aap-ee-inspect --pip-list
```

By default, every pulled image is removed after inspection to reclaim disk
space. To keep images cached locally and speed up subsequent runs, pass
`--keep-cache` (keeps everything) or configure `[cache]` in `config.toml`
to keep specific images/patterns:

```bash
uv run aap-ee-inspect --keep-cache
```

```toml
[cache]
keep_all = false
images = []
name_patterns = ["amfam_default:*"]  # keep only this EE family cached
```

Rough disk cost if keeping everything cached: **~43-45GB** for the current
set of actively-inspected EE images (measured via registry manifest sizes
with layer deduplication accounted for — see
[docs/README.md](docs/README.md#keeping-images-cached-cache) for the
methodology). If you use `podman machine` on macOS, its VM has its own disk
allocation separate from your Mac's free space — check with
`podman machine list`.

### Publishing to Confluence

`aap-ee-publish` takes the latest generated report and publishes it to a
Confluence page. Requires the `CONFLUENCE_*` variables in `.env` and
`[confluence].page_id` set in `config.toml`:

```toml
[confluence]
page_id = "19074352100"  # find it in the page URL
```

```bash
uv run aap-ee-publish
uv run aap-ee-publish --only "amfam_default:1.21,vmware_env:*"
uv run aap-ee-publish --input outputs/20260101T120000
```

**Optional intro**: if `templates/confluence_intro.md` exists, its content is
rendered as the hand-written intro above the report on the Confluence page.
The file is gitignored (local-only, like `.env`), so you can edit it freely
without it appearing in commits. To get started, copy the example:

```bash
cp templates/confluence_intro.md.example templates/confluence_intro.md
# then edit templates/confluence_intro.md as needed
```

If the file doesn't exist, `aap-ee-publish` runs fine and publishes
report-only (no intro).

## Development

```bash
uv run task lint      # ruff check
uv run task format    # ruff format
uv run task test      # pytest
```
