from pswamp.visualization.countries_geo_data.read_geo_data import read_geo_data


def test_read_geo_data():
    read_geo_data()
    read_geo_data('All')
    read_geo_data(['Norway', 'Sweden'])


if __name__ == '__main__':
    test_read_geo_data()