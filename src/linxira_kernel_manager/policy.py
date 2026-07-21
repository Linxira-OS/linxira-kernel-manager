from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Operation:
    id: str
    title: str
    summary: str
    expected_commands: tuple[tuple[str, ...], ...]
    effects: tuple[str, ...]


OPERATIONS = (
    Operation(
        "org.linxira.kernel.ensure-standard.v1",
        "Ensure standard kernels",
        "Ensure the standard and long-term-support kernels and matching headers are installed.",
        (("/usr/bin/pacman", "-S", "--needed", "linux", "linux-headers", "linux-lts", "linux-lts-headers"),),
        ("Install any missing fixed supported kernel and header packages.", "A reboot may be required."),
    ),
    Operation(
        "org.linxira.kernel.boot-lts-once.v1",
        "Boot Linux LTS once",
        "Select the detected Linux LTS GRUB entry for the next boot only.",
        (("/usr/bin/grub-reboot", "<detected-linux-lts-entry-id>"),),
        ("Set a one-shot GRUB next entry to Linux LTS.", "Do not change the persistent default."),
    ),
    Operation(
        "org.linxira.kernel.regenerate-initramfs.v1",
        "Regenerate initramfs images",
        "Regenerate initramfs images for installed presets.",
        (("/usr/bin/mkinitcpio", "-P"),),
        ("Regenerate normal and fallback images according to installed presets.", "A reboot may be required."),
    ),
    Operation(
        "org.linxira.bootloader.refresh-grub.v1",
        "Refresh GRUB configuration",
        "Regenerate the fixed GRUB configuration file.",
        (("/usr/bin/grub-mkconfig", "-o", "/boot/grub/grub.cfg"),),
        ("Replace the generated GRUB configuration at its fixed system location.", "Preserve the GRUB environment."),
    ),
)

OPERATION_BY_ID = {item.id: item for item in OPERATIONS}
OPERATION_IDS = tuple(item.id for item in OPERATIONS)
