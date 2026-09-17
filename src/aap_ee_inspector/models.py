"""Pydantic models for the AAP Controller "execution environments" API.

Field shapes were derived by inspecting live responses from
GET /api/controller/v2/execution_environments/ on the AAP controller.

All models allow extra fields (`extra="allow"`) so that fields not seen in
our sample (e.g. a populated `organization`, or new fields added by AAP in
future versions) are preserved rather than silently dropped.
"""

from __future__ import annotations

import warnings
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

# The AAP API's "copy" field shadows BaseModel.copy(); the field name must
# match the API response, so we intentionally silence this warning (it fires
# at class-definition time below).
warnings.filterwarnings(
    "ignore", message='Field name "copy" .* shadows an attribute', category=UserWarning
)


class UserCapabilities(BaseModel):
    model_config = ConfigDict(extra="allow")

    edit: bool
    delete: bool
    # Matches the AAP API's field name exactly; shadows BaseModel.copy().
    copy: bool  # pyright: ignore[reportIncompatibleMethodOverride]


class UserRef(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: int
    username: str
    first_name: str
    last_name: str


class CredentialSummary(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: int
    name: str
    description: str
    kind: str
    cloud: bool
    kubernetes: bool
    credential_type_id: int


class SummaryFields(BaseModel):
    model_config = ConfigDict(extra="allow")

    user_capabilities: UserCapabilities
    created_by: UserRef | None = None
    modified_by: UserRef | None = None
    credential: CredentialSummary | None = None


class Related(BaseModel):
    model_config = ConfigDict(extra="allow")

    activity_stream: str
    unified_job_templates: str
    # Matches the AAP API's field name exactly; shadows BaseModel.copy().
    copy: str  # pyright: ignore[reportIncompatibleMethodOverride]
    created_by: str | None = None
    modified_by: str | None = None
    credential: str | None = None


class ExecutionEnvironment(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: int
    type: Literal["execution_environment"]
    url: str
    related: Related
    summary_fields: SummaryFields
    created: datetime
    modified: datetime
    name: str
    description: str
    organization: int | None = None
    image: str
    managed: bool
    credential: int | None = None
    pull: Literal["", "always", "missing"]


class ExecutionEnvironmentListResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    count: int
    next: str | None = None
    previous: str | None = None
    results: list[ExecutionEnvironment]


class ExecutionEnvironmentDetails(BaseModel):
    """Introspection details gathered by pulling and inspecting an EE image
    locally with podman (ansible-core version, python version, and the
    collections installed in the image).
    """

    model_config = ConfigDict(extra="allow")

    names: list[str]
    image: str
    ansible_core_version: str | None = None
    python_version: str | None = None
    jinja_version: str | None = None
    collections: dict[str, str] = {}
    # Only populated when config.toml's [output].include_pip_packages is true.
    python_packages: dict[str, str] = {}
    error: str | None = None
