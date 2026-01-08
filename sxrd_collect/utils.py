from epics import caput, caget
import time
from sxrd_collect.config import epics_config


def caput_pil3(pv, value, wait=True):
    t0 = time.time()
    caput(pv, value, wait=wait)

    while time.time() - t0 < 20.0:
        time.sleep(0.02)
        if 'OK' in caget(epics_config['status_message'], as_string=True):
            return True
    return False


def move_photodiode_out():
    """Moves the photodiode out. Chris 10/4/2024"""
    if caget("13IDD:Photodiode") == 0:
        caput("13IDD:Photodiode", 1)
        time.sleep(2)
