"""带路径与 Schema 校验的配置加载。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

import yaml
from pydantic import BaseModel, ValidationError

from .models import CapabilitySpec, ModificationPolicy, ProjectManifest
from .resources import resource_root


class ConfigurationError(ValueError):
    """项目清单、内置规范或路径边界不合法时抛出。"""


ModelT = TypeVar("ModelT", bound=BaseModel)


@dataclass(frozen=True)
class ResolvedVerificationFixture:
    """解析后的隐藏验证文件。

    source 是 Controller 仓库中的真实文件；destination 是临时 worktree 内
    的相对路径。二者分离，确保 Agent 无法从目标仓库读取 oracle。
    """

    source: Path
    destination: Path


@dataclass(frozen=True)
class LoadedProject:
    """一次运行所需的已验证、绝对路径化配置。"""

    manifest_path: Path
    manifest: ProjectManifest
    repository: Path
    working_directory: Path
    capabilities: CapabilitySpec
    modification_policy: ModificationPolicy
    protocol_brief: dict[str, Any]
    verification_fixtures: tuple[ResolvedVerificationFixture, ...] = ()

    def agent_manifest(self) -> dict[str, Any]:
        """返回允许披露给三个 Agent 的项目视图。

        capability_checks、verification_fixtures 和 experiment 都属于
        Controller/评测器信息。它们若进入 Prompt，会泄漏隐藏测试位置、
        命令或实验身份，因此必须在统一入口处删除。
        """

        return self.manifest.model_dump(
            mode="json",
            exclude={"capability_checks", "verification_fixtures", "experiment"},
        )


def _read_yaml(path: Path) -> Any:
    """统一读取 YAML，并把文件/YAML 异常转换成 ConfigurationError。"""

    try:
        with path.open("r", encoding="utf-8") as handle:
            return yaml.safe_load(handle)
    except OSError as exc:
        raise ConfigurationError(f"cannot read {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"invalid YAML in {path}: {exc}") from exc


def _load_model(path: Path, model_type: type[ModelT]) -> ModelT:
    """读取 YAML 后立即执行严格 Pydantic 校验。"""

    try:
        return model_type.model_validate(_read_yaml(path))
    except ValidationError as exc:
        raise ConfigurationError(f"invalid configuration in {path}: {exc}") from exc


def load_project(
    manifest_path: str | Path,
    *,
    package_root: Path | None = None,
) -> LoadedProject:
    """加载目标 manifest、能力规范、修改策略和协议简介。

    该函数也是配置安全边界：所有用于执行命令或复制 fixture 的路径都会
    在此解析并验证，工作流后续只使用 LoadedProject 中的绝对路径。
    """

    path = Path(manifest_path).expanduser().resolve()
    root = package_root or resource_root()
    manifest = _load_model(path, ProjectManifest)

    repository = manifest.repository.expanduser()
    if not repository.is_absolute():
        repository = path.parent / repository
    repository = repository.resolve()
    if not repository.is_dir():
        raise ConfigurationError(f"repository is not a directory: {repository}")

    # working_directory 可以指向单仓库中的子模块，但绝不能逃离 repository。
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
    # Python 控制器不硬编码 Raft 概念；协议知识由 protocol YAML 提供。
    protocol_path = root / "spec" / "protocols" / f"{manifest.protocol}.yaml"
    protocol_brief = _read_yaml(protocol_path)
    if not isinstance(protocol_brief, dict):
        raise ConfigurationError(f"protocol brief must be a mapping: {protocol_path}")

    fixtures: list[ResolvedVerificationFixture] = []
    destinations: set[Path] = set()
    for fixture in manifest.verification_fixtures:
        source = fixture.source.expanduser()
        if not source.is_absolute():
            source = path.parent / source
        source = source.resolve()
        if not source.is_file():
            raise ConfigurationError(f"verification fixture is not a file: {source}")
        # 隐藏 fixture 如果位于目标仓库中，即使 Prompt 不披露路径，Agent
        # 仍可能通过 list/read 工具发现它，因此配置阶段直接拒绝。
        try:
            source.relative_to(repository)
        except ValueError:
            pass
        else:
            raise ConfigurationError(
                "verification fixtures must be outside the Agent-visible target repository"
            )
        if fixture.destination in destinations:
            raise ConfigurationError(
                f"duplicate verification fixture destination: {fixture.destination}"
            )
        destinations.add(fixture.destination)
        fixtures.append(
            ResolvedVerificationFixture(
                source=source,
                destination=fixture.destination,
            )
        )

    return LoadedProject(
        manifest_path=path,
        manifest=manifest,
        repository=repository,
        working_directory=working_directory,
        capabilities=capabilities,
        modification_policy=policy,
        protocol_brief=protocol_brief,
        verification_fixtures=tuple(fixtures),
    )
