from PyQt4 import QtCore, QtGui
import sys
import time


class Window(QtGui.QWidget):
    def __init__(self):
        super(Window, self).__init__()

        # Layout
        text_box = QtGui.QTextBrowser()
        self.button = QtGui.QPushButton()
        vert_layout = QtGui.QVBoxLayout()
        vert_layout.addWidget(text_box)
        vert_layout.addWidget(self.button)
        self.setLayout(vert_layout)

        # Connect button
        self.button.clicked.connect(self.buttonPressed)

        # Thread
        self.bee = Worker(self.someProcess, ())
        self.bee.finished.connect(self.restoreUi)
        self.bee.terminated.connect(self.restoreUi)

    def buttonPressed(self):
        self.button.setEnabled(False)
        self.bee.start()

    def someProcess(self):
        for i in xrange(10):
            time.sleep(2)
            self.test_func()

    def restoreUi(self):
        self.button.setEnabled(True)

    def test_func(self):
        print('hahaha')


class Worker(QtCore.QThread):
    def __init__(self, func, args):
        super(Worker, self).__init__()
        self.func = func
        self.args = args

    def run(self):
        self.func(*self.args)


if __name__ == "__main__":
    app = QtGui.QApplication(sys.argv)
    window = Window()
    window.show()
    sys.exit(app.exec_())