from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest

from linxira_kernel_manager.collector import collect_system_state
from linxira_kernel_manager.policy import OPERATION_IDS
from linxira_kernel_manager.reporting import (
    build_plan,
    build_report,
    load_plan,
    parse_json_strict,
    save_plan_atomic,
)

from helpers import ALL_INSTALLED, FixedRunner, state_paths


class PlanTests(unittest.TestCase):
    def report(self, installed: set[str] = ALL_INSTALLED, **options) -> dict:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        paths = state_paths(Path(temporary.name), **options)
        return build_report(collect_system_state(FixedRunner(installed), **paths))

    def test_all_fixed_plan_policies_have_contract_and_no_apply(self) -> None:
        report = self.report()
        self.assertEqual(len(OPERATION_IDS), 4)
        for operation_id in OPERATION_IDS:
            plan = build_plan(report, operation_id)
            self.assertEqual(plan["operation"]["id"], operation_id)
            self.assertEqual(plan["sourceReportSha256"], report["reportSha256"])
            self.assertTrue(plan["expected"]["displayOnly"])
            self.assertEqual(plan["apply"], {"implemented": False, "result": "backend-not-ready"})
            self.assertEqual(len(plan["planSha256"]), 64)

    def test_ensure_standard_applies_only_when_fixed_package_missing(self) -> None:
        operation = "org.linxira.kernel.ensure-standard.v1"
        self.assertFalse(build_plan(self.report(), operation)["applicable"])
        plan = build_plan(self.report(ALL_INSTALLED - {"linux-lts-headers"}), operation)
        self.assertTrue(plan["applicable"])
        self.assertEqual(plan["expected"]["commands"][0][-4:], ["linux", "linux-headers", "linux-lts", "linux-lts-headers"])

    def test_boot_lts_once_requires_exact_entry_and_not_existing_one_shot(self) -> None:
        operation = "org.linxira.kernel.boot-lts-once.v1"
        plan = build_plan(self.report(), operation)
        self.assertTrue(plan["applicable"])
        self.assertEqual(plan["expected"]["commands"], [["/usr/bin/grub-reboot", "linux-lts-main"]])
        missing = "menuentry 'Linux' --id 'linux-main' {\n linux /vmlinuz-linux rw\n}\n"
        blocked = build_plan(self.report(grub=missing), operation)
        self.assertFalse(blocked["applicable"])
        self.assertEqual(blocked["expected"]["commands"], [])

    def test_initramfs_and_grub_policy_block_without_kernel_or_config(self) -> None:
        no_packages: set[str] = set()
        initramfs = build_plan(self.report(no_packages), "org.linxira.kernel.regenerate-initramfs.v1")
        self.assertFalse(initramfs["applicable"])
        grub = build_plan(self.report(grub=None), "org.linxira.bootloader.refresh-grub.v1")
        self.assertFalse(grub["applicable"])

    def test_digest_private_atomic_state_and_load(self) -> None:
        plan = build_plan(self.report(ALL_INSTALLED - {"linux-headers"}), "org.linxira.kernel.ensure-standard.v1")
        with tempfile.TemporaryDirectory() as directory:
            output = save_plan_atomic(plan, Path(directory) / "plans")
            self.assertEqual(load_plan(output), plan)
            if os.name != "nt":
                self.assertEqual(output.stat().st_mode & 0o777, 0o600)
                self.assertEqual(output.parent.stat().st_mode & 0o777, 0o700)

    def test_duplicate_malformed_and_tampered_json_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicate"):
            parse_json_strict('{"schema":1,"schema":2}')
        with self.assertRaises(json.JSONDecodeError):
            parse_json_strict("{")
        plan = build_plan(self.report(ALL_INSTALLED - {"linux-headers"}), "org.linxira.kernel.ensure-standard.v1")
        plan["applicable"] = False
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.json"
            path.write_text(json.dumps(plan), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "digest"):
                load_plan(path)

    @unittest.skipIf(os.name == "nt", "Windows symlink creation usually requires elevated privileges")
    def test_symlink_state_directory_and_file_are_rejected(self) -> None:
        plan = build_plan(self.report(ALL_INSTALLED - {"linux-headers"}), "org.linxira.kernel.ensure-standard.v1")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            real = root / "real"
            real.mkdir()
            linked = root / "linked"
            linked.symlink_to(real, target_is_directory=True)
            with self.assertRaisesRegex(RuntimeError, "symlink"):
                save_plan_atomic(plan, linked)


if __name__ == "__main__":
    unittest.main()
