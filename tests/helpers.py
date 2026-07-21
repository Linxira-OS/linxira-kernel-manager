from __future__ import annotations

import os
from pathlib import Path
import subprocess
import time


GRUB_CONFIG = """
set default="${saved_entry}"
menuentry 'Linxira Linux' --class arch --id 'linux-main' {
    linux /vmlinuz-linux root=UUID=test rw
    initrd /initramfs-linux.img
}
submenu 'Advanced options' --id 'advanced' {
    menuentry 'Linxira Linux LTS' --id 'linux-lts-main' {
        linux /vmlinuz-linux-lts root=UUID=test rw
        initrd /initramfs-linux-lts.img
    }
}
menuentry 'Unsupported custom kernel' --id 'custom-main' {
    linux /vmlinuz-linux-zen root=UUID=test rw
}
"""


class FixedRunner:
    def __init__(
        self,
        installed: set[str] | None = None,
        release: str = "6.12.1-arch1-1",
        dkms: str = "",
        grubenv: str = "saved_entry=linux-main\n",
    ):
        self.installed = installed or set()
        self.release = release
        self.dkms = dkms
        self.grubenv = grubenv
        self.calls: list[tuple[list[str], dict]] = []

    def __call__(self, argv: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        self.calls.append((argv, kwargs))
        executable = Path(argv[0]).name
        if executable == "uname":
            return subprocess.CompletedProcess(argv, 0, self.release + "\n", "")
        if executable == "pacman":
            package = argv[2]
            if package in self.installed:
                return subprocess.CompletedProcess(argv, 0, f"{package} 1.2.3-1\n", "")
            return subprocess.CompletedProcess(argv, 1, "", "not found")
        if executable == "dkms":
            return subprocess.CompletedProcess(argv, 0, self.dkms, "")
        if executable == "grub-editenv":
            return subprocess.CompletedProcess(argv, 0, self.grubenv, "")
        raise AssertionError(f"unexpected command: {argv}")


def state_paths(
    root: Path,
    kernels: tuple[tuple[str, str], ...] = (
        ("linux", "6.12.1-arch1-1"),
        ("linux-lts", "6.6.9-arch1-1"),
    ),
    grub: str | None = GRUB_CONFIG,
    missing_fallback: str | None = None,
) -> dict:
    modules = root / "modules"
    boot = root / "boot"
    modules.mkdir()
    boot.mkdir()
    for package, release in kernels:
        directory = modules / release
        directory.mkdir()
        (directory / "pkgbase").write_text(package + "\n", encoding="utf-8")
    for package, _release in kernels:
        names = (f"initramfs-{package}.img", f"initramfs-{package}-fallback.img", f"vmlinuz-{package}")
        for name in names:
            if missing_fallback == package and "fallback" in name:
                continue
            path = boot / name
            path.write_bytes((name + "\n").encode("ascii"))
            old = time.time() - 7200
            os.utime(path, (old, old))
    grub_config = root / "grub.cfg"
    if grub is not None:
        grub_config.write_text(grub, encoding="utf-8")
    proc_cmdline = root / "cmdline"
    proc_cmdline.write_text("BOOT_IMAGE=/vmlinuz-linux root=UUID=test rw quiet\n", encoding="utf-8")
    proc_modules = root / "proc-modules"
    proc_modules.write_text("i915 1 0 - Live 0x0\nnvidia 1 0 - Live 0x0\n", encoding="utf-8")
    uptime = root / "uptime"
    uptime.write_text("60.0 30.0\n", encoding="utf-8")
    return {
        "module_root": modules,
        "boot_root": boot,
        "proc_cmdline": proc_cmdline,
        "proc_modules": proc_modules,
        "proc_uptime": uptime,
        "grub_config": grub_config,
        "reboot_marker": root / "reboot-required",
    }


ALL_INSTALLED = {"linux", "linux-headers", "linux-lts", "linux-lts-headers"}
