import numpy as np


"""This file contains synthetic test cases for the islanding detection
application."""


def islanding_test_case_1(n_channels=10, seed=0):
    # Generate frequency time series for islanding test case
    t_start = 0
    t_end = 200
    dt = 0.02
    time_stamps = np.arange(t_start, t_end + dt, dt)
    n_samples = len(time_stamps)
    # n_channels = 10
    np.random.seed(seed)
    sys_freq = 50 + 5e-3 * np.cumsum(np.random.randn(n_samples))
    island_freq = sys_freq.copy()
    t_islanded = (time_stamps > 20) * (time_stamps < 60) + (time_stamps > 130) * (
        time_stamps < 150
    )
    island_freq[t_islanded] = (
        50 + 5e-3 * np.cumsum(np.random.randn(sum(t_islanded))) + 0.1
    )

    islanded_channels = np.array([2, 3, 5])
    freq = np.vstack([sys_freq] * n_channels).T + 5e-3 * np.random.randn(
        n_samples, n_channels
    )
    freq[:, islanded_channels] = np.vstack(
        [island_freq] * len(islanded_channels)
    ).T + 5e-3 * np.random.randn(n_samples, len(islanded_channels))
    return time_stamps, freq


if __name__ == "__main__":
    import matplotlib.pyplot as plt

    time_stamps, freq = islanding_test_case_1()

    plt.plot(time_stamps, freq)
    plt.show()