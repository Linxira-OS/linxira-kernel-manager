from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re
import subprocess
from typing import Any, Callable


UNAME = "/usr/bin/uname"
PACMAN = "/usr/bin/pacman"
DKMS = "/usr/bin/dkms"
GRUB_EDITENV = "/usr/bin/grub-editenv"
GRUB_EDITENV_LIST = (GRUB_EDITENV, "-", "list")
COMMAND_TIMEOUT_SECONDS = 8
MAX_HASH_BYTES = 128 * 1024 * 1024
SUPPORTED_KERNELS = ("linux", "linux-lts")
SUPPORTED_PACKAGES = ("linux", "linux-headers", "linux-lts", "linux-lts-headers")

_MENU_RE = re.compile(r"^\s*menuentry\s+(['\"])(.*?)\1(?P<rest>.*)$")
_ID_RE = re.compile(r"--id(?:=|\s+)(?:['\"])?([A-Za-z0-9][A-Za-z0-9_.-]*)")
_VMLINUX_RE = re.compile(r"(?:^|\s)/(?:boot/)?vmlinuz-(linux(?:-lts)?)(?=\s|$)")
_DKMS_RE = re.compile(
    r"^(?P<module>[A-Za-z0-9_.+-]+)/(?P<version>[^,\s]+),\s*"
    r"(?P<release>[^,\s]+),\s*(?P<arch>[^:]+):\s*(?P<status>.+)$"
)


def _run(
    runner: Callable[..., subprocess.CompletedProcess[str]], argv: list[str]
) -> subprocess.CompletedProcess[str] | None:
    try:
        return runner(
            argv,
            capture_output=True,
            text=True,
            check=False,
            shell=False,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def _read_text(path: Path, limit: int = 4 * 1024 * 1024) -> str | None:
    try:
        if path.stat().st_size > limit:
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _timestamp(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat()


def _artifact(path: Path, kernel: str, kind: str, fallback: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {
        "kernelPackage": kernel,
        "kind": kind,
        "fallback": fallback,
        "exists": False,
        "size": None,
        "modifiedAt": None,
        "sha256": None,
    }
    try:
        stat = path.stat()
        if not path.is_file():
            return result
        result.update(exists=True, size=stat.st_size, modifiedAt=_timestamp(stat.st_mtime))
        if stat.st_size <= MAX_HASH_BYTES:
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            result["sha256"] = digest.hexdigest()
    except OSError:
        pass
    return result


def parse_grub_environment(text: str) -> dict[str, str | None]:
    values: dict[str, str | None] = {"savedEntry": None, "nextEntry": None}
    for line in text.splitlines():
        key, separator, value = line.partition("=")
        if not separator:
            continue
        if key == "saved_entry":
            values["savedEntry"] = value.strip() or None
        elif key == "next_entry":
            values["nextEntry"] = value.strip() or None
    return values


def parse_grub_config(text: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    depth = 0
    configured_default: dict[str, Any] = {"kind": "unknown", "value": None}

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("set default="):
            value = stripped.split("=", 1)[1].strip().strip("'\"")
            if "saved_entry" in value:
                configured_default = {"kind": "saved", "value": None}
            elif value.isdigit():
                configured_default = {"kind": "index", "value": int(value)}

        match = _MENU_RE.match(line)
        if match and current is None:
            id_match = _ID_RE.search(match.group("rest"))
            current = {
                "title": match.group(2),
                "id": id_match.group(1) if id_match else None,
                "kernelPackage": None,
                "startDepth": depth + line.count("{") - line.count("}"),
            }
        elif current is not None:
            kernel_match = _VMLINUX_RE.search(line)
            if kernel_match:
                current["kernelPackage"] = kernel_match.group(1)

        depth += line.count("{") - line.count("}")
        if current is not None and depth < current["startDepth"]:
            if current["kernelPackage"] in SUPPORTED_KERNELS:
                current.pop("startDepth")
                entries.append(current)
            current = None

    return entries, configured_default


def parse_dkms_status(
    text: str, supported_releases: set[str]
) -> tuple[list[dict[str, str]], int]:
    records: list[dict[str, str]] = []
    malformed = 0
    for line in (item.strip() for item in text.splitlines()):
        if not line:
            continue
        match = _DKMS_RE.fullmatch(line)
        if match is None:
            malformed += 1
            continue
        values = match.groupdict()
        if values["release"] not in supported_releases:
            continue
        records.append(
            {
                "module": values["module"],
                "moduleVersion": values["version"],
                "kernelRelease": values["release"],
                "architecture": values["arch"].strip(),
                "status": values["status"].strip().lower(),
            }
        )
    records.sort(key=lambda item: (item["module"], item["kernelRelease"], item["moduleVersion"]))
    return records, malformed


def dkms_exact_status(state: dict[str, Any], module: str, release: str) -> str | None:
    matches = [
        item["status"]
        for item in state["dkms"]
        if item["module"] == module and item["kernelRelease"] == release
    ]
    return matches[0] if len(matches) == 1 else None


def _resolve_grub_package(value: str | None, entries: list[dict[str, Any]]) -> str | None:
    if value is None:
        return None
    leaf = value.rsplit(">", 1)[-1]
    matches = {
        item["kernelPackage"]
        for item in entries
        if value in (item["id"], item["title"]) or leaf in (item["id"], item["title"])
    }
    return next(iter(matches)) if len(matches) == 1 else None


def collect_system_state(
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    module_root: Path = Path("/usr/lib/modules"),
    boot_root: Path = Path("/boot"),
    proc_cmdline: Path = Path("/proc/cmdline"),
    proc_modules: Path = Path("/proc/modules"),
    proc_uptime: Path = Path("/proc/uptime"),
    grub_config: Path = Path("/boot/grub/grub.cfg"),
    reboot_marker: Path = Path("/run/reboot-required"),
) -> dict[str, Any]:
    warnings: list[str] = []
    blockers: list[str] = []

    uname = _run(runner, [UNAME, "-r"])
    running_release = uname.stdout.strip() if uname is not None and uname.returncode == 0 else None
    if not running_release:
        running_release = None
        warnings.append("Unable to read the running kernel release.")

    kernels: list[dict[str, Any]] = []
    try:
        pkgbase_paths = sorted(module_root.glob("*/pkgbase"))
    except OSError:
        pkgbase_paths = []
        warnings.append("Unable to inspect installed kernel module trees.")
    for path in pkgbase_paths:
        pkgbase = _read_text(path, 128)
        package = pkgbase.strip() if pkgbase else ""
        if package in SUPPORTED_KERNELS:
            kernels.append(
                {
                    "package": package,
                    "release": path.parent.name,
                    "running": path.parent.name == running_release,
                }
            )
    kernels.sort(key=lambda item: (item["package"], item["release"]))
    releases = {item["release"] for item in kernels}

    packages: dict[str, dict[str, Any]] = {}
    for package in SUPPORTED_PACKAGES:
        result = _run(runner, [PACMAN, "-Q", package])
        queried = result is not None
        installed = queried and result.returncode == 0
        version = None
        if installed:
            fields = result.stdout.strip().split(maxsplit=1)
            if len(fields) == 2 and fields[0] == package:
                version = fields[1]
            else:
                installed = False
                warnings.append(f"Unexpected package query output for {package}.")
        elif not queried:
            warnings.append(f"Unable to query package {package}.")
        packages[package] = {"queried": queried, "installed": installed, "version": version}

    dkms_result = _run(runner, [DKMS, "status"])
    if dkms_result is not None and dkms_result.returncode == 0:
        dkms, malformed_dkms = parse_dkms_status(dkms_result.stdout, releases)
        if malformed_dkms:
            warnings.append(f"Ignored {malformed_dkms} malformed DKMS status line(s).")
    else:
        dkms = []
        warnings.append("Unable to read DKMS status.")

    images: list[dict[str, Any]] = []
    for kernel in SUPPORTED_KERNELS:
        images.append(_artifact(boot_root / f"initramfs-{kernel}.img", kernel, "initramfs"))
        images.append(_artifact(boot_root / f"initramfs-{kernel}-fallback.img", kernel, "initramfs", True))
        images.append(_artifact(boot_root / f"vmlinuz-{kernel}", kernel, "vmlinuz"))

    environment_result = _run(runner, list(GRUB_EDITENV_LIST))
    if environment_result is not None and environment_result.returncode == 0:
        environment = parse_grub_environment(environment_result.stdout)
    else:
        environment = {"savedEntry": None, "nextEntry": None}
        warnings.append("Unable to read the GRUB environment.")

    grub_text = _read_text(grub_config)
    if grub_text is None:
        entries: list[dict[str, Any]] = []
        configured_default = {"kind": "unknown", "value": None}
        warnings.append("Unable to read the fixed GRUB configuration.")
    else:
        entries, configured_default = parse_grub_config(grub_text)

    saved_package = _resolve_grub_package(environment["savedEntry"], entries)
    next_package = _resolve_grub_package(environment["nextEntry"], entries)
    if configured_default["kind"] == "index" and configured_default["value"] < len(entries):
        default_package = entries[configured_default["value"]]["kernelPackage"]
    elif configured_default["kind"] == "saved":
        default_package = saved_package
    else:
        default_package = None

    loaded_text = _read_text(proc_modules)
    if loaded_text is None:
        loaded_modules: list[str] = []
        warnings.append("Unable to read loaded kernel modules.")
    else:
        loaded_modules = sorted({line.split()[0] for line in loaded_text.splitlines() if line.split()})

    cmdline_text = _read_text(proc_cmdline, 128 * 1024)
    command_line = cmdline_text.strip() if cmdline_text is not None else None
    if command_line is None:
        warnings.append("Unable to read the kernel command line.")

    boot_epoch: float | None = None
    uptime_seconds: float | None = None
    uptime_text = _read_text(proc_uptime, 1024)
    try:
        uptime_seconds = float(uptime_text.split()[0]) if uptime_text else None
        if uptime_seconds is not None:
            boot_epoch = datetime.now(timezone.utc).timestamp() - uptime_seconds
    except (ValueError, IndexError):
        warnings.append("Unable to parse system uptime.")

    newer_artifacts = [
        item
        for item in images
        if boot_epoch is not None
        and item["modifiedAt"] is not None
        and datetime.fromisoformat(item["modifiedAt"]).timestamp() > boot_epoch
    ]
    marker_present = reboot_marker.exists()
    running_known = running_release is not None and any(item["running"] for item in kernels)
    reasons = []
    if marker_present:
        reasons.append("reboot-marker-present")
    if newer_artifacts:
        reasons.append("boot-artifact-newer-than-current-boot")
    if running_release and kernels and not running_known:
        reasons.append("running-kernel-not-in-supported-installed-set")
    missing_entry = [kernel for kernel in SUPPORTED_KERNELS if packages[kernel]["installed"] and not any(item["kernelPackage"] == kernel for item in entries)]
    if missing_entry:
        warnings.append("GRUB is missing an entry for: " + ", ".join(missing_entry) + ".")

    if not any(packages[item]["queried"] for item in SUPPORTED_KERNELS):
        blockers.append("Installed kernel package state is unavailable.")

    return {
        "runningKernel": {"release": running_release, "recognized": running_known},
        "supportedKernelPackages": list(SUPPORTED_KERNELS),
        "installedVersions": kernels,
        "packages": packages,
        "bootImages": images,
        "grub": {
            "configReadable": grub_text is not None,
            "entries": entries,
            "configuredDefault": configured_default,
            "savedEntry": environment["savedEntry"],
            "savedKernelPackage": saved_package,
            "nextEntry": environment["nextEntry"],
            "nextKernelPackage": next_package,
            "effectiveDefaultKernelPackage": next_package or default_package,
            "oneShotPending": environment["nextEntry"] is not None,
        },
        "dkms": dkms,
        "loadedModules": loaded_modules,
        "kernelCommandLine": command_line,
        "uptimeSeconds": uptime_seconds,
        "reboot": {"required": bool(reasons), "reasons": reasons, "markerPresent": marker_present},
        "warnings": warnings,
        "blockers": blockers,
    }
