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

# Filename timestamp format: sorts lexicographically in chronological order.
TIMESTAMP_FORMAT = "%Y%m%dT%H%M%S"

EXECUTION_ENVIRONMENTS_SUFFIX = "execution_environments.json"
DETAILS_SUFFIX = "execution_environment_details.json"
REPORT_SUFFIX = "execution_environment_report.md"


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

    images: exact image references to always skip (e.g. pinned digests that
        require registry auth we don't have).
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
    images: exact image references to always keep cached, regardless of
        keep_all.
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
        if image in self.images:
            return True
        return any(matches_any(name, self.name_patterns) for name in names)


class AppConfig(BaseModel):
    """Top-level application configuration, loaded from config.toml."""

    api: ApiConfig = Field(default_factory=ApiConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    container: ContainerConfig = Field(default_factory=ContainerConfig)
    exclusions: ExclusionsConfig = Field(default_factory=ExclusionsConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)

    def new_output_file(self, timestamp: str) -> Path:
        """Path for a new, timestamped execution_environments.json."""
        return self.output.dir / f"{timestamp}_{EXECUTION_ENVIRONMENTS_SUFFIX}"

    def new_details_output_file(self, timestamp: str) -> Path:
        """Path for a new, timestamped execution_environment_details.json."""
        return self.output.dir / f"{timestamp}_{DETAILS_SUFFIX}"

    def new_report_output_file(self, timestamp: str) -> Path:
        """Path for a new, timestamped execution_environment_report.md."""
        return self.output.dir / f"{timestamp}_{REPORT_SUFFIX}"

    def latest_output_file(self) -> Path | None:
        """Most recent existing execution_environments.json, or None if none exist."""
        return find_latest_file(self.output.dir, EXECUTION_ENVIRONMENTS_SUFFIX)

    def latest_details_output_file(self) -> Path | None:
        """Most recent existing execution_environment_details.json, or None if none exist."""
        return find_latest_file(self.output.dir, DETAILS_SUFFIX)

    @property
    def output_fields(self) -> set[str] | None:
        """Output fields as a set, or None to include everything."""
        return set(self.output.fields) if self.output.fields else None


def current_timestamp() -> str:
    """Return the current time formatted for use in output filenames."""
    return datetime.now().strftime(TIMESTAMP_FORMAT)


def find_latest_file(directory: Path, suffix: str) -> Path | None:
    """Find the most recently generated `<timestamp>_<suffix>` file in `directory`.

    Filenames sort lexicographically in chronological order (the timestamp
    format has no ambiguity), so the max() of matching names is the latest.
    Returns None if the directory doesn't exist or has no matching files.
    """
    if not directory.exists():
        return None

    matches = sorted(directory.glob(f"*_{suffix}"))
    return matches[-1] if matches else None


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> AppConfig:
    """Load AppConfig from a TOML file, falling back to defaults if missing."""
    if not path.exists():
        return AppConfig()

    with path.open("rb") as f:
        data = tomllib.load(f)

    return AppConfig.model_validate(data)
