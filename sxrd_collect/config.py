__author__ = 'Clemens Prescher'

from enum import Enum

class Detectors(Enum):
    pilatus_300k = "Pilatus 300K", "13PIL300K", 0
    pilatus_1m = "Pilatus 1M", "13PIL3", 0
    pilatus_MCdTe = "Pilatus MCdTe", "13PIL1MCdTe", 0
    eiger2_9m = "Eiger 2S 9M", "13EIG2_9M", 1


class IDDStages(Enum):
    detector_position_x = "13IDD:m8"


class Stations(Enum):
    idd = 1
    bmd = 0

for choice in Detectors:
    if choice.value[2] == 1:
        detector = choice.value[1]


epics_config = {
    'detector_position_x': '13IDD:m8',
    'sample_position_x': '13IDD:m98',
    'sample_position_y': '13IDD:m97',
    'sample_position_z': '13IDD:m99',
    'sample_position_omega': '13IDD:Auto1:m1',
    'all_stop': '13IDD_Linux:allstop',
    'all_stop_xps': '13IDD_DAC_XPS16:allstop',
    '13IDA_wavelength': '13IDA:mono_pid1_incalc.N',
    'table_shutter': '13IDD:TableShutter.VAL',
    'status_message': detector + ':cam1:StatusMessage_RBV',
    
    'pilatus': detector,
    'pilatus_proc': detector + ':Proc1',
    'pilatus_file': detector + ':TIFF1',
    'pilatus_control': detector + ':cam1',
    'pilatus_position_z': '13IDD:m5',
    'pilatus_info_wavelength': detector + ':cam1:Wavelength',
    'pilatus_info_omega': detector + ':cam1:Omega',
    'pilatus_info_omega_increment': detector + ':cam1:OmegaIncr',

    'eiger2': detector,
    'pilatus_proc': detector + ':Proc1',
    'pilatus_file': detector + ':HDF1',
    'pilatus_control': detector + ':cam1',
    'pilatus_position_z': '13IDD:m5',
    'pilatus_info_wavelength': detector + ':cam1:Wavelength',
    'pilatus_info_omega': detector + ':cam1:Omega',
    'pilatus_info_omega_increment': detector + ':cam1:OmegaIncr',

    'detector_trigger_16': '13IDD:EDIO24_1:Bo16',
    'detector_trigger_17': '13IDD:EDIO24_1:Bo17'
}

pilatus_crysalis_config = {
        'set_file': 'P:\\dac_user\\Crysalis_config\\pilatus_1m.set',
        'ccd_file': 'P:\\dac_user\\Crysalis_config\\pilatus_1m.ccd',
        'par_file': 'P:\\dac_user\\Crysalis_config\\pilatus_1m.par'
}

eiger2_crysalis_config = {
        'set_file': 'P:\\dac_user\\Crysalis_config\\eiger2_9m.set',
        'ccd_file': 'P:\\dac_user\\Crysalis_config\\eiger2_9m.ccd',
        'par_file': 'P:\\dac_user\\Crysalis_config\\eiger2_9m.par'
}

log_file = "T:/dac_user/sxrd_logs/sxrd_log.txt"
file_format_string = "%s%s_%4.4d_00001.tif"
cycle_relative_path = '/2026/IDD_2025-1'
FILEPATH = 'T:/dac_user' + cycle_relative_path
if detector == '13PIL3':
    DETECTOR_FILE_PATH = '/ramdisk/dac_user' + cycle_relative_path
# elif detector == '13PIL300K' or '13PIL1MCdTe':
#     DETECTOR_FILE_PATH = '/cars6/Data/dac_user' + cycle_relative_path
elif detector == '13EIG2_9M':
    DETECTOR_FILE_PATH = '/home/dac_user/cars6/Data/dac_user' + cycle_relative_path


print(f"DETECTOR FP: {DETECTOR_FILE_PATH}")
print(f"DETECTOR: {detector}")
