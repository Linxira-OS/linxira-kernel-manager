from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from linxira_kernel_manager.collector import (
    DKMS,
    GRUB_EDITENV,
    GRUB_EDITENV_LIST,
    PACMAN,
    SUPPORTED_PACKAGES,
    UNAME,
    collect_system_state,
    dkms_exact_status,
)

from helpers import ALL_INSTALLED, FixedRunner, state_paths


class CollectorTests(unittest.TestCase):
    def collect(self, runner: FixedRunner, **options):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        paths = state_paths(Path(temporary.name), **options)
        return collect_system_state(runner, **paths), paths

    def test_linux_and_linux_lts_complete_state(self) -> None:
        dkms = (
            "nvidia/580.1, 6.12.1-arch1-1, x86_64: installed\n"
            "nvidia/580.1, 6.6.9-arch1-1, x86_64: installed\n"
        )
        state, _ = self.collect(FixedRunner(ALL_INSTALLED, dkms=dkms))
        self.assertEqual({item["package"] for item in state["installedVersions"]}, {"linux", "linux-lts"})
        self.assertTrue(all(state["packages"][item]["installed"] for item in SUPPORTED_PACKAGES))
        self.assertEqual(len([item for item in state["bootImages"] if item["exists"]]), 6)
        self.assertEqual({item["kernelPackage"] for item in state["grub"]["entries"]}, {"linux", "linux-lts"})
        self.assertFalse(any("custom" in str(item).lower() for item in state["grub"]["entries"]))

    def test_missing_header_and_fallback_are_reported_as_state(self) -> None:
        state, _ = self.collect(FixedRunner(ALL_INSTALLED - {"linux-lts-headers"}), missing_fallback="linux-lts")
        self.assertFalse(state["packages"]["linux-lts-headers"]["installed"])
        fallback = next(item for item in state["bootImages"] if item["kernelPackage"] == "linux-lts" and item["fallback"])
        self.assertFalse(fallback["exists"])

    def test_grub_missing_entry_warns(self) -> None:
        grub = "menuentry 'Linux' --id 'linux-main' {\n linux /vmlinuz-linux rw\n}\n"
        state, _ = self.collect(FixedRunner(ALL_INSTALLED), grub=grub)
        self.assertTrue(any("linux-lts" in warning for warning in state["warnings"]))

    def test_running_saved_and_one_shot_evidence(self) -> None:
        runner = FixedRunner(ALL_INSTALLED, grubenv="saved_entry=linux-main\nnext_entry=advanced>linux-lts-main\n")
        state, _ = self.collect(runner)
        self.assertTrue(state["runningKernel"]["recognized"])
        self.assertEqual(state["grub"]["savedKernelPackage"], "linux")
        self.assertEqual(state["grub"]["nextKernelPackage"], "linux-lts")
        self.assertEqual(state["grub"]["effectiveDefaultKernelPackage"], "linux-lts")
        self.assertTrue(state["grub"]["oneShotPending"])

    def test_exact_dkms_module_and_release_matching(self) -> None:
        dkms = (
            "nvidia-open/580.1, 6.12.1-arch1-1, x86_64: installed\n"
            "nvidia/580.1, 6.12.1-arch1-1, x86_64: added\n"
            "nvidia/580.1, 6.6.9-arch1-1, x86_64: installed\n"
        )
        state, _ = self.collect(FixedRunner(ALL_INSTALLED, dkms=dkms))
        self.assertEqual(dkms_exact_status(state, "nvidia", "6.12.1-arch1-1"), "added")
        self.assertEqual(dkms_exact_status(state, "nvidia-open", "6.12.1-arch1-1"), "installed")
        self.assertIsNone(dkms_exact_status(state, "nvidia", "6.7.0"))

    def test_duplicate_exact_dkms_state_is_ambiguous(self) -> None:
        dkms = (
            "nvidia/580.1, 6.12.1-arch1-1, x86_64: installed\n"
            "nvidia/580.2, 6.12.1-arch1-1, x86_64: installed\n"
        )
        state, _ = self.collect(FixedRunner(ALL_INSTALLED, dkms=dkms))
        self.assertIsNone(dkms_exact_status(state, "nvidia", "6.12.1-arch1-1"))

    def test_reboot_marker_and_new_artifact(self) -> None:
        state, paths = self.collect(FixedRunner(ALL_INSTALLED))
        paths["reboot_marker"].write_text("", encoding="ascii")
        state = collect_system_state(FixedRunner(ALL_INSTALLED), **paths)
        self.assertTrue(state["reboot"]["required"])
        self.assertIn("reboot-marker-present", state["reboot"]["reasons"])

    def test_only_fixed_read_only_argv_with_shell_false(self) -> None:
        runner = FixedRunner(ALL_INSTALLED)
        self.collect(runner)
        argv = [call[0] for call in runner.calls]
        self.assertIn([UNAME, "-r"], argv)
        self.assertIn([DKMS, "status"], argv)
        self.assertIn(list(GRUB_EDITENV_LIST), argv)
        self.assertEqual(
            {tuple(item) for item in argv if item[0] == PACMAN},
            {(PACMAN, "-Q", package) for package in SUPPORTED_PACKAGES},
        )
        forbidden = {"-S", "-R", "-U", "install", "remove", "enable", "start", "stop", "restart"}
        for command, kwargs in runner.calls:
            self.assertIs(kwargs["shell"], False)
            self.assertGreater(kwargs["timeout"], 0)
            self.assertTrue(forbidden.isdisjoint(command))


if __name__ == "__main__":
    unittest.main()
