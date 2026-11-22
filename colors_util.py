# -*- coding: utf-8 -*-
import math

from qgis.PyQt.QtGui import QColor

# Preferred first (lime), then signal-like alternates for clash avoidance.
MEASURE_STROKE_CANDIDATES = (
    '#a3e635',  # lime
    '#22d3ee',  # cyan
    '#e879f9',  # magenta
    '#f472b6',  # hot pink
    '#2dd4bf',  # aqua
    '#38bdf8',  # sky
    '#fbbf24',  # amber
    '#fb7185',  # rose
    '#c084fc',  # violet
    '#f0abfc',  # fuchsia light
    '#fff5e6',  # cream
    '#f8fafc',  # ice white
    '#4ade80',  # green
    '#67e8f9',  # ice cyan
)

# Combined HSL score below this ≈ too close to a Group chip (see color_distance_hsl).
# Calibrated so ~80°+ hue separation (or strong S/L gap) is required — stricter than old RGB 60.
MEASURE_COLOR_MIN_DIST = 95.0


def color_for_index(i, n):
    n = max(int(n) or 1, 1)
    h = ((int(i) * 0.61803398875) % 1.0)
    return QColor.fromHsvF(h, 0.62, 0.88)


def _as_qcolor(color):
    c = color if isinstance(color, QColor) else QColor(color)
    return c if c.isValid() else None


def color_distance_rgb(a, b):
    """Euclidean distance in 8-bit RGB (0…~441)."""
    ca, cb = _as_qcolor(a), _as_qcolor(b)
    if ca is None or cb is None:
        return 999.0
    return math.sqrt(
        (ca.red() - cb.red()) ** 2
        + (ca.green() - cb.green()) ** 2
        + (ca.blue() - cb.blue()) ** 2
    )


def _hsl_tuple(color):
    """Return (H 0–360, S 0–1, L 0–1) or None."""
    c = _as_qcolor(color)
    if c is None:
        return None
    # Qt HSV: H 0–359 (−1 = achromatic), S/V 0–255.
    h, s, v, _a = c.getHsv()
    if h < 0:
        h = 0
    sf = s / 255.0
    vf = v / 255.0
    # Lightness approximation from HSV for clash scoring.
    lf = vf * (1.0 - sf * 0.5)
    return float(h), sf, lf


def color_distance_hsl(a, b):
    """Perceptual-ish distance: hue (circular) + saturation + lightness.

    Typical “too close” scores are under ~40–50; far hues score 80+.
    """
    ha = _hsl_tuple(a)
    hb = _hsl_tuple(b)
    if ha is None or hb is None:
        return 999.0
    dh = abs(ha[0] - hb[0])
    if dh > 180.0:
        dh = 360.0 - dh
    # Weight hue strongly; soft-saturated chips still need hue separation.
    return math.sqrt(
        (dh * 1.15) ** 2
        + ((ha[1] - hb[1]) * 55.0) ** 2
        + ((ha[2] - hb[2]) * 70.0) ** 2
    )


def pick_measure_stroke(used_colors, preferred='#a3e635', min_dist=None):
    """Pick a measure-line colour that is not close to any group chip colour.

    ``used_colors``: iterable of QColor / css hex from the Group filter chips.
    Returns a valid ``QColor`` (opaque).
    """
    if min_dist is None:
        min_dist = MEASURE_COLOR_MIN_DIST
    used = []
    for raw in (used_colors or []):
        c = _as_qcolor(raw)
        if c is not None:
            used.append(c)
    ordered = []
    pref = str(preferred or MEASURE_STROKE_CANDIDATES[0]).strip().lower()
    if pref:
        ordered.append(pref)
    for cand in MEASURE_STROKE_CANDIDATES:
        if cand.lower() not in ordered:
            ordered.append(cand.lower())

    def _ok(hex_cand):
        c = QColor(hex_cand)
        if not c.isValid():
            return False
        for u in used:
            if color_distance_hsl(c, u) < float(min_dist):
                return False
        return True

    for cand in ordered:
        if _ok(cand):
            out = QColor(cand)
            out.setAlpha(245)
            return out
    # Fallback: maximise the nearest-neighbour gap to used colours.
    best = QColor(ordered[0] if ordered else '#a3e635')
    best_score = -1.0
    for cand in ordered:
        c = QColor(cand)
        if not c.isValid():
            continue
        if not used:
            c.setAlpha(245)
            return c
        score = min(color_distance_hsl(c, u) for u in used)
        if score > best_score:
            best_score = score
            best = c
    best.setAlpha(245)
    return best


def color_map(values, base=None):
    values = list(values)
    out = {}
    default = None
    if base:
        for key, color in base.items():
            if key == '__default__':
                default = color if isinstance(color, QColor) else QColor(color)
                continue
            out[key] = color if isinstance(color, QColor) else QColor(color)
    n = max(len(values), 1)
    i = 0
    for val in values:
        if val in out and out[val] is not None and out[val].isValid():
            continue
        if default is not None and default.isValid():
            out[val] = QColor(default)
        else:
            out[val] = color_for_index(i, n)
            i += 1
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
