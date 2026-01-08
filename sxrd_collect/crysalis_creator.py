import os
import shutil
import numpy as np
from cryio import cbfimage, crysalis, esperanto
from dataclasses import dataclass, field
from fabio.app import eiger2crysalis


@dataclass
class Options:

    output: str  # {dirname}/{prefix}/{prefix}_1_{index}.esperanto
    wavelength: float
    distance: float
    beam: list[float]
    rotation: int
    transpose: bool
    flip_ud: bool
    flip_lr: bool
    alpha: float
    kappa: str
    theta: str
    phi: str
    omega: str
    polarization: float


    energy: float = field(init=True, default=42)
    offset: int = field(init=True, default=1)
    dry_run: bool = field(init=True, default=False)
    debug: bool = field(init=True, default=False)
    dummy: int = field(init=True, default=-1)

    images: list[str] = field(init=True, default_factory=lambda: [])
    verbose: bool = field(init=True, default=False)



def make_directory(filepath, basename):

    new_directory = os.path.normpath(os.path.join(filepath, basename + '_crys'))
    if os.path.isdir(new_directory):
        shutil.rmtree(new_directory)
    os.makedirs(new_directory)

def padarray(array):
    """
    This funcion is needed for making square images out of rectangular. Needed for esperanto format
    """
    a = np.empty((1043, 31), dtype=array.dtype)
    b = np.empty((1043, 32), dtype=array.dtype)
    a.fill(-1)
    b.fill(-1)

    array = np.hstack((array, a))
    array = np.hstack((b, array))

    c = np.empty((1,1044), dtype=array.dtype)
    c.fill(-1)
    array = np.vstack((array,c))

    return array

def transform_h5_to_esperanto(filepath, basename, filenumber, esperanto_scan_info):
    
    options = Options(
        output=f"{{dirname}}/{basename}_{filenumber:03}_crys/{basename}_{filenumber:03}_1_{{index}}.esperanto",
        wavelength=0.2952,
        distance=esperanto_scan_info["dist"],
        beam=[esperanto_scan_info["center_x"], esperanto_scan_info["center_y"]],
        rotation=180,
        transpose=False,
        flip_ud=False,
        flip_lr=True,
        alpha=esperanto_scan_info["alpha"],
        kappa=str(esperanto_scan_info["kappa"]),
        theta=str(esperanto_scan_info["theta"]),
        phi=str(esperanto_scan_info["phi"]),
        omega=f"{esperanto_scan_info["omega_start"]} + {esperanto_scan_info["domega"]} * i",
        polarization=esperanto_scan_info["mono"],
        images=[f"{filepath}/{basename}_{filenumber:03}.h5"]
    )
    converter = eiger2crysalis.Converter(options=options)
    converter.convert_all()
    converter.finish()


def transform_cbf_to_esperanto(filepath, basename, esperanto_scan_info):

    new_directory = os.path.normpath(os.path.join(filepath, basename + '_crys'))

    for i in range(esperanto_scan_info['count']):

        try:
            cbf_file = os.path.normpath(os.path.join(filepath, basename + '_{0:05d}'.format(i + 1) + '.cbf'))
            esp_file = os.path.normpath(os.path.join(new_directory, basename + '_1_' + str(i + 1) + '.esperanto'))

            image = cbfimage.CbfImage(cbf_file)

            array_trans = np.flip(image.array, 0)
            new_image_array = padarray(array_trans)

            rot = esperanto_scan_info
            rot['omega'] = rot['omega_start'] + rot['domega'] * i

            esp = esperanto.EsperantoImage()
            esp.save(esp_file, new_image_array, **rot)
        except Exception as e:
            break


def copy_set_ccd(filepath, basename, config):
    new_directory = os.path.normpath(os.path.join(filepath, basename + '_crys'))
    shutil.copy(config['set_file'], os.path.join(new_directory, basename+'.set'))
    shutil.copy(config['ccd_file'], os.path.join(new_directory, basename+'.ccd'))


def createCrysalis(scans, basename, filepath):

    new_directory = os.path.normpath(os.path.join(filepath, basename + '_crys'))

    runHeader = crysalis.RunHeader(basename.encode(), new_directory.encode(), 1)
    runname = os.path.join(new_directory, basename)
    runFile = []

    for omega_run in scans[0]:
        dscr = crysalis.RunDscr(0)
        dscr.axis = crysalis.SCAN_AXIS['OMEGA']
        dscr.kappa = omega_run['kappa']
        dscr.omegaphi = 0
        dscr.start = omega_run['omega_start']
        dscr.end = omega_run['omega_end']
        dscr.width = omega_run['domega']
        dscr.todo = dscr.done = omega_run['count']
        dscr.exposure = 1
        runFile.append(dscr)

    crysalis.saveRun(runname, runHeader, runFile)
    crysalis.saveCrysalisExpSettings(new_directory)


def create_par_file(filepath, basename, par_file):

    new_directory = os.path.normpath(os.path.join(filepath, basename + '_crys'))
    new_par = os.path.join(new_directory, basename+'.par')

    with open(new_par, 'w') as new_file:
        with open(par_file, 'r') as old_file:
            for line in old_file:
                if line.startswith("FILE CHIP"):
                    new_file.write("FILE CHIP " + basename + '.ccd ' + '\n')
                else:
                    new_file.write(line)