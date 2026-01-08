# -*- coding: utf8 -*-

# SXRD_Collect - GUI program for collection single crystal X-ray diffraction data
# Copyright (C) 2015  Clemens Prescher (clemens.prescher@gmail.com)
# GSECARS, University of Chicago
#
#     This program is free software: you can redistribute it and/or modify
#     it under the terms of the GNU General Public License as published by
#     the Free Software Foundation, either version 3 of the License, or
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

import unittest
import sys

from PyQt4 import QtCore, QtGui
from views import MainView

class MainViewTest(unittest.TestCase):
    def setUp(self):
        self.app = QtGui.QApplication(sys.argv)
        self.view = MainView()
        self.view.show()

    def tearDown(self):
        self.view.close()
        del self.view
        del self.app

    def test_adding_experiments(self):
        self.view.add_experiment_setup(-333, -100, -90, 0.5, 0.4)
        self.view.add_experiment_setup(-333, -100, -90, 0.2, 0.4)
        self.view.add_experiment_setup(-333, -100, -90, 0.3, 0.4)
        self.view.add_experiment_setup(-333, -100, -90, 0.8, 0.4)
        self.view.add_experiment_setup(-333, -100, -90, 3, 0.4)
        self.view.add_experiment_setup(-333, -100, -90, 2, 0.4)

    def test_deleting_experiments(self):
        self.view.add_experiment_setup(-333, -100, -90, 0.5, 0.4)
        self.view.add_experiment_setup(-333, -100, -90, 0.2, 0.4)
        self.view.add_experiment_setup(-333, -100, -90, 0.3, 0.4)
        self.view.add_experiment_setup(-333, -100, -90, 0.8, 0.4)

        self.view.del_experiment_setup(3)
        self.view.del_experiment_setup(1)
        self.view.del_experiment_setup(0)
