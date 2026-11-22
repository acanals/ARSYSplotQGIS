# -*- coding: utf-8 -*-
"""Orientation / inclination from a 3D axis — improved method.

Port of ARSYSplot ``plot-process-dataset-shared.js`` (mètode millorat from
``ProblemaCalculVectorsOrientacio``), adapted to the plugin/Lite axis **P2→P3**
(after import normalisation).

Conventions (site grid):
- X = east, Y = north, Z = up
- Orientation: azimuth 0–360°, 0° = North, clockwise
- Inclination: 0–90° from horizontal (0° flat, 90° vertical)

Adaptive flip: if enabled and |Δz|/L exceeds ``dz_ratio`` and Δz > 0
(vector points “up”), reverse the sense before computing angles / drawing.
"""
from __future__ import annotations

import math
from contextlib import suppress

EPS = 1e-12

# Defaults aligned with ARSYSplot / ProblemaCalculVectorsOrientacio.
DEFAULT_ENABLE_FLIP = True
DEFAULT_DZ_RATIO = 0.15
DEFAULT_L_CURT = 1.0
DEFAULT_L_MOLT_CURT = 0.3


def normalize_options(opts=None):
    """Return ``{enable_flip, dz_ratio, l_curt, l_molt_curt}`` with sane defaults."""
    o = opts if isinstance(opts, dict) else {}
    enable_flip = o.get('enable_flip', o.get('enableFlip', DEFAULT_ENABLE_FLIP))
    enable_flip = enable_flip not in (False, 0, '0', 'false', 'False')

    dz_ratio = o.get('dz_ratio', o.get('dzRatio', DEFAULT_DZ_RATIO))
    with suppress(TypeError, ValueError):
        dz_ratio = float(dz_ratio)
    if not math.isfinite(dz_ratio):
        dz_ratio = DEFAULT_DZ_RATIO
    if dz_ratio > 1.0:
        dz_ratio = dz_ratio / 100.0
    dz_ratio = max(0.0, min(1.0, dz_ratio))

    l_curt = o.get('l_curt', o.get('lCurt', DEFAULT_L_CURT))
    with suppress(TypeError, ValueError):
        l_curt = float(l_curt)
    if not math.isfinite(l_curt) or l_curt <= 0:
        l_curt = DEFAULT_L_CURT

    l_molt = o.get('l_molt_curt', o.get('lMoltCurt', DEFAULT_L_MOLT_CURT))
    with suppress(TypeError, ValueError):
        l_molt = float(l_molt)
    if not math.isfinite(l_molt) or l_molt <= 0:
        l_molt = DEFAULT_L_MOLT_CURT
    if l_molt > l_curt:
        l_molt = l_curt

    return {
        'enable_flip': bool(enable_flip),
        'dz_ratio': float(dz_ratio),
        'l_curt': float(l_curt),
        'l_molt_curt': float(l_molt),
    }


def _finite3(pt):
    return (
        pt is not None
        and math.isfinite(float(pt[0]))
        and math.isfinite(float(pt[1]))
        and math.isfinite(float(pt[2]))
    )


def _round_by_length(deg, length, opt):
    if not math.isfinite(deg):
        return deg
    if not (length > 0):
        return deg
    if length < opt['l_molt_curt']:
        return float(round(deg))
    if length < opt['l_curt']:
        return float(round(deg * 100.0) / 100.0)
    return float(deg)


def improved_deltas(a, b, options=None):
    """Deltas along **a→b** with adaptive flip.

    ``a`` / ``b`` are ``(x, y, z)`` tuples (metres). For the plugin axis use
    ``a=P2``, ``b=P3``.

    Returns ``dict`` with ``dx, dy, dz, length, flipped`` or ``None``.
    """
    if not _finite3(a) or not _finite3(b):
        return None
    opt = normalize_options(options)
    ax, ay, az = float(a[0]), float(a[1]), float(a[2])
    bx, by, bz = float(b[0]), float(b[1]), float(b[2])
    dx = bx - ax
    dy = by - ay
    dz = bz - az
    length = math.sqrt(dx * dx + dy * dy + dz * dz)
    if length < EPS:
        return None
    flipped = False
    if opt['enable_flip']:
        dz_ratio = abs(dz) / length
        if dz_ratio > opt['dz_ratio'] and dz > 0:
            dx, dy, dz = -dx, -dy, -dz
            flipped = True
    return {
        'dx': dx,
        'dy': dy,
        'dz': dz,
        'length': length,
        'flipped': flipped,
    }


def compute_orientation(a, b, options=None):
    """Azimuth 0–360° (0° = North, clockwise) from improved a→b sense."""
    d = improved_deltas(a, b, options)
    if d is None:
        return None
    if abs(d['dx']) < EPS and abs(d['dy']) < EPS:
        return None
    # atan2(east, north) → 0 at North, clockwise through East.
    deg = math.degrees(math.atan2(d['dx'], d['dy']))
    deg = (deg % 360.0 + 360.0) % 360.0
    return _round_by_length(deg, d['length'], normalize_options(options))


def compute_inclination(a, b, options=None):
    """Inclination 0–90° from horizontal (0° flat, 90° vertical)."""
    d = improved_deltas(a, b, options)
    if d is None:
        return None
    horiz = math.hypot(d['dx'], d['dy'])
    if horiz < EPS and abs(d['dz']) < EPS:
        return None
    opt = normalize_options(options)
    if abs(d['dz']) < EPS:
        return _round_by_length(0.0, d['length'], opt)
    if horiz < EPS:
        return _round_by_length(90.0, d['length'], opt)
    deg = abs(math.degrees(math.atan2(d['dz'], horiz)))
    if deg > 90.0:
        deg = 180.0 - deg
    deg = max(0.0, min(90.0, deg))
    return _round_by_length(deg, d['length'], opt)


def directed_segment(a, b, options=None):
    """Return ``(from_pt, to_pt)`` in improved drawing sense (may swap a/b).

    Length and midpoint are unchanged; only the arrow sense may flip.
    """
    d = improved_deltas(a, b, options)
    if d is None:
        return None
    if d['flipped']:
        return b, a
    return a, b


def compute_angles(a, b, options=None):
    """Convenience: ``{orientacio, inclinacio, length, flipped}`` or ``None``."""
    d = improved_deltas(a, b, options)
    if d is None:
        return None
    return {
        'orientacio': compute_orientation(a, b, options),
        'inclinacio': compute_inclination(a, b, options),
        'length': d['length'],
        'flipped': d['flipped'],
    }
