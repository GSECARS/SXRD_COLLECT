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

import time
import logging
from functools import partial
from epics import caput, caget, PV, camonitor, camonitor_clear
from threading import Thread
from pyautomation.modules import Trajectory

logging.basicConfig()
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)

from sxrd_collect.config import epics_config, xps_config
from sxrd_collect.utils import move_photodiode_out


HOST = xps_config['HOST']
GROUP_NAME = xps_config['GROUP NAME']
POSITIONERS = xps_config['POSITIONERS']
DEFAULT_ACCEL = xps_config['DEFAULT ACCEL']
USERNAME = xps_config["USER"]
PASSWORD = xps_config["PASSWORD"]
GATHER_OUTPUTS = xps_config['GATHER OUTPUTS']

def get_sample_position():
    x_pos = caget(epics_config['sample_position_x'])
    y_pos = caget(epics_config['sample_position_y'])
    z_pos = caget(epics_config['sample_position_z'])
    return x_pos, y_pos, z_pos

def collect_step_data(controller, detector_choice, detector_position_x, detector_position_z, omega_start, omega_end, omega_step,
                      actual_omega_step, exposure_time, x, y, z, callback_fcn=None):
    """
    Performs a single crystal step collection at the sample position x,y,z using trajectory scans.
    :param detector_choice:
        Which detector to use (pilatus or eiger2).
    :param detector_position_x:
        Detector x position. Whereby the X motor PV is defined in epics_config as "detector_position_x".
    :param detector_position_z:
        Detector z position. Whereby the Z motor PV is defined in epics_config as "detector_position_z".
    :param omega_start:
        Starting omega angle for the step scans. Whereby the omega motor PV  is defined in epics_config as
        "sample_position_omega".
    :param omega_end:
        End omega angle for the step scans. Whereby the omega motor PV  is defined in epics_config as
        "sample_position_omega".
    :param omega_step:
        Omega step for each single frame/ Whereby the omega motor PV  is defined in epics_config as
        "sample_position_omega".
    :param actual_omega_step:
        THe actual omega step since for Pilatus in step scan the step is set to 0.1 in some cases
    :param exposure_time:
        Exposure time per frame in seconds.
    :param x:
        Sample position x. PV is defined in epics_config as "sample_position_x".
    :param y:
        Sample position y. PV is defined in epics_config as "sample_position_y".
    :param z:
        Sample position z. PV is defined in epics_config as "sample_position_z".
    :param callback_fcn:
        A user-defined function which will be called after each collection step is performed.
        If the function returns False the step collection will be aborted. Otherwise the data collection will proceed
        until the omega_end.
    """
    # performs the actual step measurement

    print(f"Velocity: {actual_omega_step / exposure_time}")

    # Move the photodiode out
    move_photodiode_out()

    # prepare the stage:
    prepare_stage(detector_choice, detector_position_x, detector_position_z, omega_start, x, y, z)
    # prepare the detector
    previous_detector_settings = prepare_detector_settings(detector_choice)

    # perform measurements:
    num_steps = (omega_end - omega_start) / omega_step
    omega_range = omega_end - omega_start

    if callback_fcn is None or (callback_fcn is not None and callback_fcn()):

        if detector_choice == 'pilatus':
            caput(epics_config[detector_choice] + ':cam1:TriggerMode', 3, wait=True)  # 3 is Multi-Trigger, 2 is External

        elif detector_choice == 'eiger2':
            caput(epics_config[detector_choice] + ':cam1:TriggerMode', 2, wait=True)  # 2: External series, 3: External enable
            caput(epics_config[detector_choice] + ':cam1:AcquirePeriod', exposure_time*0.99-0.001, wait=True)
            caput(epics_config[detector_choice] + ':HDF1:NumCapture', num_steps)
            caput(epics_config[detector_choice] + ':HDF1:Capture', 1)

        caput(epics_config[detector_choice] + ':cam1:AcquireTime', exposure_time*0.99-0.001, wait=True)
        caput(epics_config[detector_choice] + ':cam1:NumImages', num_steps, wait=True)
        caput(epics_config[detector_choice] + ':cam1:Acquire', 1)

        # Changed to work with new Automation1 controller. (Chris)
        # TODO: Fix position offsets
        trajectory = Trajectory(
            start_position=omega_start,
            end_position=omega_end,
            exposure=exposure_time,
            number_of_pulses=num_steps,
            travel_direction=1
        )
        controller.load_trajectory(trajectory)

        caput(epics_config['table_shutter'], 0, wait=True)

        controller.run_trajectory()

        while caget(epics_config[detector_choice] + ':cam1:Acquire'):
            continue
        
        caput(epics_config['table_shutter'], 1, wait=True)
    else:
        logger.info('Data collection was aborted!')

    reset_detector_settings(previous_detector_settings)
    logger.info('Data collection finished.\n')

def prepare_stage(detector_choice, detector_position_x, detector_pos_z, omega_start, x, y, z):
    move_to_sample_pos(x, y, z)
    # move_to_omega_position(omega_start)
    if detector_choice == 'pilatus':
        move_to_detector_position(detector_position_x, detector_pos_z, detector_choice)


def prepare_detector(detector_choice):
    previous_shutter_mode = caget(epics_config[detector_choice] + ':cam1:ShutterMode')
    caput(epics_config[detector_choice] + ':cam1:ShutterMode', 1, wait=True)  # 1 is EPICS PV
    return previous_shutter_mode


def prepare_detector_settings(detector_choice):
    previous_detector_settings = {}
    previous_shutter_mode = epics_config[detector_choice] + ':cam1:ShutterMode'
    previous_detector_settings[previous_shutter_mode] = caget(previous_shutter_mode)
    previous_exposure_time = epics_config[detector_choice] + ':cam1:AcquireTime_RBV'
    previous_detector_settings[previous_exposure_time] = caget(previous_exposure_time)
    previous_exposure_period = epics_config[detector_choice] + ':cam1:AcquirePeriod_RBV'
    previous_detector_settings[previous_exposure_period] = caget(previous_exposure_period)
    previous_num_images = epics_config[detector_choice] + ':cam1:NumImages_RBV'
    previous_detector_settings[previous_num_images] = caget(previous_num_images)
    caput(epics_config[detector_choice] + ':cam1:ShutterMode', 1, wait=True)  # 1 is EPICS PV
    previous_trigger_mode = epics_config[detector_choice] + ':cam1:TriggerMode'
    previous_detector_settings[previous_trigger_mode] = caget(previous_trigger_mode)
    return previous_detector_settings


def reset_detector_settings(previous_detector_settings):
    for key in previous_detector_settings:
        pv_name = key.split('_RBV')[0]
        caput(pv_name, previous_detector_settings[key], wait=True)


def collect_wide_data(
        controller, detector_choice, detector_position_x, detector_position_z,
        omega_start, omega_end, exposure_time, x, y, z
):

    # Move the photodiode out
    move_photodiode_out()

    # prepare the stage:
    prepare_stage(detector_choice, detector_position_x, detector_position_z, omega_start, x, y, z)

    # prepare the detector
    previous_detector_settings = prepare_detector_settings(detector_choice)
    
    caput(epics_config[detector_choice] + ':cam1:TriggerMode', 0, wait=True)

    if detector_choice == 'eiger2':
        caput(epics_config[detector_choice] + ':HDF1:NumCapture', 1)
        caput(epics_config[detector_choice] + ':HDF1:Capture', 1)

    caput(epics_config[detector_choice] + ':cam1:AcquireTime', exposure_time * 0.999 - 0.001, wait=True)
    caput(epics_config[detector_choice] + ':cam1:NumImages', 1, wait=True)

    # Start linear movement
    caput(epics_config['sample_position_omega'], omega_start, wait=True)

    old_velocity = caget(epics_config['sample_position_omega'] + '.VELO')

    delta = abs(omega_end - omega_start)
    velocity = delta / exposure_time

    caput(epics_config['sample_position_omega'] + '.VELO', velocity, wait=True)

    caput(epics_config[detector_choice] + ':cam1:Acquire', 1)
    caput(epics_config['sample_position_omega'] + '.VAL', omega_end, wait=True)
    
    while caget(epics_config[detector_choice] + ':cam1:Acquire'):
        continue

    reset_detector_settings(previous_detector_settings)
    caput(epics_config['sample_position_omega'] + '.VELO', old_velocity, wait=True)

    logger.info('Wide data collection finished.\n')
    return

def collect_single_data(detector_choice, detector_position_x, detector_position_z, exposure_time, x, y, z, omega):

    # Move the photodiode out
    move_photodiode_out()

    # performs an actual single angle measurement:
    move_to_sample_pos(x, y, z)
    move_to_omega_position(omega)
    move_to_detector_position(detector_position_x, detector_position_z, detector_choice)

    if detector_choice == 'eiger2':
        caput(epics_config[detector_choice] + ':cam1:TriggerMode', 0, wait=True)
        caput(epics_config[detector_choice] + ':cam1:AcquirePeriod', exposure_time*0.99-0.001, wait=True)
        caput(epics_config[detector_choice] + ':HDF1:NumCapture', 1)
        caput(epics_config[detector_choice] + ':HDF1:Capture', 1)
        time.sleep(0.2) # TODO: Changed during map improvements: original was 1s

    caput(epics_config[detector_choice] + ':cam1:AcquireTime', exposure_time*0.99-0.001, wait=True)
    caput(epics_config[detector_choice] + ':cam1:NumImages', 1, wait=True)
    caput(epics_config[detector_choice] + ':cam1:Acquire', 1, wait=True, timeout=300)

    logger.info('Still data collection finished.\n')

    return


def collect_still_map_with_xps(xps, detector_choice, detector_position_x, detector_position_z, 
                                 exposure_time, x_positions, y, z, omega, sample_point_names=None, 
                                 filepath=None, filename_base=None, filenumber_base=None, 
                                 filename_map=None, rename_files=False, callback_fcn=None):
    """
    Performs still map collection using XPS trajectories for x motor movement.
    Uses XPS define_line_trajectories to move x motor through all positions, triggering detector at each position.
    
    :param xps: NewportXPS instance with group configured
    :param detector_choice: Which detector to use (pilatus or eiger2)
    :param detector_position_x: Detector x position
    :param detector_position_z: Detector z position
    :param exposure_time: Exposure time per still image in seconds
    :param x_positions: List of x positions to collect (sorted)
    :param y: Sample y position (constant for this map row)
    :param z: Sample z position (constant for this map row)
    :param omega: Omega angle (constant)
    :param sample_point_names: Optional list of sample point names for logging (same order as x_positions)
    :param filepath: File path for saving images
    :param filename_base: Base filename (will be updated per position if rename_files is True)
    :param filenumber_base: Base file number
    :param rename_files: If True, use sample_point_names for file naming
    :param callback_fcn: Optional callback function to check for abort (returns False to abort)
    """
    if xps is None:
        logger.error("XPS connection not available. Cannot use XPS trajectories.")
        return
    
    if callback_fcn is not None and not callback_fcn():
        logger.info('Still map collection was aborted before starting!')
        return
    
    # Move the photodiode out
    move_photodiode_out()
    
    # Move y, z, omega to correct positions (constant for this map row)
    logger.info(f'Moving to map row: y={y}, z={z}, omega={omega}')
    move_to_sample_pos(x_positions[0], y, z)  # Move to first x position
    move_to_omega_position(omega)
    move_to_detector_position(detector_position_x, detector_position_z, detector_choice)
    
    # Prepare detector settings
    previous_detector_settings = prepare_detector_settings(detector_choice)
    
    num_positions = len(x_positions)
    
    # Calculate scan parameters for XPS trajectory
    scan_start = x_positions[0]
    scan_end = x_positions[-1]
    scan_range = scan_end - scan_start
    
    # Calculate step size (assuming uniform spacing, use average if not)
    if num_positions > 1:
        step = scan_range / (num_positions - 1)
    else:
        step = 0
    
    # Total scan time
    scantime = exposure_time * num_positions
    
    logger.info(f'Starting XPS trajectory for still map: {num_positions} positions')
    logger.info(f'XPS trajectory: start={scan_start:.4f}, end={scan_end:.4f}, step={step:.4f}, scantime={scantime:.2f}s')
    
    # Set up detector for multiple acquisitions
    if detector_choice == 'eiger2':
        caput(epics_config[detector_choice] + ':cam1:TriggerMode', 2, wait=True)  # External series
        caput(epics_config[detector_choice] + ':cam1:AcquirePeriod', exposure_time*0.99-0.001, wait=True)
        caput(epics_config[detector_choice] + ':HDF1:NumCapture', num_positions)
        caput(epics_config[detector_choice] + ':HDF1:Capture', 1)
    elif detector_choice == 'pilatus':
        caput(epics_config[detector_choice] + ':cam1:TriggerMode', 3, wait=True)  # Multi-Trigger
    
    caput(epics_config[detector_choice] + ':cam1:AcquireTime', exposure_time*0.99-0.001, wait=True)
    caput(epics_config[detector_choice] + ':cam1:NumImages', num_positions, wait=True)
    
    # Set up file naming for first position (will need to handle per-position naming differently)
    if filepath and filename_base is not None:
        if detector_choice == "pilatus":
            caput(epics_config[detector_choice] + ":TIFF1:FilePath", str(filepath), wait=True)
            caput(epics_config[detector_choice] + ":TIFF1:FileName", str(filename_base), wait=True)
            try:
                first_filenumber = int(filenumber_base) if filenumber_base else 1
            except (ValueError, TypeError):
                first_filenumber = 1
            caput(epics_config[detector_choice] + ":TIFF1:FileNumber", first_filenumber, wait=True)
        elif detector_choice == "eiger2":
            caput(epics_config[detector_choice] + ":HDF1:FilePath", str(filepath), wait=True)
            caput(epics_config[detector_choice] + ":HDF1:FileName", str(filename_base), wait=True)
            try:
                first_filenumber = int(filenumber_base) if filenumber_base else 1
            except (ValueError, TypeError):
                first_filenumber = 1
            caput(epics_config[detector_choice] + ":HDF1:FileNumber", first_filenumber, wait=True)
    
    # Define XPS trajectory
    try:
        xps.define_line_trajectories(
            axis=POSITIONERS,
            group=GROUP_NAME,
            stop=scan_range,
            step=step,
            pixeltime=None,
            scantime=scantime,
        )
        
        # Start detector acquisition
        caput(epics_config[detector_choice] + ':cam1:Acquire', 1)
        
        # Run XPS trajectory
        trajectory_name = "still_map_x_trajectory"
        xps.run_trajectory(name=trajectory_name, save=False, clean=True)
        
        # Wait for detector acquisition to complete
        while caget(epics_config[detector_choice] + ':cam1:Acquire'):
            time.sleep(0.1)
            if callback_fcn is not None and not callback_fcn():
                logger.info('Still map collection was aborted during trajectory!')
                break
        
        logger.info('XPS trajectory completed')
        
    except Exception as e:
        logger.error(f'Error running XPS trajectory: {e}')
        # Fall back to individual movements if trajectory fails
        logger.info('Falling back to individual position movements')
        for idx, x_pos in enumerate(x_positions):
            if callback_fcn is not None and not callback_fcn():
                break
            
            motor_x = PV(epics_config['sample_position_x'])
            motor_x.put(x_pos, wait=True)
            time.sleep(0.1)
            
            if detector_choice == 'eiger2':
                caput(epics_config[detector_choice] + ':HDF1:NumCapture', 1)
                caput(epics_config[detector_choice] + ':HDF1:Capture', 1)
                time.sleep(0.2)
            
            caput(epics_config[detector_choice] + ':cam1:Acquire', 1, wait=True, timeout=300)
            while caget(epics_config[detector_choice] + ':cam1:Acquire'):
                time.sleep(0.1)
    
    reset_detector_settings(previous_detector_settings)
    logger.info('Still map collection with XPS finished.\n')
    
    return


def move_to_sample_pos(x, y, z, wait=True, callbacks=[]):
    logger.info('Moving Sample to x: {}, y: {}, z: {}'.format(x, y, z))
    motor_x = PV(epics_config['sample_position_x'])
    motor_y = PV(epics_config['sample_position_y'])
    motor_z = PV(epics_config['sample_position_z'])
    motor_x.put(x, use_complete=True)
    motor_y.put(y, use_complete=True)
    motor_z.put(z, use_complete=True)

    if wait:
        while not motor_x.put_complete and \
                not motor_y.put_complete and \
                not motor_z.put_complete:
            time.sleep(0.1)
        for callback in callbacks:
            callback()
    motor_x.put(x, wait=True)
    motor_y.put(y, wait=True)
    motor_z.put(z, wait=True)
    # time.sleep(0.2)  # TODO: Changed during map improvements: original was 0.5s
    logger.info('Moving Sample to x: {:.2f}, y: {:.2f}, z: {:.2f} finished.\n'.format(x, y, z))
    return


def move_to_omega_position(omega, wait=True):
    logger.info('Moving Sample Omega to {}'.format(omega))
    caput(epics_config['sample_position_omega'], omega, wait=wait)
    if wait:
        logger.info('Moving Sample Omega to {} finished.\n'.format(omega))


def move_to_detector_position(detector_position_x, detector_position_z, detector_choice):
    
    if detector_choice == 'pilatus':
        logger.info('Moving Detector X to {}'.format(detector_position_x))
        caput(epics_config['detector_position_x'], detector_position_x, wait=True, timeout=300)
        logger.info('Moving Pilatus Z to {}'.format(detector_position_z))
        caput(epics_config['pilatus_position_z'], detector_position_z, wait=True, timeout=300)
        logger.info('Moving Detector finished. \n')
        time.sleep(0.5)

    return None


def collect_data(exposure_time, detector_choice, wait=False):
    caput(epics_config[detector_choice] + ':cam1:AcquireTime', exposure_time, wait=True)
    caput(epics_config[detector_choice] + ':cam1:AcquirePeriod', exposure_time+0.001, wait=True)
    logger.info('Starting data collection.')
    caput(epics_config[detector_choice] + ':cam1:Acquire', 1, wait=wait, timeout=exposure_time + 20)
    if wait:
        logger.info('Finished data collection.\n')
