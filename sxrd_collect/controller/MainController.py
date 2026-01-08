# -*- coding: utf8 -*-
# SXRD_Collect - GUI program for collection single crystal X-ray diffraction data
# Copyright (C) 2015  Clemens Prescher (clemens.prescher@gmail.com)
# GSECARS, University of Chicago
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
#     (at your option) any later version.
#
#     This program is distributed in the hope that it will be useful,
#     but WITHOUT ANY WARRANTY; without even the implied warranty of
#     MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#     GNU General Public License for more details.
#
#     You should have received a copy of the GNU General Public License
#     along with this program.  If not, see <http://www.gnu.org/licenses/>.
__author__ = "Clemens Prescher"
__version__ = 0.2
# Modified by Maxim Bykov and Elena Bykova on 08 March 2016

import collections
import logging
import os.path
import re
import shutil
import subprocess
import time
from threading import Thread

import epics
from automation1 import PsoDistanceInput, PsoOutputPin, PsoWindowInput
from epics import caget, camonitor, caput
from pyautomation import PyAutomation
from pyautomation.controller import AutomationAxis
from pyautomation.modules import Trajectory
from qtpy import QtCore, QtGui, QtWidgets

from sxrd_collect.config import (
    DETECTOR_FILE_PATH,
    FILEPATH,
    eiger2_crysalis_config,
    epics_config,
    file_format_string,
    log_file,
    pilatus_crysalis_config,
)
from sxrd_collect.crysalis_creator import (
    copy_set_ccd,
    create_par_file,
    createCrysalis,
    make_directory,
    transform_cbf_to_esperanto,
    transform_h5_to_esperanto,
)
from sxrd_collect.measurement import (
    collect_single_data,
    collect_step_data,
    collect_wide_data,
    move_to_sample_pos,
)
from sxrd_collect.models import SxrdModel
from sxrd_collect.views.MainView import MainView

logger = logging.getLogger()


class MainController(object):
    def __init__(self):
        self.widget = MainView(__version__)
        self.widget.show()
        self.detector = "eiger2"
        self.model = SxrdModel()
        self.connect_buttons()
        self.connect_tables()
        self.connect_txt()
        # self.populate_filename()
        self.connect_checkboxes()
        self.abort_collection = False
        self.logging_handler = InfoLoggingHandler(self.update_status_txt)
        logger.addHandler(self.logging_handler)
        self.status_txt_scrollbar_is_at_max = True
        self.widget.setup_table.resizeColumnsToContents()
        self.example_str = " "
        self.crysalis_config = CrysalisConfig()
        self.filepath = ""
        self.basename = ""

        self.hor_motor_name = epics_config["sample_position_x"]
        self.ver_motor_name = epics_config["sample_position_y"]
        self.focus_motor_name = epics_config["sample_position_z"]

        # Create timer
        self.epics_update_timer = QtCore.QTimer(self.widget)

        self.connect_timer()
        self.epics_update_timer.start(1000)

        # Alternative view for detector and crysalis
        self.cmb_detectors = QtWidgets.QComboBox()

        self.config_alternative_view()

        theta_axis = AutomationAxis(name="Theta", counts_per_unit=1491308.0888888889)
        self.automation1 = PyAutomation(
            ip="10.54.160.27",
            axis=[theta_axis],
            verbose=True,
            pso_distance_input=PsoDistanceInput.iXC4ePrimaryFeedback,
            pso_window_input=PsoWindowInput.iXC4ePrimaryFeedback,
            pso_output_pin=PsoOutputPin.iXC4eAuxiliaryMarkerDifferential,
        )
        self.automation1.enable_controller()

    def config_alternative_view(self):
        # Add detector combo box to layout.
        self.widget.horizontalLayout_9.removeWidget(self.widget.crysalis_config_btn)
        self.widget.horizontalLayout_9.addWidget(
            self.cmb_detectors, alignment=QtCore.Qt.AlignLeft
        )
        self.widget.horizontalLayout_9.addWidget(self.widget.crysalis_config_btn)

        self.cmb_detectors.setMinimumSize(QtCore.QSize(75, 32))
        self.cmb_detectors.setStyleSheet("padding: 0 3px 0 13px;")

        # Connect combo box
        self.cmb_detectors.currentIndexChanged.connect(self.detector_selection_changed)

        # Add choices.
        self.cmb_detectors.addItem("Eiger 2S 9M")
        self.cmb_detectors.addItem("Pilatus 300K")
        self.cmb_detectors.addItem("Pilatus 1M")
        self.cmb_detectors.addItem("Pilatus MCdTe")

        # Set crysalis config to visible.
        self.widget.crysalis_config_btn.setVisible(True)

    def detector_selection_changed(self):
        if self.cmb_detectors.currentText().startswith("Eiger"):
            self.detector = "eiger2"
        else:
            self.detector = "pilatus"

        self.clear_experiment_setup_btn_clicked(True)

    def connect_checkboxes(self):
        self.widget.no_suffices_cb.clicked.connect(
            lambda: self.update_cb("no_suffices")
        )
        self.widget.rename_after_cb.clicked.connect(lambda: self.update_cb("rename"))
        self.widget.rename_files_cb.clicked.connect(lambda: self.update_cb("rename"))
        self.widget.rename_files_sp_cb.clicked.connect(self.set_example_lbl)
        self.widget.rename_files_pp_cb.clicked.connect(self.set_example_lbl)
        self.widget.rename_files_en_cb.clicked.connect(self.set_example_lbl)
        self.widget.rename_files_suf_cb.clicked.connect(self.set_example_lbl)
        # self.widget.rename_files_fn_cb.clicked.connect(self.set_example_lbl)
        self.widget.check_all_still_cb.clicked.connect(self.check_all_still)
        self.widget.check_all_wide_cb.clicked.connect(self.check_all_wide)
        self.widget.check_all_step_cb.clicked.connect(self.check_all_step)

    def update_cb(self, emitter):
        if emitter == "no_suffices":
            if self.widget.no_suffices_cb.isChecked():
                self.widget.rename_files_cb.setChecked(False)
                self.widget.rename_after_cb.setChecked(False)
        elif emitter == "rename":
            if (
                self.widget.rename_files_cb.isChecked()
                or self.widget.rename_after_cb.isChecked()
            ):
                self.widget.no_suffices_cb.setChecked(False)
        self.set_example_lbl()

    def connect_buttons(self):
        self.widget.epics_config_btn.clicked.connect(self.configure_epics_clicked)
        self.widget.crysalis_config_btn.clicked.connect(
            self.crysalis_config_btn_clicked
        )

        self.widget.add_setup_btn.clicked.connect(self.add_experiment_setup_btn_clicked)
        self.widget.delete_setup_btn.clicked.connect(
            self.delete_experiment_setup_btn_clicked
        )
        self.widget.clear_setup_btn.clicked.connect(
            self.clear_experiment_setup_btn_clicked
        )

        self.widget.add_sample_btn.clicked.connect(self.add_sample_point_btn_clicked)
        self.widget.delete_sample_btn.clicked.connect(
            self.delete_sample_point_btn_clicked
        )
        self.widget.clear_sample_btn.clicked.connect(
            self.clear_sample_point_btn_clicked
        )
        self.widget.create_map_btn.clicked.connect(self.create_map_btn_clicked)

        self.widget.get_folder_btn.clicked.connect(self.get_folder_btn_clicked)
        self.widget.select_folder_btn.clicked.connect(self.select_folder_btn_clicked)

        self.widget.get_basename_btn.clicked.connect(self.get_basename_btn_clicked)
        self.widget.get_framenr_btn.clicked.connect(self.get_framenr_btn_clicked)

        self.widget.collect_btn.clicked.connect(self.collect_data)
        self.widget.collect_btn.mouseHover.connect(self.update_current_position)

        self.widget.load_setup_btn.clicked.connect(self.load_exp_setup)
        self.widget.save_setup_btn.clicked.connect(self.save_exp_setup)

        self.widget.omega_pm1_btn.clicked.connect(lambda: self.omega_btn_clicked(1.0))
        self.widget.omega_pm3_btn.clicked.connect(lambda: self.omega_btn_clicked(3.0))
        self.widget.omega_pm10_btn.clicked.connect(lambda: self.omega_btn_clicked(10.0))
        self.widget.omega_pm20_btn.clicked.connect(lambda: self.omega_btn_clicked(20.0))
        self.widget.omega_pm38_btn.clicked.connect(lambda: self.omega_btn_clicked(38.0))
        self.widget.omega_set_btn.clicked.connect(
            lambda: self.omega_btn_clicked(
                abs(float(self.widget.omega_range_txt.text()))
            )
        )

        self.widget.set_map_range_02_btn.clicked.connect(
            lambda: self.set_map_range(0.02)
        )
        self.widget.set_map_range_01_btn.clicked.connect(
            lambda: self.set_map_range(0.01)
        )
        self.widget.set_map_range_006_btn.clicked.connect(
            lambda: self.set_map_range(0.006)
        )
        self.widget.set_map_range_004_btn.clicked.connect(
            lambda: self.set_map_range(0.004)
        )
        self.widget.set_map_range_btn.clicked.connect(
            lambda: self.set_map_range(self.widget.map_range_txt.text())
        )

        self.widget.set_map_step_005_btn.clicked.connect(
            lambda: self.set_map_step(0.005)
        )
        self.widget.set_map_step_003_btn.clicked.connect(
            lambda: self.set_map_step(0.003)
        )
        self.widget.set_map_step_002_btn.clicked.connect(
            lambda: self.set_map_step(0.002)
        )
        self.widget.set_map_step_001_btn.clicked.connect(
            lambda: self.set_map_step(0.001)
        )
        self.widget.set_map_step_btn.clicked.connect(
            lambda: self.set_map_step(self.widget.map_step_txt.text())
        )

        self.widget.open_path_btn.clicked.connect(self.open_path_btn_clicked)
        self.widget.framenr_reset_btn.clicked.connect(self.reset_frame_nr)

    def connect_tables(self):
        self.widget.setup_table.cellChanged.connect(self.setup_table_cell_changed)
        self.widget.sample_points_table.cellChanged.connect(
            self.sample_points_table_cell_changed
        )

        self.widget.move_sample_btn_clicked.connect(self.move_sample_btn_clicked)
        self.widget.set_sample_btn_clicked.connect(self.set_sample_btn_clicked)

        self.widget.step_cb_status_changed.connect(self.step_cb_status_changed)
        self.widget.wide_cb_status_changed.connect(self.wide_cb_status_changed)
        self.widget.still_cb_status_changed.connect(self.still_cb_status_changed)

    def connect_txt(self):
        self.widget.filename_txt.editingFinished.connect(self.basename_txt_changed)
        self.widget.filepath_txt.editingFinished.connect(self.filepath_txt_changed)
        self.widget.frame_number_txt.editingFinished.connect(
            self.frame_number_txt_changed
        )

        self.widget.status_txt.textChanged.connect(self.update_status_txt_scrollbar)
        self.widget.status_txt.verticalScrollBar().valueChanged.connect(
            self.update_status_txt_scrollbar_value
        )

    def connect_timer(self):
        self.epics_update_timer.timeout.connect(self.auto_update_current_motor_position)

    def populate_filename(self):
        self.prev_filepath, self.prev_filename, self.prev_file_number = (
            self.get_filename_info(self.detector)
        )

        self.filepath = self.prev_filepath
        self.basename = self.prev_filename

        self.widget.filename_txt.setText(self.prev_filename)
        self.widget.filepath_txt.setText(self.prev_filepath)
        self.widget.frame_number_txt.setText(str(self.prev_file_number))

        self.set_example_lbl()

    def update_status_txt(self, msg):
        self.widget.status_txt.append(msg)

    def update_status_txt_scrollbar(self):
        if self.status_txt_scrollbar_is_at_max:
            self.widget.status_txt.verticalScrollBar().setValue(
                self.widget.status_txt.verticalScrollBar().maximum()
            )

    def get_folder_btn_clicked(self):
        self.prev_filepath, _, _ = self.get_filename_info(self.detector)
        self.filepath = self.prev_filepath
        self.widget.filepath_txt.setText(self.prev_filepath)
        self.filepath_txt_changed()
        self.set_example_lbl()

    def select_folder_btn_clicked(self):
        """
        Initiates a folder browser dialog. Sets a new filepath.
        """
        path = FILEPATH + self.filepath[4:]
        folder = str(
            QtWidgets.QFileDialog.getExistingDirectory(
                self.widget, "Select Directory", path
            )
        )

        if folder != "":
            nr = len(FILEPATH)
            text = DETECTOR_FILE_PATH + folder[nr:]

            print(f"PATH {text}")
            text = text.replace("\\", "/")
            self.widget.filepath_txt.setText(text)

        self.filepath_txt_changed()
        self.set_example_lbl()

    def get_basename_btn_clicked(self):
        _, self.prev_filename, _ = self.get_filename_info(self.detector)
        self.basename = self.prev_filename
        self.widget.filename_txt.setText(self.basename)
        self.set_example_lbl()

    def get_framenr_btn_clicked(self):
        _, _, self.prev_file_number = self.get_filename_info(self.detector)
        self.file_number = self.prev_file_number
        self.widget.frame_number_txt.setText(str(self.file_number))
        self.set_example_lbl()

    def update_status_txt_scrollbar_value(self, value):
        self.status_txt_scrollbar_is_at_max = (
            value == self.widget.status_txt.verticalScrollBar().maximum()
        )

    def update_current_position(self):
        self.widget.current_position_lbl.setText(
            "  Current position:"
            + "\tx: "
            + str(round(caget("13IDD:m98.RBV"), 3))
            + "\t\ty: "
            + str(round(caget("13IDD:m97.RBV"), 3))
            + "\t\tz: "
            + str(round(caget("13IDD:m99.RBV"), 3))
        )

        pos_x, pos_y, pos_z = self.get_current_sample_position()
        if len(self.model.sample_points):
            sp_x = self.model.sample_points[0].x
            sp_y = self.model.sample_points[0].y
            sp_z = self.model.sample_points[0].z
        else:
            return

        if (
            abs(sp_x - pos_x) < 3e-4
            and abs(sp_y - pos_y) < 3e-4
            and abs(sp_z - pos_z) < 3e-4
        ):
            self.widget.current_position_lbl.setStyleSheet("font: 11px; color: black;")
        else:
            self.widget.current_position_lbl.setStyleSheet(
                "font: bold 14px; color: red;"
            )

    def load_exp_setup(self):
        filename, _ = QtWidgets.QFileDialog.getOpenFileName(
            self.widget, caption="Load experiment setup file", filter="*.ini"
        )
        filename = str(filename)
        if filename != "":
            with open(filename) as f:
                for line in f:
                    (
                        name,
                        detector_pos_x,
                        detector_pos_z,
                        omega_start,
                        omega_end,
                        omega_step,
                        step_time,
                    ) = line.split(";")
                    self.model.add_experiment_setup(
                        name,
                        float(detector_pos_x),
                        float(detector_pos_z),
                        float(omega_start),
                        float(omega_end),
                        float(omega_step),
                        float(step_time),
                    )
                    self.widget.add_experiment_setup(
                        name,
                        float(detector_pos_x),
                        float(detector_pos_z),
                        float(omega_start),
                        float(omega_end),
                        float(omega_step),
                        float(step_time),
                    )
        self.widget.setup_table.resizeColumnsToContents()

    def save_exp_setup(self):
        filename, _ = QtWidgets.QFileDialog.getSaveFileName(
            self.widget, caption="Save experiment setup file", filter="*.ini"
        )
        filename = str(filename)
        if filename != "":
            with open(filename, "w+") as f:
                for experiment_setup in self.model.experiment_setups:
                    f.write(experiment_setup.save())
                    f.write("\n")

    def reset_frame_nr(self):
        self.widget.frame_number_txt.setText("1")
        if self.detector == "pilatus":
            caput(epics_config[self.detector] + ":TIFF1:FileNumber", 1, wait=True)
        elif self.detector == "eiger2":
            caput(epics_config[self.detector] + ":HDF1:FileNumber", 1, wait=True)
        self.set_example_lbl()

    def add_experiment_setup_btn_clicked(self):
        detector_pos_x, detector_pos_z, omega, exposure_time = self.get_current_setup()
        default_name = "E{}".format(len(self.model.experiment_setups) + 1)
        self.model.add_experiment_setup(
            default_name,
            detector_pos_x,
            detector_pos_z,
            omega - 1,
            omega + 1,
            1,
            exposure_time,
        )
        self.widget.add_experiment_setup(
            default_name,
            detector_pos_x,
            detector_pos_z,
            omega - 1,
            omega + 1,
            1,
            exposure_time,
        )
        self.widget.setup_table.resizeColumnsToContents()

    def delete_experiment_setup_btn_clicked(self):
        cur_ind = self.widget.get_selected_experiment_setup()
        cur_ind.sort()
        cur_ind = cur_ind[::-1]
        if cur_ind is None or (len(cur_ind) == 0):
            return
        msgBox = QtWidgets.QMessageBox()
        msgBox.setText("Do you really want to delete selected experiment(s)?")
        msgBox.setWindowTitle("Confirmation")
        msgBox.setStandardButtons(QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
        msgBox.setDefaultButton(QtWidgets.QMessageBox.Yes)
        response = msgBox.exec_()
        if response == QtWidgets.QMessageBox.Yes:
            for ind in cur_ind:
                self.widget.delete_experiment_setup(ind)
                self.model.delete_experiment_setup(ind)
            self.widget.recreate_sample_point_checkboxes(
                self.model.get_experiment_state()
            )
        self.set_example_lbl()
        self.set_total_frames()

    def clear_experiment_setup_btn_clicked(self, auto_yes=False):
        msgBox = QtWidgets.QMessageBox()
        msgBox.setText("Do you really want to delete all experiments?")
        msgBox.setWindowTitle("Confirmation")
        msgBox.setStandardButtons(QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
        msgBox.setDefaultButton(QtWidgets.QMessageBox.Yes)
        response = msgBox.exec_()
        if response == QtWidgets.QMessageBox.Yes or auto_yes:
            self.widget.clear_experiment_setups()
            self.model.clear_experiment_setups()
            self.widget.recreate_sample_point_checkboxes(
                self.model.get_experiment_state()
            )
        self.set_example_lbl()
        self.set_total_frames()

    def add_sample_point_btn_clicked(self):
        x, y, z = self.get_current_sample_position()
        num = len(self.model.sample_points)
        self.widget.add_sample_point(
            "S{}".format(num + 1),
            x,
            y,
            z,
            self.widget.check_all_still_cb.isChecked(),
            self.widget.check_all_wide_cb.isChecked(),
            self.widget.check_all_step_cb.isChecked(),
        )
        self.model.add_sample_point(
            "S{}".format(num + 1),
            x,
            y,
            z,
            self.widget.check_all_step_cb.isChecked(),
            self.widget.check_all_wide_cb.isChecked(),
            self.widget.check_all_still_cb.isChecked(),
        )
        self.widget.recreate_sample_point_checkboxes(self.model.get_experiment_state())
        self.set_example_lbl()
        self.set_total_frames()

    def delete_sample_point_btn_clicked(self):
        cur_ind = self.widget.get_selected_sample_point()
        cur_ind.sort()
        cur_ind = cur_ind[::-1]
        for ind in cur_ind:
            self.widget.delete_sample_point(ind)
            self.model.delete_sample_point(ind)
        self.set_example_lbl()
        self.set_total_frames()

    def clear_sample_point_btn_clicked(self):
        self.widget.clear_sample_points()
        self.model.clear_sample_points()
        self.set_total_frames()
        self.set_example_lbl()

    def create_map_btn_clicked(self):
        cur_ind = self.widget.get_selected_sample_point()[-1]

        x_min = float(str(self.widget.x_min_txt.text()))
        x_max = float(str(self.widget.x_max_txt.text()))
        x_step = float(str(self.widget.x_step_txt.text()))

        y_min = float(str(self.widget.y_min_txt.text()))
        y_max = float(str(self.widget.y_max_txt.text()))
        y_step = float(str(self.widget.y_step_txt.text()))

        map = self.model.create_map(cur_ind, x_min, x_max, x_step, y_min, y_max, y_step)

        for name in map:
            position = map[name]
            x, y, z = position
            self.widget.add_sample_point(name, x, y, z)

        self.set_total_frames()

    def setup_table_cell_changed(self, row, col):
        label_item = self.widget.setup_table.item(row, col)
        value = str(label_item.text())
        self.widget.setup_table.blockSignals(True)
        if col == 0:
            if not self.model.setup_name_existent(value):
                self.model.experiment_setups[row].name = str(value)
                self.widget.update_sample_table_setup_header(
                    self.model.get_experiment_setup_names()
                )
                self.widget.sample_points_table.resizeColumnsToContents()
            else:
                self.create_name_existent_msg("Experiment setup")
                name_item = self.widget.setup_table.item(row, 0)
                name_item.setText(self.model.experiment_setups[row].name)
        else:
            value = float(value)
            if col == 1:
                self.model.experiment_setups[row].detector_pos_x = value
            elif col == 2:
                self.model.experiment_setups[row].detector_pos_z = value
            elif col == 3:
                if value >= int(caget("13IDD:Auto1:m1.LLM")) and value <= int(
                    caget("13IDD:Auto1:m1.HLM")
                ):
                    self.model.experiment_setups[row].omega_start = value
                    self.update_total_exposure_time(row)
                else:
                    self.model.experiment_setups[row].omega_start = 0.0
                    self.widget.setup_table.item(row, 3).setText("0.0")
                    self.update_total_exposure_time(row)
                    self.create_omega_error_msg("Starting omega value is incorrect")
            elif col == 4:
                if value >= int(caget("13IDD:Auto1:m1.LLM")) and value <= int(
                    caget("13IDD:Auto1:m1.HLM")
                ):
                    self.model.experiment_setups[row].omega_end = value
                    self.update_total_exposure_time(row)
                else:
                    self.model.experiment_setups[row].omega_end = 0.0
                    self.widget.setup_table.item(row, 4).setText("0.0")
                    self.update_total_exposure_time(row)
                    self.create_omega_error_msg("End omega value is incorrect")
            elif col == 5:
                value = round(value, 1)
                self.widget.setup_table.item(row, 5).setText(str(value))
                self.model.experiment_setups[row].omega_step = value
                self.update_total_exposure_time(row)
            elif col == 6:
                if value / self.model.experiment_setups[row].omega_step < 0.5:
                    fixed_value = 0.5 * self.model.experiment_setups[row].omega_step
                    self.model.experiment_setups[row].time_per_step = fixed_value
                    self.widget.setup_table.item(row, col).setText(str(fixed_value))
                    self.create_omega_error_msg(
                        "Time per degree of rotation must be at least 0.5 sec"
                    )
                else:
                    self.model.experiment_setups[row].time_per_step = value
                self.update_total_exposure_time(row)
            elif col == 7:
                step_time = self.model.experiment_setups[row].get_step_exposure_time(
                    value
                )
                step_exposure_time_item = self.widget.setup_table.item(row, 6)
                step_time = float("{0:.2f}".format(step_time))
                step_exposure_time_item.setText(str(step_time))
                self.model.experiment_setups[row].time_per_step = step_time
                self.update_total_exposure_time(row)

            # elif col == 8:
            #     self.model.experiment_setups[row].steps_per_image = value

        self.widget.setup_table.blockSignals(False)
        self.widget.setup_table.resizeColumnsToContents()
        self.set_example_lbl()
        self.set_total_frames()
        print(self.model.experiment_setups[row])

    def update_total_exposure_time(self, row):
        total_exposure_time_item = self.widget.setup_table.item(row, 7)
        omega_range = abs(
            float(self.widget.setup_table.item(row, 3).text())
            - float(self.widget.setup_table.item(row, 4).text())
        )
        total_exp_time = self.model.experiment_setups[row].get_total_exposure_time()
        velocity = omega_range / total_exp_time
        if velocity >= 5:
            self.create_omega_error_msg("Omega velocity is too fast")
        else:
            total_exposure_time_item.setText("{:.2f}".format(total_exp_time))

    def sample_points_table_cell_changed(self, row, col):
        label_item = self.widget.sample_points_table.item(row, col)
        value = str(label_item.text())
        self.widget.sample_points_table.blockSignals(True)
        if col == 0:
            if not self.model.sample_name_existent(value):
                self.model.sample_points[row].name = str(value)
            else:
                self.create_name_existent_msg("Sample")
                name_item = self.widget.sample_points_table.item(row, 0)
                name_item.setText(self.model.sample_points[row].name)
        elif col == 1:
            self.model.sample_points[row].x = float(value)
        elif col == 2:
            self.model.sample_points[row].y = float(value)
        elif col == 3:
            self.model.sample_points[row].z = float(value)
        self.widget.sample_points_table.blockSignals(False)
        self.widget.sample_points_table.resizeColumnsToContents()
        self.set_example_lbl()
        print(self.model.sample_points[row])

    def omega_btn_clicked(self, omega_range):
        cur_ind = self.widget.get_selected_experiment_setup()
        cur_ind.sort()
        cur_ind = cur_ind[::-1]
        omega_start = 0.0 - omega_range
        omega_end = 0.0 + omega_range
        if cur_ind is None or (len(cur_ind) == 0):
            return
        for ind in cur_ind:
            self.widget.setup_table.item(ind, 3).setText(str(omega_start))
            self.widget.setup_table.item(ind, 4).setText(str(omega_end))
            self.model.experiment_setups[ind].omega_start = omega_start
            self.model.experiment_setups[ind].omega_end = omega_end
            # Speeding up experiment parameter modifications for most used wide and step scans
            # This is a step scan ===> modify step size and exposure time
            if omega_range >= 30:
                self.widget.setup_table.item(ind, 5).setText(str(0.5))
                self.model.experiment_setups[ind].omega_step = 0.5
                self.widget.setup_table.item(ind, 6).setText(str(2))
                self.model.experiment_setups[ind].time_per_step = 2
            # This is a wide scan ===> modify step size and exposure time
            elif omega_range == 20:
                self.widget.setup_table.item(ind, 5).setText(str(40))
                self.model.experiment_setups[ind].omega_step = 40
                self.widget.setup_table.item(ind, 6).setText(str(20))
                self.model.experiment_setups[ind].time_per_step = 20
            elif omega_range == 1:
                self.widget.setup_table.item(ind, 5).setText(str(2))
                self.model.experiment_setups[ind].omega_step = 2
                self.widget.setup_table.item(ind, 6).setText(str(2))
                self.model.experiment_setups[ind].time_per_step = 2
            self.update_total_exposure_time(ind)

    def set_map_range(self, orange):
        self.widget.y_min_txt.setText("-" + str(orange))
        self.widget.x_min_txt.setText("-" + str(orange))
        self.widget.y_max_txt.setText(str(orange))
        self.widget.x_max_txt.setText(str(orange))

    def set_map_step(self, step):
        self.widget.x_step_txt.setText(str(step))
        self.widget.y_step_txt.setText(str(step))

    def move_sample_btn_clicked(self, ind):
        x, y, z = self.widget.get_sample_point_values(ind)
        move_to_sample_pos(x, y, z)

    def set_sample_btn_clicked(self, ind):
        x, y, z = self.get_current_sample_position()
        self.model.sample_points[ind].set_position(x, y, z)
        self.widget.set_sample_point_values(ind, x, y, z)

    def step_cb_status_changed(self, row_ind, exp_ind, state):
        cur_ind = self.widget.get_selected_sample_point()
        if row_ind in cur_ind:
            for ind in cur_ind:
                self.model.sample_points[ind].set_perform_step_scan_setup(
                    exp_ind, state
                )
            self.widget.recreate_sample_point_checkboxes(
                self.model.get_experiment_state()
            )
        else:
            self.model.sample_points[row_ind].set_perform_step_scan_setup(
                exp_ind, state
            )
        self.set_example_lbl()
        self.set_total_frames()

    def wide_cb_status_changed(self, row_ind, exp_ind, state):
        cur_ind = self.widget.get_selected_sample_point()
        if row_ind in cur_ind:
            for ind in cur_ind:
                self.model.sample_points[ind].set_perform_wide_scan_setup(
                    exp_ind, state
                )
            self.widget.recreate_sample_point_checkboxes(
                self.model.get_experiment_state()
            )
        else:
            self.model.sample_points[row_ind].set_perform_wide_scan_setup(
                exp_ind, state
            )
        self.set_example_lbl()
        self.set_total_frames()

    def still_cb_status_changed(self, row_ind, exp_ind, state):
        cur_ind = self.widget.get_selected_sample_point()
        if row_ind in cur_ind:
            for ind in cur_ind:
                self.model.sample_points[ind].set_perform_still_setup(exp_ind, state)
            self.widget.recreate_sample_point_checkboxes(
                self.model.get_experiment_state()
            )
        else:
            self.model.sample_points[row_ind].set_perform_still_setup(exp_ind, state)
        self.set_example_lbl()
        self.set_total_frames()

    def check_all_still(self):
        for exp_ind, experiment in enumerate(self.model.experiment_setups):
            for sample_point in self.model.sample_points:
                sample_point.set_perform_still_setup(
                    exp_ind, self.widget.check_all_still_cb.isChecked()
                )
        self.widget.recreate_sample_point_checkboxes(self.model.get_experiment_state())
        self.set_example_lbl()
        self.set_total_frames()

    def check_all_wide(self):
        for exp_ind, experiment in enumerate(self.model.experiment_setups):
            for sample_point in self.model.sample_points:
                sample_point.set_perform_wide_scan_setup(
                    exp_ind, self.widget.check_all_wide_cb.isChecked()
                )
        self.widget.recreate_sample_point_checkboxes(self.model.get_experiment_state())
        self.set_example_lbl()
        self.set_total_frames()

    def check_all_step(self):
        for exp_ind, experiment in enumerate(self.model.experiment_setups):
            for sample_point in self.model.sample_points:
                sample_point.set_perform_step_scan_setup(
                    exp_ind, self.widget.check_all_step_cb.isChecked()
                )
        self.widget.recreate_sample_point_checkboxes(self.model.get_experiment_state())
        self.set_example_lbl()
        self.set_total_frames()

    def basename_txt_changed(self):
        self.basename = str(self.widget.filename_txt.text())
        if self.detector == "pilatus":
            caput(
                epics_config[self.detector] + ":TIFF1:FileName",
                self.basename,
                wait=True,
            )
        elif self.detector == "eiger2":
            caput(
                epics_config[self.detector] + ":HDF1:FileName", self.basename, wait=True
            )
        self.set_example_lbl()

    def filepath_txt_changed(self):
        self.filepath = str(self.widget.filepath_txt.text())
        if self.filepath[-1] == "/":
            self.filepath = self.filepath[:-1]

        self.widget.filepath_txt.setText(self.filepath)

        if self.detector == "pilatus":
            caput(
                epics_config[self.detector] + ":TIFF1:FilePath",
                self.filepath,
                wait=True,
            )
        elif self.detector == "eiger2":
            caput(
                epics_config[self.detector] + ":HDF1:FilePath", self.filepath, wait=True
            )
        self.set_example_lbl()

    def frame_number_txt_changed(self):
        self.framenr = int(self.widget.frame_number_txt.text())
        if self.detector == "pilatus":
            caput(
                epics_config[self.detector] + ":TIFF1:FileNumber",
                self.framenr,
                wait=True,
            )
        elif self.detector == "eiger2":
            caput(
                epics_config[self.detector] + ":HDF1:FileNumber",
                self.framenr,
                wait=True,
            )
        self.set_example_lbl()

    def set_total_frames(self):
        nr = self.frame_counter()
        tm = self.estimate_collection_time(epics_config)
        if nr == 0:
            self.widget.total_frames_txt.setText(" ")
        elif nr == 1:
            self.widget.total_frames_txt.setText(
                str(nr) + " image" + "\n" + str(int(tm)) + " s"
            )
        else:
            self.widget.total_frames_txt.setText(
                str(nr) + " images" + "\n" + str(int(tm)) + " s"
            )

    def set_example_lbl(self):
        no_exp = False
        if self.widget.no_suffices_cb.isChecked():
            _, _, filenumber = self.get_filename_info(self.detector)
            example_str = (
                self.filepath + "/" + self.basename + "_" + str("%03d" % filenumber)
            )

        elif self.widget.rename_files_cb.isChecked():
            no_exp = True
            if (
                len(self.model.experiment_setups) == 0
                or len(self.model.sample_points) == 0
            ):
                example_str = (
                    self.filepath + "/" + self.basename + "_" + "S1_P1_E1_s_001"
                )
            else:
                for exp_ind, experiment in enumerate(self.model.experiment_setups):
                    for sample_point in self.model.sample_points:
                        if sample_point.perform_still_for_setup[exp_ind]:
                            example_str = self.build_file_name(
                                sample_point.name, experiment.name, "001"
                            )
                            no_exp = False
                            break
                        elif sample_point.perform_wide_scan_for_setup[exp_ind]:
                            example_str = self.build_file_name(
                                sample_point.name, experiment.name, "w_001"
                            )
                            no_exp = False
                            break
                        elif sample_point.perform_step_scan_for_setup[exp_ind]:
                            example_str = self.build_file_name(
                                sample_point.name, experiment.name, "s_001"
                            )
                            no_exp = False
                            break
                if no_exp:
                    example_str = (
                        self.filepath + "/" + self.basename + "_" + "S1_P1_E1_s_001"
                    )
        else:
            if self.detector == "pilatus":
                example_str = (
                    self.filepath
                    + "/"
                    + caget(
                        epics_config[self.detector] + ":TIFF1:FileName", as_string=True
                    )
                    + "_"
                    + str(
                        "%03d"
                        % caget(epics_config[self.detector] + ":TIFF1:FileNumber")
                    )
                )
            elif self.detector == "eiger2":
                example_str = (
                    self.filepath
                    + "/"
                    + caget(
                        epics_config[self.detector] + ":HDF1:FileName", as_string=True
                    )
                    + "_"
                    + str(
                        "%03d" % caget(epics_config[self.detector] + ":HDF1:FileNumber")
                    )
                )
            if example_str is None:
                example_str = self.filepath + "/None"

        self.example_str = example_str

        if (
            len(self.model.experiment_setups) == 0
            or len(self.model.sample_points) == 0
            or no_exp
        ):
            if len(example_str) > 40:
                example_str = "..." + example_str[len(example_str) - 40 :]
            self.widget.example_filename_lbl.setText(
                "<font color = '#888888'>" + example_str + ".tif</font>"
            )
            return
        elif self.check_filename_exists(FILEPATH + example_str[4:]):
            if len(example_str) > 30:
                example_str = "..." + example_str[len(example_str) - 30 :]
            self.widget.example_filename_lbl.setText(
                "<font color = '#AA0000' style='font-weight:bold'>"
                + example_str
                + ".tif</font>"
            )
            return
        elif not self.check_filepath_exists():
            if len(example_str) > 40:
                example_str = "..." + example_str[len(example_str) - 40 :]
            self.widget.example_filename_lbl.setText(
                "<font color = '#FF5500'>" + example_str + ".tif</font>"
            )
            return
        else:
            if len(example_str) > 40:
                example_str = "..." + example_str[len(example_str) - 40 :]
            self.widget.example_filename_lbl.setText(
                "<font color = '#228B22'>" + example_str + ".tif</font>"
            )
            return

    def configure_epics_clicked(self):
        pass

    def crysalis_config_btn_clicked(self):
        self.crysalis_config.setVisible(True)

    def open_path_btn_clicked(self):
        path = FILEPATH + self.filepath[4:]
        os.startfile(path)

    def collect_bkg_data(self):
        self.set_status_lbl("Collecting", "#FF0000")
        QtWidgets.QApplication.processEvents()
        self.set_status_lbl("Finished", "#00FF00")

    def collect_data(self):
        # check if the current file path exists
        if self.check_filepath_exists() is False:
            self.show_error_message_box(
                "The folder you specified does not exist. "
                "Please enter a valid path for saving the collected images!"
            )
            return

        all_filenames = self.build_all_file_names()

        if self.check_for_duplicate_file_names(all_filenames):
            self.show_error_message_box(
                "There are duplicate file names being created \n"
                + "Please check your settings"
            )
            return

        # for file_name in all_filenames:
        #     file_path = FILEPATH + self.filepath[4:]
        #     file_name_to_check = os.path.join(file_path, file_name)
        #     if self.check_filename_exists(file_name_to_check):
        #         self.show_error_message_box('Some filenames already exist' + '\n'
        #                                                                  'Please check your settings!')
        #         return

        if self.check_filename_exists(FILEPATH + self.example_str[4:]):
            self.show_error_message_box(
                "The filename already exists" + "\nPlease used different filename!"
            )
            return

        # check if sample position are not very far away from the current position (in case users forgot to update
        # positions....) maximum value is right now set to 200um distance
        if self.check_sample_point_distances(0.2) is False:
            reply = self.show_continue_abort_message_box(
                "Some measurement points are more than 200um away from the current sample "
                + "position.<br> Do you want to continue?!"
            )
            if reply == QtWidgets.QMessageBox.Abort:
                return

        if len(self.model.sample_points) == 1:
            if self.check_sample_point_distances(0.0) is False:
                reply = self.show_continue_abort_message_box(
                    "The measurement point is away from the current sample "
                    + "position.<br> Do you want to continue?!"
                )
                if reply == QtWidgets.QMessageBox.Abort:
                    return

        with open(log_file, "a") as outfile:
            logstr = time.asctime() + ": "
            if self.widget.override_pilatus_limits_cb.isChecked():
                logstr += "Overriding Pilatus limits. "
            logstr += "\n"
            outfile.write(logstr)

        nr = self.frame_counter()
        if nr == 1:
            self.set_status_lbl("Collecting" + "\n" + str(nr) + " image", "#FF0000")
        else:
            self.set_status_lbl("Collecting" + "\n" + str(nr) + " images", "#FF0000")
        c_frame = 1

        # save current state to be able to restore after the measurement when the checkboxes are selected.
        previous_filepath, previous_filename, previous_filenumber = (
            self.get_filename_info(self.detector)
        )
        previous_exposure_time = caget(
            epics_config[self.detector] + ":cam1:AcquireTime"
        )
        previous_detector_pos_x = caget(epics_config["detector_position_x"])
        previous_detector_pos_z = caget(epics_config["pilatus_position_z"])
        previous_omega_pos = caget(epics_config["sample_position_omega"])
        sample_x, sample_y, sample_z = self.get_current_sample_position()

        # Make sure to detector triggers are open
        caput(epics_config["detector_trigger_16"], 0, wait=True)
        caput(epics_config["detector_trigger_17"], 0, wait=True)

        # prepare for for abortion of the collection procedure
        self.abort_collection = False
        self.widget.collect_btn.setText("Abort")
        self.widget.collect_btn.clicked.disconnect(self.collect_data)
        self.widget.collect_btn.clicked.connect(self.abort_data_collection)
        self.widget.status_txt.clear()
        QtWidgets.QApplication.processEvents()

        repeat_counter = 0
        while self.widget.repeat_cb.isChecked() or not repeat_counter:
            repeat_counter += 1
            if not self.check_if_aborted():
                break

            for exp_ind, experiment in enumerate(self.model.experiment_setups):
                if not (
                    self.check_omega_in_limits(experiment.omega_start)
                    and self.check_omega_in_limits(experiment.omega_end)
                ):
                    self.show_error_message_box(
                        "Experiment starting and/or end angle are out of epics limits"
                        "Please adjust either of them!"
                    )
                    continue

                for sample_point in self.model.sample_points:
                    if not self.widget.test_mode_cb.isChecked():
                        if not caget("13IDA:eps_mbbi25") or not caget(
                            "13IDA:eps_mbbi26"
                        ):
                            self.set_status_lbl("Waiting for Beam", "#FF0000")
                            logger.info("Beam lost or one of the shutters is closed!")
                            while not caget("13IDA:eps_mbbi25") or not caget(
                                "13IDA:eps_mbbi26"
                            ):
                                QtWidgets.QApplication.processEvents()
                                time.sleep(1.0)
                                if not self.check_if_aborted():
                                    break
                            logger.info("Beam is back!")

                    if not self.check_if_aborted():
                        break

                    if sample_point.perform_still_for_setup[exp_ind]:
                        self.set_status_lbl(
                            "Collecting\n" + str(c_frame) + " of " + str(nr), "#FF0000"
                        )
                        c_frame += 1
                        if self.widget.rename_files_cb.isChecked():
                            filename = self.build_file_name(
                                sample_point.name, experiment.name
                            )
                            # if self.widget.rename_files_fn_cb.isChecked():
                            filenumber = self.widget.frame_number_txt.text()
                            # else:
                            #     filenumber = 1
                            if self.detector == "pilatus":
                                caput(
                                    epics_config[self.detector] + ":TIFF1:FilePath",
                                    str(self.filepath),
                                    wait=True,
                                )
                                caput(
                                    epics_config[self.detector] + ":TIFF1:FileName",
                                    str(filename),
                                    wait=True,
                                )
                                caput(
                                    epics_config[self.detector] + ":TIFF1:FileNumber",
                                    filenumber,
                                    wait=True,
                                )
                            elif self.detector == "eiger2":
                                caput(
                                    epics_config[self.detector] + ":HDF1:FilePath",
                                    str(self.filepath),
                                    wait=True,
                                )
                                caput(
                                    epics_config[self.detector] + ":HDF1:FileName",
                                    str(filename),
                                    wait=True,
                                )
                                caput(
                                    epics_config[self.detector] + ":HDF1:FileNumber",
                                    filenumber,
                                    wait=True,
                                )
                            time.sleep(0.1)

                        elif self.widget.no_suffices_cb.isChecked():
                            filename = self.basename
                            _, _, filenumber = self.get_filename_info(self.detector)
                            if self.detector == "pilatus":
                                caput(
                                    epics_config[self.detector] + ":TIFF1:FilePath",
                                    str(self.filepath),
                                    wait=True,
                                )
                                caput(
                                    epics_config[self.detector] + ":TIFF1:FileName",
                                    str(filename),
                                    wait=True,
                                )
                                caput(
                                    epics_config[self.detector] + ":TIFF1:FileNumber",
                                    filenumber,
                                    wait=True,
                                )
                            elif self.detector == "eiger2":
                                caput(
                                    epics_config[self.detector] + ":HDF1:FilePath",
                                    str(self.filepath),
                                    wait=True,
                                )
                                caput(
                                    epics_config[self.detector] + ":HDF1:FileName",
                                    str(filename),
                                    wait=True,
                                )
                                caput(
                                    epics_config[self.detector] + ":HDF1:FileNumber",
                                    filenumber,
                                    wait=True,
                                )
                        else:
                            _, filename, filenumber = self.get_filename_info(
                                self.detector
                            )

                        logger.info(
                            "Performing still image for:\n\t\t{}\n\t\t{}".format(
                                sample_point, experiment
                            )
                        )
                        exposure_time = (
                            abs(experiment.omega_end - experiment.omega_start)
                            / experiment.omega_step
                            * experiment.time_per_step
                        )

                        current_omega = caget(
                            epics_config["sample_position_omega"], as_string=False
                        )
                        collect_single_data_thread = Thread(
                            target=collect_single_data,
                            kwargs={
                                "detector_choice": self.detector,
                                "detector_position_x": experiment.detector_pos_x,
                                "detector_position_z": experiment.detector_pos_z,
                                "exposure_time": abs(exposure_time),
                                "x": sample_point.x,
                                "y": sample_point.y,
                                "z": sample_point.z,
                                "omega": current_omega,
                            },
                        )
                        collect_single_data_thread.start()

                        while collect_single_data_thread.is_alive():
                            QtWidgets.QApplication.processEvents()
                            time.sleep(0.2)

                    if not self.check_if_aborted():
                        break

                    if sample_point.perform_wide_scan_for_setup[exp_ind]:
                        self.set_status_lbl(
                            "Collecting\n" + str(c_frame) + " of " + str(nr), "#FF0000"
                        )
                        c_frame = c_frame + 1
                        self.check_pilatus_trigger(self.detector)
                        # check if all motor positions are in a correct position
                        if self.check_conditions() is False:
                            self.show_error_message_box(
                                "Please Move mirrors and microscope in the right positions!"
                            )
                            self.reset_gui_state()
                            return

                        if self.widget.rename_files_cb.isChecked():
                            filename = self.build_file_name(
                                sample_point.name, experiment.name, "w"
                            )

                            # Changed - Chris 11 May 2022
                            filenumber = self.widget.frame_number_txt.text()

                        elif self.widget.no_suffices_cb.isChecked():
                            filename = self.basename
                            _, _, filenumber = self.get_filename_info(self.detector)

                        else:
                            _, filename, filenumber = self.get_filename_info(
                                self.detector
                            )

                        if self.detector == "pilatus":
                            caput(
                                epics_config[self.detector] + ":TIFF1:FilePath",
                                str(self.filepath),
                                wait=True,
                            )
                            caput(
                                epics_config[self.detector] + ":TIFF1:FileName",
                                str(filename),
                                wait=True,
                            )
                            caput(
                                epics_config[self.detector] + ":TIFF1:FileNumber",
                                filenumber,
                                wait=True,
                            )
                        elif self.detector == "eiger2":
                            caput(
                                epics_config[self.detector] + ":HDF1:FilePath",
                                str(self.filepath),
                                wait=True,
                            )
                            caput(
                                epics_config[self.detector] + ":HDF1:FileName",
                                str(filename),
                                wait=True,
                            )
                            caput(
                                epics_config[self.detector] + ":HDF1:FileNumber",
                                filenumber,
                                wait=True,
                            )

                        logger.info(
                            "Performing wide scan for:\n\t\t{}\n\t\t{}".format(
                                sample_point, experiment
                            )
                        )
                        exposure_time = (
                            abs(experiment.omega_end - experiment.omega_start)
                            / experiment.omega_step
                            * experiment.time_per_step
                        )

                        collect_wide_data_thread = Thread(
                            target=collect_wide_data,
                            kwargs={
                                "controller": self.automation1,
                                "detector_choice": self.detector,
                                "detector_position_x": experiment.detector_pos_x,
                                "detector_position_z": experiment.detector_pos_z,
                                "omega_start": experiment.omega_start,
                                "omega_end": experiment.omega_end,
                                "exposure_time": abs(exposure_time),
                                "x": sample_point.x,
                                "y": sample_point.y,
                                "z": sample_point.z,
                            },
                        )
                        collect_wide_data_thread.start()

                        while collect_wide_data_thread.is_alive():
                            QtWidgets.QApplication.processEvents()
                            time.sleep(0.2)

                        time.sleep(0.1)

                    if not self.check_if_aborted():
                        break

                    if sample_point.perform_step_scan_for_setup[exp_ind]:
                        self.set_status_lbl("Collecting...", "#FF0000")
                        c_frame += 1
                        # check if all motor positions are in a correct position
                        previous_detector_settings = {}
                        self.check_pilatus_trigger(self.detector)
                        if self.check_conditions() is False:
                            self.show_error_message_box(
                                "Please Move mirrors and microscope in the right positions!"
                            )
                            self.reset_gui_state()
                            return

                        if self.widget.rename_files_cb.isChecked():
                            filename = self.build_file_name(
                                sample_point.name, experiment.name, "s"
                            )
                            print(filename)
                            filenumber = 1

                        elif self.widget.no_suffices_cb.isChecked():
                            filename = self.basename
                            _, _, filenumber = self.get_filename_info(self.detector)

                        else:
                            _, filename, filenumber = self.get_filename_info(
                                self.detector
                            )

                        if self.detector == "pilatus":
                            caput(
                                epics_config[self.detector] + ":TIFF1:FilePath",
                                str(self.filepath),
                                wait=True,
                            )
                            caput(
                                epics_config[self.detector] + ":TIFF1:FileName",
                                str(filename),
                                wait=True,
                            )
                            caput(
                                epics_config[self.detector] + ":TIFF1:FileNumber",
                                filenumber,
                                wait=True,
                            )
                        elif self.detector == "eiger2":
                            caput(
                                epics_config[self.detector] + ":HDF1:FilePath",
                                str(self.filepath),
                                wait=True,
                            )
                            caput(
                                epics_config[self.detector] + ":HDF1:FileName",
                                str(filename),
                                wait=True,
                            )
                            caput(
                                epics_config[self.detector] + ":HDF1:FileNumber",
                                filenumber,
                                wait=True,
                            )

                        logger.info(
                            "Performing step scan for:\n\t\t{}\n\t\t{}".format(
                                sample_point, experiment
                            )
                        )
                        omega_step = experiment.omega_step
                        time_per_step = experiment.time_per_step

                        if self.crysalis_config.create_crysalis_files_cb.isChecked():
                            num_steps = int(
                                (experiment.omega_end - experiment.omega_start)
                                / omega_step
                            )
                            previous_detector_settings = self.prepare_for_crysalis_collection(
                                self.filepath,
                                filename,
                                self.crysalis_config.add_frames_in_tif_cb.isChecked(),
                                num_steps,
                                experiment.omega_start,
                                omega_step,
                            )

                            if self.detector == "pilatus":
                                cbf_file_path = (
                                    FILEPATH + self.filepath[4:] + "/" + filename
                                )

                                make_directory(cbf_file_path, str(filename))
                                copy_set_ccd(
                                    cbf_file_path,
                                    str(filename),
                                    pilatus_crysalis_config,
                                )

                                scans = collections.OrderedDict()
                                scans[0] = [
                                    {
                                        "count": num_steps,
                                        "omega": 0,
                                        "omega_start": experiment.omega_start,
                                        "omega_end": experiment.omega_end,
                                        "pixel_size": 0.172,
                                        "omega_runs": None,
                                        "theta": 0,
                                        "kappa": 0,
                                        "phi": 0,
                                        "domega": omega_step,
                                        "dtheta": 0,
                                        "dkappa": 0,
                                        "dphi": 0,
                                        "center_x": 525,
                                        "center_y": 514,
                                        "alpha": 50,
                                        "dist": 206.32,
                                        "l1": 0.2952,
                                        "l2": 0.2952,
                                        "l12": 0.2952,
                                        "b": 0.2952,
                                        "mono": 0.99,
                                        "monotype": "SYNCHROTRON",
                                        "chip": [1044, 1044],
                                        "Exposure_time": 1,
                                    }
                                ]
                                createCrysalis(scans, str(filename), cbf_file_path)

                                par_filepath = self.crysalis_config.par_file_le.text()
                                if os.path.isfile(par_filepath):
                                    create_par_file(
                                        cbf_file_path, str(filename), par_filepath
                                    )
                                else:
                                    par_filepath = pilatus_crysalis_config["par_file"]
                                    create_par_file(
                                        cbf_file_path, str(filename), par_filepath
                                    )
                            elif self.detector == "eiger2":
                                make_directory(
                                    self.filepath.replace(
                                        "/home/dac_user/cars6/Data/", "T:/"
                                    ),
                                    f"{filename}_{filenumber:03}",
                                )
                                copy_set_ccd(
                                    self.filepath.replace(
                                        "/home/dac_user/cars6/Data/", "T:/"
                                    ),
                                    f"{filename}_{filenumber:03}",
                                    eiger2_crysalis_config,
                                )

                                scans = collections.OrderedDict()
                                scans[0] = [
                                    {
                                        "count": num_steps,
                                        "omega": 0,
                                        "omega_start": experiment.omega_start,
                                        "omega_end": experiment.omega_end,
                                        "pixel_size": 0.075,
                                        "omega_runs": None,
                                        "theta": 0,
                                        "kappa": 0,
                                        "phi": 0,
                                        "domega": omega_step,
                                        "dtheta": 0,
                                        "dkappa": 0,
                                        "dphi": 0,
                                        "center_x": 1541.383,
                                        "center_y": 1712.742,
                                        "alpha": 50,
                                        "dist": 206.32,
                                        "l1": 0.2952,
                                        "l2": 0.2952,
                                        "l12": 0.2952,
                                        "b": 0.2952,
                                        "mono": 0.99,
                                        "monotype": "SYNCHROTRON",
                                        "chip": [3263, 3263],
                                        "Exposure_time": 1,
                                    }
                                ]
                                createCrysalis(
                                    scans,
                                    f"{filename}_{filenumber:03}",
                                    self.filepath.replace(
                                        "/home/dac_user/cars6/Data/", "T:/"
                                    ),
                                )

                                par_filepath = self.crysalis_config.par_file_le.text()
                                if os.path.isfile(par_filepath):
                                    create_par_file(
                                        self.filepath.replace(
                                            "/home/dac_user/cars6/Data/", "T:/"
                                        ),
                                        f"{filename}_{filenumber:03}",
                                        par_filepath,
                                    )
                                else:
                                    par_filepath = eiger2_crysalis_config["par_file"]
                                    create_par_file(
                                        self.filepath.replace(
                                            "/home/dac_user/cars6/Data/", "T:/"
                                        ),
                                        f"{filename}_{filenumber:03}",
                                        par_filepath,
                                    )

                        collect_step_data_thread = Thread(
                            target=collect_step_data,
                            kwargs={
                                "controller": self.automation1,
                                "detector_choice": self.detector,
                                "detector_position_x": experiment.detector_pos_x,
                                "detector_position_z": experiment.detector_pos_z,
                                "omega_start": experiment.omega_start,
                                "omega_end": experiment.omega_end,
                                "omega_step": omega_step,
                                "actual_omega_step": experiment.omega_step,
                                "exposure_time": time_per_step,
                                "x": sample_point.x,
                                "y": sample_point.y,
                                "z": sample_point.z,
                                "callback_fcn": self.check_if_aborted,
                            },
                        )

                        collect_step_data_thread.start()

                        while collect_step_data_thread.is_alive():
                            QtWidgets.QApplication.processEvents()
                            time.sleep(0.2)

                        if self.crysalis_config.create_crysalis_files_cb.isChecked():
                            if self.detector == "pilatus":
                                transform_cbf_to_esperanto(
                                    cbf_file_path, str(filename), scans[0][0]
                                )
                            elif self.detector == "eiger2":
                                transform_h5_to_esperanto(
                                    self.filepath.replace(
                                        "/home/dac_user/cars6/Data/", "T:/"
                                    ),
                                    str(filename),
                                    filenumber,
                                    scans[0][0],
                                )

                        if previous_detector_settings:
                            self.reset_settings(previous_detector_settings)

                    if not self.check_if_aborted():
                        break
            if self.widget.rename_files_cb.isChecked():
                self.increase_point_number()

        caput(
            epics_config[self.detector] + ":cam1:AcquireTime",
            previous_exposure_time,
            wait=True,
        )

        # move to previous detector position:
        if self.widget.reset_detector_position_cb.isChecked():
            if self.detector == "pilatus":
                caput(
                    epics_config["detector_position_x"],
                    previous_detector_pos_x,
                    wait=True,
                    timeout=300,
                )
                caput(
                    epics_config["pilatus_position_z"],
                    previous_detector_pos_z,
                    wait=True,
                    timeout=300,
                )

        # move to previous sample position
        if self.widget.reset_sample_position_cb.isChecked():
            caput(epics_config["sample_position_omega"], previous_omega_pos, wait=True)
            move_to_sample_pos(sample_x, sample_y, sample_z)

        caput(
            epics_config[self.detector] + ":cam1:ShutterMode", 1, wait=True
        )  # enable epics PV shutter mode

        if self.widget.rename_after_cb.isChecked():
            if self.detector == "pilatus":
                caput(
                    epics_config[self.detector] + ":TIFF1:FilePath",
                    previous_filepath,
                    wait=True,
                )
                caput(
                    epics_config[self.detector] + ":TIFF1:FileName",
                    previous_filename,
                    wait=True,
                )
            elif self.detector == "eiger2":
                caput(
                    epics_config[self.detector] + ":HDF1:FilePath",
                    previous_filepath,
                    wait=True,
                )
                caput(
                    epics_config[self.detector] + ":HDF1:FileName",
                    previous_filename,
                    wait=True,
                )

            # Changed - Chris 11 May 2022
            if self.widget.rename_files_cb.isChecked():
                if not self.widget.rename_files_suf_cb.isChecked():
                    if self.detector == "pilatus":
                        caput(
                            epics_config[self.detector] + ":TIFF1:FileNumber",
                            previous_filenumber,
                            wait=True,
                        )
                    elif self.detector == "eiger2":
                        caput(
                            epics_config[self.detector] + ":HDF1:FileNumber",
                            previous_filenumber,
                            wait=True,
                        )

        # Changed - Chris 11 May 2022
        # Advance frame numbers
        update_frame_number = False
        if not self.widget.rename_files_cb.isChecked():
            update_frame_number = True
        else:
            if self.widget.rename_files_suf_cb.isChecked():
                update_frame_number = True
        if update_frame_number:
            _, _, filenumber = self.get_filename_info(self.detector)
            self.widget.frame_number_txt.setText(str(filenumber))

        if self.abort_collection:
            while (
                caget(epics_config["sample_position_omega"] + ".RBV")
                != previous_omega_pos
            ):
                time.sleep(0.1)
                continue

            self.set_status_lbl("Abort Finished", "#00FF00")
        else:
            self.set_status_lbl("Finished", "#00FF00")

        # reset the state of the gui:
        self.widget.collect_btn.setText("Collect")
        self.widget.collect_btn.clicked.connect(self.collect_data)
        self.widget.collect_btn.clicked.disconnect(self.abort_data_collection)
        self.set_example_lbl()

    def reset_gui_state(self):
        self.widget.collect_btn.setText("Collect")
        self.widget.collect_btn.clicked.connect(self.collect_data)
        self.widget.collect_btn.clicked.disconnect(self.abort_data_collection)
        self.set_status_lbl("Finished", "#00FF00")
        self.set_example_lbl()

    def abort_data_collection(self):
        self.abort_collection = True

        # Make sure that table shutter is closed when user aborts (Stella)
        caput(epics_config["table_shutter"], 1)

        # Abort all stage operations - Chris
        self.set_status_lbl("Aborting...", "#FF0000")

        caput(epics_config["all_stop_xps"], 1)
        caput(epics_config["all_stop"], 1)

        # Abort detector collection - Chris
        if self.detector == "pilatus":
            caput(epics_config["pilatus"] + ":cam1:Acquire", 0)
        else:
            caput(epics_config["eiger2"] + ":cam1:Acquire", 0)

        # E-Set detector - Chris
        if self.detector == "pilatus":
            caput(epics_config["pilatus"] + ":cam1:ThresholdApply", 1)

        # Reset detector number of images - Chris
        if self.detector == "pilatus":
            caput(epics_config["pilatus"] + ":cam1:NumImages", 1)
            caput(epics_config["pilatus"] + ":Proc1:NumFilter", 1)
        else:
            caput(epics_config["eiger2"] + ":cam1:NumImages", 1)
            caput(epics_config["eiger2"] + ":Proc1:NumFilter", 1)
            caput(epics_config["eiger2"] + ":HDF1:Capture", 0)

        if self.detector == "pilatus":
            # Reset file format and ramdisk file path - Chris
            current_file_path = DETECTOR_FILE_PATH + "/pilatus"
            current_file_path_pv = epics_config["pilatus"] + ":cam1:FilePath"

            caput(epics_config["pilatus"] + ":cam1:FileTemplate", file_format_string)
            if caget(current_file_path_pv) != current_file_path:
                caput(current_file_path_pv, current_file_path)

    def check_if_aborted(self):
        # QtWidgets.QApplication.processEvents()
        return not self.abort_collection

    def set_status_lbl(self, msg, color, size=20):
        self.widget.status_lbl.setStyleSheet(
            "font-size: {}px; color: {};".format(size, color)
        )
        self.widget.status_lbl.setText(msg)

    def build_file_name(self, sample_point_name, experiment_name, suffix=""):
        point_number = str(self.widget.point_txt.text())
        filename = self.basename
        if self.widget.rename_files_sp_cb.isChecked():
            filename += "_" + sample_point_name
        if self.widget.rename_files_pp_cb.isChecked():
            filename += "_P" + point_number
        if self.widget.rename_files_en_cb.isChecked():
            filename += "_" + experiment_name
        if self.widget.rename_files_suf_cb.isChecked() and suffix:
            filename += "_" + suffix
        # if self.widget.rename_files_fn_cb.isChecked():
        #     filename += '_' + self.widget.frame_number_txt.text()

        return filename

    def increase_point_number(self):
        cur_point_number = int(str(self.widget.point_txt.text()))
        self.widget.point_txt.setText(str(cur_point_number + 1))

    def build_all_file_names(self):
        filename = "None"
        filenumber = 1
        filenames = []
        for exp_ind, experiment in enumerate(self.model.experiment_setups):
            for sample_point in self.model.sample_points:
                if sample_point.perform_still_for_setup[exp_ind]:
                    if self.widget.rename_files_cb.isChecked():
                        filename = self.build_file_name(
                            sample_point.name, experiment.name
                        )
                        filenumber = self.widget.frame_number_txt.text()

                    elif self.widget.no_suffices_cb.isChecked():
                        filename = self.basename
                        _, _, filenumber = self.get_filename_info(self.detector)
                    else:
                        _, filename, filenumber = self.get_filename_info(self.detector)
                    filenames.append(filename + "_" + str("%03d" % int(filenumber)))

                if sample_point.perform_wide_scan_for_setup[exp_ind]:
                    if self.widget.rename_files_cb.isChecked():
                        filename = self.build_file_name(
                            sample_point.name, experiment.name, "w"
                        )
                        filenumber = 1

                    elif self.widget.no_suffices_cb.isChecked():
                        filename = self.basename
                        _, _, filenumber = self.get_filename_info(self.detector)

                    else:
                        _, filename, filenumber = self.get_filename_info(self.detector)
                    filenames.append(filename + "_" + str("%03d" % int(filenumber)))

                if sample_point.perform_step_scan_for_setup[exp_ind]:
                    if self.widget.rename_files_cb.isChecked():
                        filename = self.build_file_name(
                            sample_point.name, experiment.name, "s"
                        )
                        filenumber = 1

                    elif self.widget.no_suffices_cb.isChecked():
                        filename = self.basename
                        _, _, filenumber = self.get_filename_info(self.detector)

                    else:
                        _, filename, filenumber = self.get_filename_info(self.detector)
                    filenames.append(filename + "_" + str("%03d" % int(filenumber)))

        return filenames

    def check_for_duplicate_file_names(self, filenames):
        for file_name in filenames:
            if filenames.count(file_name) > 1:
                return True

    def estimate_collection_time(self, epics_config):
        total_time = 0
        det_x_speed = caget(epics_config["detector_position_x"] + ".VELO")
        det_x_pos = caget(epics_config["detector_position_x"])
        det_z_speed = caget(epics_config["pilatus_position_z"] + ".VELO")
        det_z_pos = caget(epics_config["pilatus_position_z"])

        for exp_ind, experiment in enumerate(self.model.experiment_setups):
            exp_collection = False
            for sample_point in self.model.sample_points:
                if sample_point.perform_still_for_setup[exp_ind]:
                    exposure_time = (
                        abs(experiment.omega_end - experiment.omega_start)
                        / experiment.omega_step
                        * experiment.time_per_step
                    )
                    total_time += exposure_time + 4.5
                    exp_collection = True
                if sample_point.perform_wide_scan_for_setup[exp_ind]:
                    exposure_time = (
                        abs(experiment.omega_end - experiment.omega_start)
                        / experiment.omega_step
                        * experiment.time_per_step
                    )
                    total_time += exposure_time + 4.5
                    exp_collection = True
                if sample_point.perform_step_scan_for_setup[exp_ind]:
                    print(
                        "Performing step scan for {}, with setup {}".format(
                            sample_point, experiment
                        )
                    )
                    number_of_steps = (
                        abs(experiment.omega_end - experiment.omega_start)
                        / experiment.omega_step
                    )
                    exposure_time = number_of_steps * (4.5 + experiment.time_per_step)
                    total_time += exposure_time
                    exp_collection = True
                if exp_collection:
                    det_x_move_time = abs(
                        experiment.detector_pos_x - det_x_pos
                    ) / float(det_x_speed)
                    det_y_move_time = abs(
                        experiment.detector_pos_z - det_z_pos
                    ) / float(det_z_speed)
                    total_time += det_x_move_time + det_y_move_time
                    det_x_pos = experiment.detector_pos_x
                    det_z_pos = experiment.detector_pos_z
        return total_time

    def frame_counter(self):
        counter = 0
        for exp_ind, experiment in enumerate(self.model.experiment_setups):
            for sample_point in self.model.sample_points:
                if sample_point.perform_wide_scan_for_setup[exp_ind]:
                    counter += 1
                if sample_point.perform_step_scan_for_setup[exp_ind]:
                    number_of_steps = int(
                        abs(experiment.omega_end - experiment.omega_start)
                        / experiment.omega_step
                    )
                    counter += number_of_steps
                if sample_point.perform_still_for_setup[exp_ind]:
                    counter += 1
        return counter

    @staticmethod
    def create_name_existent_msg(name_type):
        msg_box = QtWidgets.QMessageBox()
        msg_box.setWindowFlags(QtCore.Qt.Tool)
        msg_box.setText("{} name already exists.".format(name_type))
        msg_box.setIcon(QtWidgets.QMessageBox.Critical)
        msg_box.setWindowTitle("Error")
        msg_box.setStandardButtons(QtWidgets.QMessageBox.Ok)
        msg_box.setDefaultButton(QtWidgets.QMessageBox.Ok)
        msg_box.exec_()

    @staticmethod
    def create_omega_error_msg(msg):
        msg_box = QtWidgets.QMessageBox()
        msg_box.setWindowFlags(QtCore.Qt.Tool)
        msg_box.setText(msg)
        msg_box.setIcon(QtWidgets.QMessageBox.Critical)
        msg_box.setWindowTitle("Error")
        msg_box.setStandardButtons(QtWidgets.QMessageBox.Ok)
        msg_box.setDefaultButton(QtWidgets.QMessageBox.Ok)
        msg_box.exec_()

    @staticmethod
    def get_current_sample_position():
        try:
            x = float("{:.4g}".format(caget(epics_config["sample_position_x"])))
            y = float("{:.4g}".format(caget(epics_config["sample_position_y"])))
            z = float("{:.4g}".format(caget(epics_config["sample_position_z"])))
        except epics.ca.ChannelAccessException:
            x = y = z = 0
        return x, y, z

    def get_current_setup(self):
        """
        Checks epics for the current setup setting.
        returns: detector position, omega, exposure_time
        :return: float, float, float
        """
        try:
            detector_pos_x = float(
                "{:g}".format(caget(epics_config["detector_position_x"]))
            )
            detector_pos_z = float(
                "{:g}".format(caget(epics_config["pilatus_position_z"]))
            )
            omega = float("{:g}".format(caget(epics_config["sample_position_omega"])))
            exposure_time = float(
                "{:g}".format(caget(epics_config[self.detector] + ":cam1:AcquireTime"))
            )
        except epics.ca.ChannelAccessException:
            if self.detector == "pilatus":
                detector_pos_x = 0
                detector_pos_z = 30
            omega = 0.0
            exposure_time = 0.5
        return detector_pos_x, detector_pos_z, omega, exposure_time

    @staticmethod
    def get_filename_info(detector):
        if detector == "pilatus":
            path = caget(epics_config[detector] + ":TIFF1:FilePath", as_string=True)
            filename = caget(epics_config[detector] + ":TIFF1:FileName", as_string=True)
            file_number = caget(epics_config[detector] + ":TIFF1:FileNumber")
        elif detector == "eiger2":
            path = caget(epics_config[detector] + ":HDF1:FilePath", as_string=True)
            filename = caget(epics_config[detector] + ":HDF1:FileName", as_string=True)
            file_number = caget(epics_config[detector] + ":HDF1:FileNumber")
        if path is None:
            path = ""
            filename = "test"
            file_number = 0
        return path, filename, file_number

    def get_framenumber(self):
        if str(self.widget.frame_number_txt.text()) == "":
            return 1
        else:
            return int(str(self.widget.frame_number_txt.text()))

    def check_filepath_exists(self):
        if self.detector == "pilatus":
            cur_epics_filepath = caget(
                epics_config[self.detector] + ":TIFF1:FilePath", as_string=True
            )
            caput(
                epics_config[self.detector] + ":TIFF1:FilePath",
                self.filepath,
                wait=True,
            )
            exists = caget(epics_config[self.detector] + ":TIFF1:FilePathExists_RBV")
            caput(
                epics_config[self.detector] + ":TIFF1:FilePath",
                cur_epics_filepath,
                wait=True,
            )
        elif self.detector == "eiger2":
            cur_epics_filepath = caget(
                epics_config[self.detector] + ":HDF1:FilePath", as_string=True
            )
            caput(
                epics_config[self.detector] + ":HDF1:FilePath", self.filepath, wait=True
            )
            exists = caget(epics_config[self.detector] + ":HDF1:FilePathExists_RBV")
            caput(
                epics_config[self.detector] + ":HDF1:FilePath",
                cur_epics_filepath,
                wait=True,
            )

        return exists == 1

    def check_filename_exists(self, filename):
        return os.path.isfile(filename + ".tif")

    def check_conditions(self):
        if int(caget("13IDD:m103.RBV")) > -170:
            return False
        elif int(caget("13IDD:m102.RBV")) > -170:
            return False
        elif int(caget("13IDD:m67.RBV")) > -135:
            return False
        return True

    def prepare_for_crysalis_collection(
        self, file_path, file_name, add_frames, num_steps, omega_start, omega_step
    ):
        previous_settings = {}

        if self.detector == "pilatus":
            output_file_name_format_pv = (
                epics_config["pilatus_control"] + ":FileTemplate_RBV"
            )
            previous_settings[output_file_name_format_pv] = caget(
                output_file_name_format_pv
            )
            output_file_name_pv = epics_config["pilatus_control"] + ":FileName_RBV"
            previous_settings[output_file_name_pv] = caget(output_file_name_pv)
            output_file_path_pv = epics_config["pilatus_control"] + ":FilePath_RBV"
            previous_settings[output_file_path_pv] = caget(output_file_path_pv)
            output_file_num_pv = epics_config["pilatus_control"] + ":FileNumber_RBV"
            previous_settings[output_file_num_pv] = caget(output_file_num_pv)

            caput(
                output_file_name_format_pv.split("_RBV")[0], "%s%s_00001.cbf", wait=True
            )
            caput(output_file_name_pv.split("_RBV")[0], file_name, wait=True)
            file_path = file_path.replace("/DAC", DETECTOR_FILE_PATH) + "/" + file_name

            caput(output_file_path_pv.split("_RBV")[0], file_path, wait=True)
            caput(output_file_num_pv.split("_RBV")[0], 1, wait=True)
            # TODO: Fix this to use the calculation instead
            # caput(epics_config['pilatus_info_wavelength'], caget(epics_config['13IDA_wavelength']), wait=True)
            caput(epics_config["pilatus_info_wavelength"], 0.3344, wait=True)
            caput(epics_config["pilatus_info_omega"], omega_start)
            caput(epics_config["pilatus_info_omega_increment"], omega_step)

            self.frames = add_frames
            if self.frames:
                num_filter_pv = epics_config["pilatus_proc"] + ":NumFilter_RBV"
                previous_settings[num_filter_pv] = caget(num_filter_pv)
                enable_filter_pv = epics_config["pilatus_proc"] + ":EnableFilter_RBV"
                previous_settings[enable_filter_pv] = caget(enable_filter_pv)
                filter_enable_callbacks_pv = (
                    epics_config["pilatus_proc"] + ":EnableCallbacks_RBV"
                )
                previous_settings[filter_enable_callbacks_pv] = caget(
                    filter_enable_callbacks_pv
                )
                tiff_array_port_pv = epics_config["pilatus_file"] + ":NDArrayPort_RBV"
                previous_settings[tiff_array_port_pv] = caget(tiff_array_port_pv)

                caput(epics_config["pilatus_proc"] + ":ResetFilter", 1, wait=True)
                caput(num_filter_pv.split("_RBV")[0], num_steps, wait=True)
                caput(enable_filter_pv.split("_RBV")[0], 1, wait=True)  # 1 is Enable
                caput(
                    filter_enable_callbacks_pv.split("_RBV")[0], 1, wait=True
                )  # 1 is Enable
                caput(tiff_array_port_pv.split("_RBV")[0], "PROC1", wait=True)

        elif self.detector == "eiger2":
            output_file_name_pv = epics_config["eiger2"] + ":cam1:FileName_RBV"
            previous_settings[output_file_name_pv] = caget(output_file_name_pv)
            output_file_path_pv = epics_config["eiger2"] + ":cam1:FilePath_RBV"
            previous_settings[output_file_path_pv] = caget(output_file_path_pv)
            output_file_num_pv = epics_config["eiger2"] + ":cam1:FileNumber_RBV"
            previous_settings[output_file_num_pv] = caget(output_file_num_pv)

            caput(output_file_name_pv.split("_RBV")[0], file_name, wait=True)

            caput(output_file_path_pv.split("_RBV")[0], file_path, wait=True)
            caput(output_file_num_pv.split("_RBV")[0], 1, wait=True)
            # TODO: Fix this to use the calculation instead
            caput(
                epics_config["pilatus_info_wavelength"],
                caget(epics_config["13IDA_wavelength"]),
                wait=True,
            )
            # caput(epics_config['pilatus_info_wavelength'], 0.3344, wait=True)
            caput(epics_config["eiger2"] + ":cam1:OmegaStart", omega_start)
            caput(epics_config["pilatus_info_omega_increment"], omega_step)

            return previous_settings

    def reset_settings(self, previous_settings):
        for key in previous_settings:
            pv_name = key.split("_RBV")[0]
            caput(pv_name, previous_settings[key], wait=True)

    @staticmethod
    def check_pilatus_trigger(detector):
        if detector == "pilatus":
            if caget("13IDD:EDIO24_1:Bo18"):
                caput("13IDD:EDIO24_1:Bo18.VAL", 0)

    @staticmethod
    def check_omega_in_limits(omega):
        if int(caget("13IDD:Auto1:m1.HLM")) < omega:
            return False
        if int(caget("13IDD:Auto1:m1.LLM")) > omega:
            return False
        return True

    def check_sample_point_distances(self, dist):
        pos_x, pos_y, pos_z = self.get_current_sample_position()
        largest_distance = (
            self.model.get_largest_largest_collecting_sample_point_distance_to(
                pos_x, pos_y, pos_z
            )
        )

        return largest_distance <= dist

    @staticmethod
    def show_error_message_box(msg):
        msg_box = QtWidgets.QMessageBox()
        msg_box.setWindowFlags(QtCore.Qt.Tool)
        msg_box.setText(msg)
        msg_box.setIcon(QtWidgets.QMessageBox.Critical)
        msg_box.setWindowTitle("Error")
        msg_box.setStandardButtons(QtWidgets.QMessageBox.Ok)
        msg_box.setDefaultButton(QtWidgets.QMessageBox.Ok)
        msg_box.exec_()

    @staticmethod
    def show_continue_abort_message_box(msg):
        msg_box = QtWidgets.QMessageBox()
        msg_box.setWindowFlags(QtCore.Qt.Tool)
        msg_box.setText("<p align='center' style='font-size:20px' >{}</p>".format(msg))
        msg_box.setIcon(QtWidgets.QMessageBox.Critical)
        msg_box.setWindowTitle("Continue?")
        msg_box.setStandardButtons(
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.Abort
        )
        msg_box.setDefaultButton(QtWidgets.QMessageBox.Abort)
        msg_box.exec_()
        return msg_box.result()

    def auto_update_current_motor_position(self):
        # hor = epics.caget(self.hor_motor_name + '.RBV', as_string=True)
        # ver = epics.caget(self.ver_motor_name + '.RBV', as_string=True)
        # focus = epics.caget(self.focus_motor_name + '.RBV', as_string=True)

        # if ver is not None and hor is not None and focus is not None:
        #     self.epics_update_timer.start(1000)
        # else:
        if self.epics_update_timer.isActive():
            self.epics_update_timer.stop()
        self.update_current_position()
        self.epics_update_timer.start(1000)
        # self.move_widget.hor_lbl.setText(str(hor))
        # self.move_widget.ver_lbl.setText(str(ver))
        # self.move_widget.focus_lbl.setText(str(focus))
        # self.move_widget.omega_lbl.setText(str(omega))

    def caput_pil3(pv, value, wait=True):
        t0 = time.time()
        caput(pv, value, wait=wait)

        while time.time() - t0 < 20.0:
            time.sleep(0.02)
            if "OK" in caget(epics_config["status_message"], as_string=True):
                return True
        return False


class InfoLoggingHandler(logging.Handler):
    def __init__(self, return_function):
        super(InfoLoggingHandler, self).__init__()
        self.return_function = return_function

    def emit(self, log_record):
        message = str(log_record.getMessage())
        self.return_function(time.strftime("%X") + ": " + message)


def test_dummy_function(iterations):
    print("the dummy function")
    for n in range(iterations):
        time.sleep(0.5)
        print("{} iterations".format(n + 1))


class ThreadRunner:
    def __init__(self, fcn, args):
        self.worker_thread = WorkerThread(fcn, args)
        self.worker_finished = False

        self.worker_thread.finished.connect(self.update_status)
        self.worker_thread.terminated.connect(self.update_status)

    def run(self):
        print("running something")
        self.worker_finished = False
        self.worker_thread.start()

        while not self.worker_finished:
            QtWidgets.QApplication.processEvents()
            time.sleep(0.1)

    def update_status(self):
        print("updating status")
        self.worker_finished = True


class WorkerThread(QtCore.QThread):
    def __init__(self, func, args):
        super(WorkerThread, self).__init__()
        self.func = func
        self.args = args

    def run(self):
        self.func(*self.args)


class CrysalisConfig(QtWidgets.QWidget):
    def __init__(self):
        super(CrysalisConfig, self).__init__()
        self.setVisible(False)
        self.create_widgets()
        self.create_layout()
        self.create_connections()
        self.setWindowTitle("CrysAlisCreator")

    def create_widgets(self):
        self.create_crysalis_files_cb = QtWidgets.QCheckBox(
            "Create CrysAlis files for single-crystal data collections"
        )
        # self.create_par_file_from_exp_params_cb = QtWidgets.QCheckBox(
        #      'Create .par file from the experimental parameters (not recommended)')
        # self.read_par_file_cb = QtWidgets.QCheckBox('Read .par file from the calibration crystal')
        self.par_file_le = QtWidgets.QLineEdit()
        self.load_par_file_btn = QtWidgets.QPushButton("Load .par")
        self.add_frames_in_tif_cb = QtWidgets.QCheckBox(
            "Add all frames in TIF (Pilatus only)"
        )

    def create_layout(self):
        self.v_box = QtWidgets.QVBoxLayout()
        self.par_h_box = QtWidgets.QHBoxLayout()
        self.v_box.addWidget(self.create_crysalis_files_cb)
        # self.v_box.addWidget(self.create_par_file_from_exp_params_cb)
        # self.v_box.addWidget(self.read_par_file_cb)
        self.par_h_box.addWidget(self.par_file_le)
        self.par_h_box.addWidget(self.load_par_file_btn)
        self.v_box.addLayout(self.par_h_box)
        self.v_box.addWidget(self.add_frames_in_tif_cb)
        self.setLayout(self.v_box)

    def create_connections(self):
        self.load_par_file_btn.clicked.connect(self.load_par_file_btn_clicked)

    def load_par_file_btn_clicked(self):
        filename, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, caption="Load .par file", filter="*.par"
        )
        filename = str(filename)
        if filename != "":
            self.par_file_le.setText(filename)
