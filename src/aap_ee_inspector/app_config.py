"""Application configuration loaded from config.toml.

Unlike `Settings` (config.py), which holds secrets sourced from environment
variables / `.env`, this module holds non-secret settings that are safe to
commit to version control and tweak per-environment without touching code
(output paths, which fields to keep, and which images/EE names to skip).
"""

from __future__ import annotations

import tomllib
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from aap_ee_inspector.filters import matches_any

DEFAULT_CONFIG_PATH = Path("config.toml")

# Run directory timestamp format: sorts lexicographically in chronological
# order, so the max() of directory names is always the latest run.
TIMESTAMP_FORMAT = "%Y%m%dT%H%M%S"

# Plain filenames used within each run directory (outputs/<timestamp>/).
EXECUTION_ENVIRONMENTS_FILENAME = "execution_environments.json"
DETAILS_FILENAME = "execution_environment_details.json"
REPORT_FILENAME = "execution_environment_report.md"


class ApiConfig(BaseModel):
    """Settings related to the AAP controller API itself."""

    execution_environments_path: str = "/api/controller/v2/execution_environments/"


class OutputConfig(BaseModel):
    """Settings controlling where and what gets written to disk."""

    dir: Path = Path("outputs")
    # Fields to keep in execution_environments.json. None/omitted = all fields.
    fields: list[str] | None = None
    # Opt-in: also run `pip list` inside each EE image during inspection.
    # Off by default since the package list can be very large (hundreds of
    # transitive dependencies) and significantly bloats the output files.
    include_pip_packages: bool = False


class ContainerConfig(BaseModel):
    """Settings for the container engine used to pull/run/remove EE images."""

    engine: Literal["podman", "docker"] = "podman"


class ExclusionsConfig(BaseModel):
    """Images/EEs to skip during the inspect stage.

    images: glob patterns (fnmatch syntax) matched against the full image
        reference; an image is skipped if it matches any pattern here (e.g.
        "*/amfam_default:1.*" or an exact full reference). Exact strings
        with no glob characters work too, since fnmatch falls back to a
        literal match when there's nothing to expand.
    name_patterns: glob patterns (fnmatch syntax) matched against EE names;
        an image is skipped if any of its associated EE names match any
        pattern (e.g. "rhel6_env:*" to skip every tag of that EE family).
    """

    images: list[str] = Field(default_factory=list)
    name_patterns: list[str] = Field(default_factory=list)


class CacheConfig(BaseModel):
    """Controls whether pulled EE images are removed after inspection or kept.

    By default, every image is pulled, inspected, and removed again to
    reclaim disk space. This section lets you opt into keeping some or all
    images cached locally to speed up subsequent runs, at the cost of disk
    space (roughly 1-2GB per unique image, though shared base layers between
    EE version tags reduce the actual total).

    keep_all: if true, never remove any image after inspection.
    images: glob patterns (fnmatch syntax) matched against the full image
        reference; an image is kept cached if it matches any pattern here,
        regardless of keep_all. Exact strings with no glob characters work
        too (e.g. "*/amfam_default:1.*" or a full literal reference).
    name_patterns: glob patterns (fnmatch syntax) matched against EE names;
        an image is kept cached if any of its associated EE names match any
        pattern here.
    """

    keep_all: bool = False
    images: list[str] = Field(default_factory=list)
    name_patterns: list[str] = Field(default_factory=list)

    def should_keep(self, image: str, names: list[str]) -> bool:
        """Return True if `image` should be kept cached rather than removed."""
        if self.keep_all:
            return True
        if matches_any(image, self.images):
            return True
        return any(matches_any(name, self.name_patterns) for name in names)


class AppConfig(BaseModel):
    """Top-level application configuration, loaded from config.toml."""

    api: ApiConfig = Field(default_factory=ApiConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    container: ContainerConfig = Field(default_factory=ContainerConfig)
    exclusions: ExclusionsConfig = Field(default_factory=ExclusionsConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)

    def new_run_dir(self, timestamp: str) -> Path:
        """Path to a new run directory: outputs/<timestamp>/."""
        return self.output.dir / timestamp

    def latest_run_dir(self) -> Path | None:
        """Most recent existing run directory, or None if none exist."""
        return find_latest_run_dir(self.output.dir)

    def latest_output_file(self) -> Path | None:
        """execution_environments.json in the most recent run directory, if any."""
        return find_latest_file_in_run(self.output.dir, EXECUTION_ENVIRONMENTS_FILENAME)

    def latest_details_output_file(self) -> Path | None:
        """execution_environment_details.json in the most recent run directory, if any."""
        return find_latest_file_in_run(self.output.dir, DETAILS_FILENAME)

    @property
    def output_fields(self) -> set[str] | None:
        """Output fields as a set, or None to include everything."""
        return set(self.output.fields) if self.output.fields else None


def current_timestamp() -> str:
    """Return the current time formatted for use in output filenames."""
    return datetime.now().strftime(TIMESTAMP_FORMAT)


def is_run_dir_name(name: str) -> bool:
    """Return True if `name` looks like a run directory timestamp we generated."""
    try:
        datetime.strptime(name, TIMESTAMP_FORMAT)
    except ValueError:
        return False
    return True


def list_run_dirs(output_dir: Path) -> list[Path]:
    """List run directories under `output_dir`, sorted oldest to newest.

    Non-run-directory entries (anything not matching TIMESTAMP_FORMAT) are
    ignored, so stray files or manually-created directories don't interfere.
    """
    if not output_dir.exists():
        return []

    return sorted(p for p in output_dir.iterdir() if p.is_dir() and is_run_dir_name(p.name))


def find_latest_run_dir(output_dir: Path) -> Path | None:
    """Find the most recently generated run directory under `output_dir`."""
    run_dirs = list_run_dirs(output_dir)
    return run_dirs[-1] if run_dirs else None


def find_latest_file_in_run(output_dir: Path, filename: str) -> Path | None:
    """Find `filename` inside the most recent run directory that contains it.

    Searches run directories from newest to oldest and returns the first
    match, so a run that only did `fetch` (no `inspect` yet) is skipped when
    looking for a details file, falling back to an older run that has one.
    """
    for run_dir in reversed(list_run_dirs(output_dir)):
        candidate = run_dir / filename
        if candidate.exists():
            return candidate

    return None


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> AppConfig:
    """Load AppConfig from a TOML file, falling back to defaults if missing."""
    if not path.exists():
        return AppConfig()

    with path.open("rb") as f:
        data = tomllib.load(f)

    return AppConfig.model_validate(data)
