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

import sys
from PySide6.QtWidgets import *  # QTabWidget, QWidget, QToolButton, QTabBar, QApplication, QInputDialog, QRadioButton, QLineEdit


class NewViewOpts(QDialog):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout()

        text_label = QLabel('View name')
        layout.addWidget(text_label)
        self.text_input = QLineEdit()
        layout.addWidget(self.text_input)

        self.done_button = QPushButton('Done')
        self.done_button.clicked.connect(self.submitclose)
        layout.addWidget(self.done_button)

        self.data = {}
        self.canceled = True

        self.setLayout(layout)

    def submitclose(self):
        # do whatever you need with self.roiGroups
        self.canceled = False
        self.data = {
            'view_name': self.text_input.text(),
        }
        self.accept()

    def submitcancel(self):
        # do whatever you need with self.roiGroups
        self.canceled = True
        self.accept()


class QTabWidgetPlus(QTabWidget):
    """Tab widget where additional tabs can be created."""
    new_tab_dialog_type=NewViewOpts
    def __init__(self,  ):
        QTabWidget.__init__(self)
        self.setTabsClosable(True)
        self.tabCloseRequested.connect(lambda index: self.removeTab(index))
        self._build_tabs()
        self.n_tabs = 1

    def _build_tabs(self):
        """Defines how new tabs are created."""
        self.insertTab(0, QWidget(), "View 1")
        self.insertTab(1, QWidget(), '')
        nb = self.new_btn = QToolButton()
        nb.setText('+')  # you could set an icon instead of text
        nb.setAutoRaise(True)
        nb.clicked.connect(self.new_tab)
        self.tabBar().setTabButton(1, QTabBar.RightSide, nb)

    def new_tab(self):
        """Create new tab"""
        new_view_dialog = self.new_tab_dialog_type()
        new_view_dialog.exec()
        print(new_view_dialog.data)
        
        if not new_view_dialog.canceled:
            self.n_tabs += 1
            index = self.count() - 1
            # "View %d" % (self.n_tabs))
            self.insertTab(index, QWidget(), new_view_dialog.data['view_name'])
            self.setCurrentIndex(index)


        
        


if __name__ == '__main__':

    app = QApplication(sys.argv)

    # new_view_opts = NewViewOpts()
    # new_view_opts.exec()
    # print(new_view_opts.data)
   
    tabs = QTabWidgetPlus()
    tabs.show()
    

    app.exec()
