import numpy as np
import ezdxf
import pathlib


def load(file='sld.dxf'):
    path = pathlib.Path(__file__).parent / file
    doc = ezdxf.readfile(path)
    texts = doc.query('MTEXT')
    names = [text.dxf.text for text in texts]
    x = [text.dxf.insert.x for text in texts]
    y = [text.dxf.insert.y for text in texts]
    coords = np.vstack([x, y]).T
    return names, coords


if __name__ == '__main__':
    print(load(file='sld.dxf'))
    print(load(file='sld_geo.dxf'))
