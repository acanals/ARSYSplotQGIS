# -*- coding: utf-8 -*-
"""Manual profile: segment A→B + horizontal Wide (XY), vertical prism.

Wide is the horizontal width perpendicular to A→B. Membership is a 2D XY test;
Z is not clipped by Wide (vertical prism). Local frame: origin at A, U along
A→B, V perpendicular. LONG = Plan X or Y of the axial foot (dominant A→B) × Z;
TRANS = the other Plan axis of each point × Z (same tick style as Planta).
"""
from contextlib import suppress
import math


def cm_to_m(wide_cm):
    try:
        return max(0.0, float(wide_cm)) / 100.0
    except (TypeError, ValueError):
        return 0.0


def segment_frame(ax, ay, bx, by):
    """Return (ax, ay, cos, sin, length) or None if A≈B."""
    try:
        ax, ay, bx, by = float(ax), float(ay), float(bx), float(by)
    except (TypeError, ValueError):
        return None
    dx, dy = bx - ax, by - ay
    length = math.hypot(dx, dy)
    if not math.isfinite(length) or length < 1e-9:
        return None
    return ax, ay, dx / length, dy / length, length


def to_uv(x, y, frame):
    """Map site (x,y) → (u,v) in the segment frame (origin A)."""
    if frame is None:
        return None
    ax, ay, c, s, _length = frame
    try:
        dx, dy = float(x) - ax, float(y) - ay
    except (TypeError, ValueError):
        return None
    u = dx * c + dy * s
    v = -dx * s + dy * c
    return u, v


def in_corridor(x, y, frame, wide_m):
    """True if (x,y) lies in the finite XY footprint of the vertical prism."""
    uv = to_uv(x, y, frame)
    if uv is None or frame is None:
        return False
    u, v = uv
    half = max(0.0, float(wide_m or 0.0)) * 0.5
    if half <= 0.0:
        return False
    _ax, _ay, _c, _s, length = frame
    return (0.0 <= u <= length) and (abs(v) <= half)


def corridor_polygon(ax, ay, bx, by, wide_m):
    """Four XY corners of the profile footprint (closed ring, CCW-ish).

    Order: A-left, B-left, B-right, A-right (looking along A→B).
    """
    frame = segment_frame(ax, ay, bx, by)
    if frame is None:
        return None
    half = max(0.0, float(wide_m or 0.0)) * 0.5
    if half <= 0.0:
        return None
    ax, ay, c, s, length = frame
    # Perpendicular unit (left of direction): (-s, c)
    px, py = -s * half, c * half
    bx2 = ax + c * length
    by2 = ay + s * length
    return (
        (ax + px, ay + py),
        (bx2 + px, by2 + py),
        (bx2 - px, by2 - py),
        (ax - px, ay - py),
    )


def xy_from_uv(u, v, frame):
    """Inverse of to_uv."""
    if frame is None:
        return None
    ax, ay, c, s, _length = frame
    try:
        uu, vv = float(u), float(v)
    except (TypeError, ValueError):
        return None
    return ax + uu * c - vv * s, ay + uu * s + vv * c


def long_plan_axis(frame):
    """Which Plan axis to use on LONG: dominant A→B direction ('x' or 'y')."""
    if frame is None:
        return 'x'
    _ax, _ay, c, s, _length = frame
    return 'x' if abs(c) >= abs(s) else 'y'


def trans_plan_axis(frame):
    """Plan axis for TRANS: the other site axis (same tick style as Planta)."""
    return 'y' if long_plan_axis(frame) == 'x' else 'x'


def long_h_from_uv(u, frame):
    """Plan X or Y of the foot of the perpendicular on A→B (for LONG axis)."""
    if frame is None:
        return None
    ax, ay, c, s, _length = frame
    try:
        uu = float(u)
    except (TypeError, ValueError):
        return None
    # Axial foot at (u, 0) in local frame → site XY, then take dominant axis.
    if abs(c) >= abs(s):
        return ax + uu * c
    return ay + uu * s


def trans_h_from_xy(x, y, frame):
    """Plan coordinate for TRANS: the non-dominant site axis of the point."""
    try:
        x, y = float(x), float(y)
    except (TypeError, ValueError):
        return None
    if trans_plan_axis(frame) == 'y':
        return y
    return x


def round_axis_bounds(vmin, vmax):
    """Whole-metre axis span: floor(min) … ceil(max), at least 1 m wide."""
    try:
        lo, hi = float(vmin), float(vmax)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(lo) and math.isfinite(hi)):
        return None
    if hi < lo:
        lo, hi = hi, lo
    a = math.floor(lo)
    b = math.ceil(hi)
    if b <= a:
        b = a + 1
    return float(a), float(b)


def profile_ready(a, b, wide_cm):
    """True when A, B and Wide define a usable profile."""
    if not a or not b or len(a) < 2 or len(b) < 2:
        return False
    if cm_to_m(wide_cm) <= 0.0:
        return False
    return segment_frame(a[0], a[1], b[0], b[1]) is not None


def count_in_corridor(points_xy, a, b, wide_cm):
    """Count (x,y) pairs inside the profile (for status labels)."""
    frame = None
    with suppress(TypeError, ValueError, IndexError):
        frame = segment_frame(a[0], a[1], b[0], b[1])
    wide_m = cm_to_m(wide_cm)
    if frame is None or wide_m <= 0.0:
        return 0
    n = 0
    for pt in points_xy or ():
        if pt is None or len(pt) < 2:
            continue
        if in_corridor(pt[0], pt[1], frame, wide_m):
            n += 1
    return n
