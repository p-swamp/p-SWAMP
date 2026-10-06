from pswamp.utils.time_window_labeled import TimeWindowLabeled

def test_time_window_labeled():
    header=dict(
        station_name=   ['SW1',	    'SW1',      'N1',	'N2'],
        channel_name=   ['V',	    'I:L1-2',   'I',	'V'],
        type=           ['v',	    'i',	    'i',    'v'],
    )

    tw = TimeWindowLabeled(n_samples=10, header=header)

     
    assert((tw.get_col_idx(station_name='SW1', channel_name='V')) == [0]).all()
    assert((tw.get_col_idx(channel_name='V')) == [0, 3]).all()
    assert (tw.get_col_idx(type='v') == [0, 3]).all()
    assert (tw.get_col_idx() == [0, 1, 2, 3]).all()
    assert (tw.get_col_idx(station_name='N1') == [2]).all()
    assert (tw.get_col_idx(station_name='N1', type='i') == [2]).all()
    assert (tw.get_col_idx('SW1', 'V') == [0]).all()
    assert (tw.get_col_idx(None, 'V', 'v') == [0, 3]).all()


if __name__ == '__main__':
    test_time_window_labeled()
    