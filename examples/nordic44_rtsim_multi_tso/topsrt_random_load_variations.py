import tops.dynamic as dps
import tops.solvers as dps_sol
from topsrt.sim import RealTimeSimulator, RealTimeSimulatorThread
import threading
import time
import sys
from PySide6 import QtWidgets
from topsrt.gui import LineOutageWidget
from topsrt.time_window_plot import TimeWindowPlot
from topsrt.rtsim_plot import RTSimPlot, SyncPlot
from topsrt.pmu import PMUPublisher
from topsrt.interfacing import InterfacerQueuesThread


import numpy as np
from pyqtgraph.console import ConsoleWidget

# load_bus_idx = rts.ps.loads['Load'].bus_idx_red['terminal']
# random_process = np.zeros(len(load_bus_idx), dtype=complex)
# dt = rts.dt
# th = 1
# mu = 0
# sig = 1e-1
# def apply_random_load_variations(rts, random_process):
#     while True:
#         random_process[:] = random_process + th*(mu - random_process)*dt+sig*np.sqrt(dt) * np.random.randn(len(load_bus_idx))
#         rts.ps.y_bus_red_mod[load_bus_idx, load_bus_idx] = random_process
# import threading
# random_load_variations_thread = threading.Thread(target=apply_random_load_variations, args=(rts, random_process))
# random_load_variations_thread.start()


class RandomLoadVariations(InterfacerQueuesThread):
    @staticmethod
    def read_input_signal(rts):
        return 1

    @staticmethod
    def get_init_data(rts):
        load_mdl = rts.ps.loads['DynamicLoadFiltered']
        # n_loads = load_mdl.n_unit
        g_0 = load_mdl.g_setp(rts.ps.x_0, rts.ps.v_0)
        # B_0 = load_mdl.b_setp(rts.ps.x_0, rts.ps.v_0)
        return rts.dt, g_0

    def initialize(self, init_data):
        self.dt, self.g_0 = init_data
        self.n_loads = len(self.g_0)
        self.mu = self.g_0.copy()
        self.th = np.ones(self.n_loads)
        self.sig = 2e-2*np.ones(self.n_loads)*self.g_0
        self.random_process = self.mu.copy()

    @staticmethod
    def apply_ctrl_signal(rts, ctrl_signal):
        rts.ps.loads['DynamicLoadFiltered'].set_input('g_setp', ctrl_signal)
        # rts.ps.loads['DynamicLoad'].set_input('b_setp', ctrl_signal)

    def update(self, input_signal):
        self.random_process[:] = self.random_process + self.th*(
            self.mu - self.random_process)*self.dt + self.sig*np.sqrt(self.dt) * np.random.randn(self.n_loads)

    def generate_ctrl_signal(self):
        # Generate control signal from internal states
        # self.sliders_G[load_idx].value()*self.max_Y/100
        # self.sliders_B[load_idx].value()*self.max_Y/100
        ctrl_signal = self.random_process
        return ctrl_signal


def remove_model_data(self, target_container, target_mdl):
    getattr(self, target_container).pop(target_mdl)
    removed_mdl = self.dyn_mdls_dict[target_container].pop(target_mdl)
    self.dyn_mdls.pop(
        np.argmax(np.array(self.dyn_mdls, dtype=object) == removed_mdl))
    print(f"Model {target_container}: {target_mdl} was removed.")


def main():

    import socket
    # Get local ip automatically
    ip = socket.gethostbyname(socket.gethostname())
    port = 50000

    import tops.ps_models.k2a as model_data
    model = model_data.load()
    # model['loads'] = {'DynamicLoadFiltered': model['loads']}

    ps = dps.PowerSystemModel(model=model)
    ps.add_model_data({"loads": {
        "DynamicLoadFiltered": [
            [*ps.loads["Load"].par.dtype.names, "T_g", "T_b"],
            *[[*load_data, 10, 10] for load_data in ps.loads["Load"].par],
        ]}
    })

    remove_model_data(ps, "loads", "Load")
    # ps.add_model_data({'DynamicLoad': ps.loads['Load'].par})
    # ps.loads.pop('Load')
    ps.init_dyn_sim()

    ps.ode_fun(0, ps.x0)
    rts = RealTimeSimulatorThread(
        ps, dt=10e-3, speed=1, solver=dps_sol.ModifiedEulerDAE)

    random_loads = RandomLoadVariations(rts, name='RandomLoads')
    random_loads.start()

    app = QtWidgets.QApplication(sys.argv)

    c = ConsoleWidget(
        namespace={'np': np, 'rts': rts, 'random_loads': random_loads}, text='')
    c.show()

    tw_plot = RTSimPlot(rts=rts, n_samples=1000)
    sync_plot = SyncPlot(rts=rts, n_samples=1000, update_freq=25)

    rts.start()
    tw_plot.start()
    sync_plot.start()

    # Add Control Widgets
    line_outage_ctrl = LineOutageWidget(rts)

    app.exec()

    return app


if __name__ == '__main__':
    main()
