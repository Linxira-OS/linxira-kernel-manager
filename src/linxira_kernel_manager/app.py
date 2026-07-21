from __future__ import annotations

import argparse
import json
import os
import sys

from .policy import OPERATION_IDS
from .reporting import build_plan, build_report, save_plan_atomic


def arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="linxira-kernel-manager")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--report-json", action="store_true", help="Print the schema-v1 read-only report")
    mode.add_argument("--plan", choices=OPERATION_IDS, metavar="OPERATION_ID", help="Create and save one fixed-operation plan")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = arguments(argv)
    report = build_report()
    if args.report_json:
        print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
        return 0
    if args.plan:
        plan = build_plan(report, args.plan)
        path = save_plan_atomic(plan)
        print(json.dumps({"path": str(path), "plan": plan}, ensure_ascii=True, indent=2, sort_keys=True))
        return 0 if plan["applicable"] else 3

    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    from PySide6.QtWidgets import QApplication
    from .ui import MainWindow

    application = QApplication(sys.argv[:1])
    application.setApplicationName("Linxira Kernel Manager")
    application.setOrganizationName("Linxira OS")
    window = MainWindow(report)
    window.show()
    return application.exec()
