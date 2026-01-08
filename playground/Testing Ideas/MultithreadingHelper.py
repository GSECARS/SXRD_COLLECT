__author__ = 'DAC_User'

import time
import sys
from PyQt4 import QtCore, QtGui


def test_dummy_function(iterations):
    for n in range(iterations):
        time.sleep(1)
        print("{} iterations".format(n+1))


class ThreadRunner():
    def __init__(self, fcn, args):
        self.worker_thread = WorkerThread(fcn, args)
        self.worker_finished = False

        self.worker_thread.finished.connect(self.update_status)
        self.worker_thread.terminated.connect(self.update_status)

    def run(self):
        self.worker_finished = False
        self.worker_thread.start()

        while not self.worker_finished:
            time.sleep(0.1)

    def update_status(self):
        self.worker_finished = True


class WorkerThread(QtCore.QThread):
    def __init__(self, func, args):
        super(WorkerThread, self).__init__()
        self.func = func
        self.args = args

    def run(self):
        self.func(*self.args)


if __name__ == '__main__':

    app = QtGui.QApplication(sys.argv)

    thread_runner = ThreadRunner(test_dummy_function, 4)
    thread_runner.run()


    app.exec_()

