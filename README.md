# Linxira Kernel Manager

Read-only kernel and boot reporting with fixed-operation planning for Linxira OS.
The support matrix is deliberately limited to `linux`, `linux-lts`,
`linux-headers`, and `linux-lts-headers`.

## Safety boundary

- Production collection reads only fixed `/usr/lib/modules`, `/boot`, `/proc`, and GRUB locations.
- Subprocesses are fixed argument vectors for `/usr/bin/uname -r`, fixed `pacman -Q` package queries, `dkms status`, and `/usr/bin/grub-editenv list`; every call uses `shell=False` and a timeout.
- GRUB reporting retains entries only when they boot one of the two exact supported kernel images.
- No CLI option accepts a package name, kernel name, module name, command, or path.
- Plans contain display-only expected commands and effects. Apply always returns `backend-not-ready`.
- Plans have source-state and plan SHA-256 digests and are atomically stored with private permissions below `$XDG_STATE_HOME/linxira/kernel-manager/plans`.
- The application never invokes privilege tools, package mutation, service writes, initramfs generation, or bootloader writes.

## CLI

```console
linxira-kernel-manager --report-json
linxira-kernel-manager --plan org.linxira.kernel.ensure-standard.v1
linxira-kernel-manager --plan org.linxira.kernel.boot-lts-once.v1
linxira-kernel-manager --plan org.linxira.kernel.regenerate-initramfs.v1
linxira-kernel-manager --plan org.linxira.bootloader.refresh-grub.v1
```

With no arguments, the PySide6 interface opens Overview, Kernels, Boot, and
Activity/report views. Saving requires review confirmation. Apply is disabled.

## Development

```console
python -m pip install -e .
QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -v
python -m compileall -q src tests
python -m pip wheel --no-deps --wheel-dir dist .
```
