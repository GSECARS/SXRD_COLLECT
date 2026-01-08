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
__author__ = 'Clemens Prescher'

from qtpy import QtGui, QtCore, QtWidgets
from functools import partial
from epics import caput, caget, camonitor
import time
from sxrd_collect.config import epics_config, DETECTOR_FILE_PATH, file_format_string
from sxrd_collect.views.UiFiles.mainUI import Ui_SXRDCollectWidget


class MainView(QtWidgets.QWidget, Ui_SXRDCollectWidget):
    set_sample_btn_clicked = QtCore.Signal(int)
    move_sample_btn_clicked = QtCore.Signal(int)

    step_cb_status_changed = QtCore.Signal(int, int, bool)
    wide_cb_status_changed = QtCore.Signal(int, int, bool)
    still_cb_status_changed = QtCore.Signal(int, int, bool)

    def __init__(self, version):
        super(MainView, self).__init__()
        self.setupUi(self)

        self.table_delegate = FirstItemStringDelegate(self)
        self.setup_table.setItemDelegate(self.table_delegate)
        self.setup_table.horizontalHeaderItem(4).setToolTip('For BX90 + BA diamonds \n'
                                                            'Wide scan: -70 \n'
                                                            'Step scan: -52')
        self.setup_table.horizontalHeaderItem(3).setToolTip('For BX90 + BA diamonds \n'
                                                            'Wide scan: -110 \n'
                                                            'Step scan: -128')

        self.sample_points_table.setItemDelegate(self.table_delegate)

        self.setWindowTitle("SXRD Collect {}".format(version))

        self.point_txt.setValidator(QtGui.QIntValidator())
        self.x_min_txt.setValidator(QtGui.QDoubleValidator())
        self.x_max_txt.setValidator(QtGui.QDoubleValidator())
        self.x_step_txt.setValidator(QtGui.QDoubleValidator())
        self.y_min_txt.setValidator(QtGui.QDoubleValidator())
        self.y_max_txt.setValidator(QtGui.QDoubleValidator())
        self.y_step_txt.setValidator(QtGui.QDoubleValidator())


        # TODO: Temporary disconnected reset button - Chris        
        self.btn_reset.setEnabled(False)
        # self.btn_reset.clicked.connect(self.reset_state)

        self.btn_power_cycle.clicked.connect(self.power_cycle_detector)
        self.io_iterations.setValidator(QtGui.QDoubleValidator(0, 1000, 0))
        self.io_iterations.returnPressed.connect(self.change_iterations)
        self.power_cycle_iterations = 1
        self.detector_status = None
        camonitor(epics_config['status_message'], callback=self.monitor_callback)

    def monitor_callback(self, **kwargs):
        self.detector_status = kwargs["char_value"]

    def change_iterations(self):
        if int(self.io_iterations.text()) > 20 or int(self.io_iterations.text()) <= 0:
            self.io_iterations.setText(str(self.power_cycle_iterations))
        else:
            self.power_cycle_iterations = int(self.io_iterations.text())

        QtWidgets.QApplication.processEvents()

    # Added power cycle - Chris
    def power_cycle_detector(self):

        for i in range(0, self.power_cycle_iterations):

            self.status_lbl.setStyleSheet("font-size: {}px; color: {};".format(20, "#FF0000"))
            self.status_lbl.setText(f"Power Cycle ({i + 1}/{self.power_cycle_iterations})")
            QtWidgets.QApplication.processEvents()

            # Reset detector
            caput(epics_config['pilatus'] + ":cam1:ResetPower", 1, wait=True)
            time.sleep(0.5)

            while self.detector_status != "Camserver returned OK":
                continue

        self.status_lbl.setStyleSheet("font-size: {}px; color: {};".format(20, "#00FF00"))
        self.status_lbl.setText("Power Cycle Finished")
        QtWidgets.QApplication.processEvents()

    def reset_state(self):
        self.status_lbl.setStyleSheet("font-size: {}px; color: {};".format(20, "#FF0000"))
        self.status_lbl.setText("Resetting Detector")

        QtWidgets.QApplication.processEvents()

        # Disable reset button
        self.btn_reset.setEnabled(False)

        # Make sure that table shutter is closed when user aborts (Stella)
        caput(epics_config['table_shutter'], 1)

        # Abort all stage operations - Chris
        caput(epics_config['all_stop_xps'], 1)
        caput(epics_config['all_stop'], 1)

        # Abort detector collection - Chris
        caput(epics_config["pilatus"] + ":cam1:Acquire", 0)

        # Reset to internal mode
        caput(epics_config['pilatus'] + ':cam1:TriggerMode', 0, wait=True)

        # E-Set detector - Chris
        caput(epics_config["pilatus"] + ":cam1:ThresholdApply", 1)
        time.sleep(2)

        # Reset detector number of images - Chris
        caput(epics_config["pilatus"] + ":cam1:NumImages", 1)
        caput(epics_config["pilatus"] + ":Proc1:NumFilter", 1)

        # Reset file format and ramdisk file path - Chris
        current_file_path = DETECTOR_FILE_PATH + "/pilatus"
        current_file_path_pv = epics_config["pilatus"] + ":cam1:FilePath"

        caput(epics_config["pilatus"] + ":cam1:FileTemplate", file_format_string)
        if caget(current_file_path_pv, as_string=True) != current_file_path:
            caput(current_file_path_pv, current_file_path)

        # Enable reset button
        self.btn_reset.setEnabled(True)

        while self.detector_status != "Camserver returned OK":
            continue

        self.status_lbl.setStyleSheet("font-size: {}px; color: {};".format(20, "#00FF00"))
        self.status_lbl.setText("Reset Finished")
        QtWidgets.QApplication.processEvents()

    def add_experiment_setup(self, name, detector_pos_x, detector_pos_y, omega_start,
                             omega_end, omega_step, exposure_time):
        self.setup_table.blockSignals(True)
        new_row_ind = int(self.setup_table.rowCount())
        self.setup_table.setRowCount(new_row_ind + 1)

        name_item = QtWidgets.QTableWidgetItem(name)
        name_item.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        detector_x_item = QtWidgets.QTableWidgetItem(str(detector_pos_x))
        detector_x_item.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        detector_y_item = QtWidgets.QTableWidgetItem(str(detector_pos_y))
        detector_y_item.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        omega_start_item = QtWidgets.QTableWidgetItem(str(omega_start))
        omega_start_item.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        omega_end_item = QtWidgets.QTableWidgetItem(str(omega_end))
        omega_end_item.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        omega_step_item = QtWidgets.QTableWidgetItem(str(omega_step))
        omega_step_item.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        exposure_time_step_item = QtWidgets.QTableWidgetItem(str(exposure_time))
        exposure_time_step_item.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        total_exposure_time = (omega_end - omega_start) / omega_step * exposure_time
        exposure_time_total_item = QtWidgets.QTableWidgetItem(str(total_exposure_time))
        exposure_time_total_item.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        # steps_per_image = 1
        # steps_per_image_item = QtWidgets.QTableWidgetItem(str(steps_per_image))
        # steps_per_image_item.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)

        self.setup_table.setItem(new_row_ind, 0, name_item)
        self.setup_table.setItem(new_row_ind, 1, detector_x_item)
        self.setup_table.setItem(new_row_ind, 2, detector_y_item)
        self.setup_table.setItem(new_row_ind, 3, omega_start_item)
        self.setup_table.setItem(new_row_ind, 4, omega_end_item)
        self.setup_table.setItem(new_row_ind, 5, omega_step_item)
        self.setup_table.setItem(new_row_ind, 6, exposure_time_step_item)
        self.setup_table.setItem(new_row_ind, 7, exposure_time_total_item)
        # self.setup_table.setItem(new_row_ind, 8, steps_per_image_item)

        self.setup_table.setVerticalHeaderItem(new_row_ind, QtWidgets.QTableWidgetItem(name))
        self.setup_table.resizeColumnsToContents()

        # update the sample_points_table_accordingly:
        self.sample_points_table.setColumnCount(7 + new_row_ind)
        for sample_point_row in range(self.sample_points_table.rowCount()):
            self.create_sample_point_checkboxes(sample_point_row, new_row_ind)

        self.sample_points_table.setHorizontalHeaderItem(6 + new_row_ind,
                                                         QtWidgets.QTableWidgetItem(name))
        self.sample_points_table.resizeColumnsToContents()
        self.setup_table.blockSignals(False)

    def get_selected_experiment_setup(self):
        selected = self.setup_table.selectionModel().selectedRows()
        try:
            row = []
            for element in selected:
                row.append(int(element.row()))
        except IndexError:
            row = None
        return row

    def delete_experiment_setup(self, row_ind):
        self.setup_table.blockSignals(True)
        self.setup_table.removeRow(row_ind)

        # rename row Headers:
        for row_ind in range(self.setup_table.rowCount()):
            self.setup_table.setVerticalHeaderItem(row_ind,
                                                   QtWidgets.QTableWidgetItem('E{}'.format(row_ind + 1)))

        self.setup_table.blockSignals(False)

        self.sample_points_table.blockSignals(True)
        self.sample_points_table.removeColumn(6 + row_ind)

        #rename column Headers:
        # for row_ind in range(self.setup_table.rowCount()):
        #     self.sample_points_table.setHorizontalHeaderItem(
        #          6 + row_ind, QtGui.QTableWidgetItem(name))

        for row_ind in range(self.setup_table.rowCount()):
            self.sample_points_table.setHorizontalHeaderItem(
                 6 + row_ind, QtWidgets.QTableWidgetItem(self.setup_table.item(row_ind,0).text()))

        self.sample_points_table.blockSignals(False)

    def update_sample_table_setup_header(self, header_names):
        for row, header_name in enumerate(header_names):
            header_item = self.sample_points_table.horizontalHeaderItem(row+6)
            header_item.setText(header_name)

    def add_sample_point(self, name, x, y, z, still_state=False, wide_state=False, step_state=False):
        self.sample_points_table.blockSignals(True)
        new_row_ind = int(self.sample_points_table.rowCount())
        self.sample_points_table.setRowCount(new_row_ind + 1)

        name_item = QtWidgets.QTableWidgetItem(str(name))
        name_item.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        x_pos_item = QtWidgets.QTableWidgetItem(str(x))
        x_pos_item.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        y_pos_item = QtWidgets.QTableWidgetItem(str(y))
        y_pos_item.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        z_pos_item = QtWidgets.QTableWidgetItem(str(z))
        z_pos_item.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)

        self.sample_points_table.setItem(new_row_ind, 0, name_item)
        self.sample_points_table.setItem(new_row_ind, 1, x_pos_item)
        self.sample_points_table.setItem(new_row_ind, 2, y_pos_item)
        self.sample_points_table.setItem(new_row_ind, 3, z_pos_item)

        set_btn = QtWidgets.QPushButton('Get')
        set_btn.clicked.connect(partial(self.set_sample_btn_click, new_row_ind))
        self.sample_points_table.setCellWidget(new_row_ind, 4, set_btn)

        move_btn = QtWidgets.QPushButton('Move')
        move_btn.clicked.connect(partial(self.move_sample_btn_click, new_row_ind))
        self.sample_points_table.setCellWidget(new_row_ind, 5, move_btn)

        for exp_row in range(self.setup_table.rowCount()):
            self.create_sample_point_checkboxes(new_row_ind, exp_row, step_state, wide_state, still_state)
        self.sample_points_table.resizeColumnsToContents()
        self.sample_points_table.blockSignals(False)

    def create_sample_point_checkboxes(self, row_index, exp_index, step_state=False, wide_state=False, still_state=False):
        exp_widget = QtWidgets.QWidget()
        wide_cb = QtWidgets.QCheckBox('wide')
        step_cb = QtWidgets.QCheckBox('step')
        still_cb = QtWidgets.QCheckBox('still')
        exp_layout = QtWidgets.QHBoxLayout()
        exp_layout.addWidget(still_cb)
        exp_layout.addWidget(wide_cb)
        exp_layout.addWidget(step_cb)
        exp_widget.setLayout(exp_layout)

        still_cb.setChecked(still_state)
        step_cb.setChecked(step_state)
        wide_cb.setChecked(wide_state)

        still_cb.stateChanged.connect(partial(self.still_cb_changed, row_index, exp_index))
        step_cb.stateChanged.connect(partial(self.step_cb_changed, row_index, exp_index))
        wide_cb.stateChanged.connect(partial(self.wide_cb_changed, row_index, exp_index))
        self.sample_points_table.setCellWidget(row_index, exp_index + 6, exp_widget)

    def recreate_sample_point_checkboxes(self, values):
        for row_index, row in enumerate(values):
            for exp_index, experiment_state in enumerate(row):
                self.create_sample_point_checkboxes(row_index, exp_index, experiment_state[0], experiment_state[1], experiment_state[2])

    def get_selected_sample_point(self):
        selected = self.sample_points_table.selectionModel().selectedRows()
        try:
            row = []
            for element in selected:
                row.append(int(element.row()))
        except IndexError:
            row = None
        return row

    def delete_sample_point(self, row_ind):
        self.sample_points_table.blockSignals(True)
        self.sample_points_table.removeRow(row_ind)
        self.sample_points_table.blockSignals(False)

    def clear_sample_points(self):
        self.sample_points_table.clearContents()
        self.sample_points_table.setRowCount(0)

    def clear_experiment_setups(self):
        self.setup_table.blockSignals(True)
        self.setup_table.clearContents()
        self.setup_table.setRowCount(0)
        self.setup_table.blockSignals(False)
        self.sample_points_table.blockSignals(True)
        for col_ind in reversed(range(self.sample_points_table.columnCount())):
            if col_ind >= 6:
                self.sample_points_table.removeColumn(col_ind)
        self.sample_points_table.blockSignals(False)

    def set_sample_point_values(self, ind, x, y, z):
        x_item = self.sample_points_table.item(ind, 1)
        x_item.setText(str(x))
        y_item = self.sample_points_table.item(ind, 2)
        y_item.setText(str(y))
        z_item = self.sample_points_table.item(ind, 3)
        z_item.setText(str(z))
        self.sample_points_table.resizeColumnsToContents()

    def get_sample_point_values(self, ind):
        x_item = self.sample_points_table.item(ind, 1)
        x = float(str(x_item.text()))
        y_item = self.sample_points_table.item(ind, 2)
        y = float(str(y_item.text()))
        z_item = self.sample_points_table.item(ind, 3)
        z = float(str(z_item.text()))
        return x, y, z

    def set_sample_btn_click(self, index):
        self.set_sample_btn_clicked.emit(index)

    def move_sample_btn_click(self, index):
        self.move_sample_btn_clicked.emit(index)

    def step_cb_changed(self, row_index, exp_index, state):
        self.step_cb_status_changed.emit(row_index, exp_index, bool(state))

    def wide_cb_changed(self, row_index, exp_index, state):
        self.wide_cb_status_changed.emit(row_index, exp_index, bool(state))

    def still_cb_changed(self, row_index, exp_index, state):
        self.still_cb_status_changed.emit(row_index, exp_index, bool(state))


class TextDoubleDelegate(QtWidgets.QStyledItemDelegate):
    def __init__(self, parent):
        super(TextDoubleDelegate, self).__init__(parent)

    def createEditor(self, parent, _, model):
        self.editor = QtWidgets.QLineEdit(parent)
        self.editor.setFrame(False)
        self.editor.setValidator(QtWidgets.QDoubleValidator())
        self.editor.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        return self.editor

    def setEditorData(self, parent, index):
        value = index.model().data(index, QtCore.Qt.EditRole)
        self.editor.setText("{:g}".format(float(str(value))))

    def setModelData(self, parent, model, index):
        value = self.editor.text()
        model.setData(index, value, QtCore.Qt.EditRole)

    def updateEditorGeometry(self, editor, option, _):
        editor.setGeometry(option.rect)


class FirstItemStringDelegate(QtWidgets.QStyledItemDelegate):
    def __init__(self, parent):
        super(FirstItemStringDelegate, self).__init__(parent)

    def createEditor(self, parent, _, model):
        self.editor = QtWidgets.QLineEdit(parent)
        self.editor.setFrame(False)
        if model.column() != 0:
            self.editor.setValidator(QtGui.QDoubleValidator())
        self.editor.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        return self.editor

    def setEditorData(self, parent, index):
        value = index.model().data(index, QtCore.Qt.EditRole)
        self.editor.setText(str(value))

    def setModelData(self, parent, model, index):
        value = self.editor.text()
        model.setData(index, value, QtCore.Qt.EditRole)

    def updateEditorGeometry(self, editor, option, _):
        editor.setGeometry(option.rect)