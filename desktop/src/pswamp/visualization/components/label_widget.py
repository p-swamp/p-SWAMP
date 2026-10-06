# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

from PySide6.QtWidgets import QWidget, QVBoxLayout, QApplication
from PySide6.QtGui import QPainter, QPixmap
# from PySide6.QtCore import Qt
import sys

class Label(QWidget):
    def __init__(self, parent=None):
        QWidget.__init__(self, parent=parent)
        self.p = QPixmap()

    def setPixmap(self, p):
        self.p = p
        self.update()

    def paintEvent(self, event):
        if not self.p.isNull():
            painter = QPainter(self)
            painter.setRenderHint(QPainter.SmoothPixmapTransform)
            r = self.rect()
            rect_w = r.getRect()[2]
            pixmap_aspect = self.p.width()/self.p.height()
            new_height = rect_w/pixmap_aspect
            r.setHeight(new_height)
            painter.drawPixmap(r, self.p)
            self.setMinimumHeight(new_height)


class LabelWidget(QWidget):
    def __init__(self, img_path, parent=None):
        QWidget.__init__(self, parent=parent)
        lay = QVBoxLayout(self)
        lb = Label(self)
        lb.setPixmap(QPixmap(img_path))
        lay.addWidget(lb)


if __name__ == '__main__':
    app = QApplication(sys.argv)
    from pathlib import Path
    img_path = Path(__file__).parents[4] /\
        r"examples\nordic44_rtsim_multi_tso\tso_logos\statnett.svg"
    w = LabelWidget(img_path)
    w.show()
    sys.exit(app.exec())
