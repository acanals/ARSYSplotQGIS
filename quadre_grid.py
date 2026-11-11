# -*- coding: utf-8 -*-
"""Excavation-square (quadre) axis labels — same model as ARSYSplotLite.

X → numbers, Y → letters (e.g. R16). Cell size = 1 m; labels at cell centres.
Square [n, n+1) is labelled ``n + ox`` with ``ox = median(q.num - floor(x))``.
"""
from __future__ import annotations

import math
import re
from typing import Iterable, Tuple


_QUADRE_RE = re.compile(r'^([A-Za-z]+)\s*([0-9]+)$')


def parse_quadre_cell(value):
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    m = _QUADRE_RE.match(s)
    if not m:
        return None
    try:
        num = int(m.group(2))
    except ValueError:
        return None
    return m.group(1).upper(), num


def letters_to_index(letters):
    n = 0
    for ch in str(letters or '').upper():
        c = ord(ch)
        if c < 65 or c > 90:
            return float('nan')
        n = n * 26 + (c - 64)
    return float(n)


def index_to_letters(idx):
    n = int(math.floor(idx))
    if not math.isfinite(n) or n <= 0:
        return str(idx)
    out = ''
    while n > 0:
        r = (n - 1) % 26
        out = chr(65 + r) + out
        n = (n - 1) // 26
    return out


def _floor_cell(value):
    return math.floor(float(value) + 1e-9)


def _median(values):
    arr = sorted(v for v in values if v is not None and math.isfinite(float(v)))
    if not arr:
        return float('nan')
    mid = len(arr) // 2
    if len(arr) % 2:
        return float(arr[mid])
    return 0.5 * (float(arr[mid - 1]) + float(arr[mid]))


def _mad(arr, med):
    if not math.isfinite(med):
        return float('inf')
    dev = sorted(abs(float(v) - med) for v in arr if math.isfinite(float(v)))
    if not dev:
        return float('inf')
    mid = len(dev) // 2
    if len(dev) % 2:
        return float(dev[mid])
    return 0.5 * (float(dev[mid - 1]) + float(dev[mid]))


def build_formatters(points: Iterable[Tuple[float, float, object]]):
    """Return ``(fmt_x, fmt_y)`` or ``None``.

    ``points``: iterable of ``(x, y, quadre)``.
    """
    oxs = []
    dys_pos = []
    dys_neg = []
    samples = []
    for item in points:
        try:
            x, y, raw_q = item
            x = float(x)
            y = float(y)
        except (TypeError, ValueError):
            continue
        parsed = parse_quadre_cell(raw_q)
        if not parsed:
            continue
        letters, num = parsed
        yi = letters_to_index(letters)
        if not math.isfinite(yi):
            continue
        samples.append((x, y, num, yi))
        oxs.append(num - _floor_cell(x))
        dys_pos.append(yi - y)
        dys_neg.append(yi + y)
        if len(samples) >= 20000:
            break
    if len(oxs) < 3:
        return None
    ox = int(round(_median(oxs)))
    b_pos = _median(dys_pos)
    b_neg = _median(dys_neg)
    a_y = -1 if _mad(dys_neg, b_neg) < _mad(dys_pos, b_pos) else 1
    oys = []
    for x, y, num, yi in samples:
        oys.append(yi - _floor_cell(a_y * y))
    if len(oys) < 3:
        return None
    oy = int(round(_median(oys)))
    if not math.isfinite(float(ox)) or not math.isfinite(float(oy)):
        return None

    def fmt_x(x_val):
        return str(_floor_cell(x_val) + ox)

    def fmt_y(y_val):
        return index_to_letters(_floor_cell(a_y * float(y_val)) + oy)

    return fmt_x, fmt_y


def for_axes(h_axis, v_axis, base):
    if not base:
        return None, None
    fmt_x, fmt_y = base

    def pick(axis):
        if axis == 'x':
            return fmt_x
        if axis == 'y':
            return fmt_y
        return None

    return pick(h_axis), pick(v_axis)


def grid_lines(min_v, max_v):
    start = _floor_cell(min_v)
    end = math.ceil(float(max_v) - 1e-9)
    if end <= start:
        end = start + 1
    return list(range(start, end + 1))


def cell_mids(min_v, max_v):
    x0 = _floor_cell(min_v)
    x1 = math.ceil(float(max_v) - 1e-9)
    if x1 <= x0:
        x1 = x0 + 1
    return [c + 0.5 for c in range(x0, x1)]


def find_quadre_field(layer):
    if layer is None:
        return None
    for field in layer.fields():
        name = str(field.name() or '')
        if name.lower().strip() in (
            'quadre', 'square', 'carre', 'cuadrado', 'cuadro', 'quadrato', 'quadrat',
        ):
            return name
    return None


def _feature_xy(feat, layer):
    """Map X/Y from geometry, falling back to ``p1x`` / ``p1y`` attributes."""
    geom = feat.geometry() if feat is not None else None
    if geom is not None and not geom.isEmpty():
        try:
            pt = geom.constGet() if hasattr(geom, 'constGet') else None
            if pt is not None and hasattr(pt, 'x'):
                return float(pt.x()), float(pt.y())
            c = geom.centroid().asPoint()
            return float(c.x()), float(c.y())
        except Exception:
            pass
        try:
            p = geom.asPoint()
            return float(p.x()), float(p.y())
        except Exception:
            pass
    if layer is not None:
        fields = layer.fields()
        ix = fields.lookupField('p1x')
        iy = fields.lookupField('p1y')
        if ix >= 0 and iy >= 0:
            try:
                return float(feat.attribute(ix)), float(feat.attribute(iy))
            except (TypeError, ValueError):
                return None
    return None


def _attr_text(value):
    if value is None:
        return ''
    # QVariant / numpy scalars → plain string for parse_quadre_cell.
    try:
        if hasattr(value, 'isNull') and value.isNull():
            return ''
    except Exception:
        pass
    try:
        if hasattr(value, 'value'):
            value = value.value()
    except Exception:
        pass
    return str(value).strip()


def formatters_from_layer(layer, max_features=20000):
    """Build ``(fmt_x, fmt_y)`` from a point layer, or ``None``."""
    q_field = find_quadre_field(layer)
    if not q_field or layer is None:
        return None
    pts = []
    for i, feat in enumerate(layer.getFeatures()):
        if i >= max_features:
            break
        xy = _feature_xy(feat, layer)
        if xy is None:
            continue
        x, y = xy
        raw = feat.attribute(q_field)
        text = _attr_text(raw)
        if not text:
            continue
        pts.append((x, y, text))
    return build_formatters(pts)
