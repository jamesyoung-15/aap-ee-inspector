# Architecture

This tool is a 3-stage pipeline. Each stage reads the previous stage's output
from `outputs/` and can be re-run independently.

```
main.py                          inspect_execution_environments.py       generate_report.py
  (AAP API)                        (podman pull/run per image)             (JSON -> Markdown)
     |                                      |                                      |
     v                                      v                                      v
outputs/execution_environments.json -> outputs/execution_environment_details.json -> outputs/execution_environment_report.md
```

## Stage 1: `main.py` (entry point: `aap-ee-fetch`)

Fetches every execution environment from the AAP controller API
(`GET /api/controller/v2/execution_environments/`), following pagination via
the `next` link until exhausted.

- Auth: Bearer token from `Settings` (see `config.py`), loaded from `.env`.
- TLS verification is disabled (`verify=False`) since the AAP host uses an
  internal/self-signed certificate not present in the default trust store.
- Output fields are trimmed to `config.toml`'s `[output].fields` (currently
  `name`, `image`, `description`) before writing to
  `outputs/execution_environments.json`. Remove/comment out `fields` in
  `config.toml` to dump full records instead.

## Stage 2: `inspect_execution_environments.py` (entry point: `aap-ee-inspect`)

For each **unique image** referenced in stage 1's output (multiple EE names
can point at the same image), excluding any matched by `config.toml`'s
`[exclusions]` section, this stage:

1. `podman pull <image>`
2. Runs `ansible --version` and `ansible-galaxy collection list --format json`
   inside a throwaway container in a single `podman run --rm` invocation.
3. Parses ansible-core / Python / jinja versions out of the `ansible --version`
   text output via regex (there is no JSON output mode for `--version`).
4. Parses and flattens the collection-list JSON into a single
   `{name: version}` dict.
5. `podman rmi <image>` to reclaim disk space (images can be several GB each).

Failures at any step (pull or inspect) are recorded on that image's result
entry (`error` field) rather than aborting the whole batch — one bad image
shouldn't block the rest.

### Excluding images (`config.toml`)

Some EEs are known-unreachable (e.g. `registry.redhat.io` images without
local registry auth) or unsupported (e.g. old `ansible-galaxy` versions that
don't support `collection list`). Rather than let these show up as noisy
`error` entries every run, list them in `config.toml`:

```toml
[exclusions]
images = ["registry.example.com/some/pinned@sha256:..."]
name_patterns = ["rhel6_env:*", "Minimal execution environment"]
```

- `images` — exact image reference matches.
- `name_patterns` — glob patterns (`fnmatch` syntax) matched against EE
  names; an image is skipped if *any* of its associated EE names match
  *any* pattern.

Excluded images are skipped entirely (never pulled) and printed as a summary
count at the start of the inspect run.

### Filtering to specific EEs (`--only`)

Both `aap-ee-inspect` and `aap-ee-report` accept an optional `--only` flag
for ad-hoc, one-off filtering without editing `config.toml`:

```
aap-ee-inspect --only "amfam_default:1.21,vmware_env:*"
aap-ee-report --only "amfam_default:1.21,vmware_env:*"
```

The value is a comma-separated list of glob patterns (`fnmatch` syntax)
matched against EE names. `--only` is applied *after* `config.toml`
exclusions — it narrows further, it doesn't override exclusions.

This is distinct from `[exclusions]` in `config.toml`: exclusions are
persistent, always-applied denylist entries (e.g. "this EE is permanently
unreachable"), while `--only` is a transient, per-invocation allowlist for
one-off runs (e.g. "I only care about these two EEs today").

**Known gotcha**: the bare `python3` binary in some EE images is *not*
necessarily the interpreter Ansible actually uses (multiple Pythons can be
installed). The Python version must be parsed from `ansible --version`'s
"python version = ..." line, not from a separate `python3 --version` call.

## Stage 3: `generate_report.py` (entry point: `aap-ee-report`)

Renders `outputs/execution_environment_details.json` into a single Markdown
file for quick human reference — one `##` section per unique image, with
collections listed in a fenced code block (one per line, sorted
alphabetically). Successful inspections are listed first; failed/skipped
images are grouped in a trailing section.

## Data models (`models.py`)

Two families of Pydantic models:

- `ExecutionEnvironment` / `ExecutionEnvironmentListResponse` — mirror the
  AAP API response shape (derived by inspecting live API responses; see
  `models.py`'s module docstring). All models use `extra="allow"` so
  unexpected/future API fields are preserved rather than dropped.
- `ExecutionEnvironmentDetails` — the podman-derived introspection result
  for a single image.

## Configuration (`app_config.py` + `config.toml`)

Two separate configuration sources, intentionally kept apart:

- **`config.py` (`Settings`)** — secrets, sourced from environment
  variables / `.env`: `AAP_API_TOKEN`, `AAP_BASE_URL`. Never committed.
- **`app_config.py` (`AppConfig`)** — everything else: the AAP API path,
  output directory/filenames, which output fields to keep, and inspect-stage
  exclusions. Sourced from `config.toml` in the repo root, which *is* meant
  to be committed and edited directly. If `config.toml` is missing,
  `load_config()` falls back to built-in defaults rather than erroring.

## Known limitations

- **Platform emulation**: on non-x86_64 hosts (e.g. Apple Silicon), pulling
  `linux/amd64` images requires QEMU emulation, which is slower than native
  execution but works transparently through podman.
- Known-unreachable/unsupported images (registry auth gaps, old
  `ansible-galaxy` versions) should be added to `config.toml`'s
  `[exclusions]` rather than left to fail every run.
