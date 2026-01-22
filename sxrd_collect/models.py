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

import numpy as np
from collections import OrderedDict


class SxrdModel(object):
    def __init__(self):
        self.experiment_setups = []
        self.sample_points = []

    def add_experiment_setup(self, name, detector_pos_x=0, detector_pos_y=49, omega_start=0, omega_end=0, omega_step=0,
                             time_per_step=0, steps_per_image=1):
        self.experiment_setups.append(
            ExperimentSetup(name, detector_pos_x, detector_pos_y, omega_start, omega_end, omega_step, time_per_step,
                            steps_per_image))

        for point in self.sample_points:
            point.register_setup(self.experiment_setups[-1])

    def delete_experiment_setup(self, ind):
        for point in self.sample_points:
            point.unregister_setup(self.experiment_setups[ind])
        del self.experiment_setups[ind]

    def clear_experiment_setups(self):
        exp_setup_nr = len(self.experiment_setups)
        for ind in range(exp_setup_nr):
            cur_ind = exp_setup_nr - ind -1
            self.delete_experiment_setup(cur_ind)

    def get_experiment_state(self):
        data = []
        for point in self.sample_points:
            point_data = []
            for ind, experiment in enumerate(self.experiment_setups):
                point_data.append([point.perform_step_scan_for_setup[ind],
                                   point.perform_wide_scan_for_setup[ind],
                                   point.perform_still_for_setup[ind]])
            data.append(point_data)
        return data

    def add_sample_point(self, name, x, y, z, step_state=False, wide_state=False, still_state=False):
        self.sample_points.append(SamplePoint(name, x, y, z))
        for setup in self.experiment_setups:
            self.sample_points[-1].register_setup(setup, step_state, wide_state, still_state)

    def delete_sample_point(self, ind):
        del self.sample_points[ind]

    def clear_sample_points(self):
        self.sample_points = []

    def create_map(self, center_ind, x_min, x_max, x_step,
                   y_min, y_max, y_step):

        x_center = self.sample_points[center_ind].x
        y_center = self.sample_points[center_ind].y
        z_center = self.sample_points[center_ind].z
        name_center = self.sample_points[center_ind].name

        # x_map = x_center + np.arange(x_min, x_max + x_step, x_step)
        # y_map = y_center + np.arange(y_min, y_max + y_step, y_step)
        x_map = x_center + np.arange(x_min, x_max + 0.0001, x_step)
        y_map = y_center + np.arange(y_min, y_max + 0.0001, y_step)
        # x_map = x_center + np.arange(x_min, x_max, x_step)
        # y_map = y_center + np.arange(y_min, y_max, y_step)


        ind = 0

        map = OrderedDict()

        for y in y_map:
            for x in x_map:
                x_iter = x_map  # Left to right
            else:
                x_iter = x_map[::-1]  # Right to left (reversed)
            
            for x in x_iter:
                point_name = "{}_map_{}".format(name_center, ind+1)
                self.add_sample_point(point_name, x, y, z_center)
                map[point_name] = [x, y, z_center]
                ind += 1

        return map

    def get_experiment_setup_names(self):
        res = []
        for experiment_setup in self.experiment_setups:
            res.append(experiment_setup.name)
        return res

    def setup_name_existent(self, name):
        for setup in self.experiment_setups:
            if name == setup.name:
                return True
        return False

    def sample_name_existent(self, name):
        for setup in self.sample_points:
            if name == setup.name:
                return True
        return False

    def get_largest_largest_collecting_sample_point_distance_to(self, x, y, z):
        largest_distance = 0
        for point in self.sample_points:
            if point.is_collecting():
                point_distance = point.distance_to(x, y, z)
                if point_distance > largest_distance:
                    largest_distance = point_distance
        return largest_distance


class ExperimentSetup(object):
    def __init__(self, name, detector_pos_x=0, detector_pos_z=49, omega_start=0, omega_end=0, omega_step=0,
                 time_per_step=0, steps_per_image=1):
        self.name = name
        self.detector_pos_x = detector_pos_x
        self.detector_pos_z = detector_pos_z
        self.omega_start = omega_start
        self.omega_end = omega_end
        self.omega_step = omega_step
        self.time_per_step = time_per_step
        self.steps_per_image = steps_per_image

    def get_total_exposure_time(self):
        return (self.omega_end - self.omega_start) / self.omega_step * self.time_per_step

    def get_step_exposure_time(self, total_time):
        return total_time * self.omega_step / (self.omega_end - self.omega_start)

    def __str__(self):
        return "{}: {}, {}, {}, {}, {}, {}".format(self.name, self.detector_pos_x, self.detector_pos_z,
                                                   self.omega_start, self.omega_end, self.omega_step,
                                                   self.time_per_step)

    def save(self):
        return "{};{};{};{};{};{};{}".format(self.name, self.detector_pos_x, self.detector_pos_z,
                                                   self.omega_start, self.omega_end, self.omega_step,
                                                   self.time_per_step)


class SamplePoint(object):
    def __init__(self, name='P', x=0, y=0, z=0):
        self.name = name
        self.x = x
        self.y = y
        self.z = z

        self.experiment_setups = []
        self.perform_wide_scan_for_setup = []
        self.perform_step_scan_for_setup = []
        self.perform_still_for_setup = []

    def set_position(self, x, y, z):
        self.x = x
        self.y = y
        self.z = z

    def distance_to(self, x, y, z):
        return ((self.x - x) ** 2 + (self.y - y) ** 2 + (self.z - z) ** 2) ** 0.5

    def register_setup(self, experiment_setup, step_state=False, wide_state=False, still_state=False):
        self.experiment_setups.append(experiment_setup)
        self.perform_step_scan_for_setup.append(step_state)
        self.perform_wide_scan_for_setup.append(wide_state)
        self.perform_still_for_setup.append(still_state)

    def unregister_setup(self, experiment_setup):
        ind = self.experiment_setups.index(experiment_setup)
        del self.experiment_setups[ind]
        del self.perform_step_scan_for_setup[ind]
        del self.perform_wide_scan_for_setup[ind]
        del self.perform_still_for_setup[ind]

    def set_perform_wide_scan_setup(self, exp_ind, state):
        self.perform_wide_scan_for_setup[exp_ind] = state

    def set_perform_step_scan_setup(self, exp_ind, state):
        self.perform_step_scan_for_setup[exp_ind] = state

    def set_perform_still_setup(self, exp_ind, state):
        self.perform_still_for_setup[exp_ind] = state

    def is_collecting(self):
        for state in self.perform_step_scan_for_setup:
            if state:
                return True
        for state in self.perform_wide_scan_for_setup:
            if state:
                return True
        for state in self.perform_still_for_setup:
            if state:
                return True
        return False

    def __str__(self):
        return "{}, {}, {}, {}".format(self.name, self.x, self.y, self.z)
