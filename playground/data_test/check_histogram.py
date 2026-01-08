__author__ = 'DAC_User'
import os

import numpy as np
import fabio
import matplotlib.pyplot as plt
from scipy.optimize import curve_fit

file_path = 'T:\\dac_user\\2014\\IDD_2014-2\\BGI\\BallII_KCl_Au_film'

step_base_name = 'BallII_'
num_img = 160

img_number = 20


def get_img_matrix(filename):
    fab_img = fabio.open(filename)
    return np.array(fab_img.data)


def gauss_function(x, center, sigma, intensity):
    factor = 1 / (sigma * (2 * np.pi) ** 2)
    exponential = np.exp(-(x - center) ** 2 / (2 * sigma ** 2))
    return intensity * factor * exponential


background_intensity = []
for ind in xrange(187,219 ):
    file_name = step_base_name + '{0:03d}.tif'.format(ind + 1)
    print(file_name)
    step_file_path = os.path.join(file_path, file_name)
    step_img_data = get_img_matrix(step_file_path)
    hist = np.histogram(step_img_data.ravel(), np.max(step_img_data))
    diff = hist[1][1]
    x = np.arange(diff / 2.0, (len(hist[1]) - 1) * diff + diff / 2.0, diff)

    max_ind = np.argmax(hist[0][1:])
    print(hist[0][ind + 1])
    res, _ = curve_fit(gauss_function, x[1:], hist[0][1:], (max_ind, 2, hist[0][max_ind]))
    background_intensity.append(res[0])
    plt.plot(x[1:], hist[0][1:])

plt.figure()
plt.plot(background_intensity)
plt.show()


