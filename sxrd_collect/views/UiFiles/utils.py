from qtpy import QtCore, QtGui, QtWidgets


class HoverButton(QtWidgets.QPushButton):
    mouseHover = QtCore.Signal(bool)

    def __init__(self, parent=None):
        QtWidgets.QPushButton.__init__(self, parent)
        self.setMouseTracking(True)

    def enterEvent(self, event):
        self.mouseHover.emit(True)

    def leaveEvent(self, event):
        self.mouseHover.emit(False)
