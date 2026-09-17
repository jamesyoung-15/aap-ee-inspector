# Architecture

This tool is a 3-stage pipeline. Each stage writes into (and, for stages 2
and 3, reads from) a shared **run directory**, so all output from a single
end-to-end run lives together in one place.

```
main.py                          inspect_execution_environments.py       generate_report.py
  (AAP API)                        (podman/docker pull/run per image)      (JSON -> Markdown)
     |                                      |                                      |
     v                                      v                                      v
outputs/<timestamp>/execution_environments.json
                     execution_environment_details.json   <- written into the same dir
                     execution_environment_report.md       <- written into the same dir
```

## Run directories

Every `aap-ee-fetch` run creates a new directory:
`outputs/<YYYYMMDDTHHMMSS>/`, e.g. `outputs/20260917T141049/`. All output
from that run — the fetched EE list, inspection details, and the generated
report — lands in that same directory, so it's immediately obvious which
files belong to which run (no more guessing which timestamp-prefixed file
goes with which). This also keeps a history of past runs for comparison
without overwriting anything.

`aap-ee-inspect` and `aap-ee-report` each need an input file from the
previous stage, and write their own output into the **same run directory**
the input came from. By default they auto-select the file from the **most
recently generated** run directory that has one (falling back to an older
run if the newest one hasn't gotten that far yet — e.g. a run that's only
done `fetch` so far). To target a specific historical run instead, pass
`--input` with either the run directory or a direct path to the file inside
it:

```
aap-ee-inspect --input outputs/20260101T120000
aap-ee-report --input outputs/20260101T120000
# or, equivalently, pointing directly at the file:
aap-ee-inspect --input outputs/20260101T120000/execution_environments.json
aap-ee-report --input outputs/20260101T120000/execution_environment_details.json
```

## Stage 1: `main.py` (entry point: `aap-ee-fetch`)

Fetches every execution environment from the AAP controller API
(`GET /api/controller/v2/execution_environments/`), following pagination via
the `next` link until exhausted.

- Auth: Bearer token from `Settings` (see `config.py`), loaded from `.env`.
- TLS verification is disabled (`verify=False`) since the AAP host uses an
  internal/self-signed certificate not present in the default trust store.
- Output fields are trimmed to `config.toml`'s `[output].fields` (currently
  `name`, `image`, `description`) before writing to a new
  `outputs/<timestamp>/execution_environments.json`. Remove/comment out
  `fields` in `config.toml` to dump full records instead.

## Stage 2: `inspect_execution_environments.py` (entry point: `aap-ee-inspect`)

For each **unique image** referenced in the input file (multiple EE names
can point at the same image), excluding any matched by `config.toml`'s
`[exclusions]` section, this stage:

1. `<engine> pull <image>`
2. Runs `ansible --version` and `ansible-galaxy collection list --format json`
   (and, if `--pip-list` is enabled, `pip list --format json`) inside a
   throwaway container in a single `<engine> run --rm` invocation.
3. Parses ansible-core / Python / jinja versions out of the `ansible --version`
   text output via regex (there is no JSON output mode for `--version`).
4. Parses and flattens the collection-list JSON (and pip-list JSON, if
   enabled) into `{name: version}` dicts.
5. `<engine> rmi <image>` to reclaim disk space (images can be several GB each),
   unless the image is configured to be kept — see
   [Keeping images cached](#keeping-images-cached-cache) below.

Where `<engine>` is `config.toml`'s `[container].engine` (`podman` by
default). Podman and Docker use compatible `pull`/`run --rm`/`rmi` command
syntax, so this is a drop-in swap:

```toml
[container]
engine = "docker"  # or "podman" (default)
```

Docker support was implemented as a straightforward swap of the CLI binary
name rather than exhaustively tested end-to-end (development environment
didn't have a running Docker daemon at the time); the failure path was
verified though — with the Docker daemon not running, `pull_image` correctly
invokes `docker pull`, receives Docker's connection error, and records it
as a per-image `error` exactly like a podman failure would, without
crashing the run.

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
images = ["*/pinned-image:1.0", "registry.example.com/some/pinned@sha256:..."]
name_patterns = ["rhel6_env:*", "Minimal execution environment"]
```

- `images` — glob patterns (`fnmatch` syntax) matched against the full
  image reference; an image is skipped if it matches *any* pattern here.
  Plain strings with no glob characters (`*`, `?`, `[...]`) work too and
  match only that exact image.
- `name_patterns` — glob patterns (`fnmatch` syntax) matched against EE
  names; an image is skipped if *any* of its associated EE names match
  *any* pattern.

Excluded images are skipped entirely (never pulled) and printed as a summary
count at the start of the inspect run.

### Keeping images cached (`[cache]`)

By default every image is removed (`<engine> rmi`) immediately after
inspection to reclaim disk space. Since pulling is the slow part of a run
(inspection itself is fast), you can opt into keeping some or all images
cached locally so re-runs skip the pull step entirely for images already
present:

```toml
[cache]
keep_all = false               # true = never remove any image
images = []                    # glob patterns (or exact refs) to always keep
name_patterns = ["amfam_default:*"]  # glob patterns matched against EE names
```

- `keep_all = true` keeps every image, unconditionally.
- `images`/`name_patterns` use the exact same `fnmatch`-glob semantics as
  `[exclusions]` (see above), but for retention instead of skipping — e.g.
  `images = ["*/amfam_default:*"]` keeps every version of that EE family
  cached without spelling out the full registry path for each tag.
- Per-run override without editing `config.toml`: `aap-ee-inspect --keep-cache`
  (forces `keep_all` behavior for that invocation only).

**Disk space guidance**: based on querying the GitLab container registry
directly for compressed layer sizes across the ~23 actively-inspected EE
images (excluding config-excluded ones), and cross-checking against
observed on-disk sizes (uncompressed images run roughly 3.9-4.1x their
compressed registry size for these RHEL/Python-based images), keeping
**every currently-inspectable image cached costs roughly 43-45GB**. Layer
deduplication (shared base layers across `amfam_default:*` version tags,
handled automatically by podman/Docker) is the main reason this is much
less than the naive per-image sum (~65GB) would suggest.

If running podman via `podman machine` on macOS, note the VM has its own
disk allocation independent of the host Mac's free space (check with
`podman machine list`; default is commonly 100GB) — that's the actual
constraint to watch, not the host disk.

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

### Optional: pip package listing (`--pip-list`)

By default, only Ansible collections are recorded. To also capture every
Python package installed in each EE image (via `pip list --format json`),
either:

```toml
# config.toml — persistent, applies to every run
[output]
include_pip_packages = true
```

```
# or per-run, overriding config.toml for just this invocation
aap-ee-inspect --pip-list
```

This is opt-in because the package list can be large (100+ transitive
dependencies per image is typical) and noticeably increases output file
size; it's most useful for occasional deep-dives rather than every routine
run.

## Stage 3: `generate_report.py` (entry point: `aap-ee-report`)

Renders the latest (or `--input`-specified) execution environment details
file into `execution_environment_report.md` in that same run directory —
one `##` section per unique image, with collections listed in a fenced code
block (one per line, sorted alphabetically). If pip package data was
collected, it's rendered in a second code block per image. Successful
inspections are listed first; failed/skipped images are grouped in a
trailing section.

## Stage 4 (optional): `publish_confluence_report.py` (entry point: `aap-ee-publish`)

Publishes the latest (or `--input`-specified) execution environment details
to a Confluence page, entirely separate from the run-directory pipeline
above (it reads `execution_environment_details.json` directly, the same
way `aap-ee-report` does, but doesn't write anything into the run
directory itself).

1. Reads `config.toml`'s `[confluence].page_id` and `.env`'s
   `CONFLUENCE_BASE_URL` / `CONFLUENCE_EMAIL` / `CONFLUENCE_API_TOKEN`.
2. Renders `templates/confluence_intro.md` (via Jinja2, then Markdown → HTML)
   for the optional hand-written intro section. If the file doesn't exist,
   the intro is skipped and only the report + footnote are published. The
   file is gitignored (local-only, like `.env`) — copy
   `templates/confluence_intro.md.example` to get started.
3. Renders the report body directly into Confluence **storage format**
   XHTML (`confluence_report.py`) — a separate renderer from the Markdown
   one in `generate_report.py`, so collection listings become native
   `<ac:structured-macro ac:name="code">` blocks (proper syntax-highlight-off
   code blocks with a copy button) rather than a lossy Markdown-to-HTML
   conversion.
4. Renders an "Excluded Execution Environments" footnote from
   `config.toml`'s `[exclusions].name_patterns`.
5. `GET`s the current page to read its version number (Confluence's update
   API requires the exact next version number for its optimistic-concurrency
   check — there's no "auto-increment" option), then `PUT`s the assembled
   intro + report + footnote as the new page body.

This does a **full-page replace** every run, matching how the report
itself is a full re-dump each time — there's no attempt to diff/patch the
live page. Crucially, the intro (when present) is sourced from the local
`templates/confluence_intro.md` file, not scraped from the live page, so
there's no fragile "find where the auto-generated section starts" logic
(an earlier prototype tried an HTML-comment marker for this and found
Confluence's markdown-to-storage-format conversion silently strips HTML
comments — storage-format-native rendering with a locally-sourced intro
avoids that problem entirely).

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

- **`config.py` (`Settings`, `ConfluenceSettings`)** — secrets, sourced from
  environment variables / `.env`: `AAP_API_TOKEN`, `AAP_BASE_URL`, and
  (only needed for `aap-ee-publish`) `CONFLUENCE_BASE_URL`,
  `CONFLUENCE_EMAIL`, `CONFLUENCE_API_TOKEN`. Never committed.
- **`app_config.py` (`AppConfig`)** — everything else: the AAP API path,
  output directory/filenames, which output fields to keep, inspect-stage
  exclusions, image cache retention, and the Confluence page ID to publish
  to. Sourced from `config.toml` in the repo root, which *is* meant to be
  committed and edited directly. If `config.toml` is missing,
  `load_config()` falls back to built-in defaults rather than erroring.

## Known limitations

- **Platform emulation**: on non-x86_64 hosts (e.g. Apple Silicon), pulling
  `linux/amd64` images requires QEMU emulation, which is slower than native
  execution but works transparently through podman/docker.
- Known-unreachable/unsupported images (registry auth gaps, old
  `ansible-galaxy` versions) should be added to `config.toml`'s
  `[exclusions]` rather than left to fail every run.
- **Docker support is unverified end-to-end**: the `[container].engine`
  toggle is a straightforward CLI-binary swap (podman and Docker share
  compatible `pull`/`run --rm`/`rmi` syntax), but has only been confirmed to
  invoke the right binary and fail gracefully when the Docker daemon isn't
  running — not a full successful pull/inspect/cleanup cycle against a real
  Docker daemon.
