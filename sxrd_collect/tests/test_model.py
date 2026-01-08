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

import unittest

from models import SxrdModel


class SxrdModelTest(unittest.TestCase):
    def setUp(self):
        self.model = SxrdModel()

    def tearDown(self):
        pass

    def test_create_map(self):
        self.model.add_sample_point('S1', 1.0, 1.0, 0.5)
        self.assertEqual(len(self.model.sample_points), 1)

        self.model.create_map(0,
                              -0.01, 0.01, 0.005,
                              -0.01, 0.01, 0.005)

        self.assertEqual(len(self.model.sample_points), 26)
        self.assertEqual(self.model.sample_points[1].x, 0.99)

        self.model.clear_sample_points()
        self.model.add_sample_point('S1', 0, 0, 0)
        self.model.add_sample_point('S2', 1.0, 2.0, 0.3)

        self.model.create_map(1,
                              -0.01, 0.01, 0.005,
                              0, 0, 0.005)

        self.assertEqual(len(self.model.sample_points), 7)

        self.model.clear_sample_points()
        self.model.add_sample_point('S1', 0, 0, 0)
        self.model.add_sample_point('S2', 1.0, 2.0, 0.3)
        self.model.create_map(1,
                              0, 0, 0.005,
                              -0.01, 0.01, 0.005)

        self.assertEqual(len(self.model.sample_points), 7)
