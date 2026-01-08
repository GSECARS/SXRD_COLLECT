# -*- coding: utf8 -*-
# SXRD_Collect - GUI program for collection single crystal X-ray diffraction data
#     Copyright (C) 2015  Clemens Prescher (clemens.prescher@gmail.com)
#     GSECARS, University of Chicago
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

import os
import shutil

import numpy as np
import fabio
from PIL import Image

file_path = 'T:/dac_user/2014/IDD_2014-2/BGI/Enstatite'
step_base_name = 'Enst_2_P8_center_p49_s_'
num_img = 160
wide_file_name = 'Enst_2_P9_center_p49_w_001.tif'

wide_file_path = os.path.join(file_path, wide_file_name)


def get_img_matrix(filename):
    fab_img = fabio.open(filename)
    return fab_img.data


wide_img_data = get_img_matrix(wide_file_path)

step_img_sum_data = np.zeros(wide_img_data.shape)

for ind in range(num_img):
    file_name = step_base_name + '{0:03d}.tif'.format(ind+1)
    print(file_name)
    step_file_path = os.path.join(file_path, file_name)
    step_img_data = get_img_matrix(step_file_path)
    step_img_sum_data += step_img_data

im = Image.fromarray(step_img_sum_data)
im.save('sum_step_data.tiff')

im = Image.fromarray(np.ones(wide_img_data.shape)*3000+wide_img_data-step_img_sum_data/2.0)
im.save('subtracted_img_data.tiff')


shutil.copy(wide_file_path, 'wide_img.tiff')