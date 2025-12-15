import numpy as np
import datetime
import pandas as pd
import collections

def recursively_default_dict():
    """Dict which allows assigning fields that don't exist. Source:
    https://stackoverflow.com/questions/13151276/automatically-add-key-to-python-dict

    Returns:
        dict: Empty dict
    """
    return collections.defaultdict(recursively_default_dict)


def lookup_strings(a, b, return_mask=False):
    # Function to find the index of the element in b that equal the element in a, for each element in a
    if isinstance(a, (pd.DataFrame, pd.Series)): a = a.to_numpy()
    if isinstance(b, (pd.DataFrame, pd.Series)): b = b.to_numpy()

    if isinstance(a, np.ndarray) or isinstance(a, list):
        lookups = []
        found = []
        for a_ in a:
            lookup = np.where(b == a_)[0]
            if len(lookup) > 0:
                lookups.append(lookup[0])
                found.append(True)
            else:
                found.append(False)
        if return_mask:
            return np.array(lookups), np.array(found)
        else:
            return np.array(lookups)
    else:
        lookup = np.where(b == a)[0]
        if len(lookup) > 0:
            return lookup[0]
        else:
            return np.nan
        

def convert_time_stamp_to_seconds(time_stamp):
    """Convert time stamp (datetime) to seconds (float)

    Args:
        time_stamp (datetime.datetime): Input datetime object.

    Returns:
        float: Number of seconds.
    """
    first_date = datetime.datetime(1970, 1, 1, tzinfo=datetime.UTC)
    time_since = time_stamp - first_date
    return int(time_since.total_seconds())


convert_datetime_to_seconds = convert_time_stamp_to_seconds


def convert_seconds_to_datetime(time_seconds):
    """Convert seconds (float) to datetime object

    Args:
        time_seconds (float): Number of seconds

    Returns:
        datetime.datetime: Datetime object
    """
    return datetime.datetime.fromtimestamp(time_seconds, datetime.UTC)


def flatten_array_insert_nan(x, y):
    """Flatten arrays and insert nan values, useful for fast plotting

    Allows multiple series (in y) to be plotted with a single plot call.
    E.g. instead of plt.plot(x, y), plt.plot(*flatten_array_insert_nan(x, y)).
    Since the latter produces a single plot handle, it is much faster when there
    are many time series in y. Depending on plotting library, formatting of
    individual lines might not be possible.

    Output arrays both have shape (n_series*(n_samples+1),).

    Args:
        x (np.ndarray): x-values, with shape (n_series, n_samples) or (n_series,)
        y (np.ndarray): y-values, with shape (n_series, n_samples)

    Raises:
        Exception: If dimensions of x and y are not compatible.

    Returns:
        x_data: x-values, with shape (n_series*(n_samples+1),)
        y_data: y-values, with shape (n_series*(n_samples+1),)
    """

    if x.ndim == 1 and y.ndim == 2:
        x_data = np.concatenate(y.shape[1]*[x, [np.nan]])
        y_data = np.vstack([y, np.nan*np.ones(y.shape[1])]).T.flatten()
    elif x.shape == y.shape and x.ndim == 2:
        x_data = np.vstack([x, np.nan*np.ones(x.shape[1])]).T.flatten()
        y_data = np.vstack([y, np.nan*np.ones(y.shape[1])]).T.flatten()
    else:
        raise Exception('Dimensions of x and y arrays are not compatible.')
    return x_data, y_data


def flatten_list_insert_nan(listlist):
    dim = listlist[0].shape[1]
    z = [*zip(listlist, [np.ones((1, dim)) * np.nan] * len(listlist))]
    flattened_list = [y for x in z for y in x]
    return np.vstack(flattened_list) if len(flattened_list) > 0 else np.empty((0, dim))
