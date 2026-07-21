from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from .collector import SUPPORTED_KERNELS, SUPPORTED_PACKAGES, collect_system_state
from .policy import OPERATION_BY_ID


REPORT_SCHEMA = "org.linxira.kernel-report.v1"
PLAN_SCHEMA = "org.linxira.kernel-plan.v1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digest(value: dict[str, Any]) -> str:
    canonical = json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def build_report(state: dict[str, Any] | None = None) -> dict[str, Any]:
    observed = state if state is not None else collect_system_state()
    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "generatedAt": _now(),
        "support": {
            "kernelPackages": list(SUPPORTED_KERNELS),
            "headerPackages": ["linux-headers", "linux-lts-headers"],
            "customKernelsSupported": False,
        },
        "state": observed,
        "warnings": list(observed["warnings"]),
        "blockers": list(observed["blockers"]),
    }
    report["reportSha256"] = _digest(report)
    return report


def _base_preconditions(report: dict[str, Any]) -> list[dict[str, Any]]:
    state = report["state"]
    return [
        {
            "id": "fixed-support-matrix",
            "required": True,
            "satisfied": state["supportedKernelPackages"] == list(SUPPORTED_KERNELS),
            "evidence": list(SUPPORTED_KERNELS),
        },
        {
            "id": "package-state-readable",
            "required": True,
            "satisfied": all(state["packages"][item]["queried"] for item in SUPPORTED_PACKAGES),
            "evidence": {item: state["packages"][item]["queried"] for item in SUPPORTED_PACKAGES},
        },
    ]


def build_plan(report: dict[str, Any], operation_id: str) -> dict[str, Any]:
    operation = OPERATION_BY_ID[operation_id]
    state = report["state"]
    preconditions = _base_preconditions(report)
    warnings = list(report["warnings"])
    blockers = list(report["blockers"])
    commands = [list(item) for item in operation.expected_commands]
    changes_needed = True

    if operation_id == "org.linxira.kernel.ensure-standard.v1":
        missing = [item for item in SUPPORTED_PACKAGES if not state["packages"][item]["installed"]]
        preconditions.append({"id": "fixed-packages-missing", "required": False, "satisfied": bool(missing), "evidence": missing})
        changes_needed = bool(missing)
        if not missing:
            warnings.append("All fixed supported kernel and header packages are already installed.")

    elif operation_id == "org.linxira.kernel.boot-lts-once.v1":
        commands = []
        entries = [item for item in state["grub"]["entries"] if item["kernelPackage"] == "linux-lts"]
        valid_entries = [item for item in entries if item["id"]]
        lts_installed = state["packages"]["linux-lts"]["installed"]
        preconditions.extend(
            [
                {"id": "linux-lts-installed", "required": True, "satisfied": lts_installed, "evidence": lts_installed},
                {"id": "one-unambiguous-linux-lts-grub-entry", "required": True, "satisfied": len(valid_entries) == 1, "evidence": len(valid_entries)},
            ]
        )
        if not lts_installed:
            blockers.append("Linux LTS is not installed.")
        if len(valid_entries) != 1:
            blockers.append("Exactly one Linux LTS GRUB entry with a safe entry ID is required.")
        else:
            commands = [["/usr/bin/grub-reboot", valid_entries[0]["id"]]]
        changes_needed = state["grub"]["nextKernelPackage"] != "linux-lts"
        if not changes_needed:
            warnings.append("Linux LTS is already selected for the next boot.")

    elif operation_id == "org.linxira.kernel.regenerate-initramfs.v1":
        installed = [item for item in SUPPORTED_KERNELS if state["packages"][item]["installed"]]
        preconditions.append({"id": "supported-kernel-installed", "required": True, "satisfied": bool(installed), "evidence": installed})
        if not installed:
            blockers.append("No fixed supported kernel is installed.")

    elif operation_id == "org.linxira.bootloader.refresh-grub.v1":
        readable = state["grub"]["configReadable"]
        installed = [item for item in SUPPORTED_KERNELS if state["packages"][item]["installed"]]
        preconditions.extend(
            [
                {"id": "grub-config-readable", "required": True, "satisfied": readable, "evidence": readable},
                {"id": "supported-kernel-installed", "required": True, "satisfied": bool(installed), "evidence": installed},
            ]
        )
        if not readable:
            blockers.append("The fixed GRUB configuration is not readable.")
        if not installed:
            blockers.append("No fixed supported kernel is installed.")

    required_ok = all(item["satisfied"] for item in preconditions if item["required"])
    plan: dict[str, Any] = {
        "schema": PLAN_SCHEMA,
        "generatedAt": _now(),
        "operation": {"id": operation.id, "title": operation.title, "summary": operation.summary},
        "sourceReportSha256": report["reportSha256"],
        "preconditions": preconditions,
        "expected": {"commands": commands, "effects": list(operation.effects), "displayOnly": True},
        "warnings": warnings,
        "blockers": blockers,
        "applicable": required_ok and changes_needed and not blockers,
        "apply": {"implemented": False, "result": "backend-not-ready"},
    }
    plan["planSha256"] = _digest(plan)
    return plan


def parse_json_strict(text: str) -> Any:
    def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    return json.loads(text, object_pairs_hook=unique_pairs)


def validate_plan_document(plan: Any) -> dict[str, Any]:
    if not isinstance(plan, dict) or plan.get("schema") != PLAN_SCHEMA:
        raise ValueError("unsupported plan schema")
    digest = plan.get("planSha256")
    unsigned = dict(plan)
    unsigned.pop("planSha256", None)
    if not isinstance(digest, str) or digest != _digest(unsigned):
        raise ValueError("plan digest mismatch")
    operation = plan.get("operation")
    if not isinstance(operation, dict) or operation.get("id") not in OPERATION_BY_ID:
        raise ValueError("unsupported plan operation")
    return plan


def plan_directory() -> Path:
    base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return base / "linxira" / "kernel-manager" / "plans"


def _reject_existing_symlinks(path: Path) -> None:
    for component in reversed(path.parents):
        if component.exists() and component.is_symlink():
            raise RuntimeError("plan state path must not contain a symlink")
    if path.exists() and path.is_symlink():
        raise RuntimeError("plan state path must not contain a symlink")


def save_plan_atomic(plan: dict[str, Any], directory: Path | None = None) -> Path:
    validate_plan_document(plan)
    target_dir = directory or plan_directory()
    _reject_existing_symlinks(target_dir)
    target_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    _reject_existing_symlinks(target_dir)
    if not target_dir.is_dir():
        raise RuntimeError("plan state path is not a directory")
    os.chmod(target_dir, 0o700)
    target = target_dir / f"{plan['planSha256']}.json"
    if target.is_symlink():
        raise RuntimeError("plan target must not be a symlink")
    payload = json.dumps(plan, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    descriptor, temporary = tempfile.mkstemp(prefix=".plan-", suffix=".tmp", dir=target_dir)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        os.chmod(target, 0o600)
        if hasattr(os, "O_DIRECTORY"):
            directory_fd = os.open(target_dir, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return target


def load_plan(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise RuntimeError("plan file must not be a symlink")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError("plan file is unavailable") from exc
    return validate_plan_document(parse_json_strict(text))
