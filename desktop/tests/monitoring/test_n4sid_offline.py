from pswamp.monitoring.n4sid import N4SID
import numpy as np
# import matplotlib.pyplot as plt


def test_N4SID_offline():

    n_measurements = 10
    dt = 0.02
    t = np.arange(0, 10, dt)
    f = 0.5
    np.random.seed(0)
    y = np.vstack([amp*np.sin(2*np.pi*f*t+phi) for phi, amp in zip(np.random.randn(n_measurements), np.random.randn(n_measurements))]).T

    # plt.plot(t, y)
    # plt.show()

    sid = N4SID(dt=dt, n_measurements=n_measurements, sys_order=2)
    sid.run_sid(y)
    # print(sid.eigs[0].imag / (2 * np.pi), f)
    assert np.isclose(sid.eigs[0].imag/(2*np.pi), f)