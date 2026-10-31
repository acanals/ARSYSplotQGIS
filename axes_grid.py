# -*- coding: utf-8 -*-
"""Metric axes + grid overlay for the three projection canvases (Lite-style)."""
import math

from qgis.core import QgsPointXY, QgsRectangle
from qgis.PyQt.QtCore import QPoint, Qt, QRectF
from qgis.PyQt.QtGui import QColor, QFont, QPainter, QPen
from qgis.PyQt.QtWidgets import QWidget

from .export_dialog import mm_to_px, pt_to_px

from .layers import group_label, padded_data_extent

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
LEGEND_GAP = 8
LEGEND_W = 56
SCREEN_BG = QColor('#161411')

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
        out.append(round(v / step) * step)
        v += step
        n += 1
    if not out:
        out = [minv, maxv]
    elif abs(out[0] - minv) > step * 0.05:
        out.insert(0, minv)
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


def _scale_bar_metres(span):
    span = max(float(span), 1e-6)
    target = span * 0.28
    for metres in (0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100):
        if metres >= target * 0.55:
            return metres
    return 1.0


def paint_paper_axes(
    painter, left, top, right, bottom,
    xmin, xmax, ymin, ymax,
    h_axis, v_axis, h_label, v_label, dpi,
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
    v_step, v_ticks = _ticks(ymin, ymax, v_axis, ph)
    grid_w = max(1.0, mm_to_px(0.12, dpi))
    axis_w = max(1.2, mm_to_px(0.32, dpi))
    tick_w = max(1.0, mm_to_px(0.22, dpi))
    tick_len = mm_to_px(1.6, dpi)

    painter.setRenderHint(QPainter.Antialiasing, True)
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
            Qt.AlignHCenter | Qt.AlignTop,
            _fmt(tick, h_step, h_axis),
        )
    for tick in v_ticks:
        y = sy(tick)
        if y < top - 2 or y > bottom + 2:
            continue
        painter.drawText(
            QRectF(left - mm_to_px(17, dpi), y - lab_h / 2.0,
                   mm_to_px(15.2, dpi), lab_h),
            Qt.AlignRight | Qt.AlignVCenter,
            _fmt(tick, v_step, v_axis),
        )

    font.setPixelSize(pt_to_px(9, dpi))
    painter.setFont(font)
    painter.setPen(TITLE_PAPER)
    painter.drawText(
        QRectF(left, bottom + mm_to_px(6.2, dpi), pw, mm_to_px(5, dpi)),
        Qt.AlignHCenter | Qt.AlignTop,
        '%s (m)' % h_label,
    )
    painter.save()
    painter.translate(left - mm_to_px(14.5, dpi), (top + bottom) / 2.0)
    painter.rotate(-90)
    painter.drawText(
        QRectF(-mm_to_px(24, dpi), -mm_to_px(4, dpi), mm_to_px(48, dpi), mm_to_px(5, dpi)),
        Qt.AlignCenter,
        '%s (m)' % v_label,
    )
    painter.restore()

    bar_m = _scale_bar_metres(dx if _is_planar(h_axis) else dy)
    bar_px = bar_m / dx * pw
    if bar_px >= mm_to_px(8, dpi):
        bx = left
        by = bottom + mm_to_px(12.5, dpi)
        bh = mm_to_px(2.0, dpi)
        painter.setPen(QPen(AXIS_PAPER, max(1.0, mm_to_px(0.22, dpi))))
        painter.setBrush(AXIS_PAPER)
        painter.drawRect(QRectF(bx, by, bar_px, bh))
        font.setPixelSize(pt_to_px(7, dpi))
        painter.setFont(font)
        painter.setPen(LABEL_PAPER)
        painter.setBrush(Qt.NoBrush)
        label = ('%g m' % bar_m) if bar_m >= 1 else ('%g cm' % (bar_m * 100))
        painter.drawText(
            QRectF(bx, by + bh + mm_to_px(0.4, dpi), max(bar_px, mm_to_px(18, dpi)), lab_h),
            Qt.AlignLeft | Qt.AlignTop,
            label,
        )


def paint_paper_legend(painter, items, field, x, top, bottom, dpi, ink):
    if not items and not field:
        return
    max_w = mm_to_px(22, dpi)
    row_h = mm_to_px(3.6, dpi)
    font = QFont()
    font.setPixelSize(pt_to_px(7, dpi))
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(ink)
    heading = field or 'Groups'
    painter.drawText(
        QRectF(x, top, max_w, row_h),
        Qt.AlignLeft | Qt.AlignVCenter,
        heading,
    )
    ly = top + row_h + mm_to_px(0.8, dpi)
    font.setBold(False)
    painter.setFont(font)
    r = max(1.4, mm_to_px(1.1, dpi))
    room = max(1, int((bottom - ly) / row_h))
    shown = items[:room]
    extra = len(items) - len(shown)
    if extra > 0 and shown:
        shown = shown[:-1]
        extra = len(items) - len(shown)
    for name, color in shown:
        cy = ly + row_h / 2.0
        painter.setPen(QPen(QColor(20, 20, 20, 160), max(0.6, mm_to_px(0.12, dpi))))
        painter.setBrush(color)
        painter.drawEllipse(QPoint(int(round(x + r + 1)), int(round(cy))), int(round(r)), int(round(r)))
        painter.setPen(ink)
        painter.setBrush(Qt.NoBrush)
        painter.drawText(
            QRectF(x + r * 2 + mm_to_px(1.6, dpi), ly, max_w - r * 2, row_h),
            Qt.AlignLeft | Qt.AlignVCenter,
            name,
        )
        ly += row_h
    if extra > 0:
        painter.setPen(TITLE_PAPER)
        painter.drawText(
            QRectF(x, ly, max_w, row_h),
            Qt.AlignLeft | Qt.AlignVCenter,
            '+%d more' % extra,
        )


class AxesGridOverlay(QWidget):
    def __init__(self, canvas, h_axis, v_axis, h_label, v_label, parent=None):
        super().__init__(parent)
        self.canvas = canvas
        self.h_axis = h_axis
        self.v_axis = v_axis
        self.h_label = h_label
        self.v_label = v_label
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)
        self.setStyleSheet('background: transparent;')
        self.setCursor(Qt.OpenHandCursor)
        self._paper = False
        self._paper_bg = QColor('#ffffff')
        canvas.extentsChanged.connect(self.update)
        try:
            canvas.scaleChanged.connect(lambda _s: self.update())
        except Exception:
            pass
        try:
            canvas.mapCanvasRefreshed.connect(self.update)
        except Exception:
            pass

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
        if event.button() not in (Qt.LeftButton, Qt.MiddleButton):
            event.ignore()
            return
        canvas = self.canvas
        if canvas is None or not hasattr(canvas, 'pan_start'):
            event.ignore()
            return
        pos = event.position() if hasattr(event, 'position') else event.pos()
        canvas.pan_start(pos.x(), pos.y())
        self.setCursor(Qt.ClosedHandCursor)
        event.accept()

    def mouseMoveEvent(self, event):
        canvas = self.canvas
        if canvas is None or getattr(canvas, '_pan_last', None) is None:
            event.ignore()
            return
        pos = event.position() if hasattr(event, 'position') else event.pos()
        canvas.pan_move(pos.x(), pos.y())
        event.accept()

    def mouseReleaseEvent(self, event):
        canvas = self.canvas
        if canvas is not None and hasattr(canvas, 'pan_end'):
            canvas.pan_end()
        self.setCursor(Qt.OpenHandCursor)
        event.accept()

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
        title = ''
        if hasattr(renderer, 'classAttribute'):
            title = (renderer.classAttribute() or '').strip()
        cmap = {}
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
            sym = cat.symbol()
            if sym is not None:
                try:
                    color = QColor(sym.color())
                except Exception:
                    pass
            cmap[label] = color
            order.append(label)
        if title:
            idx = layer.fields().lookupField(title)
            if idx >= 0:
                try:
                    present = set(group_label(v) for v in layer.uniqueValues(idx))
                except Exception:
                    present = None
                if present is not None:
                    order = [k for k in order if k in present]
        return [(key, cmap[key]) for key in order], title

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
        v_step, v_ticks = _ticks(ymin, ymax, self.v_axis, bottom - top)

        def sx(map_x):
            return xform.transform(QgsPointXY(map_x, ymin)).x()

        def sy(map_y):
            return xform.transform(QgsPointXY(xmin, map_y)).y()

        if self._paper:
            grid, axis, label, title = GRID_LIGHT, AXIS_LIGHT, LABEL_LIGHT, TITLE_LIGHT
            margin = self._paper_bg if self._paper_bg is not None else QColor('#ffffff')
        else:
            grid, axis, label, title = GRID, AXIS, LABEL, TITLE
            margin = SCREEN_BG

        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(Qt.NoPen)
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
                Qt.AlignHCenter | Qt.AlignTop,
                _fmt(tick, h_step, self.h_axis),
            )
        for tick in v_ticks:
            y = sy(tick)
            if y < top - 4 or y > bottom + 4:
                continue
            p.drawText(
                QRectF(28, y - 8, left - 36, 16),
                Qt.AlignRight | Qt.AlignVCenter,
                _fmt(tick, v_step, self.v_axis),
            )

        p.setPen(title)
        p.drawText(
            QRectF(left, bottom + 30, right - left, 18),
            Qt.AlignHCenter | Qt.AlignTop,
            '%s (m)' % self.h_label,
        )
        p.save()
        p.translate(max(12.0, left - 54.0), (top + bottom) / 2.0)
        p.rotate(-90)
        p.drawText(
            QRectF(-80, -10, 160, 20),
            Qt.AlignCenter,
            '%s (m)' % self.v_label,
        )
        p.restore()

    def paint_export_legend(self, p, plot_right, top, bottom):
        if self._paper:
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
        heading = field or 'Groups'
        metrics = p.fontMetrics()
        p.drawText(
            QRectF(lx, ly, max_w, 10),
            Qt.AlignLeft | Qt.AlignVCenter,
            metrics.elidedText(heading, Qt.ElideRight, max_w),
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
        for name, color in shown:
            cy = ly + row_h / 2.0
            p.setPen(QPen(QColor(20, 20, 20, 140), 0.6))
            p.setBrush(color)
            p.drawEllipse(QPoint(int(round(lx + 3)), int(round(cy))), 2, 2)
            p.setPen(ink)
            p.drawText(
                QRectF(lx + 8, ly, max_w - 8, row_h),
                Qt.AlignLeft | Qt.AlignVCenter,
                metrics.elidedText(name, Qt.ElideRight, max_w - 8),
            )
            ly += row_h
        if extra > 0:
            p.setPen(heading_color)
            p.drawText(
                QRectF(lx, ly, max_w, row_h),
                Qt.AlignLeft | Qt.AlignVCenter,
                '+%d more' % extra,
            )
