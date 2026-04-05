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

import numpy as np
import threading
from PySide6 import QtGui
import uuid
from pswamp.utils.get_station_coords import load_bus_coords_for_stations
import pyqtgraph.opengl as gl
import pickle
from pswamp.streaming import Consumer, get_last_message_from_topic
from pswamp.utils.gl import set_gl_options


class VoltageStability:
    def __init__(self, parent, config, geo=True) -> None:
        self.config = config

        self.input_stream = Consumer(
            topic=config['topics']['voltage.stability.index'], **config["streaming"], value_deserializer=pickle.loads)

        self.is_stopped = False

        sample_msg = get_last_message_from_topic(
            config["topics"]["voltage.stability.index"], **config["streaming"]
        )
        station = sample_msg['info']['locations']

        consumer_thread = threading.Thread(target=self.run_consumer)
            
        self.plotWidget = parent.plotWidget

        self.k = 2 if geo else 1
        self.uuid = uuid.uuid4()
        self.parent = parent
        self.z_scale = 3

        bus_coords_3d =  load_bus_coords_for_stations(config, [station], return_3d=True, geo=geo)
        # bus_names, bus_coords_3d = load_bus_coords_for_current_stations(
        #     config, geo=geo, return_3d=True)
        bus_coords_3d[:, 1] *= self.k

        self.x = bus_coords_3d[:, 0]
        self.y = bus_coords_3d[:, 1]
        self.z = bus_coords_3d[:, 2]
        # self.z = self.z_0.copy()

        # self.base_color = [255, 0, 0]
        
        pos = np.concatenate([self.x, self.y, self.z])
        # self.bus_scatter = gl.GLScatterPlotItem(
        #     pos=
        #     color=[0, 0, 0],
        #     size=100,
        # )
        # self.plotWidget.addItem(self.bus_scatter)
        font = QtGui.QFont()
        font.setPixelSize(12)
        self.text_item = gl.GLTextItem(
            pos=pos, text="", font=font
        )
        
        set_gl_options(self.config, self.text_item)

        self.plotWidget.addItem(self.text_item)

        parent.update_funs[self.uuid] = self.update_text

        consumer_thread.start()

    def run_consumer(self):
        for kafka_msg in self.input_stream:
            if self.is_stopped:
                break
            self.vsi = kafka_msg.value['result']['ratio']
            self.power_margin = kafka_msg.value['result']['Pmargin']

    def stop(self):
        self.stopped = True
    
    def update_text(self):
        self.text_item.setData(
            text="VSI: {:.2f}, P: {:.2f}".format(self.vsi, self.power_margin))

        # self.bus_scatter.setData(pos=np.vstack([self.x, self.y, self.z]).T)
        # self.bus_scatter.update(freq)
        # edge_pos = self.generate_bus_lines()
        # self.bus_lines.setData(pos=edge_pos)
        # color = [0, 0, 0] if self.vsi < 0.8 else self.base_color*self.vsi
        # self.bus_scatter.setData(color=color)
    
    def remove_layer(self):
        self.plotWidget.removeItem(self.bus_scatter)
