# Testing

Basic unit tests for sanity check for essential functions, full integration tests with container images not included.

Run with:

```bash
uv run task test
# or
uv run pytest
```

Covered:

- `filters.py` — glob matching and CLI arg parsing helpers.
- `app_config.py` — config.toml loading and defaults.
- `inspect_execution_environments.py` — version/collection output parsing,
  exclusion matching, and image grouping (no actual podman subprocess calls).
- `generate_report.py` — Markdown rendering and `--only` filtering.

Not covered (verify manually/ad-hoc against real EEs instead):

- Actual `podman pull` / `podman run` / `podman rmi` behavior.
- End-to-end pipeline runs against the live AAP API.

For manual verification, run against a single EE or small subset with
`--only`, e.g.:

```bash
uv run aap-ee-inspect --only "amfam_default:1.21"
uv run aap-ee-report --only "amfam_default:1.21"
```
