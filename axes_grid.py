# -*- coding: utf-8 -*-
"""Metric axes + grid overlay for the three projection canvases (Lite-style)."""
from contextlib import suppress
import math

from qgis.core import QgsPointXY, QgsRectangle
from qgis.PyQt.QtCore import QPoint, QPointF, Qt, QRectF
from qgis.PyQt.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen, QPolygonF
from qgis.PyQt.QtWidgets import QWidget

from .export_dialog import is_light_color, mm_to_px, pt_to_px
from . import quadre_grid as QG

from .layers import (
    DEFAULT_MARKER,
    _symbol_marker_shape,
    _symbol_paint_color,
    group_label,
    padded_data_extent,
    resolve_marker_shape,
)

INK = QColor(255, 245, 230)
# Screen grid: alpha ~ Lite --plot-ink-faint (0.38); width > 1 so lines read on HiDPI.
GRID = QColor(255, 245, 230, 95)
AXIS = QColor(255, 245, 230, 120)
LABEL = QColor(255, 245, 230, 190)
TITLE = QColor(255, 245, 230, 140)
GRID_LIGHT = QColor(40, 40, 40, 95)
AXIS_LIGHT = QColor(30, 30, 30, 200)
LABEL_LIGHT = QColor(20, 20, 20, 230)
TITLE_LIGHT = QColor(40, 40, 40, 200)
GRID_PEN_W = 1
# Paper colours / mm — keep in sync with Lite CSS --paper-*.
PAPER_BG = QColor('#ffffff')
PAPER_INK = QColor('#1c1916')
PAPER_MUTED = QColor('#6b645c')
PAPER_FAINT = QColor('#9a9288')
PAPER_GRID = QColor('#c8c0b4')
GRID_PAPER = PAPER_GRID
AXIS_PAPER = PAPER_INK
LABEL_PAPER = PAPER_INK
TITLE_PAPER = PAPER_MUTED
PAPER_FRAME_MM = 0.25
PAPER_GRID_MM = 0.30
PAPER_TICK_MM = 0.25
PAPER_SCALE_BAR_MM = 0.22
PAPER_SCALE_BAR_H_MM = 2.0
PAPER_SCALE_BAR_Y_MM = 12.5
PAPER_TICK_LEN_MM = 1.6
PAPER_POINT_DIAM_MM = 2.2

# Axis names sit outside the tick numbers. Legend is export-only (extra strip).
PAD_L, PAD_R, PAD_T, PAD_B = 68, 16, 10, 52
LEGEND_GAP = 32
LEGEND_W = 64
SCREEN_BG = QColor('#161411')


def draw_legend_marker(painter, cx, cy, r, shape, color):
    """Paint a Point-model glyph (colour + shape) for export/screen legends."""
    shape = resolve_marker_shape(shape)
    fill = QColor(color) if color is not None else QColor('#888888')
    if not fill.isValid():
        fill = QColor('#888888')
    rim = QColor(20, 20, 20, 160)
    pen_w = max(0.7, float(r) * 0.18)
    cx, cy, r = float(cx), float(cy), max(1.2, float(r))

    if shape in ('cross', 'cross2'):
        stroke = QPen(fill, max(1.0, r * 0.38), Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap, Qt.PenJoinStyle.MiterJoin)
        painter.setPen(stroke)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if shape == 'cross':
            painter.drawLine(QPointF(cx - r, cy), QPointF(cx + r, cy))
            painter.drawLine(QPointF(cx, cy - r), QPointF(cx, cy + r))
        else:
            painter.drawLine(QPointF(cx - r, cy - r), QPointF(cx + r, cy + r))
            painter.drawLine(QPointF(cx - r, cy + r), QPointF(cx + r, cy - r))
        return

    painter.setPen(QPen(rim, pen_w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.SquareCap, Qt.PenJoinStyle.MiterJoin))
    painter.setBrush(fill)

    if shape == 'square':
        painter.drawRect(QRectF(cx - r, cy - r, 2.0 * r, 2.0 * r))
        return
    if shape == 'diamond':
        painter.drawPolygon(QPolygonF([
            QPointF(cx, cy - r), QPointF(cx + r, cy),
            QPointF(cx, cy + r), QPointF(cx - r, cy),
        ]))
        return
    if shape in ('triangle', 'equilateral_triangle', 'triangle-inverted'):
        h = r * 1.15
        if shape == 'triangle-inverted':
            painter.drawPolygon(QPolygonF([
                QPointF(cx, cy + h),
                QPointF(cx - h * 0.95, cy - h * 0.65),
                QPointF(cx + h * 0.95, cy - h * 0.65),
            ]))
        else:
            painter.drawPolygon(QPolygonF([
                QPointF(cx, cy - h),
                QPointF(cx + h * 0.95, cy + h * 0.65),
                QPointF(cx - h * 0.95, cy + h * 0.65),
            ]))
        return
    if shape in ('pentagon', 'hexagon', 'octagon'):
        n = 5 if shape == 'pentagon' else (6 if shape == 'hexagon' else 8)
        pts = []
        for i in range(n):
            a = -math.pi / 2.0 + i * (2.0 * math.pi / n)
            pts.append(QPointF(cx + r * math.cos(a), cy + r * math.sin(a)))
        painter.drawPolygon(QPolygonF(pts))
        return
    if shape == 'star':
        pts = []
        for i in range(10):
            a = -math.pi / 2.0 + i * (math.pi / 5.0)
            rad = r if (i % 2 == 0) else r * 0.42
            pts.append(QPointF(cx + rad * math.cos(a), cy + rad * math.sin(a)))
        painter.drawPolygon(QPolygonF(pts))
        return
    # circle (default)
    painter.drawEllipse(QPointF(cx, cy), r, r)


def _unpack_legend_item(item):
    """Support (name, color) and (name, color, shape)."""
    if item is None:
        return '', QColor('#888888'), DEFAULT_MARKER
    if len(item) >= 3:
        return item[0], item[1], resolve_marker_shape(item[2])
    if len(item) == 2:
        return item[0], item[1], DEFAULT_MARKER
    return str(item), QColor('#888888'), DEFAULT_MARKER

Z_STEPS = (0.01, 0.02, 0.05, 0.1, 0.2, 0.25, 0.5, 1, 2, 5, 10)


def _is_planar(axis):
    return axis in ('x', 'y')


def _floor_m(value):
    return float(math.floor(float(value) + 1e-9))


def _ceil_m(value):
    return float(math.ceil(float(value) - 1e-9))


def snap_world_rect(xmin, xmax, ymin, ymax, h_axis, v_axis):
    """Expand planar sides to whole metres so the frame is complete squares."""
    xmin, xmax, ymin, ymax = float(xmin), float(xmax), float(ymin), float(ymax)
    if _is_planar(h_axis):
        xmin = _floor_m(xmin)
        xmax = _ceil_m(xmax)
        if xmax <= xmin:
            xmax = xmin + 1.0
    if _is_planar(v_axis):
        ymin = _floor_m(ymin)
        ymax = _ceil_m(ymax)
        if ymax <= ymin:
            ymax = ymin + 1.0
    return xmin, xmax, ymin, ymax


def _near_metre(value):
    nearest = round(float(value))
    return abs(float(value) - nearest) < 0.05


def snap_inward_rect(xmin, xmax, ymin, ymax, h_axis, v_axis):
    """Keep only complete metre squares inside a visible window."""
    xmin, xmax, ymin, ymax = float(xmin), float(xmax), float(ymin), float(ymax)
    if _is_planar(h_axis):
        x0 = float(round(xmin)) if _near_metre(xmin) else float(math.ceil(xmin - 1e-9))
        x1 = float(round(xmax)) if _near_metre(xmax) else float(math.floor(xmax + 1e-9))
        if x1 < x0:
            x0, x1 = _floor_m(xmin), _ceil_m(xmax)
            if x1 <= x0:
                x1 = x0 + 1.0
        xmin, xmax = x0, x1
    if _is_planar(v_axis):
        y0 = float(round(ymin)) if _near_metre(ymin) else float(math.ceil(ymin - 1e-9))
        y1 = float(round(ymax)) if _near_metre(ymax) else float(math.floor(ymax + 1e-9))
        if y1 < y0:
            y0, y1 = _floor_m(ymin), _ceil_m(ymax)
            if y1 <= y0:
                y1 = y0 + 1.0
        ymin, ymax = y0, y1
    return xmin, xmax, ymin, ymax


def snapped_data_extent(rect, h_axis, v_axis):
    if rect is None or rect.isEmpty():
        return rect
    x0, x1, y0, y1 = snap_world_rect(
        rect.xMinimum(), rect.xMaximum(),
        rect.yMinimum(), rect.yMaximum(),
        h_axis, v_axis,
    )
    return QgsRectangle(x0, y0, x1, y1)


def _ticks(minv, maxv, axis, px_span):
    minv, maxv = float(minv), float(maxv)
    if _is_planar(axis):
        # Inclusive metre lines: floor(min) … ceil(max). Every cell is 1 m,
        # even when points only occupy a corner of the first/last square.
        step = 1.0
        start = int(_floor_m(minv))
        end = int(_ceil_m(maxv))
        if end <= start:
            end = start + 1
        out = []
        v = start
        n = 0
        while v <= end and n < 400:
            out.append(v)
            v += 1
            n += 1
        if not out:
            out = [start, start + 1]
        return step, out
    span = max(maxv - minv, 1e-9)
    px_span = max(float(px_span), 1.0)
    rough = span / 8.0
    step = Z_STEPS[-1]
    for s in Z_STEPS:
        if s >= rough:
            step = s
            break
    start = math.ceil(minv / step - 1e-9) * step
    out = []
    v = start
    n = 0
    while v <= maxv + step * 1e-6 and n < 80:
        t = round(v / step) * step
        # Skip duplicates from float drift (same step slot twice).
        if not out or abs(out[-1] - t) > step * 1e-9:
            out.append(t)
        v += step
        n += 1
    if not out:
        out = [minv, maxv]
    # Do not prepend raw minv: it often formats to the same label as out[0]
    # (e.g. -2.03 and -2.0 → both "-2.0") and doubles the first Z tick.
    return step, out


def _line(painter, x1, y1, x2, y2):
    p1 = QPoint(int(round(float(x1))), int(round(float(y1))))
    p2 = QPoint(int(round(float(x2))), int(round(float(y2))))
    painter.drawLine(p1, p2)


def _fmt(value, step, axis):
    if axis in ('x', 'y') and step >= 1:
        return str(int(round(value)))
    abs_s = abs(step)
    digits = 0
    if 0 < abs_s < 1:
        digits = min(4, int(math.ceil(-math.log10(abs_s))))
    elif abs_s >= 1 and abs(value - round(value)) > 1e-6:
        digits = 1
    return ('%%.%df' % digits) % value


# Preferred scale-bar ground length (Lite parity); may adapt at extreme 1∶N.
SCALE_BAR_M = 0.5  # 50 cm
_SCALE_BAR_CANDIDATES_M = (
    0.5, 1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 5000,
)


def pick_scale_bar_metres(scale_n):
    """Prefer 50 cm; adapt so the bar stays ~14–52 mm on paper (Lite parity)."""
    try:
        n = max(1.0, float(scale_n))
    except (TypeError, ValueError):
        n = 1.0
    fixed_mm = (SCALE_BAR_M * 1000.0) / n
    if 8.0 <= fixed_mm <= 60.0:
        return float(SCALE_BAR_M)
    target_mm = 32.0
    best = float(SCALE_BAR_M)
    best_diff = float('inf')
    for metres in _SCALE_BAR_CANDIDATES_M:
        mm = (float(metres) * 1000.0) / n
        if mm < 14.0 or mm > 52.0:
            continue
        diff = abs(mm - target_mm)
        if diff < best_diff:
            best_diff = diff
            best = float(metres)
    if best_diff == float('inf'):
        rough = (target_mm * n) / 1000.0
        best = max(0.5, float(('%.1g' % rough)))
    return best


def _scale_bar_label(metres):
    m = float(metres)
    if abs(m - SCALE_BAR_M) < 1e-9:
        return '50 cm'
    if m >= 1.0:
        if abs(m - round(m)) < 1e-9:
            return '%d m' % int(round(m))
        return '%g m' % m
    return '%g cm' % (m * 100.0)


def _vertical_axis_ticks(ymin, ymax, v_axis, height_px, z_stretch=1.0):
    """Ticks for the vertical axis.

    When ``v_axis`` is Z and ``z_stretch`` ≠ 1, map coords are stretched but
    labels stay in real metres. Returns ``(step, [(map_y, label_value), …])``.
    """
    try:
        stretch = float(z_stretch)
    except (TypeError, ValueError):
        stretch = 1.0
    if stretch < 1e-12:
        stretch = 1.0
    if v_axis == 'z' and abs(stretch - 1.0) > 1e-9:
        y0 = float(ymin) / stretch
        y1 = float(ymax) / stretch
        step, ticks = _ticks(y0, y1, v_axis, height_px)
        pairs = [(t * stretch, t) for t in ticks]
    else:
        step, ticks = _ticks(ymin, ymax, v_axis, height_px)
        pairs = [(t, t) for t in ticks]
    # Drop consecutive ticks that paint as the same label (first-Z double).
    cleaned = []
    prev_lab = None
    for map_y, lab in pairs:
        text = _fmt(lab, step, v_axis)
        if text == prev_lab:
            continue
        cleaned.append((map_y, lab))
        prev_lab = text
    return step, cleaned


def _z_axis_title(v_label, z_stretch=1.0):
    try:
        stretch = float(z_stretch)
    except (TypeError, ValueError):
        stretch = 1.0
    if v_label == 'Z' and stretch > 1.0 + 1e-9:
        text = '%.3g' % stretch
        if text.endswith('.00'):
            text = text[:-3]
        elif text.endswith('0') and '.' in text:
            text = text.rstrip('0').rstrip('.')
        return '%s ×%s (m)' % (v_label, text)
    return '%s (m)' % v_label


def paint_paper_axes(
    painter, left, top, right, bottom,
    xmin, xmax, ymin, ymax,
    h_axis, v_axis, h_label, v_label, dpi,
    z_stretch=1.0,
    show_grid=True,
    fmt_h=None,
    fmt_v=None,
    scale_n=None,
):
    """Axes, metre grid and scale bar in output pixels (paper).

    Returns ``(bar_metres, bar_px)`` for placing the 1∶N label next to the bar.
    """
    dx = max(xmax - xmin, 1e-9)
    dy = max(ymax - ymin, 1e-9)
    pw = max(right - left, 1.0)
    ph = max(bottom - top, 1.0)

    def sx(x):
        return left + (float(x) - xmin) / dx * pw

    def sy(y):
        return bottom - (float(y) - ymin) / dy * ph

    use_h = callable(fmt_h)
    use_v = callable(fmt_v)
    if use_h:
        h_step, h_ticks = 1.0, QG.grid_lines(xmin, xmax)
        h_labels = QG.cell_mids(xmin, xmax)
    else:
        h_step, h_ticks = _ticks(xmin, xmax, h_axis, pw)
        h_labels = h_ticks
    if use_v:
        v_step = 1.0
        v_pairs = [(t, t) for t in QG.grid_lines(ymin, ymax)]
        v_labels = [(t, t) for t in QG.cell_mids(ymin, ymax)]
    else:
        v_step, v_pairs = _vertical_axis_ticks(
            ymin, ymax, v_axis, ph, z_stretch=z_stretch,
        )
        v_labels = v_pairs
    v_ticks = [m for m, _lab in v_pairs]
    # Metre / excavation-square network — Lite CSS --paper-*-mm.
    grid_w = max(1.2, mm_to_px(PAPER_GRID_MM, dpi))
    axis_w = max(1.0, mm_to_px(PAPER_FRAME_MM, dpi))
    tick_w = max(1.0, mm_to_px(PAPER_TICK_MM, dpi))
    tick_len = mm_to_px(PAPER_TICK_LEN_MM, dpi)

    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    if show_grid:
        painter.setPen(QPen(GRID_PAPER, grid_w))
        for tick in h_ticks:
            x = sx(tick)
            if x < left - 0.5 or x > right + 0.5:
                continue
            _line(painter, x, top, x, bottom)
        for tick in v_ticks:
            y = sy(tick)
            if y < top - 0.5 or y > bottom + 0.5:
                continue
            _line(painter, left, y, right, y)

    # Complete data-frame outline (Lite export rect), not only the L-axes.
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(AXIS_PAPER, axis_w))
    painter.drawRect(QRectF(left, top, right - left, bottom - top))
    painter.setPen(QPen(AXIS_PAPER, tick_w))
    for tick in h_ticks:
        x = sx(tick)
        if x < left - 1 or x > right + 1:
            continue
        _line(painter, x, bottom, x, bottom + tick_len)
    for tick in v_ticks:
        y = sy(tick)
        if y < top - 1 or y > bottom + 1:
            continue
        _line(painter, left - tick_len, y, left, y)

    font = QFont()
    font.setPixelSize(pt_to_px(8, dpi))
    painter.setFont(font)
    painter.setPen(LABEL_PAPER)
    lab_h = mm_to_px(4.2, dpi)
    for tick in h_labels:
        x = sx(tick)
        if x < left - 2 or x > right + 2:
            continue
        text = fmt_h(tick) if use_h else _fmt(tick, h_step, h_axis)
        painter.drawText(
            QRectF(x - mm_to_px(10, dpi), bottom + tick_len + mm_to_px(0.4, dpi),
                   mm_to_px(20, dpi), lab_h),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
            text,
        )
    for map_y, lab_v in v_labels:
        y = sy(map_y)
        if y < top - 2 or y > bottom + 2:
            continue
        text = fmt_v(lab_v) if use_v else _fmt(lab_v, v_step, v_axis)
        painter.drawText(
            QRectF(left - mm_to_px(17, dpi), y - lab_h / 2.0,
                   mm_to_px(15.2, dpi), lab_h),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            text,
        )

    font.setPixelSize(pt_to_px(9, dpi))
    painter.setFont(font)
    painter.setPen(TITLE_PAPER)
    h_title = h_label if use_h else '%s (m)' % h_label
    painter.drawText(
        QRectF(left, bottom + mm_to_px(6.2, dpi), pw, mm_to_px(5, dpi)),
        Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
        h_title,
    )
    painter.save()
    painter.translate(left - mm_to_px(14.5, dpi), (top + bottom) / 2.0)
    painter.rotate(-90)
    v_title = v_label if use_v else _z_axis_title(v_label, z_stretch)
    painter.drawText(
        QRectF(-mm_to_px(28, dpi), -mm_to_px(4, dpi), mm_to_px(56, dpi), mm_to_px(5, dpi)),
        Qt.AlignmentFlag.AlignCenter,
        v_title,
    )
    painter.restore()

    # Prefer 50 cm; adapt ground length at extreme 1∶N (Lite pickScaleBarMetres).
    bar_m = pick_scale_bar_metres(scale_n if scale_n is not None else 50)
    bar_px = float(bar_m) / dx * pw
    # 5 × 10 cm segments when bar is 50 cm; otherwise 4 equal parts.
    n_seg = 5 if abs(float(bar_m) - SCALE_BAR_M) < 1e-9 else 4
    seg_px = bar_px / float(n_seg)
    bx = left
    by = bottom + mm_to_px(PAPER_SCALE_BAR_Y_MM, dpi)
    bh = mm_to_px(PAPER_SCALE_BAR_H_MM, dpi)
    rim = QPen(AXIS_PAPER, max(1.0, mm_to_px(PAPER_SCALE_BAR_MM, dpi)))
    for i in range(n_seg):
        sx0 = bx + i * seg_px
        fill = AXIS_PAPER if (i % 2 == 0) else PAPER_BG
        painter.setPen(rim)
        painter.setBrush(fill)
        painter.drawRect(QRectF(sx0, by, seg_px, bh))
    painter.setPen(rim)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRect(QRectF(bx, by, bar_px, bh))
    font.setPixelSize(pt_to_px(7, dpi))
    painter.setFont(font)
    painter.setPen(TITLE_PAPER)
    painter.drawText(
        QRectF(bx, by + bh + mm_to_px(0.4, dpi), max(bar_px, mm_to_px(18, dpi)), lab_h),
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
        _scale_bar_label(bar_m),
    )
    return bar_m, bar_px


def _legend_col_width_px(items, field, dpi):
    """Natural column width from the longest label (+ glyph)."""
    font = QFont()
    font.setPixelSize(pt_to_px(7, dpi))
    metrics = QFontMetrics(font)
    glyph = mm_to_px(1.1, dpi) * 2.0 + mm_to_px(1.6, dpi)
    pad = mm_to_px(2.5, dpi)
    min_col = mm_to_px(18, dpi)
    max_label = 0
    for item in items or ():
        name, _c, _s = _unpack_legend_item(item)
        with suppress(AttributeError, RuntimeError, TypeError, ValueError):
            max_label = max(max_label, metrics.horizontalAdvance(str(name)))
        with suppress(AttributeError, RuntimeError, TypeError, ValueError):
            max_label = max(max_label, metrics.width(str(name)))
    heading = field or 'Legend'
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        font.setBold(True)
        hm = QFontMetrics(font)
        max_label = max(max_label, hm.horizontalAdvance(heading))
        with suppress(AttributeError, RuntimeError, TypeError, ValueError):
            max_label = max(max_label, hm.width(heading))
        font.setBold(False)
    return min(mm_to_px(42, dpi), max(min_col, glyph + max_label + pad))


def prefer_legend_place(
    drawn_w_mm, drawn_h_mm, avail_w_mm, avail_h_mm,
    paper_w_mm, paper_h_mm, n_items, rows_fit_side,
):
    """Pick ``side`` (vertical) or ``below`` (horizontal columns).

    Uses leftover letterbox space after placing the drawing on the sheet, plus
    paper orientation. Falls back to orientation when the frame fills the area.
    """
    n = max(0, int(n_items or 0))
    rows_ok = max(1, int(rows_fit_side or 1))
    if n == 0:
        return 'side'
    if n > rows_ok:
        return 'below'
    free_w = max(0.0, float(avail_w_mm) - float(drawn_w_mm))
    free_h = max(0.0, float(avail_h_mm) - float(drawn_h_mm))
    paper_land = float(paper_w_mm) >= float(paper_h_mm)
    # Not enough side room (typical with custom 1∶N) → under the frame.
    if free_w < 22.0:
        return 'below'
    # Clear leftover preference: more side room → vertical legend.
    if free_w >= free_h + 6.0 and free_w >= 22.0:
        return 'side'
    if free_h >= free_w + 6.0:
        return 'below'
    # Frame fills the plot area — use paper / drawing aspect.
    drawn_land = float(drawn_w_mm) >= float(drawn_h_mm) * 0.95
    if paper_land and drawn_land:
        return 'below'  # wide drawing on landscape: room is under the frame
    if (not paper_land) and (not drawn_land):
        return 'side'  # tall drawing on portrait: room is beside
    if paper_land:
        return 'side'
    return 'below'


def paper_legend_plan(
    items, field, plot_h_px, plot_w_px, dpi,
    prefer_place=None,
    drawn_w_mm=None, drawn_h_mm=None,
    avail_w_mm=None, avail_h_mm=None,
    paper_w_mm=None, paper_h_mm=None,
):
    """Choose side (1 column) vs below (multi-column) for a complete legend.

    Placement prefers leftover letterbox space / paper orientation when the
    sizes are provided; otherwise falls back to “fits in height → side”.
    """
    items = list(items or [])
    row_h = mm_to_px(3.6, dpi)
    head_h = row_h + mm_to_px(0.8, dpi) if (field or items) else 0.0
    col_w = _legend_col_width_px(items, field, dpi)
    n = len(items)
    plot_h_px = max(1.0, float(plot_h_px))
    plot_w_px = max(1.0, float(plot_w_px))
    body_h = max(row_h, plot_h_px - head_h)
    rows_side = max(1, int(body_h / row_h))

    if n == 0:
        return {
            'place': 'side', 'n_cols': 1, 'rows_per_col': 1,
            'col_w': col_w, 'total_w': col_w, 'total_h': head_h,
            'row_h': row_h, 'head_h': head_h, 'n': 0,
        }

    place = prefer_place
    if place not in ('side', 'below'):
        if (
            drawn_w_mm is not None and drawn_h_mm is not None
            and avail_w_mm is not None and avail_h_mm is not None
            and paper_w_mm is not None and paper_h_mm is not None
        ):
            place = prefer_legend_place(
                drawn_w_mm, drawn_h_mm, avail_w_mm, avail_h_mm,
                paper_w_mm, paper_h_mm, n, rows_side,
            )
        else:
            place = 'side' if n <= rows_side else 'below'
    if place == 'side' and n > rows_side:
        place = 'below'

    if place == 'side':
        return {
            'place': 'side', 'n_cols': 1, 'rows_per_col': rows_side,
            'col_w': col_w, 'total_w': col_w,
            'total_h': head_h + n * row_h,
            'row_h': row_h, 'head_h': head_h, 'n': n,
        }

    # Below: pack left with natural column width (do not stretch across the plot).
    # Prefer a single row when every entry fits.
    natural_w = float(col_w)
    max_cols = max(1, int(plot_w_px / max(natural_w, 1.0)))
    if n <= max_cols:
        n_cols = n
        rows = 1
        col_w = natural_w
    else:
        n_cols = max_cols
        rows = max(1, int(math.ceil(n / float(n_cols))))
        max_rows = max(2, int(math.ceil(n / 3.0)))
        while rows > max_rows and n_cols < n:
            n_cols += 1
            rows = max(1, int(math.ceil(n / float(n_cols))))
        col_w = min(natural_w, plot_w_px / float(max(n_cols, 1)))
    total_w = min(plot_w_px, n_cols * col_w)
    return {
        'place': 'below', 'n_cols': n_cols, 'rows_per_col': rows,
        'col_w': col_w, 'total_w': total_w,
        'total_h': head_h + rows * row_h,
        'row_h': row_h, 'head_h': head_h, 'n': n,
    }


def paper_legend_side_width_mm(plan, dpi=96.0):
    """Right-margin mm when the legend sits beside the plot."""
    if not plan or plan.get('place') != 'side':
        return 0.0
    px_per_mm = mm_to_px(1.0, dpi)
    if px_per_mm <= 0:
        return 0.0
    return max(18.0, float(plan['total_w']) / px_per_mm)


def paper_legend_below_height_mm(plan, dpi=96.0):
    """Extra bottom mm when the legend sits under the plot."""
    if not plan or plan.get('place') != 'below':
        return 0.0
    px_per_mm = mm_to_px(1.0, dpi)
    if px_per_mm <= 0:
        return 0.0
    return max(8.0, float(plan['total_h']) / px_per_mm) + 2.0


def paint_paper_legend(painter, items, field, x, top, bottom, dpi, ink, plan=None):
    """Full group legend (side or below). Returns width used (px)."""
    items = list(items or [])
    if not items and not field:
        return 0.0
    if plan is None:
        avail_h = max(1.0, float(bottom) - float(top))
        plan = paper_legend_plan(items, field, avail_h, mm_to_px(22, dpi), dpi)
    n_cols = int(plan['n_cols'])
    rows_per_col = int(plan['rows_per_col'])
    col_w = float(plan['col_w'])
    total_w = float(plan['total_w'])
    row_h = float(plan['row_h'])
    head_h = float(plan['head_h'])
    place = plan.get('place') or 'side'

    font = QFont()
    font.setPixelSize(pt_to_px(7, dpi))
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(ink)
    heading = field or 'Legend'
    painter.drawText(
        QRectF(x, top, total_w, row_h),
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        heading,
    )
    ly0 = top + head_h
    font.setBold(False)
    painter.setFont(font)
    metrics = painter.fontMetrics()
    r = max(1.4, mm_to_px(1.1, dpi))
    text_x0 = r * 2 + mm_to_px(1.6, dpi)
    text_w = max(4.0, col_w - text_x0 - mm_to_px(1.0, dpi))
    for i, item in enumerate(items):
        if place == 'below':
            # Left → right, then next row (natural reading order under the plot).
            col = i % n_cols
            row = i // n_cols
        else:
            col = i // rows_per_col
            row = i % rows_per_col
        if col >= n_cols:
            continue
        lx = x + col * col_w
        ly = ly0 + row * row_h
        name, color, shape = _unpack_legend_item(item)
        cy = ly + row_h / 2.0
        draw_legend_marker(painter, lx + r + 1.0, cy, r, shape, color)
        painter.setPen(ink)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        label = name
        with suppress(AttributeError, RuntimeError, TypeError, ValueError):
            label = metrics.elidedText(str(name), Qt.TextElideMode.ElideRight, int(text_w))
        painter.drawText(
            QRectF(lx + text_x0, ly, text_w, row_h),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            label,
        )
    return float(total_w)


class AxesGridOverlay(QWidget):
    def __init__(self, canvas, h_axis, v_axis, h_label, v_label, parent=None):
        super().__init__(parent)
        self.canvas = canvas
        self.h_axis = h_axis
        self.v_axis = v_axis
        self.h_label = h_label
        self.v_label = v_label
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)
        self.setStyleSheet('background: transparent;')
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setMouseTracking(True)
        self._paper = False
        self._paper_bg = QColor('#ffffff')
        self._z_stretch = 1.0
        self._show_grid = True
        self._square_grid = False
        self._quadre_fmt = None  # (fmt_x, fmt_y) or None
        # Cross-view hover: (map_x, map_y) in this pane's CRS, role 'here'|'other'|None
        self._hover_xy = None
        self._hover_role = None
        self._hover_move = None  # callback(x_px, y_px) from dock
        self._hover_leave = None
        # Find selection mark (map x,y in this pane's CRS), or None.
        self._select_xy = None
        # Profile on Plan: footprint + optional endpoint marks.
        self._profile_poly = None
        self._profile_a = None
        self._profile_b = None
        self._profile_ab = None
        self._profile_click = None  # callback(px, py) while picking A/B
        # Drag existing A/B: callback(which, map_x, map_y, phase) with
        # phase in ('move', 'end'). which is 'A' or 'B'.
        self._profile_drag = None
        self._profile_drag_which = None
        self._profile_hit_px = 12.0
        canvas.extentsChanged.connect(self.update)
        with suppress(AttributeError, RuntimeError, TypeError, ValueError):
            canvas.scaleChanged.connect(lambda _s: self.update())
        with suppress(AttributeError, RuntimeError, TypeError, ValueError):
            canvas.mapCanvasRefreshed.connect(self.update)

    def set_show_grid(self, on):
        on = bool(on)
        if on == self._show_grid:
            return
        self._show_grid = on
        self.update()

    def set_square_grid(self, on):
        on = bool(on)
        self._square_grid = on
        self.update()

    def set_quadre_formatters(self, pair):
        """``pair`` is ``(fmt_x, fmt_y)`` from ``quadre_grid.build_formatters``, or None."""
        self._quadre_fmt = pair
        self.update()

    def axis_formatters(self):
        if not self._square_grid or not self._quadre_fmt:
            return None, None
        return QG.for_axes(self.h_axis, self.v_axis, self._quadre_fmt)

    def set_cross_hover(self, map_x, map_y, role=None):
        """Show / clear the cross-view hover mark. ``role``: 'here', 'other', or None."""
        if role is None or map_x is None or map_y is None:
            if self._hover_role is None and self._hover_xy is None:
                return
            self._hover_xy = None
            self._hover_role = None
            self.update()
            return
        xy = (float(map_x), float(map_y))
        if self._hover_role == role and self._hover_xy == xy:
            return
        self._hover_xy = xy
        self._hover_role = role
        self.update()

    def set_selection_mark(self, map_x, map_y):
        """Find selection ring in this pane's map CRS, or ``None`` to clear."""
        if map_x is None or map_y is None:
            if self._select_xy is None:
                return
            self._select_xy = None
            self.update()
            return
        xy = (float(map_x), float(map_y))
        if self._select_xy == xy:
            return
        self._select_xy = xy
        self.update()

    def set_profile_corridor(self, polygon_xy=None, a=None, b=None):
        """Plan footprint + endpoint marks.

        ``a`` / ``b`` are optional (x,y). A alone is enough to show a labeled mark
        while picking B. Corridor fill needs both endpoints + ``polygon_xy``.
        """
        poly = None
        if polygon_xy:
            try:
                poly = tuple(
                    (float(p[0]), float(p[1])) for p in polygon_xy if p is not None
                )
            except (TypeError, ValueError, IndexError):
                poly = None
            if poly is not None and len(poly) < 3:
                poly = None
        pa = pb = None
        if a is not None:
            with suppress(TypeError, ValueError, IndexError):
                pa = (float(a[0]), float(a[1]))
        if b is not None:
            with suppress(TypeError, ValueError, IndexError):
                pb = (float(b[0]), float(b[1]))
        if (
            poly == self._profile_poly
            and pa == getattr(self, '_profile_a', None)
            and pb == getattr(self, '_profile_b', None)
        ):
            return
        self._profile_poly = poly
        self._profile_a = pa
        self._profile_b = pb
        # Keep legacy pair for any older callers/tests.
        self._profile_ab = (pa, pb) if (pa is not None and pb is not None) else None
        self.update()

    def set_z_stretch(self, stretch):
        try:
            s = float(stretch)
        except (TypeError, ValueError):
            s = 1.0
        if s < 1.0:
            s = 1.0
        if abs(s - self._z_stretch) < 1e-9:
            return
        self._z_stretch = s
        self.update()

    def z_stretch(self):
        return float(getattr(self, '_z_stretch', 1.0) or 1.0)

    def wheelEvent(self, event):
        canvas = self.canvas
        delta = event.angleDelta().y()
        if delta == 0:
            delta = event.pixelDelta().y()
        if canvas is not None and delta and hasattr(canvas, 'zoom_by_wheel'):
            canvas.zoom_by_wheel(delta)
            event.accept()
            return
        event.ignore()

    def _profile_map_to_screen(self, xy):
        if xy is None or self.canvas is None:
            return None
        try:
            xform = self.canvas.getCoordinateTransform()
            scr = xform.transform(QgsPointXY(float(xy[0]), float(xy[1])))
            return float(scr.x()), float(scr.y())
        except Exception:
            return None

    def _profile_screen_to_map(self, px, py):
        if self.canvas is None:
            return None
        try:
            xform = self.canvas.getCoordinateTransform()
            pt = xform.toMapCoordinates(int(round(px)), int(round(py)))
            return float(pt.x()), float(pt.y())
        except Exception:
            return None

    def _hit_profile_endpoint(self, px, py):
        """Return 'A' / 'B' if the cursor is on a profile mark (Plan only)."""
        # Corridor marks only exist on Plan (x/y).
        if self.h_axis != 'x' or self.v_axis != 'y':
            return None
        if getattr(self, '_profile_drag', None) is None:
            return None
        hit_r = float(getattr(self, '_profile_hit_px', 12.0) or 12.0)
        best = None
        best_d = hit_r
        for label, xy in (
            ('A', getattr(self, '_profile_a', None)),
            ('B', getattr(self, '_profile_b', None)),
        ):
            scr = self._profile_map_to_screen(xy)
            if scr is None:
                continue
            d = math.hypot(px - scr[0], py - scr[1])
            if d <= best_d:
                best_d = d
                best = label
        return best

    def _restore_idle_cursor(self, px=None, py=None):
        """Cross while picking; open-hand near A/B; else arrow."""
        if getattr(self, '_profile_drag_which', None) is not None:
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if getattr(self, '_profile_click', None) is not None:
            if px is not None and py is not None and self._hit_profile_endpoint(px, py):
                self.setCursor(Qt.CursorShape.OpenHandCursor)
            else:
                self.setCursor(Qt.CursorShape.CrossCursor)
            return
        if (
            px is not None and py is not None
            and self._hit_profile_endpoint(px, py) is not None
        ):
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            return
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def _finish_profile_drag(self, px, py):
        which = getattr(self, '_profile_drag_which', None)
        if which is None:
            return False
        self._profile_drag_which = None
        xy = self._profile_screen_to_map(px, py)
        cb = getattr(self, '_profile_drag', None)
        if cb is not None and xy is not None:
            with suppress(AttributeError, RuntimeError, TypeError, ValueError):
                cb(which, xy[0], xy[1], 'end')
        self._restore_idle_cursor(px, py)
        return True

    def mousePressEvent(self, event):
        if event.button() not in (Qt.MouseButton.LeftButton, Qt.MouseButton.MiddleButton):
            event.ignore()
            return
        pos = event.position() if hasattr(event, 'position') else event.pos()
        px, py = float(pos.x()), float(pos.y())
        # Drag existing A/B (takes priority over pick-to-place and pan).
        if event.button() == Qt.MouseButton.LeftButton:
            which = self._hit_profile_endpoint(px, py)
            if which is not None and getattr(self, '_profile_drag', None) is not None:
                self._profile_drag_which = which
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                xy = self._profile_screen_to_map(px, py)
                cb = self._profile_drag
                if cb is not None and xy is not None:
                    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
                        cb(which, xy[0], xy[1], 'move')
                event.accept()
                return
        # Profile Pick A/B: left-click places a point instead of panning.
        if (
            event.button() == Qt.MouseButton.LeftButton
            and getattr(self, '_profile_click', None) is not None
        ):
            cb = self._profile_click
            with suppress(AttributeError, RuntimeError, TypeError, ValueError):
                cb(px, py)
            event.accept()
            return
        canvas = self.canvas
        if canvas is None or not hasattr(canvas, 'pan_start'):
            event.ignore()
            return
        canvas.pan_start(pos.x(), pos.y())
        self.setCursor(Qt.CursorShape.ClosedHandCursor)  # drag; idle cursor is Arrow
        event.accept()

    def mouseMoveEvent(self, event):
        canvas = self.canvas
        pos = event.position() if hasattr(event, 'position') else event.pos()
        px, py = float(pos.x()), float(pos.y())
        which = getattr(self, '_profile_drag_which', None)
        if which is not None:
            xy = self._profile_screen_to_map(px, py)
            cb = getattr(self, '_profile_drag', None)
            if cb is not None and xy is not None:
                with suppress(AttributeError, RuntimeError, TypeError, ValueError):
                    cb(which, xy[0], xy[1], 'move')
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if canvas is not None and getattr(canvas, '_pan_last', None) is not None:
            canvas.pan_move(px, py)
            event.accept()
            return
        # Hover affordance near A/B (even while Pick cue is active).
        if self._hit_profile_endpoint(px, py) is not None:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        elif getattr(self, '_profile_click', None) is not None:
            self.setCursor(Qt.CursorShape.CrossCursor)
        cb = getattr(self, '_hover_move', None)
        if cb is not None:
            with suppress(AttributeError, RuntimeError, TypeError, ValueError):
                cb(px, py)
            event.accept()
            return
        event.ignore()

    def mouseReleaseEvent(self, event):
        pos = event.position() if hasattr(event, 'position') else event.pos()
        px, py = float(pos.x()), float(pos.y())
        if self._finish_profile_drag(px, py):
            event.accept()
            return
        canvas = self.canvas
        if canvas is not None and hasattr(canvas, 'pan_end'):
            canvas.pan_end()
        self._restore_idle_cursor(px, py)
        event.accept()

    def leaveEvent(self, event):
        # If dragging out of the pane, commit at the last known mark position.
        which = getattr(self, '_profile_drag_which', None)
        if which is not None:
            self._profile_drag_which = None
            xy = getattr(self, '_profile_a' if which == 'A' else '_profile_b', None)
            cb = getattr(self, '_profile_drag', None)
            if cb is not None and xy is not None:
                with suppress(AttributeError, RuntimeError, TypeError, ValueError):
                    cb(which, float(xy[0]), float(xy[1]), 'end')
            self.setCursor(Qt.CursorShape.ArrowCursor)
        cb = getattr(self, '_hover_leave', None)
        if cb is not None:
            with suppress(AttributeError, RuntimeError, TypeError, ValueError):
                cb()
        super().leaveEvent(event)

    def pads(self):
        return PAD_L, PAD_R, PAD_T, PAD_B

    def export_legend_width(self):
        items, title = self._legend_entries()
        if items or title:
            return LEGEND_GAP + LEGEND_W
        return 0

    def _legend_entries(self):
        canvas = self.canvas
        if canvas is None:
            return [], ''
        layers = canvas.layers() or []
        if not layers:
            return [], ''
        layer = layers[0]
        renderer = layer.renderer()
        if renderer is None or not hasattr(renderer, 'categories'):
            return [], ''
        # classAttribute is often a CASE WHEN expression — never use it as heading.
        title = 'Legend'
        cmap = {}
        shapes = {}
        order = []
        try:
            cats = renderer.categories()
        except Exception:
            return [], title
        for cat in cats:
            label = (cat.label() or '').strip()
            if not label:
                label = group_label(cat.value())
            if label in cmap:
                continue
            color = QColor('#888888')
            shape = DEFAULT_MARKER
            sym = cat.symbol()
            if sym is not None:
                with suppress(AttributeError, RuntimeError, TypeError, ValueError):
                    paint = _symbol_paint_color(sym)
                    if paint is not None and paint.isValid():
                        color = QColor(paint)
                    else:
                        color = QColor(sym.color())
                with suppress(AttributeError, RuntimeError, TypeError, ValueError):
                    shape = resolve_marker_shape(_symbol_marker_shape(sym))
            cmap[label] = color
            shapes[label] = shape
            order.append(label)
        # Prefer visible features when a real group field is known on the layer.
        field_name = ''
        with suppress(AttributeError, RuntimeError, TypeError, ValueError):
            field_name = str(layer.customProperty('arsysplotqgis_group') or '').strip()
        if not field_name and hasattr(renderer, 'classAttribute'):
            # Fallback: plain field name only (not a CASE expression).
            raw = (renderer.classAttribute() or '').strip()
            if raw and 'CASE' not in raw.upper() and '"' not in raw:
                field_name = raw
        if field_name:
            idx = layer.fields().lookupField(field_name)
            if idx >= 0:
                try:
                    present = set(group_label(v) for v in layer.uniqueValues(idx))
                except Exception:
                    present = None
                if present is not None:
                    order = [k for k in order if k in present]
        return [(key, cmap[key], shapes[key]) for key in order], title

    def paintEvent(self, _event):
        try:
            painter = QPainter(self)
            self._paint_axes(painter)
        except Exception:
            return

    def paint_onto(self, painter):
        self._paint_axes(painter)

    def _data_rect(self):
        canvas = self.canvas
        if canvas is None:
            return None
        ext = getattr(canvas, '_data_ext', None)
        if ext is not None and not ext.isEmpty():
            return QgsRectangle(ext)
        ext = padded_data_extent(canvas.layers() or [])
        if ext is not None and not ext.isEmpty():
            return ext
        return None

    def _plot_frame(self, xform, w, h):
        """Axis box of the data footprint (small pad), clamped to the pane.

        Fit keeps isotropic metres (letterbox). Planar tick bounds stay on
        whole metres (Lite ``tickMin/Max``) so grid cells are always 1 m even
        after the screen clamp makes ``xmin…ymax`` slightly fractional.
        """
        pad_l, pad_r, pad_t, pad_b = self.pads()
        panel_left, panel_right = float(pad_l), float(w - pad_r)
        panel_top, panel_bottom = float(pad_t), float(h - pad_b)
        if panel_right - panel_left < 20 or panel_bottom - panel_top < 20:
            return None
        left, right, top, bottom = panel_left, panel_right, panel_top, panel_bottom
        tick_xmin = tick_xmax = tick_ymin = tick_ymax = None
        data = self._data_rect()
        if data is not None and not data.isEmpty():
            x0, x1, y0, y1 = snap_world_rect(
                data.xMinimum(), data.xMaximum(),
                data.yMinimum(), data.yMaximum(),
                self.h_axis, self.v_axis,
            )
            tick_xmin, tick_xmax, tick_ymin, tick_ymax = x0, x1, y0, y1
            p_tl = xform.transform(QgsPointXY(x0, y1))
            p_br = xform.transform(QgsPointXY(x1, y0))
            dleft = min(p_tl.x(), p_br.x())
            dright = max(p_tl.x(), p_br.x())
            dtop = min(p_tl.y(), p_br.y())
            dbottom = max(p_tl.y(), p_br.y())
            left = max(dleft, panel_left)
            right = min(dright, panel_right)
            top = max(dtop, panel_top)
            bottom = min(dbottom, panel_bottom)
            # Thin section bands (flat LONG or narrow TRANS) used to fall back to
            # the full pane → enormous empty grid with the profile as a "fly".
            # Pad the thin screen axis around the data; never jump to full panel
            # while we still have a usable tick footprint.
            if self.v_axis == 'z' and (
                right - left < 20 or bottom - top < 20
            ):
                if right - left < 20:
                    mid = 0.5 * (left + right)
                    half = max(
                        28.0, 0.5 * (right - left),
                        (panel_right - panel_left) * 0.22,
                    )
                    left = max(panel_left, mid - half)
                    right = min(panel_right, mid + half)
                if bottom - top < 20:
                    mid = 0.5 * (top + bottom)
                    half = max(
                        28.0, 0.5 * (bottom - top),
                        (panel_bottom - panel_top) * 0.22,
                    )
                    top = max(panel_top, mid - half)
                    bottom = min(panel_bottom, mid + half)
            elif right - left < 20 or bottom - top < 20:
                left, right, top, bottom = (
                    panel_left, panel_right, panel_top, panel_bottom
                )
        tl = xform.toMapCoordinates(int(round(left)), int(round(top)))
        br = xform.toMapCoordinates(int(round(right)), int(round(bottom)))
        xmin = min(tl.x(), br.x())
        xmax = max(tl.x(), br.x())
        ymin = min(tl.y(), br.y())
        ymax = max(tl.y(), br.y())
        # Fallback tick bounds when no data rect: still whole metres on planar axes.
        if tick_xmin is None:
            if _is_planar(self.h_axis):
                tick_xmin, tick_xmax = _floor_m(xmin), _ceil_m(xmax)
                if tick_xmax <= tick_xmin:
                    tick_xmax = tick_xmin + 1.0
            else:
                tick_xmin, tick_xmax = xmin, xmax
            if _is_planar(self.v_axis):
                tick_ymin, tick_ymax = _floor_m(ymin), _ceil_m(ymax)
                if tick_ymax <= tick_ymin:
                    tick_ymax = tick_ymin + 1.0
            else:
                tick_ymin, tick_ymax = ymin, ymax
        return (
            left, right, top, bottom,
            xmin, xmax, ymin, ymax,
            tick_xmin, tick_xmax, tick_ymin, tick_ymax,
        )

    def _paint_axes(self, p):
        canvas = self.canvas
        if canvas is None:
            return
        ext = canvas.extent()
        if ext is None or ext.isEmpty():
            return
        xform = canvas.getCoordinateTransform()
        if xform is None:
            return
        w, h = self.width(), self.height()
        if w < 60 or h < 50:
            return

        frame = self._plot_frame(xform, w, h)
        if frame is None:
            return
        (
            left, right, top, bottom,
            xmin, xmax, ymin, ymax,
            tick_xmin, tick_xmax, tick_ymin, tick_ymax,
        ) = frame
        # Grid / labels use whole-metre tick bounds (not the fractional clamp).
        fmt_h, fmt_v = self.axis_formatters()
        use_h = callable(fmt_h)
        use_v = callable(fmt_v)
        if use_h:
            h_step, h_ticks = 1.0, QG.grid_lines(tick_xmin, tick_xmax)
            h_labels = QG.cell_mids(tick_xmin, tick_xmax)
        else:
            h_step, h_ticks = _ticks(
                tick_xmin, tick_xmax, self.h_axis, right - left,
            )
            h_labels = h_ticks
        if use_v:
            v_step = 1.0
            v_pairs = [(t, t) for t in QG.grid_lines(tick_ymin, tick_ymax)]
            v_labels = [(t, t) for t in QG.cell_mids(tick_ymin, tick_ymax)]
        else:
            v_step, v_pairs = _vertical_axis_ticks(
                tick_ymin, tick_ymax, self.v_axis, bottom - top,
                z_stretch=self.z_stretch(),
            )
            v_labels = v_pairs
        v_ticks = [m for m, _lab in v_pairs]

        def sx(map_x):
            return xform.transform(QgsPointXY(map_x, ymin)).x()

        def sy(map_y):
            return xform.transform(QgsPointXY(xmin, map_y)).y()

        if self._paper:
            grid, axis, label, title = GRID_LIGHT, AXIS_LIGHT, LABEL_LIGHT, TITLE_LIGHT
            margin = self._paper_bg if self._paper_bg is not None else QColor('#ffffff')
        else:
            # Follow the map canvas (dark / light UI theme).
            try:
                margin = QColor(canvas.canvasColor())
            except Exception:
                margin = QColor(SCREEN_BG)
            if is_light_color(margin):
                grid, axis, label, title = (
                    GRID_LIGHT, AXIS_LIGHT, LABEL_LIGHT, TITLE_LIGHT,
                )
            else:
                grid, axis, label, title = GRID, AXIS, LABEL, TITLE

        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(margin)
        p.drawRect(QRectF(0, 0, w, top + 1))
        p.drawRect(QRectF(0, bottom - 1, w, h - bottom + 1))
        p.drawRect(QRectF(0, top, left + 1, bottom - top))
        p.drawRect(QRectF(right - 1, top, w - right + 1, bottom - top))

        if self._show_grid:
            p.setClipRect(QRectF(left, top, right - left, bottom - top))
            p.setPen(QPen(grid, GRID_PEN_W))
            for tick in h_ticks:
                x = sx(tick)
                if x < left or x > right:
                    continue
                _line(p, x, top, x, bottom)
            for tick in v_ticks:
                y = sy(tick)
                if y < top or y > bottom:
                    continue
                _line(p, left, y, right, y)
            p.setClipping(False)

        # Complete data-frame outline (Lite), not only the classical L-axes.
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(axis, 1.25))
        p.drawRect(QRectF(left, top, right - left, bottom - top))

        p.setPen(QPen(axis, 1))
        for tick in h_ticks:
            x = sx(tick)
            if x < left - 4 or x > right + 4:
                continue
            _line(p, x, bottom, x, bottom + 5)
        for tick in v_ticks:
            y = sy(tick)
            if y < top - 4 or y > bottom + 4:
                continue
            _line(p, left - 5, y, left, y)

        font = QFont()
        font.setPixelSize(10)
        p.setFont(font)
        p.setPen(label)
        for tick in h_labels:
            x = sx(tick)
            if x < left - 4 or x > right + 4:
                continue
            text = fmt_h(tick) if use_h else _fmt(tick, h_step, self.h_axis)
            p.drawText(
                QRectF(x - 28, bottom + 7, 56, 16),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                text,
            )
        for map_y, lab_v in v_labels:
            y = sy(map_y)
            if y < top - 4 or y > bottom + 4:
                continue
            text = fmt_v(lab_v) if use_v else _fmt(lab_v, v_step, self.v_axis)
            p.drawText(
                QRectF(28, y - 8, left - 36, 16),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                text,
            )

        p.setPen(title)
        h_title = self.h_label if use_h else '%s (m)' % self.h_label
        p.drawText(
            QRectF(left, bottom + 30, right - left, 18),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
            h_title,
        )
        p.save()
        p.translate(max(12.0, left - 54.0), (top + bottom) / 2.0)
        p.rotate(-90)
        v_title = (
            self.v_label if use_v
            else _z_axis_title(self.v_label, self.z_stretch())
        )
        p.drawText(
            QRectF(-80, -10, 160, 20),
            Qt.AlignmentFlag.AlignCenter,
            v_title,
        )
        p.restore()
        self._paint_profile_corridor(p, xform, left, right, top, bottom)
        self._paint_cross_hover(p, xform, left, right, top, bottom)
        self._paint_selection_mark(p, xform, left, right, top, bottom)

    def _paint_profile_corridor(self, p, xform, left, right, top, bottom):
        """Semi-transparent green XY footprint + labeled A/B marks (Plan)."""
        # Only meaningful on Plan (x/y). Skip section panes.
        if self.h_axis != 'x' or self.v_axis != 'y':
            return
        poly = getattr(self, '_profile_poly', None)
        pa = getattr(self, '_profile_a', None)
        pb = getattr(self, '_profile_b', None)
        if (poly is None or len(poly) < 3) and pa is None and pb is None:
            return
        if xform is None:
            return
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setClipRect(QRectF(left, top, right - left, bottom - top))
        if poly is not None and len(poly) >= 3:
            pts = []
            for mx, my in poly:
                try:
                    scr = xform.transform(QgsPointXY(mx, my))
                    pts.append(QPointF(float(scr.x()), float(scr.y())))
                except Exception:
                    pts = []
                    break
            if len(pts) >= 3:
                # Stronger green profile footprint.
                p.setPen(QPen(QColor(0, 150, 35, 245), 2.2))
                p.setBrush(QColor(20, 200, 55, 150))
                p.drawPolygon(QPolygonF(pts))
        if pa is not None and pb is not None:
            try:
                s0 = xform.transform(QgsPointXY(pa[0], pa[1]))
                s1 = xform.transform(QgsPointXY(pb[0], pb[1]))
                p.setPen(QPen(QColor(0, 140, 40, 240), 2.4))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawLine(
                    QPointF(float(s0.x()), float(s0.y())),
                    QPointF(float(s1.x()), float(s1.y())),
                )
            except Exception:
                pass
        # A = red, B = blue (matches Pick A / Pick B cues).
        self._paint_profile_endpoint(p, xform, pa, 'A', QColor(220, 30, 30, 245))
        self._paint_profile_endpoint(p, xform, pb, 'B', QColor(30, 90, 230, 245))
        p.setClipping(False)

    def _paint_profile_endpoint(self, p, xform, xy, label, fill=None):
        """Labeled A/B disc on Plan (visible as soon as that endpoint exists)."""
        if xy is None or xform is None:
            return
        try:
            scr = xform.transform(QgsPointXY(xy[0], xy[1]))
            cx, cy = float(scr.x()), float(scr.y())
        except Exception:
            return
        r = 6.0
        brush = fill if fill is not None else QColor(30, 160, 60, 240)
        p.setBrush(brush)
        p.setPen(QPen(QColor(255, 255, 255, 230), 1.4))
        p.drawEllipse(QPointF(cx, cy), r, r)
        font = QFont()
        font.setPixelSize(11)
        font.setBold(True)
        p.setFont(font)
        ink = QColor(brush.red(), brush.green(), brush.blue(), 255)
        p.setPen(QPen(ink))
        p.drawText(
            QRectF(cx + r + 2, cy - 10, 18, 16),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            str(label),
        )

    def _paint_cross_hover(self, p, xform, left, right, top, bottom):
        """Blue ring (other panes) or filled disc (source pane) — Lite-style."""
        role = self._hover_role
        xy = self._hover_xy
        if role is None or xy is None or xform is None:
            return
        try:
            scr = xform.transform(QgsPointXY(xy[0], xy[1]))
            cx, cy = float(scr.x()), float(scr.y())
        except Exception:
            return
        if cx < left - 40 or cx > right + 40 or cy < top - 40 or cy > bottom + 40:
            return
        r = 11.0
        stroke = QColor(30, 144, 255)
        fill = QColor(30, 144, 255, 55)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if role == 'here':
            p.setPen(QPen(stroke, 2.0))
            p.setBrush(fill)
            p.drawEllipse(QPointF(cx, cy), r, r)
        else:
            p.setPen(QPen(stroke, 2.2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(cx, cy), r, r)
            # Small crosshair inside the ring.
            arm = r * 0.55
            p.drawLine(QPointF(cx - arm, cy), QPointF(cx + arm, cy))
            p.drawLine(QPointF(cx, cy - arm), QPointF(cx, cy + arm))

    def _paint_selection_mark(self, p, xform, left, right, top, bottom):
        """Green Find selection ring — Lite ``drawSelectedMark``."""
        xy = getattr(self, '_select_xy', None)
        if xy is None or xform is None:
            return
        try:
            scr = xform.transform(QgsPointXY(xy[0], xy[1]))
            cx, cy = float(scr.x()), float(scr.y())
        except Exception:
            return
        if cx < left - 40 or cx > right + 40 or cy < top - 40 or cy > bottom + 40:
            return
        r = 12.0
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(34, 140, 64), 3.2))
        p.drawEllipse(QPointF(cx, cy), r, r)
        p.setPen(QPen(QColor(180, 240, 190), 1.4))
        p.drawEllipse(QPointF(cx, cy), r, r)

    def paint_export_legend(self, p, plot_right, top, bottom):
        if self._paper:
            ink, heading = LABEL_LIGHT, TITLE_LIGHT
        else:
            try:
                bg = QColor(self.canvas.canvasColor())
            except Exception:
                bg = QColor(SCREEN_BG)
            if is_light_color(bg):
                ink, heading = LABEL_LIGHT, TITLE_LIGHT
            else:
                ink, heading = LABEL, TITLE
        self._paint_legend(p, plot_right, top, bottom, ink, heading)

    def _paint_legend(self, p, plot_right, top, bottom, ink, heading_color):
        items, field = self._legend_entries()
        if not items and not field:
            return
        lx = plot_right + LEGEND_GAP
        ly = top
        max_w = LEGEND_W - 2
        font = QFont()
        font.setPixelSize(7)
        font.setBold(True)
        p.setFont(font)
        p.setPen(heading_color)
        heading = field or 'Legend'
        metrics = p.fontMetrics()
        p.drawText(
            QRectF(lx, ly, max_w, 10),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            metrics.elidedText(heading, Qt.TextElideMode.ElideRight, max_w),
        )
        ly += 12
        font.setBold(False)
        p.setFont(font)
        metrics = p.fontMetrics()
        row_h = 10
        room = max(1, int((bottom - ly) / row_h))
        shown = items[:room]
        extra = len(items) - len(shown)
        if extra > 0 and shown:
            shown = shown[:-1]
            extra = len(items) - len(shown)
        for item in shown:
            name, color, shape = _unpack_legend_item(item)
            cy = ly + row_h / 2.0
            draw_legend_marker(p, lx + 4.0, cy, 3.0, shape, color)
            p.setPen(ink)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawText(
                QRectF(lx + 10, ly, max_w - 10, row_h),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                metrics.elidedText(name, Qt.TextElideMode.ElideRight, max_w - 10),
            )
            ly += row_h
        if extra > 0:
            p.setPen(heading_color)
            p.drawText(
                QRectF(lx, ly, max_w, row_h),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                '+%d more' % extra,
            )
