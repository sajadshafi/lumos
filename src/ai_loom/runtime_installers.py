"""Safe, extensible installers for AI runtime integrations."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import asdict, dataclass
from importlib import resources
from pathlib import Path
from typing import Any

from . import __version__
from .errors import ConfigError

MANIFEST_NAME = ".lumos-install.json"


@dataclass(frozen=True)
class InstallPlan:
    """One runtime installation decision, suitable for text or JSON output."""

    runtime: str
    detected: bool
    destination: str
    action: str
    reason: str
    restart_required: bool
    files: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["files"] = list(self.files)
        return data


@dataclass(frozen=True)
class Verification:
    runtime: str
    destination: str
    status: str
    installed_version: str = ""
    problems: tuple[str, ...] = ()
    remediation: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "healthy"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["problems"] = list(self.problems)
        data["ok"] = self.ok
        return data


class RuntimeInstaller:
    """Base contract for a runtime-specific Lumos integration installer."""

    name = "base"
    executable = ""
    home_env = ""
    default_home = ""
    restart_required = True

    def __init__(self, *, home: Path | None = None, destination: Path | None = None) -> None:
        self.home = home or self.resolve_home()
        self.destination = destination or self.home / "skills" / "lumos"

    def resolve_home(self) -> Path:
        configured = os.environ.get(self.home_env) if self.home_env else None
        return Path(configured).expanduser() if configured else Path.home() / self.default_home

    def detect(self) -> tuple[bool, str]:
        """Detect without creating directories or changing runtime configuration."""
        if self.home_env and os.environ.get(self.home_env):
            return True, f"{self.home_env} is configured"
        if self.home.exists():
            return True, f"runtime home exists at {self.home}"
        if self.executable and shutil.which(self.executable):
            return True, f"{self.executable} executable is available"
        return False, f"{self.name} was not detected"

    def source_files(self) -> dict[str, bytes]:
        source = resources.files("ai_loom").joinpath("resources", "lumos")
        return {
            "SKILL.md": source.joinpath("SKILL.md").read_bytes(),
            "agents/openai.yaml": source.joinpath("agents", "openai.yaml").read_bytes(),
        }

    def plan(self, *, force: bool = False, selected: bool = True) -> InstallPlan:
        detected, evidence = self.detect()
        files = tuple(self.source_files())
        if not selected:
            return InstallPlan(
                self.name, detected, str(self.destination), "skipped", evidence, self.restart_required, files
            )
        if not self.destination.exists():
            return InstallPlan(
                self.name,
                detected,
                str(self.destination),
                "install",
                "integration is not installed",
                self.restart_required,
                files,
            )

        manifest = self._read_manifest()
        current = self._current_hashes(files)
        desired = _hashes(self.source_files())
        if current == desired:
            if manifest is None:
                action = "repair-manifest"
                reason = "legacy integration matches Lumos"
            elif str(manifest.get("lumos_version", "")) != __version__:
                action = "update"
                reason = (
                    f"integration files match, but the manifest records Lumos "
                    f"{manifest.get('lumos_version') or 'unknown'}; update it to {__version__}"
                )
            else:
                action = "unchanged"
                reason = "integration is current"
            return InstallPlan(self.name, detected, str(self.destination), action, reason, self.restart_required, files)

        if manifest is None and not force:
            return InstallPlan(
                self.name,
                detected,
                str(self.destination),
                "conflict",
                "destination exists but is not managed by Lumos; use --force to replace known integration files",
                self.restart_required,
                files,
            )

        owned = set((manifest or {}).get("files", {}))
        modified_owned = [name for name in owned if current.get(name) != (manifest or {})["files"].get(name)]
        if modified_owned and not force:
            return InstallPlan(
                self.name,
                detected,
                str(self.destination),
                "conflict",
                "managed files were modified: " + ", ".join(sorted(modified_owned)),
                self.restart_required,
                files,
            )
        return InstallPlan(
            self.name,
            detected,
            str(self.destination),
            "update",
            "a different integration version is installed",
            self.restart_required,
            files,
        )

    def install(self, plan: InstallPlan, *, dry_run: bool = False) -> dict[str, Any]:
        if plan.action in {"skipped", "conflict", "unchanged"} or dry_run:
            return {**plan.to_dict(), "applied": False}
        source_files = self.source_files()
        self.destination.mkdir(parents=True, exist_ok=True)
        for relative, content in source_files.items():
            target = self._safe_target(relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(target, content)
        manifest = {
            "schema_version": 1,
            "runtime": self.name,
            "lumos_version": __version__,
            "files": _hashes(source_files),
        }
        _atomic_write(self.destination / MANIFEST_NAME, json.dumps(manifest, indent=2).encode() + b"\n")
        return {**plan.to_dict(), "action": "installed" if plan.action == "install" else "updated", "applied": True}

    def verify(self) -> Verification:
        if not self.destination.exists():
            return Verification(self.name, str(self.destination), "missing", remediation=f"lumos install {self.name}")
        manifest = self._read_manifest()
        if manifest is None:
            matching = self._current_hashes(tuple(self.source_files())) == _hashes(self.source_files())
            status = "legacy" if matching else "unmanaged"
            return Verification(
                self.name,
                str(self.destination),
                status,
                problems=("installation manifest is missing",),
                remediation=f"lumos install {self.name}" if matching else f"lumos install {self.name} --force",
            )
        problems = []
        current = self._current_hashes(tuple(manifest.get("files", {})))
        for relative, expected in manifest.get("files", {}).items():
            if relative not in current:
                problems.append(f"missing managed file: {relative}")
            elif current[relative] != expected:
                problems.append(f"modified managed file: {relative}")
        installed_version = str(manifest.get("lumos_version", ""))
        if installed_version != __version__:
            problems.append(f"installed integration is {installed_version or 'unknown'}, CLI is {__version__}")
        return Verification(
            self.name,
            str(self.destination),
            "healthy" if not problems else "outdated-or-modified",
            installed_version=installed_version,
            problems=tuple(problems),
            remediation="" if not problems else f"lumos install {self.name} --force",
        )

    def uninstall(self, *, dry_run: bool = False) -> dict[str, Any]:
        manifest = self._read_manifest()
        if manifest is None:
            return {
                "runtime": self.name,
                "destination": str(self.destination),
                "action": "not-managed",
                "applied": False,
                "reason": "no Lumos installation manifest was found",
            }
        files = tuple(str(name) for name in manifest.get("files", {}))
        # Validate the complete set even for a dry run so its result describes
        # an operation that could actually be applied safely.
        targets = [self._safe_target(relative) for relative in files]
        if not dry_run:
            # Validate the complete set before removing the first file so a
            # corrupt manifest cannot cause a partial uninstall.
            for target in targets:
                if target.is_file():
                    target.unlink()
                _remove_empty_parents(target.parent, stop=self.destination)
            manifest_path = self.destination / MANIFEST_NAME
            if manifest_path.is_file():
                manifest_path.unlink()
            if self.destination.is_dir() and not any(self.destination.iterdir()):
                self.destination.rmdir()
        return {
            "runtime": self.name,
            "destination": str(self.destination),
            "action": "uninstall",
            "files": list(files),
            "applied": not dry_run,
        }

    def _safe_target(self, relative: str) -> Path:
        root = self.destination.resolve()
        target = (root / relative).resolve()
        if target != root and root not in target.parents:
            raise ConfigError(f"unsafe runtime integration path {relative!r}")
        return target

    def _read_manifest(self) -> dict[str, Any] | None:
        path = self.destination / MANIFEST_NAME
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigError(f"invalid Lumos installation manifest at {path}") from exc
        if data.get("runtime") != self.name or not isinstance(data.get("files"), dict):
            raise ConfigError(f"installation manifest at {path} does not belong to {self.name}")
        return data

    def _current_hashes(self, files: tuple[str, ...]) -> dict[str, str]:
        current = {}
        for relative in files:
            path = self._safe_target(relative)
            if path.is_file():
                current[relative] = _digest(path.read_bytes())
        return current


class CodexInstaller(RuntimeInstaller):
    name = "codex"
    executable = "codex"
    home_env = "CODEX_HOME"
    default_home = ".codex"


class ClaudeInstaller(RuntimeInstaller):
    name = "claude"
    executable = "claude"
    home_env = "CLAUDE_HOME"
    default_home = ".claude"


_INSTALLERS: dict[str, type[RuntimeInstaller]] = {
    CodexInstaller.name: CodexInstaller,
    ClaudeInstaller.name: ClaudeInstaller,
}


def register_runtime_installer(name: str, installer: type[RuntimeInstaller]) -> None:
    if not issubclass(installer, RuntimeInstaller):
        raise TypeError("runtime installer must inherit RuntimeInstaller")
    _INSTALLERS[name] = installer


def runtime_installers() -> dict[str, type[RuntimeInstaller]]:
    return dict(_INSTALLERS)


def create_runtime_installer(
    name: str, *, home: Path | None = None, destination: Path | None = None
) -> RuntimeInstaller:
    try:
        installer = _INSTALLERS[name]
    except KeyError:
        available = ", ".join(sorted(_INSTALLERS))
        raise ConfigError(f"unknown AI runtime {name!r}; supported: {available}") from None
    return installer(home=home, destination=destination)


def _digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _hashes(files: dict[str, bytes]) -> dict[str, str]:
    return {name: _digest(content) for name, content in files.items()}


def _atomic_write(path: Path, content: bytes) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            Path(temporary).unlink(missing_ok=True)
        finally:
            raise


def _remove_empty_parents(path: Path, *, stop: Path) -> None:
    current = path
    stop = stop.resolve()
    while current.resolve() != stop and stop in current.resolve().parents:
        if not current.is_dir() or any(current.iterdir()):
            break
        current.rmdir()
        current = current.parent
