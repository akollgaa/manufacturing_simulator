from __future__ import annotations

import sys
from pathlib import Path

from .controller import ApplyResult, StudioDocumentController
from .results import StudyDisplayModel, build_study_display

try:
    from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QDockWidget,
        QFileDialog,
        QLabel,
        QHBoxLayout,
        QInputDialog,
        QListWidget,
        QListWidgetItem,
        QMainWindow,
        QMessageBox,
        QPushButton,
        QPlainTextEdit,
        QSlider,
        QTableWidget,
        QTableWidgetItem,
        QVBoxLayout,
        QWidget,
    )
except ImportError as exc:  # pragma: no cover - GUI-only behavior
    raise RuntimeError("PySide6 is required to launch ManufacturingStudio.") from exc

from mfg_viewport.qt_widget import ViewportWidget


class _StudyWorker(QObject):  # pragma: no cover - GUI-only behavior
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, controller: StudioDocumentController, include_distribution: bool) -> None:
        super().__init__()
        self._controller = controller
        self._include_distribution = include_distribution

    @Slot()
    def run(self) -> None:
        try:
            result = self._controller.run_current_study(include_distribution=self._include_distribution)
            self.finished.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


class ManufacturingStudioWindow(QMainWindow):  # pragma: no cover - GUI-only behavior
    def __init__(self, document_path: str | None = None) -> None:
        super().__init__()
        self.controller = StudioDocumentController()
        self._study_thread: QThread | None = None
        self._study_worker: _StudyWorker | None = None
        self.setWindowTitle("ManufacturingStudio")
        self.resize(1400, 900)
        self._build_ui()
        self._build_menu()
        if document_path:
            self.controller.open_document(document_path)
            self.editor.setPlainText(self.controller.editor_text)
            self._refresh_ui()

    def _build_ui(self) -> None:
        self.viewport = ViewportWidget(self)
        self.setCentralWidget(self.viewport)

        self.editor = QPlainTextEdit(self)
        editor_dock = QDockWidget("XML", self)
        editor_dock.setWidget(self.editor)
        self.addDockWidget(Qt.LeftDockWidgetArea, editor_dock)

        self.validation_list = QListWidget(self)
        validation_dock = QDockWidget("Validation", self)
        validation_dock.setWidget(self.validation_list)
        self.addDockWidget(Qt.BottomDockWidgetArea, validation_dock)

        simulator_widget = QWidget(self)
        simulator_layout = QVBoxLayout(simulator_widget)
        controls_row = QHBoxLayout()
        self.run_button = QPushButton("Run Study", simulator_widget)
        self.run_button.clicked.connect(self._run_study)
        self.export_replay_button = QPushButton("Export Likely Replay", simulator_widget)
        self.export_replay_button.clicked.connect(self._export_likely_replay)
        self.distribution_checkbox = QCheckBox("Include distribution", simulator_widget)
        controls_row.addWidget(self.run_button)
        controls_row.addWidget(self.export_replay_button)
        controls_row.addWidget(self.distribution_checkbox)
        controls_row.addStretch(1)
        simulator_layout.addLayout(controls_row)
        self.horizon_label = QLabel("Horizon: -", simulator_widget)
        self.output_target_label = QLabel("Output target: -", simulator_widget)
        self.horizon_label.setWordWrap(True)
        self.output_target_label.setWordWrap(True)
        simulator_layout.addWidget(self.horizon_label)
        simulator_layout.addWidget(self.output_target_label)

        self.scenario_table = QTableWidget(0, 5, simulator_widget)
        self.scenario_table.setHorizontalHeaderLabels(["Scenario", "Output", "Replications", "Policy", "Seed"])
        self.scenario_table.horizontalHeader().setStretchLastSection(True)
        simulator_layout.addWidget(self.scenario_table)

        self.distribution_label = QLabel("Likely distribution", simulator_widget)
        simulator_layout.addWidget(self.distribution_label)
        self.distribution_table = QTableWidget(0, 2, simulator_widget)
        self.distribution_table.setHorizontalHeaderLabels(["Metric", "Value"])
        self.distribution_table.horizontalHeader().setStretchLastSection(True)
        simulator_layout.addWidget(self.distribution_table)

        self.stage_metrics_label = QLabel("Machine KPIs", simulator_widget)
        simulator_layout.addWidget(self.stage_metrics_label)
        self.stage_metrics_table = QTableWidget(0, 6, simulator_widget)
        self.stage_metrics_table.setHorizontalHeaderLabels(["Machine", "Kind", "Output", "Utilization", "Avg WIP", "Peak WIP"])
        self.stage_metrics_table.horizontalHeader().setStretchLastSection(True)
        simulator_layout.addWidget(self.stage_metrics_table)

        self.worker_metrics_label = QLabel("Worker KPIs", simulator_widget)
        simulator_layout.addWidget(self.worker_metrics_label)
        self.worker_metrics_table = QTableWidget(0, 4, simulator_widget)
        self.worker_metrics_table.setHorizontalHeaderLabels(["Pool", "Size", "Utilization", "Peak Busy"])
        self.worker_metrics_table.horizontalHeader().setStretchLastSection(True)
        simulator_layout.addWidget(self.worker_metrics_table)

        self.simulator_output = QPlainTextEdit(simulator_widget)
        self.simulator_output.setReadOnly(True)
        self.simulator_output.setMaximumBlockCount(400)
        self.simulator_output.setPlaceholderText("Structured results appear above. Raw JSON is mirrored here for debugging.")
        simulator_layout.addWidget(self.simulator_output)
        simulator_dock = QDockWidget("Simulator", self)
        simulator_dock.setWidget(simulator_widget)
        self.addDockWidget(Qt.RightDockWidgetArea, simulator_dock)

        assets_widget = QWidget(self)
        assets_layout = QVBoxLayout(assets_widget)
        asset_buttons = QHBoxLayout()
        add_asset_button = QPushButton("Add Asset", assets_widget)
        add_asset_button.clicked.connect(self._add_asset)
        remove_asset_button = QPushButton("Remove Asset", assets_widget)
        remove_asset_button.clicked.connect(self._remove_selected_asset)
        asset_buttons.addWidget(add_asset_button)
        asset_buttons.addWidget(remove_asset_button)
        asset_buttons.addStretch(1)
        assets_layout.addLayout(asset_buttons)
        self.asset_table = QTableWidget(0, 4, assets_widget)
        self.asset_table.setHorizontalHeaderLabels(["Id", "Display Name", "Path", "Status"])
        self.asset_table.horizontalHeader().setStretchLastSection(True)
        assets_layout.addWidget(self.asset_table)
        assets_dock = QDockWidget("DXF Registry", self)
        assets_dock.setWidget(assets_widget)
        self.addDockWidget(Qt.RightDockWidgetArea, assets_dock)

        replay_widget = QWidget(self)
        replay_layout = QVBoxLayout(replay_widget)
        replay_buttons = QHBoxLayout()
        load_replay_button = QPushButton("Load Replay", replay_widget)
        load_replay_button.clicked.connect(self._load_replay)
        clear_replay_button = QPushButton("Clear Replay", replay_widget)
        clear_replay_button.clicked.connect(self._clear_replay)
        replay_buttons.addWidget(load_replay_button)
        replay_buttons.addWidget(clear_replay_button)
        replay_buttons.addStretch(1)
        replay_layout.addLayout(replay_buttons)
        self.replay_status_label = QLabel("No replay loaded.", replay_widget)
        self.replay_time_label = QLabel("Replay time: -", replay_widget)
        replay_layout.addWidget(self.replay_status_label)
        replay_layout.addWidget(self.replay_time_label)
        self.replay_slider = QSlider(Qt.Horizontal, replay_widget)
        self.replay_slider.setEnabled(False)
        self.replay_slider.valueChanged.connect(self._on_replay_slider_changed)
        replay_layout.addWidget(self.replay_slider)
        replay_dock = QDockWidget("Replay", self)
        replay_dock.setWidget(replay_widget)
        self.addDockWidget(Qt.BottomDockWidgetArea, replay_dock)

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        open_action = file_menu.addAction("Open")
        open_action.triggered.connect(self._open_document)
        save_action = file_menu.addAction("Save")
        save_action.triggered.connect(self._save_document)
        save_as_action = file_menu.addAction("Save As")
        save_as_action.triggered.connect(self._save_document_as)

        model_menu = self.menuBar().addMenu("&Model")
        apply_action = model_menu.addAction("Apply")
        apply_action.triggered.connect(self._apply_document)
        validate_action = model_menu.addAction("Validate")
        validate_action.triggered.connect(self._apply_document)

    def _refresh_ui(self, apply_result: ApplyResult | None = None) -> None:
        self.validation_list.clear()
        parse_result = apply_result.parse_result if apply_result else self.controller.last_parse_result
        if parse_result:
            for message in parse_result.messages:
                item = QListWidgetItem(f"[{message.severity}] {message.code}: {message.message}")
                self.validation_list.addItem(item)
        if self.controller.last_valid_result is not None:
            scene = self.controller.current_scene()
            self.viewport.set_scene(scene)
        self._refresh_window_title()
        self._refresh_asset_table()
        self._refresh_replay_ui()

    def _refresh_asset_table(self) -> None:
        assets = list(self.controller.project_metadata.assets.values())
        self.asset_table.setRowCount(len(assets))
        for row, asset in enumerate(assets):
            self.asset_table.setItem(row, 0, QTableWidgetItem(asset.asset_id))
            self.asset_table.setItem(row, 1, QTableWidgetItem(asset.display_name))
            self.asset_table.setItem(row, 2, QTableWidgetItem(asset.path))
            exists = "found" if Path(self.controller.project_metadata.as_scene_registry(self.controller.current_path)[asset.asset_id]["path"]).exists() else "missing"
            self.asset_table.setItem(row, 3, QTableWidgetItem(exists))

    def _refresh_window_title(self) -> None:
        if self.controller.current_path is None:
            self.setWindowTitle("ManufacturingStudio")
            return
        self.setWindowTitle(f"ManufacturingStudio - {self.controller.current_path.name}")

    @Slot()
    def _open_document(self) -> None:
        file_name, _ = QFileDialog.getOpenFileName(self, "Open Factory XML", "", "XML Files (*.xml);;All Files (*)")
        if not file_name:
            return
        self.controller.open_document(file_name)
        self.editor.setPlainText(self.controller.editor_text)
        self._refresh_ui()

    @Slot()
    def _save_document(self) -> None:
        if self.controller.current_path is None:
            self._save_document_as()
            return
        self.controller.update_text(self.editor.toPlainText())
        self.controller.save_document()
        self.statusBar().showMessage(f"Saved {self.controller.current_path}", 4000)

    @Slot()
    def _save_document_as(self) -> None:
        file_name, _ = QFileDialog.getSaveFileName(self, "Save Factory XML", "", "XML Files (*.xml);;All Files (*)")
        if not file_name:
            return
        self.controller.update_text(self.editor.toPlainText())
        path = self.controller.save_document(file_name)
        self.statusBar().showMessage(f"Saved {path}", 4000)

    @Slot()
    def _apply_document(self) -> None:
        self.controller.update_text(self.editor.toPlainText())
        apply_result = self.controller.apply_document()
        if not apply_result.applied and apply_result.used_last_valid_snapshot:
            self.statusBar().showMessage("Apply failed. Keeping the last valid model snapshot.", 6000)
        elif apply_result.applied:
            self.statusBar().showMessage("Applied model successfully.", 4000)
        self._refresh_ui(apply_result)

    @Slot()
    def _run_study(self) -> None:
        self._apply_document()
        if self.controller.last_valid_result is None:
            QMessageBox.warning(self, "No valid model", "Fix validation errors before running the study.")
            return
        self.run_button.setEnabled(False)
        self.horizon_label.setText("Horizon: Running study...")
        self.output_target_label.setText("Output target: -")
        self.scenario_table.setRowCount(0)
        self.distribution_table.setRowCount(0)
        self.stage_metrics_table.setRowCount(0)
        self.worker_metrics_table.setRowCount(0)
        self.simulator_output.setPlainText("Running study...")
        self._study_thread = QThread(self)
        self._study_worker = _StudyWorker(self.controller, self.distribution_checkbox.isChecked())
        self._study_worker.moveToThread(self._study_thread)
        self._study_thread.started.connect(self._study_worker.run)
        self._study_worker.finished.connect(self._on_study_finished)
        self._study_worker.failed.connect(self._on_study_failed)
        self._study_worker.finished.connect(self._study_thread.quit)
        self._study_worker.failed.connect(self._study_thread.quit)
        self._study_thread.finished.connect(self._study_thread.deleteLater)
        self._study_thread.start()

    @Slot()
    def _export_likely_replay(self) -> None:
        self._apply_document()
        if self.controller.last_valid_result is None:
            QMessageBox.warning(self, "No valid model", "Fix validation errors before exporting replay.")
            return
        file_name, _ = QFileDialog.getSaveFileName(self, "Export Replay JSONL", "", "JSON Lines (*.jsonl);;All Files (*)")
        if not file_name:
            return
        path = self.controller.export_current_replay(file_name, scenario_id="likely")
        self.statusBar().showMessage(f"Replay exported to {path}", 5000)

    @Slot()
    def _load_replay(self) -> None:
        file_name, _ = QFileDialog.getOpenFileName(self, "Load Replay JSONL", "", "JSON Lines (*.jsonl);;All Files (*)")
        if not file_name:
            return
        try:
            replay = self.controller.load_replay(file_name)
        except Exception as exc:
            QMessageBox.warning(self, "Replay load failed", str(exc))
            return
        self._refresh_replay_ui()
        self._refresh_ui()
        self.statusBar().showMessage(f"Loaded replay {replay.scenario_id}", 5000)

    @Slot()
    def _clear_replay(self) -> None:
        self.controller.clear_replay()
        self._refresh_replay_ui()
        self._refresh_ui()
        self.statusBar().showMessage("Replay overlay cleared.", 4000)

    @Slot(int)
    def _on_replay_slider_changed(self, value: int) -> None:
        self.controller.set_replay_index(value)
        self._refresh_replay_ui()
        if self.controller.last_valid_result is not None:
            self.viewport.set_scene(self.controller.current_scene())

    @Slot(object)
    def _on_study_finished(self, study_result) -> None:
        display_model = build_study_display(study_result)
        self._populate_study_results(display_model)
        self.run_button.setEnabled(True)
        self.statusBar().showMessage("Study completed.", 4000)

    @Slot(str)
    def _on_study_failed(self, error_message: str) -> None:
        self.simulator_output.setPlainText(error_message)
        self.run_button.setEnabled(True)
        self.statusBar().showMessage("Study failed.", 6000)

    @Slot()
    def _add_asset(self) -> None:
        file_name, _ = QFileDialog.getOpenFileName(self, "Select DXF asset", "", "CAD Files (*.dxf *.dwg);;All Files (*)")
        if not file_name:
            return
        asset_id, accepted = QInputDialog.getText(self, "Asset id", "Stable asset id:")
        if not accepted or not asset_id.strip():
            return
        display_name, accepted = QInputDialog.getText(self, "Display name", "Display name:")
        if not accepted:
            return
        self.controller.add_asset(asset_id.strip(), display_name.strip() or asset_id.strip(), file_name)
        self._refresh_asset_table()
        self._apply_document()

    @Slot()
    def _remove_selected_asset(self) -> None:
        selected = self.asset_table.currentRow()
        if selected < 0:
            return
        asset_item = self.asset_table.item(selected, 0)
        if asset_item is None:
            return
        self.controller.remove_asset(asset_item.text())
        self._refresh_asset_table()
        self._apply_document()

    def _populate_study_results(self, display_model: StudyDisplayModel) -> None:
        self.horizon_label.setText(f"Horizon: {display_model.horizon_label}")
        self.output_target_label.setText(f"Output target: {display_model.output_target_label}")

        self.scenario_table.setRowCount(len(display_model.scenario_rows))
        for row, scenario in enumerate(display_model.scenario_rows):
            self.scenario_table.setItem(row, 0, QTableWidgetItem(scenario.label))
            self.scenario_table.setItem(row, 1, QTableWidgetItem(scenario.output))
            self.scenario_table.setItem(row, 2, QTableWidgetItem(scenario.replications))
            self.scenario_table.setItem(row, 3, QTableWidgetItem(scenario.policy))
            self.scenario_table.setItem(row, 4, QTableWidgetItem(scenario.seed))

        self.distribution_table.setRowCount(len(display_model.distribution_rows))
        for row, metric in enumerate(display_model.distribution_rows):
            self.distribution_table.setItem(row, 0, QTableWidgetItem(metric.label))
            self.distribution_table.setItem(row, 1, QTableWidgetItem(metric.value))
        self.distribution_label.setText(
            "Likely distribution" if display_model.distribution_rows else "Likely distribution (single run)"
        )
        self.stage_metrics_table.setRowCount(len(display_model.stage_rows))
        for row, metric in enumerate(display_model.stage_rows):
            self.stage_metrics_table.setItem(row, 0, QTableWidgetItem(metric.label))
            self.stage_metrics_table.setItem(row, 1, QTableWidgetItem(metric.kind))
            self.stage_metrics_table.setItem(row, 2, QTableWidgetItem(metric.output))
            self.stage_metrics_table.setItem(row, 3, QTableWidgetItem(metric.utilization))
            self.stage_metrics_table.setItem(row, 4, QTableWidgetItem(metric.average_inventory))
            self.stage_metrics_table.setItem(row, 5, QTableWidgetItem(metric.peak_inventory))

        self.worker_metrics_table.setRowCount(len(display_model.worker_rows))
        for row, metric in enumerate(display_model.worker_rows):
            self.worker_metrics_table.setItem(row, 0, QTableWidgetItem(metric.label))
            self.worker_metrics_table.setItem(row, 1, QTableWidgetItem(metric.size))
            self.worker_metrics_table.setItem(row, 2, QTableWidgetItem(metric.utilization))
            self.worker_metrics_table.setItem(row, 3, QTableWidgetItem(metric.peak_busy))
        self.simulator_output.setPlainText(display_model.raw_json)

    def _refresh_replay_ui(self) -> None:
        replay = self.controller.active_replay
        if replay is None or replay.frame_count() == 0:
            self.replay_status_label.setText("No replay loaded.")
            self.replay_time_label.setText("Replay time: -")
            self.replay_slider.blockSignals(True)
            self.replay_slider.setEnabled(False)
            self.replay_slider.setRange(0, 0)
            self.replay_slider.setValue(0)
            self.replay_slider.blockSignals(False)
            return
        self.replay_status_label.setText(
            f"{replay.scenario_id.title()} replay from {replay.source_path.name if replay.source_path else 'memory'} ({replay.frame_count()} frames)"
        )
        frame = replay.frame_at_index(self.controller.active_replay_index)
        self.replay_time_label.setText(f"Replay time: {frame.time:.2f} {replay.horizon_unit}")
        self.replay_slider.blockSignals(True)
        self.replay_slider.setEnabled(True)
        self.replay_slider.setRange(0, max(replay.frame_count() - 1, 0))
        self.replay_slider.setValue(self.controller.active_replay_index)
        self.replay_slider.blockSignals(False)


def launch_qt_app(document_path: str | None = None) -> int:  # pragma: no cover - GUI-only behavior
    application = QApplication.instance() or QApplication(sys.argv)
    window = ManufacturingStudioWindow(document_path=document_path)
    window.show()
    return application.exec()
