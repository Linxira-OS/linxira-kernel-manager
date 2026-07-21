from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from linxira_kernel_manager.app import arguments
from linxira_kernel_manager.collector import collect_system_state
from linxira_kernel_manager.reporting import build_report

from helpers import ALL_INSTALLED, FixedRunner, state_paths


class CliAndMetadataTests(unittest.TestCase):
    def test_cli_accepts_only_report_or_fixed_plan_choice(self) -> None:
        self.assertTrue(arguments(["--report-json"]).report_json)
        operation = "org.linxira.kernel.ensure-standard.v1"
        self.assertEqual(arguments(["--plan", operation]).plan, operation)
        for rejected in (["--plan", "linux-zen"], ["--path", "/tmp/x"], ["--kernel", "linux"], ["--package", "linux"]):
            with self.assertRaises(SystemExit):
                arguments(rejected)

    def test_desktop_and_appstream_metadata_parse(self) -> None:
        root = Path(__file__).parents[1]
        desktop = (root / "data" / "org.linxira.KernelManager.desktop").read_text(encoding="utf-8")
        self.assertIn("Exec=linxira-kernel-manager", desktop)
        self.assertIn("Terminal=false", desktop)
        component = ET.parse(root / "data" / "org.linxira.KernelManager.metainfo.xml").getroot()
        self.assertEqual(component.findtext("id"), "org.linxira.KernelManager")


try:
    from PySide6.QtWidgets import QApplication
    from linxira_kernel_manager.ui import MainWindow
except ImportError:
    QApplication = None


@unittest.skipIf(QApplication is None, "PySide6 is unavailable")
class UiSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_offscreen_tabs_review_save_and_disabled_apply(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = state_paths(Path(directory))
            report = build_report(collect_system_state(FixedRunner(ALL_INSTALLED), **paths))
        window = MainWindow(report)
        self.assertEqual([window.tabs.tabText(index) for index in range(window.tabs.count())], ["Overview", "Kernels", "Boot", "Activity / report"])
        self.assertIn("org.linxira.kernel.ensure-standard.v1", window.plan_view.toPlainText())
        self.assertFalse(window.save_button.isEnabled())
        self.assertFalse(window.apply_button.isEnabled())
        window.confirm.setChecked(True)
        self.assertTrue(window.save_button.isEnabled())
        self.assertIn("backend-not-ready", window.backend_status.text())
        window.close()


if __name__ == "__main__":
    unittest.main()
