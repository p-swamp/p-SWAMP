# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

import numpy as np
from pswamp.app_templates.time_window_app import TimeWindowApp
from pswamp.app_templates.status_reporting import AlarmHandler
from pswamp import load_config
from nfoursid.nfoursid import NFourSID
import pandas as pd
from scipy.linalg import logm
from scipy.linalg._matfuncs_inv_ssq import LogmNearlySingularWarning, LogmExactlySingularWarning
import warnings

# warnings.filterwarnings("error")
warnings.simplefilter("error", category=LogmNearlySingularWarning)
warnings.simplefilter("error", category=LogmExactlySingularWarning)

class N4SID:
    """
    Class for running system identification using the NFourSID package.
    """
    def __init__(self, dt, n_measurements, sys_order=10, num_block_rows=10):
        self.n_measurements = n_measurements
        self.sys_order = sys_order
        self.num_block_rows = num_block_rows
        self.dt = dt

        self.eigs = np.zeros(self.sys_order, dtype=complex)
        self.damping = np.zeros(self.sys_order)
        self.freq = np.zeros(self.sys_order)
        self.em_idx = np.zeros(self.sys_order, dtype=bool)

        self.rev = np.zeros((self.sys_order,) * 2, dtype=complex)
        self.a_c = np.zeros((self.sys_order,) * 2, dtype=complex)
        self.c = np.zeros((self.n_measurements, self.sys_order), dtype=complex)
        self.mode_shapes = np.zeros(
            (self.n_measurements, self.sys_order), dtype=complex
        )

    def run_sid(self, y):
        """Run system identification (N4SID) and calculate eigenvalues and observability mode shapes.
        Args:
            y:

        Returns:

        """
        y_names = ["y{}".format(i) for i in range(y.shape[1])]
        y_df = pd.DataFrame(columns=y_names, data=y)
        #
        nfoursid = NFourSID(
            y_df,
            output_columns=y_names,
            num_block_rows=self.num_block_rows,
        )
        nfoursid.subspace_identification()
        state_space_identified, covariance_matrix = nfoursid.system_identification(
            rank=self.sys_order
        )

        
        try:
            a_log_mat = logm(state_space_identified.a)
        except (LogmNearlySingularWarning, LogmExactlySingularWarning):
            self.eigs *= np.nan
            self.damping *= np.nan
            self.freq *= np.nan
            self.rev *= np.nan
            self.mode_shapes *= np.nan
            return self.eigs, self.mode_shapes


        self.a_c = (np.array(a_log_mat)/self.dt)  # Convert discrete system to continuous
        self.c = state_space_identified.c
        self.eigs, self.rev = np.linalg.eig(
            self.a_c
        )  # Compute eigenvalues from continuous system matrix
        self.damping = -self.eigs.real / abs(self.eigs)
        self.freq = self.eigs.imag / (2 * np.pi)

        # Sorting: Lowest damping first. Non-oscillatory eigenvalues are left out of sorting.
        self.em_idx = (abs(self.eigs.imag)/(2*np.pi) > 0.1) & (abs(self.eigs.imag)/(2*np.pi) < 2)
        to_be_sorted = self.em_idx  # (abs(self.eigs)> 1e-6) & (abs(self.eigs.imag) > 1e-6)
        sort_idx = np.argsort(self.damping[to_be_sorted])
                
        self.eigs = np.concatenate([self.eigs[to_be_sorted][sort_idx], self.eigs[~to_be_sorted]])
        self.damping = np.concatenate([self.damping[to_be_sorted][sort_idx], self.damping[~to_be_sorted]])
        self.freq = np.concatenate([self.freq[to_be_sorted][sort_idx], self.freq[~to_be_sorted]])
        self.rev = np.hstack([self.rev[:, to_be_sorted][:, sort_idx], self.rev[:, ~to_be_sorted]])

        self.em_idx = np.concatenate([self.em_idx[to_be_sorted][sort_idx], self.em_idx[~to_be_sorted]])


        self.mode_shapes = self.c.dot(self.rev)  # Observability mode shapes
        

        return self.eigs, self.mode_shapes

class N4SIDApp(N4SID, TimeWindowApp):
    """
    An online implementation of the N4SID system identification class.
    """

    def __init__(
            self,
            eval_freq=1,
            channel_selection={'measurement': 'f'}, 
            sys_order=10,
            num_block_rows=10,
            **kwargs
        ):
        TimeWindowApp.__init__(
            self,
            eval_freq=eval_freq,
            channel_selection=channel_selection,
            app_name='N4SIDApp',
            report_status=True,
            **kwargs
        )
        self.init(sys_order=sys_order, num_block_rows=num_block_rows)
        self.alarm_handler = AlarmHandler(self)
        self.update_callbacks.append(self.alarm_handler.update)

    def init(self, sys_order=10, num_block_rows=10):
        self.sys_order = sys_order
        N4SID.__init__(self, self.sampling_time, self.tw.n_channels,
            sys_order=self.sys_order, num_block_rows=num_block_rows)

    def run_analysis(self, t, phasors):
        # If time window is not yet filled up (i.e. there are nan values left), remove the nan values and perform
        # the analysis
        if np.any(np.isnan(t)):
            not_nan_idx = ~(np.isnan(t) | np.any(np.isnan(phasors), axis=1))
            t = t[not_nan_idx]
            phasors = phasors[not_nan_idx, :]

            self.status = 'Initializing...'
            return None
        
        # Return system identification result
        sid_res = self.run_sid(phasors)
        
        if np.any(self.damping[self.em_idx] < 0.03):
            self.status = 'Emergency'
        elif np.any(self.damping[self.em_idx] < 0.07):
            self.status = 'Alert'
        else:
            self.status = 'OK'

        return_value = {
            'info': {
                'app_name': self.app_name,
                'uuid': self.uuid,
            },
            'parameters': {
                'n_measurements': self.n_measurements,
                'order': self.sys_order,
                'eval_freq': self.eval_freq,
                # 'channel_selection_idx': self.decoder.channel_selection_idx,

            },
            'result': {
                'time_stamp': t[-1],
                'eigenvalues': sid_res[0],
                'mode_shapes': sid_res[1],
            },
        }
        return return_value



def run_n4sid(config, window_length=45, sys_order=10, channel_selection_idx=None,):
    sid = N4SIDApp(
        io_kwargs=config["streaming"],
        window_length=window_length,
        input_topic=config['topics']["pmudata"],
        output_topic=config['topics']["modeestimation"],
        sys_order=sys_order,
        channel_selection_idx=channel_selection_idx,
    )

    sid.start()


if __name__ == '__main__':
    config = load_config()
    run_n4sid(config)
