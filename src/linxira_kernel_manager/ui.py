from __future__ import annotations

import json

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .policy import OPERATIONS
from .reporting import build_plan, save_plan_atomic


STYLE = """
QMainWindow, QWidget { background: #f5f6f7; color: #202428; font-size: 13px; }
QTabWidget::pane { border: 1px solid #d8dcdf; background: #ffffff; }
QTabBar::tab { padding: 10px 20px; border-bottom: 2px solid transparent; }
QTabBar::tab:selected { color: #116b5b; border-bottom-color: #1c8a75; font-weight: 600; }
QFrame#statusPanel { background: #ffffff; border: 1px solid #d8dcdf; border-radius: 6px; }
QLabel#metric { font-size: 22px; font-weight: 650; color: #116b5b; }
QLabel#section { font-size: 16px; font-weight: 650; }
QPushButton { min-height: 30px; padding: 0 14px; border: 1px solid #b8bec2; border-radius: 4px; background: #ffffff; }
QPushButton:enabled:hover { border-color: #1c8a75; }
QPushButton:disabled { color: #8c9499; background: #eceeef; }
QComboBox { min-height: 30px; padding: 0 8px; border: 1px solid #b8bec2; border-radius: 4px; background: #ffffff; }
QTableWidget, QPlainTextEdit { background: #ffffff; border: 1px solid #d8dcdf; gridline-color: #e6e8ea; }
QHeaderView::section { background: #eef1f2; border: 0; border-bottom: 1px solid #d8dcdf; padding: 7px; font-weight: 600; }
"""


class MainWindow(QMainWindow):
    def __init__(self, report: dict):
        super().__init__()
        self.report = report
        self.plan: dict | None = None
        self.setWindowTitle("Linxira Kernel Manager")
        self.setMinimumSize(820, 600)
        self.resize(1080, 740)
        self.setStyleSheet(STYLE)
        self._build()

    @staticmethod
    def _text_view(value: object) -> QPlainTextEdit:
        view = QPlainTextEdit(json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True))
        view.setReadOnly(True)
        font = QFont("monospace")
        font.setStyleHint(QFont.StyleHint.Monospace)
        view.setFont(font)
        return view

    @staticmethod
    def _metric(title: str, value: str) -> QFrame:
        frame = QFrame()
        frame.setObjectName("statusPanel")
        layout = QVBoxLayout(frame)
        label = QLabel(value)
        label.setObjectName("metric")
        layout.addWidget(label)
        layout.addWidget(QLabel(title))
        return frame

    def _build(self) -> None:
        state = self.report["state"]
        tabs = QTabWidget()

        overview = QWidget()
        overview_layout = QVBoxLayout(overview)
        overview_layout.setContentsMargins(22, 20, 22, 20)
        heading = QLabel("Kernel status")
        heading.setObjectName("section")
        overview_layout.addWidget(heading)
        metrics = QHBoxLayout()
        release = state["runningKernel"]["release"] or "Unavailable"
        default = state["grub"]["effectiveDefaultKernelPackage"] or "Unknown"
        reboot = "Required" if state["reboot"]["required"] else "Current"
        metrics.addWidget(self._metric("Running release", release))
        metrics.addWidget(self._metric("Effective next boot", default))
        metrics.addWidget(self._metric("Reboot state", reboot))
        overview_layout.addLayout(metrics)
        overview_layout.addSpacing(16)
        overview_layout.addWidget(QLabel("Warnings and blockers"))
        messages = state["blockers"] + state["warnings"]
        message_view = QPlainTextEdit("\n".join(messages) if messages else "No current warnings or blockers.")
        message_view.setReadOnly(True)
        message_view.setMaximumHeight(180)
        overview_layout.addWidget(message_view)
        overview_layout.addStretch()
        tabs.addTab(overview, "Overview")

        kernels = QWidget()
        kernel_layout = QVBoxLayout(kernels)
        kernel_layout.setContentsMargins(22, 20, 22, 20)
        table = QTableWidget(2, 5)
        table.setHorizontalHeaderLabels(["Package", "Version", "Release", "Headers", "Images"])
        for row, package in enumerate(("linux", "linux-lts")):
            versions = [item["release"] for item in state["installedVersions"] if item["package"] == package]
            header = f"{package}-headers"
            image_count = sum(1 for item in state["bootImages"] if item["kernelPackage"] == package and item["exists"])
            values = [
                package,
                state["packages"][package]["version"] or "Not installed",
                ", ".join(versions) or "Unavailable",
                state["packages"][header]["version"] or "Missing",
                f"{image_count}/3 present",
            ]
            for column, value in enumerate(values):
                table.setItem(row, column, QTableWidgetItem(value))
        table.horizontalHeader().setStretchLastSection(True)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        kernel_layout.addWidget(table)
        kernel_layout.addWidget(QLabel("DKMS exact module and release records"))
        kernel_layout.addWidget(self._text_view(state["dkms"]), 1)
        tabs.addTab(kernels, "Kernels")

        boot = QWidget()
        boot_layout = QVBoxLayout(boot)
        boot_layout.setContentsMargins(22, 20, 22, 20)
        boot_layout.addWidget(QLabel("Supported GRUB entries"))
        boot_layout.addWidget(self._text_view(state["grub"]), 1)
        boot_layout.addWidget(QLabel("Normal, fallback, and kernel image evidence"))
        image_view = self._text_view(state["bootImages"])
        image_view.setMaximumHeight(220)
        boot_layout.addWidget(image_view)
        tabs.addTab(boot, "Boot")

        activity = QWidget()
        activity_layout = QVBoxLayout(activity)
        activity_layout.setContentsMargins(22, 20, 22, 20)
        top = QHBoxLayout()
        top.addWidget(QLabel("Review fixed operation"))
        self.selector = QComboBox()
        for operation in OPERATIONS:
            self.selector.addItem(operation.title, operation.id)
        self.selector.currentIndexChanged.connect(self._refresh_plan)
        top.addWidget(self.selector, 1)
        activity_layout.addLayout(top)
        self.plan_view = self._text_view({})
        self.plan_view.setAccessibleName("Complete display-only kernel operation plan")
        activity_layout.addWidget(self.plan_view, 1)
        controls = QHBoxLayout()
        self.confirm = QCheckBox("I reviewed this exact plan")
        self.confirm.stateChanged.connect(self._confirmation_changed)
        controls.addWidget(self.confirm)
        controls.addStretch()
        self.save_button = QPushButton("Save plan")
        self.save_button.clicked.connect(self._save)
        controls.addWidget(self.save_button)
        self.apply_button = QPushButton("Apply")
        self.apply_button.setEnabled(False)
        self.apply_button.setToolTip("Apply backend is not ready")
        controls.addWidget(self.apply_button)
        activity_layout.addLayout(controls)
        self.backend_status = QLabel("Apply unavailable: backend-not-ready")
        activity_layout.addWidget(self.backend_status)
        tabs.addTab(activity, "Activity / report")

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.addWidget(tabs)
        self.setCentralWidget(container)
        self.tabs = tabs
        self._refresh_plan()

    def _refresh_plan(self) -> None:
        operation_id = self.selector.currentData()
        self.plan = build_plan(self.report, operation_id) if operation_id else None
        self.plan_view.setPlainText(json.dumps(self.plan or {}, ensure_ascii=True, indent=2, sort_keys=True))
        self.confirm.setChecked(False)
        self.save_button.setEnabled(False)

    def _confirmation_changed(self, state: int) -> None:
        self.save_button.setEnabled(state == Qt.CheckState.Checked.value and self.plan is not None)

    def _save(self) -> None:
        if self.plan is not None and self.confirm.isChecked():
            path = save_plan_atomic(self.plan)
            self.backend_status.setText(f"Plan saved: {path}. Apply unavailable: backend-not-ready")
