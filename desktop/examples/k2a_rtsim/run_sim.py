import multiprocessing as mp
import numpy as np

from topsrt.interfacing import QueueManager, InterfaceListener
from PySide6 import QtWidgets, QtCore
from topsrt.rtsim_plot import SyncPlot
import sys
from topsrt.rtsim_plot import RTSimPlot
import tops.dynamic as dps
from topsrt.sim import RealTimeSimulatorThread
from topsrt.gui import LineOutageWidget, SimulationControl, ConsoleWidget, VSCControlWidget
from topsrt.pmu_currents_freq import PMUPublisherCurrentsFreq as PMUPublisher
from multiprocessing.managers import dispatch,listener_client

import time
import multiprocessing as mp
from topsrt_random_load_variations import RandomLoadVariations, remove_model_data
import socket
local_ip = socket.gethostbyname(socket.gethostname())



def main_pmu(qm_kwargs, pmu_publisher_type=PMUPublisher, pmu_kwargs={'ip': local_ip, 'port': 50000, 'publish_frequency': 10}):
    manager = QueueManager(**qm_kwargs)
    manager.connect()

    app = QtWidgets.QApplication(sys.argv)
    # interface = RTSimPlot(n_samples=1000)
    # InterfaceListener.send_interface_init(manager, interface)

    sync_plot = SyncPlot(n_samples=1000, update_freq=50)
    tw_plot = RTSimPlot(n_samples=1000)
    pmus = pmu_publisher_type(**pmu_kwargs)

    [InterfaceListener.send_interface_init(manager, interface) for interface in [sync_plot, pmus, tw_plot]]
    sync_plot.start()
    pmus.start()
    tw_plot.start()

    app.exec()

    return app


def stop_server(address, authkey):
    # From stackoverflow:
    # https://stackoverflow.com/questions/44940164/stopping-a-python-multiprocessing-basemanager-serve-forever-server
    _Client = listener_client['pickle'][1]
    conn = _Client(address=address, authkey=authkey)
    dispatch(conn, None, 'shutdown')
    conn.close()


class RTSimControlPanel(QtWidgets.QWidget):
    def __init__(self, rts, console_namespace={}):
        super().__init__()

        self.setAutoFillBackground(True) 
        p = self.palette()
        p.setColor(self.backgroundRole(), QtCore.Qt.gray)
        self.setPalette(p)

        self.setWindowTitle('Real time simulation controls')
        
        self.line_outage_ctrl = LineOutageWidget(rts)
        self.sim_ctrl = SimulationControl(rts)
        # self.load_ctrl = VSCControlWidget(rts, max_dev=5)
        self.console = ConsoleWidget(namespace=console_namespace)
        
        layout = QtWidgets.QGridLayout()
        layout.addWidget(QtWidgets.QLabel('Connect/disconnect lines'), 0, 0, 1, 2)
        layout.addWidget(self.line_outage_ctrl.ctrlWidget, 1, 0, 1, 2)
        layout.addWidget(QtWidgets.QLabel('Simulation speed, pause, reset'), 2, 0)
        layout.addWidget(self.sim_ctrl.ctrlWidget, 3, 0)
        layout.addWidget(QtWidgets.QLabel('Adjust loads'), 4, 0)
        # layout.addWidget(self.load_ctrl.ctrlWidget, 5, 0)
        layout.addWidget(QtWidgets.QLabel('Console'), 2, 1)
        layout.addWidget(self.console, 3, 1, 3, 1)

        self.setLayout(layout)



def main(qm_kwargs, speed=1, t_end=np.inf):

    manager = QueueManager(**qm_kwargs)
    manager.connect()
    init_queue = manager.get_init_queue()
    interface_listener = InterfaceListener(init_queue)

    from sim import create_sim
    ps = create_sim()
    rts = RealTimeSimulatorThread(ps, dt=10e-3, t_end=t_end, speed=speed)

    random_loads = RandomLoadVariations(rts, name='RandomLoads')
    random_loads.start()

    interface_listener.connect(rts)
    interface_listener.start()

    app = QtWidgets.QApplication(sys.argv)

    # Add Control Widgets
    control_panel = RTSimControlPanel(rts, console_namespace=dict(
        rts=rts, random_loads=random_loads)
    )
    control_panel.show()

    rts.start()
    app.exec()
    rts.stop()
        
    stop_server(**qm_kwargs)

    return app


def main_server(qm_kwargs):
    manager = QueueManager(server=True, **qm_kwargs)
    manager.start()




def run_rtsim(**pmu_kwargs):
    ip = 'localhost'
    qm_kwargs = dict(address=(ip, 51020), authkey=b'abracadabra')

    p_server = mp.Process(target=main_server, args=(qm_kwargs,))
    p_server.start()
    time.sleep(1)

    p_1 = mp.Process(target=main, args=(qm_kwargs,))
    p_1.start()

    p_2 = mp.Process(target=main_pmu, args=(qm_kwargs,), kwargs=pmu_kwargs)
    p_2.start()


if __name__ == '__main__':
    from pswamp import load_config
    config = load_config('config.toml')
    run_rtsim(pmu_kwargs=dict(ip=config['pmus']['ip'], port=config['pmus']['port']))
