# -*- coding: utf-8 -*-
"""Metric axes + grid overlay for the three projection canvases (Lite-style)."""
from contextlib import suppress
import math

from qgis.core import QgsPointXY, QgsRectangle
from qgis.PyQt.QtCore import QPoint, QPointF, Qt, QRectF
from qgis.PyQt.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen, QPolygonF
from qgis.PyQt.QtWidgets import QWidget

from .export_dialog import is_light_color, mm_to_px, pt_to_px

from .layers import (
    DEFAULT_MARKER,
    _symbol_marker_shape,
    _symbol_paint_color,
    group_label,
    padded_data_extent,
    resolve_marker_shape,
)

INK = QColor(255, 245, 230)
GRID = QColor(255, 245, 230, 22)
AXIS = QColor(255, 245, 230, 120)
LABEL = QColor(255, 245, 230, 190)
TITLE = QColor(255, 245, 230, 140)
GRID_LIGHT = QColor(40, 40, 40, 40)
AXIS_LIGHT = QColor(30, 30, 30, 200)
LABEL_LIGHT = QColor(20, 20, 20, 230)
TITLE_LIGHT = QColor(40, 40, 40, 200)
GRID_PAPER = QColor(50, 48, 44, 110)
AXIS_PAPER = QColor(26, 24, 22)
LABEL_PAPER = QColor(26, 24, 22)
TITLE_PAPER = QColor(70, 66, 60)

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
    if shape in ('triangle', 'equilateral_triangle'):
        h = r * 1.15
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
        step = 1.0
        start = int(math.ceil(minv - 1e-9))
        end = int(math.floor(maxv + 1e-9))
        if end < start:
            start, end = int(_floor_m(minv)), int(_ceil_m(maxv))
        out = []
        v = start
        n = 0
        while v <= end and n < 400:
            out.append(v)
            v += 1
            n += 1
        if abs(minv - round(minv)) < 0.05:
            origin = int(round(minv))
            if not out or out[0] != origin:
                out.insert(0, origin)
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


# Fixed scale-bar length on every paper export (map metres).
SCALE_BAR_M = 0.5  # 50 cm


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
):
    """Axes, metre grid and scale bar in output pixels (paper)."""
    dx = max(xmax - xmin, 1e-9)
    dy = max(ymax - ymin, 1e-9)
    pw = max(right - left, 1.0)
    ph = max(bottom - top, 1.0)

    def sx(x):
        return left + (float(x) - xmin) / dx * pw

    def sy(y):
        return bottom - (float(y) - ymin) / dy * ph

    h_step, h_ticks = _ticks(xmin, xmax, h_axis, pw)
    v_step, v_pairs = _vertical_axis_ticks(
        ymin, ymax, v_axis, ph, z_stretch=z_stretch,
    )
    v_ticks = [m for m, _lab in v_pairs]
    grid_w = max(1.0, mm_to_px(0.12, dpi))
    axis_w = max(1.2, mm_to_px(0.32, dpi))
    tick_w = max(1.0, mm_to_px(0.22, dpi))
    tick_len = mm_to_px(1.6, dpi)

    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
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

    painter.setPen(QPen(AXIS_PAPER, axis_w))
    _line(painter, left, top, left, bottom)
    _line(painter, left, bottom, right, bottom)
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
    for tick in h_ticks:
        x = sx(tick)
        if x < left - 2 or x > right + 2:
            continue
        painter.drawText(
            QRectF(x - mm_to_px(10, dpi), bottom + tick_len + mm_to_px(0.4, dpi),
                   mm_to_px(20, dpi), lab_h),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
            _fmt(tick, h_step, h_axis),
        )
    for map_y, lab_v in v_pairs:
        y = sy(map_y)
        if y < top - 2 or y > bottom + 2:
            continue
        painter.drawText(
            QRectF(left - mm_to_px(17, dpi), y - lab_h / 2.0,
                   mm_to_px(15.2, dpi), lab_h),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            _fmt(lab_v, v_step, v_axis),
        )

    font.setPixelSize(pt_to_px(9, dpi))
    painter.setFont(font)
    painter.setPen(TITLE_PAPER)
    painter.drawText(
        QRectF(left, bottom + mm_to_px(6.2, dpi), pw, mm_to_px(5, dpi)),
        Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
        '%s (m)' % h_label,
    )
    painter.save()
    painter.translate(left - mm_to_px(14.5, dpi), (top + bottom) / 2.0)
    painter.rotate(-90)
    painter.drawText(
        QRectF(-mm_to_px(28, dpi), -mm_to_px(4, dpi), mm_to_px(56, dpi), mm_to_px(5, dpi)),
        Qt.AlignmentFlag.AlignCenter,
        _z_axis_title(v_label, z_stretch),
    )
    painter.restore()

    # Always 50 cm at true map scale; 5 × 10 cm alternating black / white.
    bar_m = float(SCALE_BAR_M)
    bar_px = bar_m / dx * pw
    n_seg = 5  # 10 cm each
    seg_px = bar_px / float(n_seg)
    bx = left
    by = bottom + mm_to_px(12.5, dpi)
    bh = mm_to_px(2.0, dpi)
    rim = QPen(AXIS_PAPER, max(1.0, mm_to_px(0.22, dpi)))
    for i in range(n_seg):
        sx0 = bx + i * seg_px
        fill = AXIS_PAPER if (i % 2 == 0) else QColor(255, 255, 255)
        painter.setPen(rim)
        painter.setBrush(fill)
        painter.drawRect(QRectF(sx0, by, seg_px, bh))
    painter.setPen(rim)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRect(QRectF(bx, by, bar_px, bh))
    font.setPixelSize(pt_to_px(7, dpi))
    painter.setFont(font)
    painter.setPen(LABEL_PAPER)
    painter.drawText(
        QRectF(bx, by + bh + mm_to_px(0.4, dpi), max(bar_px, mm_to_px(18, dpi)), lab_h),
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
        '50 cm',
    )


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


def paper_legend_plan(items, field, plot_h_px, plot_w_px, dpi):
    """Choose side (1 column) vs below (multi-column) for a complete legend.

    Side only when every entry fits in the plot height as a single column.
    Otherwise place under the plot and fill its width with columns — avoids
    stretching short section exports sideways.
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

    if n <= rows_side:
        return {
            'place': 'side', 'n_cols': 1, 'rows_per_col': rows_side,
            'col_w': col_w, 'total_w': col_w,
            'total_h': head_h + n * row_h,
            'row_h': row_h, 'head_h': head_h, 'n': n,
        }

    # Below: as many columns as fit in the plot width.
    max_cols = max(1, int(plot_w_px / max(col_w, 1.0)))
    n_cols = min(n, max_cols)
    if n_cols < 2:
        # Long labels / narrow plot: still split into several equal columns.
        n_cols = min(n, max(2, int(math.ceil(math.sqrt(float(n))))))
        col_w = plot_w_px / float(n_cols)
    else:
        col_w = min(col_w, plot_w_px / float(n_cols))
    rows = max(1, int(math.ceil(n / float(n_cols))))
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
        # Cross-view hover: (map_x, map_y) in this pane's CRS, role 'here'|'other'|None
        self._hover_xy = None
        self._hover_role = None
        self._hover_move = None  # callback(x_px, y_px) from dock
        self._hover_leave = None
        canvas.extentsChanged.connect(self.update)
        with suppress(AttributeError, RuntimeError, TypeError, ValueError):
            canvas.scaleChanged.connect(lambda _s: self.update())
        with suppress(AttributeError, RuntimeError, TypeError, ValueError):
            canvas.mapCanvasRefreshed.connect(self.update)

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

    def mousePressEvent(self, event):
        if event.button() not in (Qt.MouseButton.LeftButton, Qt.MouseButton.MiddleButton):
            event.ignore()
            return
        canvas = self.canvas
        if canvas is None or not hasattr(canvas, 'pan_start'):
            event.ignore()
            return
        pos = event.position() if hasattr(event, 'position') else event.pos()
        canvas.pan_start(pos.x(), pos.y())
        self.setCursor(Qt.CursorShape.ClosedHandCursor)  # drag; idle cursor is Arrow
        event.accept()

    def mouseMoveEvent(self, event):
        canvas = self.canvas
        pos = event.position() if hasattr(event, 'position') else event.pos()
        px, py = float(pos.x()), float(pos.y())
        if canvas is not None and getattr(canvas, '_pan_last', None) is not None:
            canvas.pan_move(px, py)
            event.accept()
            return
        cb = getattr(self, '_hover_move', None)
        if cb is not None:
            with suppress(AttributeError, RuntimeError, TypeError, ValueError):
                cb(px, py)
            event.accept()
            return
        event.ignore()

    def mouseReleaseEvent(self, event):
        canvas = self.canvas
        if canvas is not None and hasattr(canvas, 'pan_end'):
            canvas.pan_end()
        self.setCursor(Qt.CursorShape.ArrowCursor)
        event.accept()

    def leaveEvent(self, event):
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

        Fit keeps isotropic metres (letterbox), but ticks must not label empty
        margins as excavation metres. When zoomed in, the frame stays on the
        pad box so axes do not jump off the window.
        """
        pad_l, pad_r, pad_t, pad_b = self.pads()
        panel_left, panel_right = float(pad_l), float(w - pad_r)
        panel_top, panel_bottom = float(pad_t), float(h - pad_b)
        if panel_right - panel_left < 20 or panel_bottom - panel_top < 20:
            return None
        left, right, top, bottom = panel_left, panel_right, panel_top, panel_bottom
        data = self._data_rect()
        if data is not None and not data.isEmpty():
            x0, x1, y0, y1 = snap_world_rect(
                data.xMinimum(), data.xMaximum(),
                data.yMinimum(), data.yMaximum(),
                self.h_axis, self.v_axis,
            )
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
            if right - left < 20 or bottom - top < 20:
                left, right, top, bottom = (
                    panel_left, panel_right, panel_top, panel_bottom
                )
        tl = xform.toMapCoordinates(int(round(left)), int(round(top)))
        br = xform.toMapCoordinates(int(round(right)), int(round(bottom)))
        xmin = min(tl.x(), br.x())
        xmax = max(tl.x(), br.x())
        ymin = min(tl.y(), br.y())
        ymax = max(tl.y(), br.y())
        return left, right, top, bottom, xmin, xmax, ymin, ymax

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
        left, right, top, bottom, xmin, xmax, ymin, ymax = frame
        h_step, h_ticks = _ticks(xmin, xmax, self.h_axis, right - left)
        v_step, v_pairs = _vertical_axis_ticks(
            ymin, ymax, self.v_axis, bottom - top,
            z_stretch=self.z_stretch(),
        )
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

        p.setClipRect(QRectF(left, top, right - left, bottom - top))
        p.setPen(QPen(grid, 1))
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

        p.setPen(QPen(axis, 1.25))
        _line(p, left, top, left, bottom)
        _line(p, left, bottom, right, bottom)

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
        for tick in h_ticks:
            x = sx(tick)
            if x < left - 4 or x > right + 4:
                continue
            p.drawText(
                QRectF(x - 28, bottom + 7, 56, 16),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                _fmt(tick, h_step, self.h_axis),
            )
        for map_y, lab_v in v_pairs:
            y = sy(map_y)
            if y < top - 4 or y > bottom + 4:
                continue
            p.drawText(
                QRectF(28, y - 8, left - 36, 16),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                _fmt(lab_v, v_step, self.v_axis),
            )

        p.setPen(title)
        p.drawText(
            QRectF(left, bottom + 30, right - left, 18),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
            '%s (m)' % self.h_label,
        )
        p.save()
        p.translate(max(12.0, left - 54.0), (top + bottom) / 2.0)
        p.rotate(-90)
        p.drawText(
            QRectF(-80, -10, 160, 20),
            Qt.AlignmentFlag.AlignCenter,
            _z_axis_title(self.v_label, self.z_stretch()),
        )
        p.restore()
        self._paint_cross_hover(p, xform, left, right, top, bottom)

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
