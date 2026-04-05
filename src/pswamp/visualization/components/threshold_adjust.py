# LICENSE HEADER MANAGED BY add-license-header
#
# Copyright 2026 NTNU/SINTEF/Statnett SF
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

from PySide6.QtWidgets import QApplication, QWidget, QGridLayout, QSlider
from PySide6.QtCore import Qt
import numpy as np
import time
import threading

import warnings
warnings.filterwarnings("ignore", category=RuntimeWarning)
# from qtrangeslider import QRangeSlider


class QSliderReadOnly(QSlider):
    def mousePressEvent(self, ev):
        pass
    def mouseReleaseEvent(self, ev):
        pass
    def mouseMoveEvent(self, ev):
        pass
    def keyPressEvent(self, ev):
        pass
    def keyReleaseEvent(self, ev):
        pass


class ThresholdAdjustment(QWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        layout = QGridLayout()
        self.range_slider = QRangeSlider(Qt.Horizontal)
        self.indicator_slider = QSliderReadOnly(Qt.Horizontal)
        self.indicator_slider.setStyleSheet('''
            QSlider::groove:horizontal {border: 0px solid;}
            QSlider::handle:horizontal {
                background-color: red;
                border: 0px solid;
                height: 40px;
                width: 3px;
                margin: -15px 0px;
            }
        ''')

        layout.addWidget(self.indicator_slider, 0, 0)
        layout.addWidget(self.range_slider, 0, 0)
        self.setLayout(layout)


def main():
    app = QApplication()
    thr_adj = ThresholdAdjustment()

    def move_indicator():
        while True:
            rand_nr = np.random.randn()
            thr_adj.indicator_slider.setValue(abs(rand_nr)*100)
            time.sleep(1)

    thr = threading.Thread(target=move_indicator)
    thr.start()

    thr_adj.show()
    app.exec()


if __name__ == '__main__':
    main()
