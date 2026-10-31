# -*- coding: utf-8 -*-
from qgis.PyQt.QtGui import QColor


def color_for_index(i, n):
    n = max(int(n) or 1, 1)
    h = ((int(i) * 0.61803398875) % 1.0)
    return QColor.fromHsvF(h, 0.62, 0.88)


def color_map(values):
    values = list(values)
    out = {}
    for i, val in enumerate(values):
        out[val] = color_for_index(i, len(values))
    return out


def css_hex(color):
    """#rrggbb from a QColor. Avoid QColor.name() (Qt6 may emit #aarrggbb)."""
    c = color if isinstance(color, QColor) else QColor(color)
    if not c.isValid():
        return '#888888'
    return '#%02x%02x%02x' % (c.red(), c.green(), c.blue())


def qgis_color(color):
    """r,g,b,a string for QgsSymbol.createSimple."""
    c = color if isinstance(color, QColor) else QColor(color)
    if not c.isValid():
        return '136,136,136,255'
    return '%d,%d,%d,%d' % (c.red(), c.green(), c.blue(), c.alpha())
