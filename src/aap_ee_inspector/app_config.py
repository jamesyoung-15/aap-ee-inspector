"""Application configuration loaded from config.toml.

Unlike `Settings` (config.py), which holds secrets sourced from environment
variables / `.env`, this module holds non-secret settings that are safe to
commit to version control and tweak per-environment without touching code
(output paths, which fields to keep, and which images/EE names to skip).
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from pydantic import BaseModel, Field

DEFAULT_CONFIG_PATH = Path("config.toml")


class ApiConfig(BaseModel):
    """Settings related to the AAP controller API itself."""

    execution_environments_path: str = "/api/controller/v2/execution_environments/"


class OutputConfig(BaseModel):
    """Settings controlling where and what gets written to disk."""

    dir: Path = Path("outputs")
    # Fields to keep in execution_environments.json. None/omitted = all fields.
    fields: list[str] | None = None


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


class AppConfig(BaseModel):
    """Top-level application configuration, loaded from config.toml."""

    api: ApiConfig = Field(default_factory=ApiConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    exclusions: ExclusionsConfig = Field(default_factory=ExclusionsConfig)

    @property
    def output_file(self) -> Path:
        """Path to the raw AAP execution environment list."""
        return self.output.dir / "execution_environments.json"

    @property
    def details_output_file(self) -> Path:
        """Path to the per-image inspection details."""
        return self.output.dir / "execution_environment_details.json"

    @property
    def report_output_file(self) -> Path:
        """Path to the generated Markdown report."""
        return self.output.dir / "execution_environment_report.md"

    @property
    def output_fields(self) -> set[str] | None:
        """Output fields as a set, or None to include everything."""
        return set(self.output.fields) if self.output.fields else None


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> AppConfig:
    """Load AppConfig from a TOML file, falling back to defaults if missing."""
    if not path.exists():
        return AppConfig()

    with path.open("rb") as f:
        data = tomllib.load(f)

    return AppConfig.model_validate(data)
