"""Configuration loading with path and schema validation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

import yaml
from pydantic import BaseModel, ValidationError

from .models import CapabilitySpec, ModificationPolicy, ProjectManifest
from .resources import resource_root


class ConfigurationError(ValueError):
    """Raised when a project or bundled specification is invalid."""


ModelT = TypeVar("ModelT", bound=BaseModel)


@dataclass(frozen=True)
class LoadedProject:
    manifest_path: Path
    manifest: ProjectManifest
    repository: Path
    working_directory: Path
    capabilities: CapabilitySpec
    modification_policy: ModificationPolicy
    protocol_brief: dict[str, Any]


def _read_yaml(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return yaml.safe_load(handle)
    except OSError as exc:
        raise ConfigurationError(f"cannot read {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"invalid YAML in {path}: {exc}") from exc


def _load_model(path: Path, model_type: type[ModelT]) -> ModelT:
    try:
        return model_type.model_validate(_read_yaml(path))
    except ValidationError as exc:
        raise ConfigurationError(f"invalid configuration in {path}: {exc}") from exc


def load_project(
    manifest_path: str | Path,
    *,
    package_root: Path | None = None,
) -> LoadedProject:
    """Load a target manifest and the v0.1 bundled policy files."""

    path = Path(manifest_path).expanduser().resolve()
    root = package_root or resource_root()
    manifest = _load_model(path, ProjectManifest)

    repository = manifest.repository.expanduser()
    if not repository.is_absolute():
        repository = path.parent / repository
    repository = repository.resolve()
    if not repository.is_dir():
        raise ConfigurationError(f"repository is not a directory: {repository}")

    requested_working_directory = manifest.working_directory
    if requested_working_directory.is_absolute():
        working_directory = requested_working_directory.resolve()
    else:
        working_directory = (repository / requested_working_directory).resolve()
    try:
        working_directory.relative_to(repository)
    except ValueError as exc:
        raise ConfigurationError("working_directory must stay inside repository") from exc
    if not working_directory.is_dir():
        raise ConfigurationError(f"working_directory is not a directory: {working_directory}")

    capabilities = _load_model(root / "spec" / "capabilities.yaml", CapabilitySpec)
    policy = _load_model(root / "spec" / "modification-policy.yaml", ModificationPolicy)
    protocol_path = root / "spec" / "protocols" / f"{manifest.protocol}.yaml"
    protocol_brief = _read_yaml(protocol_path)
    if not isinstance(protocol_brief, dict):
        raise ConfigurationError(f"protocol brief must be a mapping: {protocol_path}")

    return LoadedProject(
        manifest_path=path,
        manifest=manifest,
        repository=repository,
        working_directory=working_directory,
        capabilities=capabilities,
        modification_policy=policy,
        protocol_brief=protocol_brief,
    )
