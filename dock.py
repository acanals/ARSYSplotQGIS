# -*- coding: utf-8 -*-
"""Lite-style workspace: plan / longitudinal / transversal + filters."""
import os

from qgis.core import (
    QgsMapRendererCustomPainterJob,
    QgsPointXY,
    QgsRectangle,
    QgsWkbTypes,
)
from qgis.gui import QgsMapCanvas
from qgis.PyQt.QtCore import QPoint, QRect, QSize, Qt, QTimer
from qgis.PyQt.QtGui import QBrush, QColor, QIcon, QImage, QPainter, QPen, QFont
from qgis.PyQt.QtWidgets import (
    QAbstractButton,
    QAbstractSpinBox,
    QButtonGroup,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QGridLayout,
    QMainWindow,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from . import density as D
from . import export_dialog as E
from . import importer
from . import layers as L
from . import view3d
from .colors_util import css_hex
from .axes_grid import (
    PAD_B,
    PAD_L,
    PAD_R,
    PAD_T,
    AxesGridOverlay,
    paint_paper_axes,
    paint_paper_legend,
    snap_world_rect,
)
from .crs_util import align_project_to_layer

DARK = '#161411'
INK = '#fff5e6'
TOOLTIP_CSS = (
    'QToolTip { background-color:#fff8ee; color:#1a1816;'
    '  border:1px solid #8a8178; padding:5px 8px; }'
)
COMPACT_BTN_CSS = (
    'QPushButton { background:#2a2520; color:%s; border:1px solid #3a342e;'
    '  border-radius:6px; font-size:10px; padding:2px 4px; }'
    'QPushButton:hover { background:#3a342e; }'
    'QPushButton:disabled { color:#6b645c; }'
    'QPushButton:checked { background:#d97726; border-color:#f0a15a; }'
    % INK
)


def _tune_clip_spin(spn):
    """Same +/- chrome as Radius/Cell; smaller digits so Min/Max fit one row."""
    spn.setButtonSymbols(QAbstractSpinBox.UpDownArrows)
    spn.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    spn.setMinimumWidth(70)
    spn.setMinimumHeight(26)
    spn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    line = spn.lineEdit()
    if line is not None:
        line.setStyleSheet(
            'QLineEdit { font-size:10px; padding:0px; border:none; background:transparent; }'
        )


class ToggleSwitch(QAbstractButton):
    """On/off switch visible on the dark plugin chrome."""

    TRACK_W = 42
    TRACK_H = 22

    def __init__(self, text='', parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setText(text)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.setFocusPolicy(Qt.TabFocus)

    def sizeHint(self):
        fm = self.fontMetrics()
        try:
            tw = fm.horizontalAdvance(self.text())
        except AttributeError:
            tw = fm.width(self.text())
        return QSize(tw + self.TRACK_W + 16, max(28, self.TRACK_H + 6))

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = self.contentsRect()
        tw, th = self.TRACK_W, self.TRACK_H
        track = QRect(r.right() - tw, r.y() + (r.height() - th) // 2, tw, th)
        text_w = max(0, track.x() - r.x() - 10)
        p.setPen(QColor(INK if self.isEnabled() else '#6b645c'))
        p.drawText(
            QRect(r.x(), r.y(), text_w, r.height()),
            Qt.AlignVCenter | Qt.AlignLeft,
            self.text(),
        )
        on = self.isChecked()
        if on:
            p.setBrush(QBrush(QColor('#d97726')))
            p.setPen(QPen(QColor('#f0a15a'), 1))
        else:
            p.setBrush(QBrush(QColor('#3a342e')))
            p.setPen(QPen(QColor('#8a8178'), 1))
        p.drawRoundedRect(track, th / 2.0, th / 2.0)
        kd = th - 6
        kx = track.right() - 3 - kd if on else track.x() + 3
        ky = track.y() + 3
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor('#fffdf8')))
        p.drawEllipse(kx, ky, kd, kd)


PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))


def _icon_button(filename, tooltip):
    btn = QPushButton()
    btn.setIcon(QIcon(os.path.join(PLUGIN_DIR, filename)))
    btn.setIconSize(QSize(14, 14))
    btn.setFixedSize(24, 22)
    btn.setCursor(Qt.PointingHandCursor)
    btn.setToolTip(tooltip)
    return btn


def _suggest_png(title):
    base = title.split('·')[0].strip().replace(' ', '_')
    keep = []
    for ch in base:
        keep.append(ch if ch.isalnum() or ch in '-_' else '_')
    name = ''.join(keep).strip('_') or 'view'
    return name + '.png'


def _mouse_x(event):
    if hasattr(event, 'position'):
        return event.position().x()
    return event.pos().x()


class DualRangeBar(QWidget):
    """One track, two handles (min / max), Lite-style XYZ filter."""

    PAD = 8

    def __init__(self, callback):
        super().__init__()
        self._cb = callback
        self._a = 0
        self._b = 1000
        self._drag = None
        self.setMinimumHeight(22)
        self.setMinimumWidth(80)
        self.setCursor(Qt.PointingHandCursor)

    def span(self):
        return self._a, self._b

    def set_span(self, a, b):
        self._a = max(0, min(1000, int(a)))
        self._b = max(self._a, min(1000, int(b)))
        self.update()

    def _t_to_x(self, t):
        w = max(self.width() - 2 * self.PAD, 1)
        return self.PAD + (t / 1000.0) * w

    def _x_to_t(self, x):
        w = max(self.width() - 2 * self.PAD, 1)
        t = (float(x) - self.PAD) / w * 1000.0
        return max(0, min(1000, int(round(t))))

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        cy = self.height() // 2
        x0 = self.PAD
        x1 = self.width() - self.PAD
        gy = cy - 3
        p.setPen(Qt.NoPen)
        p.setBrush(QColor('#2a2520'))
        p.drawRoundedRect(QRect(x0, gy, max(x1 - x0, 1), 6), 3, 3)
        xa = int(round(self._t_to_x(self._a)))
        xb = int(round(self._t_to_x(self._b)))
        p.setBrush(QColor('#d97726'))
        p.drawRoundedRect(QRect(xa, gy, max(xb - xa, 2), 6), 3, 3)
        p.setPen(QPen(QColor('#1c1916'), 1))
        p.setBrush(QColor('#fff5e6'))
        p.drawEllipse(QPoint(xa, cy), 6, 6)
        p.drawEllipse(QPoint(xb, cy), 6, 6)

    def mousePressEvent(self, event):
        x = _mouse_x(event)
        xa = self._t_to_x(self._a)
        xb = self._t_to_x(self._b)
        self._drag = 'a' if abs(x - xa) <= abs(x - xb) else 'b'
        self._move(x)

    def mouseMoveEvent(self, event):
        if self._drag:
            self._move(_mouse_x(event))

    def mouseReleaseEvent(self, _event):
        self._drag = None

    def _move(self, x):
        t = self._x_to_t(x)
        if self._drag == 'a':
            self._a = min(t, self._b)
        elif self._drag == 'b':
            self._b = max(t, self._a)
        self.update()
        self._cb()


class RangeSliders(QWidget):
    def __init__(self, axis, callback):
        super().__init__()
        self.axis = axis
        self._cb = callback
        self._lo = 0.0
        self._hi = 1.0
        self._block = False
        lab = QLabel(axis.upper())
        lab.setStyleSheet('color:%s;font-weight:700;' % INK)
        lab.setFixedWidth(16)
        self.v0 = QLabel('—')
        self.v1 = QLabel('—')
        self.v0.setMinimumWidth(52)
        self.v1.setMinimumWidth(52)
        self.bar = DualRangeBar(self._changed)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addWidget(lab)
        row.addWidget(self.v0)
        row.addWidget(self.bar, 1)
        row.addWidget(self.v1)
        self.v0.setStyleSheet('color:%s;' % INK)
        self.v1.setStyleSheet('color:%s;' % INK)

    def set_bounds(self, lo, hi):
        self._block = True
        self._lo, self._hi = float(lo), float(hi)
        self.bar.set_span(0, 1000)
        self._block = False
        self._sync_labels()

    def values(self):
        t0, t1 = self.bar.span()
        span = self._hi - self._lo
        a = self._lo + (t0 / 1000.0) * span
        b = self._lo + (t1 / 1000.0) * span
        return (a, b) if a <= b else (b, a)

    def reset(self, notify=True):
        self._block = True
        self.bar.set_span(0, 1000)
        self._block = False
        self._sync_labels()
        if notify:
            self._cb()

    def _changed(self):
        self._sync_labels()
        if not self._block:
            self._cb()

    def _sync_labels(self):
        a, b = self.values()
        self.v0.setText('%.3f' % a)
        self.v1.setText('%.3f' % b)


class PlotCanvas(QgsMapCanvas):
    """Wheel-zoom around the axis-frame centre; fit keeps the cloud in that frame."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data_ext = None
        self._user_view = False
        self._fitting = False
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.timeout.connect(self._refit_if_needed)
        self.extentsChanged.connect(self._on_extents)
        self._pan_last = None
        if hasattr(self, 'setLabelsVisible'):
            try:
                self.setLabelsVisible(True)
            except Exception:
                pass
        nothing = getattr(QgsMapCanvas, 'WheelNothing', None)
        if nothing is not None and hasattr(self, 'setWheelAction'):
            try:
                self.setWheelAction(nothing)
            except Exception:
                pass

    def fit_data_extent(self, ext):
        if ext is None or ext.isEmpty():
            return
        self._data_ext = QgsRectangle(ext)
        self._user_view = False
        self._apply_fit()

    def _on_extents(self):
        if not self._fitting:
            self._user_view = True

    def _refit_if_needed(self):
        if not self._user_view and self._data_ext is not None:
            self._apply_fit()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self._user_view and self._data_ext is not None:
            self._resize_timer.start(40)

    def _axis_frame_px(self):
        overlay = getattr(self, '_overlay', None)
        if overlay is not None and hasattr(overlay, 'pads'):
            pad_l, pad_r, pad_t, pad_b = overlay.pads()
        else:
            pad_l, pad_r, pad_t, pad_b = PAD_L, PAD_R, PAD_T, PAD_B
        w = max(self.width(), 1)
        h = max(self.height(), 1)
        inner_w = max(w - pad_l - pad_r, 1)
        inner_h = max(h - pad_t - pad_b, 1)
        return pad_l + inner_w / 2.0, pad_t + inner_h / 2.0, w, h, inner_w, inner_h

    def zoom_by_wheel(self, delta):
        """Scale around the axis-frame centre. Axes stay pinned to the pane."""
        if not delta:
            return
        steps = max(-3.0, min(3.0, float(delta) / 120.0))
        factor = 0.88 ** steps
        ext = QgsRectangle(self.extent())
        if ext.isEmpty():
            return
        icx, icy, w, h, inner_w, inner_h = self._axis_frame_px()
        try:
            mupp = float(self.mapUnitsPerPixel())
        except Exception:
            mupp = 0.0
        if mupp <= 0:
            mupp = ext.width() / float(max(w, 1))
        new_mupp = mupp * factor
        if self._data_ext is not None and not self._data_ext.isEmpty():
            ref = max(
                self._data_ext.width() / float(inner_w),
                self._data_ext.height() / float(inner_h),
                1e-9,
            )
            new_mupp = max(ref * 0.04, min(ref * 25.0, new_mupp))
        else:
            new_mupp = max(1e-6, min(1.0e4, new_mupp))
        factor = new_mupp / mupp if mupp > 0 else factor
        xform = self.getCoordinateTransform()
        if xform is None:
            return
        anchor = xform.toMapCoordinates(int(round(icx)), int(round(icy)))
        self._user_view = True
        self._fitting = True
        try:
            center = QgsPointXY(anchor.x(), anchor.y())
            if hasattr(self, 'zoomByFactor'):
                self.zoomByFactor(factor, center)
            else:
                self.setExtent(QgsRectangle(
                    anchor.x() - icx * new_mupp,
                    anchor.y() - (h - icy) * new_mupp,
                    anchor.x() + (w - icx) * new_mupp,
                    anchor.y() + icy * new_mupp,
                ))
            xform2 = self.getCoordinateTransform()
            if xform2 is not None:
                now = xform2.toMapCoordinates(int(round(icx)), int(round(icy)))
                dx = now.x() - anchor.x()
                dy = now.y() - anchor.y()
                if abs(dx) > 1e-9 or abs(dy) > 1e-9:
                    cur = QgsRectangle(self.extent())
                    self.setExtent(QgsRectangle(
                        cur.xMinimum() - dx,
                        cur.yMinimum() - dy,
                        cur.xMaximum() - dx,
                        cur.yMaximum() - dy,
                    ))
            self.refresh()
        finally:
            self._fitting = False

    def pan_start(self, x, y):
        self._pan_last = (float(x), float(y))
        self._user_view = True

    def pan_move(self, x, y):
        if self._pan_last is None:
            return
        dx = float(x) - self._pan_last[0]
        dy = float(y) - self._pan_last[1]
        self._pan_last = (float(x), float(y))
        self._pan_by(dx, dy)

    def pan_end(self):
        self._pan_last = None

    def _pan_by(self, dx, dy):
        if dx == 0 and dy == 0:
            return
        try:
            mupp = float(self.mapUnitsPerPixel())
        except Exception:
            mupp = 0.0
        if mupp <= 0:
            return
        ext = QgsRectangle(self.extent())
        if ext.isEmpty():
            return
        self._fitting = True
        try:
            self.setExtent(QgsRectangle(
                ext.xMinimum() - dx * mupp,
                ext.yMinimum() + dy * mupp,
                ext.xMaximum() - dx * mupp,
                ext.yMaximum() + dy * mupp,
            ))
            self.refresh()
        finally:
            self._fitting = False

    def _apply_fit(self):
        data = QgsRectangle(self._data_ext)
        overlay = getattr(self, '_overlay', None)
        if data.width() <= 0 or data.height() <= 0:
            data.grow(0.5)
        w = self.width()
        h = self.height()
        if overlay is not None and hasattr(overlay, 'pads'):
            pad_l, pad_r, pad_t, pad_b = overlay.pads()
        else:
            pad_l, pad_r, pad_t, pad_b = PAD_L, PAD_R, PAD_T, PAD_B
        inner_w = w - pad_l - pad_r
        inner_h = h - pad_t - pad_b
        self._fitting = True
        try:
            if inner_w < 20 or inner_h < 20:
                self.setExtent(data)
            else:
                mupp = max(
                    data.width() / float(inner_w),
                    data.height() / float(inner_h),
                    1e-9,
                )
                full_w = mupp * w
                full_h = mupp * h
                dc = data.center()
                icx = pad_l + inner_w / 2.0
                icy = pad_t + inner_h / 2.0
                mcx = dc.x() - (icx - w / 2.0) * mupp
                mcy = dc.y() + (icy - h / 2.0) * mupp
                rect = QgsRectangle(
                    mcx - full_w / 2.0,
                    mcy - full_h / 2.0,
                    mcx + full_w / 2.0,
                    mcy + full_h / 2.0,
                )
                try:
                    self.setExtent(rect, False)
                except TypeError:
                    self.setExtent(rect)
            self.refresh()
        finally:
            self._fitting = False
            self._user_view = False

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta == 0:
            delta = event.pixelDelta().y()
        if delta:
            self.zoom_by_wheel(delta)
        event.accept()


class PlotPane(QWidget):
    def __init__(self, title, h_axis, v_axis, h_label, v_label, on_zoom=None):
        super().__init__()
        self.title = title
        self.h_axis = h_axis
        self.v_axis = v_axis
        self.h_label = h_label
        self.v_label = v_label
        self._on_zoom = on_zoom
        self.canvas = PlotCanvas(self)
        self.canvas.setCanvasColor(QColor(DARK))
        self.canvas.enableAntiAliasing(True)
        self.canvas.setMinimumHeight(160)
        self.wrap = QWidget()
        stack = QGridLayout(self.wrap)
        stack.setContentsMargins(0, 0, 0, 0)
        stack.setSpacing(0)
        stack.addWidget(self.canvas, 0, 0)
        self.overlay = AxesGridOverlay(
            self.canvas, h_axis, v_axis, h_label, v_label, self.wrap
        )
        self.canvas._overlay = self.overlay
        stack.addWidget(self.overlay, 0, 0)
        lab = QLabel(title)
        lab.setStyleSheet(
            'color:rgba(255,245,230,0.55);font-size:11px;letter-spacing:0.04em;'
        )
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.addWidget(lab, 1)
        self.btn_export = _icon_button(
            'export.svg', 'Export this view as PNG (with axes)'
        )
        self.btn_export.setEnabled(False)
        self.btn_export.clicked.connect(self.export_image)
        head.addWidget(self.btn_export)
        self.btn_zoom = _icon_button(
            'zoom.svg', 'Zoom: open this view in a large window'
        )
        self.btn_zoom.setEnabled(False)
        self.btn_zoom.clicked.connect(self._emit_zoom)
        if on_zoom is None:
            self.btn_export.hide()
            self.btn_zoom.hide()
        head.addWidget(self.btn_zoom)
        box = QVBoxLayout(self)
        box.setContentsMargins(6, 4, 6, 6)
        box.setSpacing(2)
        box.addLayout(head)
        box.addWidget(self.wrap, 1)
        self.setStyleSheet('background:%s; %s' % (DARK, TOOLTIP_CSS))

    def _emit_zoom(self):
        if self._on_zoom:
            self._on_zoom(self)

    def export_image(self):
        if self.wrap.width() < 20 or self.wrap.height() < 20:
            QMessageBox.warning(self, 'Export', 'The view is too small to export.')
            return
        layer_name = ''
        layers = self.canvas.layers()
        if layers:
            layer_name = layers[0].name()
        dlg = E.ExportImageDialog(
            self, title=self.title, subtitle=layer_name, bg=QColor('#ffffff')
        )
        exec_fn = getattr(dlg, 'exec', None) or dlg.exec_
        if exec_fn() != dlg.Accepted:
            return
        opts = dlg.values()
        path, _flt = QFileDialog.getSaveFileName(
            self, 'Export image', _suggest_png(opts['title'] or self.title),
            'PNG (*.png)'
        )
        if not path:
            return
        if not path.lower().endswith('.png'):
            path += '.png'
        img = self._render_export(opts)
        if img is None or img.isNull() or not img.save(path, 'PNG'):
            QMessageBox.warning(self, 'Export', 'Could not write %s' % path)
            return
        win = self.window()
        iface = getattr(win, 'iface', None)
        if iface is None and win is not None:
            iface = getattr(win.parent(), 'iface', None) if win.parent() else None
        if iface is not None:
            iface.messageBar().pushInfo(
                'ARSYSplotQGIS', 'Saved %s' % os.path.basename(path)
            )

    def _export_world_rect(self):
        """World box of the labelled plot (data hug), not the letterboxed pane."""
        overlay = self.overlay
        canvas = self.canvas
        data = overlay._data_rect() if overlay is not None else None
        h_axis = getattr(overlay, 'h_axis', 'x')
        v_axis = getattr(overlay, 'v_axis', 'y')
        if data is not None and not data.isEmpty():
            return snap_world_rect(
                data.xMinimum(), data.xMaximum(),
                data.yMinimum(), data.yMaximum(),
                h_axis, v_axis,
            )
        xform = canvas.getCoordinateTransform()
        if overlay is not None and xform is not None:
            frame = overlay._plot_frame(xform, overlay.width(), overlay.height())
            if frame is not None:
                _l, _r, _t, _b, xmin, xmax, ymin, ymax = frame
                return xmin, xmax, ymin, ymax
        ext = canvas.extent()
        if ext is None or ext.isEmpty():
            return None
        return ext.xMinimum(), ext.xMaximum(), ext.yMinimum(), ext.yMaximum()

    def _render_export(self, opts):
        bg = opts['bg']
        dpi = max(72, int(opts['dpi']))
        world = self._export_world_rect()
        if world is None:
            return None
        xmin, xmax, ymin, ymax = world
        data_w = max(xmax - xmin, 1e-6)
        data_h = max(ymax - ymin, 1e-6)
        title = (opts.get('title') or '').strip()
        subtitle = (opts.get('subtitle') or '').strip()
        ink = QColor('#1a1816') if E.is_light_color(bg) else QColor('#fff5e6')

        layers = [lyr for lyr in (self.canvas.layers() or []) if lyr is not None]
        raster = None
        for lyr in layers:
            if lyr.customProperty('arsysplotqgis') == 'density-raster':
                raster = lyr
                break
        bar = D.heatmap_legend(raster) if raster is not None else None
        groups, group_field = self.overlay._legend_entries()
        show_groups = bool(groups)

        margin = 10.0
        pad_l, pad_r, pad_t, pad_b = 18.0, 7.0, 5.0, 22.0
        extra_r = 0.0
        if bar is not None:
            extra_r += 26.0
        if show_groups:
            extra_r += 24.0
        head_mm = 0.0
        if title:
            head_mm += 8.0
        if subtitle:
            head_mm += 5.5
        if head_mm:
            head_mm += 3.0

        long_mm = 175.0
        if data_w >= data_h:
            inner_w_mm = long_mm
            inner_h_mm = long_mm * (data_h / data_w)
        else:
            inner_h_mm = long_mm
            inner_w_mm = long_mm * (data_w / data_h)
        inner_w_mm = max(inner_w_mm, 28.0)
        inner_h_mm = max(inner_h_mm, 28.0)
        plot_w = max(1, int(round(E.mm_to_px(inner_w_mm, dpi))))
        plot_h = max(1, int(round(E.mm_to_px(inner_h_mm, dpi))))
        left = int(round(E.mm_to_px(margin + pad_l, dpi)))
        top = int(round(E.mm_to_px(margin + head_mm + pad_t, dpi)))
        right = left + plot_w
        bottom = top + plot_h
        cx = 0.5 * (xmin + xmax)
        cy = 0.5 * (ymin + ymax)
        need_h = data_w * (plot_h / float(plot_w))
        if need_h >= data_h:
            ymin, ymax = cy - need_h / 2.0, cy + need_h / 2.0
        else:
            need_w = data_h * (plot_w / float(plot_h))
            xmin, xmax = cx - need_w / 2.0, cx + need_w / 2.0

        out_w = int(round(E.mm_to_px(margin * 2 + pad_r + extra_r, dpi))) + right
        out_h = int(round(E.mm_to_px(margin + pad_b, dpi))) + bottom
        img = QImage(out_w, out_h, QImage.Format_ARGB32)
        E.apply_png_dpi(img, dpi)
        img.fill(bg)

        painter = QPainter(img)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        try:
            y = E.mm_to_px(margin, dpi)
            if title:
                font = QFont()
                font.setPixelSize(E.pt_to_px(13, dpi))
                font.setBold(True)
                painter.setFont(font)
                painter.setPen(ink)
                painter.drawText(
                    QRect(
                        int(E.mm_to_px(margin, dpi)), int(y),
                        out_w - int(E.mm_to_px(margin * 2, dpi)),
                        int(E.mm_to_px(7.5, dpi)),
                    ),
                    Qt.AlignLeft | Qt.AlignVCenter,
                    title,
                )
                y += E.mm_to_px(8.0, dpi)
            if subtitle:
                font = QFont()
                font.setPixelSize(E.pt_to_px(9, dpi))
                painter.setFont(font)
                painter.setPen(QColor('#5a554e') if E.is_light_color(bg) else ink)
                painter.drawText(
                    QRect(
                        int(E.mm_to_px(margin, dpi)), int(y),
                        out_w - int(E.mm_to_px(margin * 2, dpi)),
                        int(E.mm_to_px(5.2, dpi)),
                    ),
                    Qt.AlignLeft | Qt.AlignVCenter,
                    subtitle,
                )

            settings = self.canvas.mapSettings()
            settings.setOutputSize(QSize(plot_w, plot_h))
            settings.setOutputDpi(float(dpi))
            settings.setBackgroundColor(bg)
            settings.setExtent(QgsRectangle(xmin, ymin, xmax, ymax))
            try:
                from qgis.core import Qgis
                flags = getattr(Qgis, 'MapSettingsFlag', None)
                if flags is not None:
                    for name in (
                        'Antialiasing', 'HighQualityImageTransforms',
                        'DrawLabeling', 'UseAdvancedEffects',
                    ):
                        flag = getattr(flags, name, None)
                        if flag is not None:
                            settings.setFlag(flag, True)
            except Exception:
                pass
            bumped = []
            try:
                for lyr in layers:
                    try:
                        filt = lyr.resampleFilter()
                    except Exception:
                        filt = None
                    if filt is None or not hasattr(filt, 'setMaxOversampling'):
                        continue
                    try:
                        bumped.append((filt, filt.maxOversampling()))
                        filt.setMaxOversampling(8.0)
                    except Exception:
                        pass
                painter.save()
                painter.translate(left, top)
                painter.setClipRect(QRect(0, 0, plot_w, plot_h))
                try:
                    job = QgsMapRendererCustomPainterJob(settings, painter)
                    job.start()
                    job.waitForFinished()
                except Exception:
                    self.canvas.render(painter)
                painter.restore()
            finally:
                for filt, old in bumped:
                    try:
                        filt.setMaxOversampling(old)
                    except Exception:
                        pass

            paint_paper_axes(
                painter, left, top, right, bottom,
                xmin, xmax, ymin, ymax,
                self.h_axis, self.v_axis, self.h_label, self.v_label, dpi,
            )
            side_x = right + E.mm_to_px(4.5, dpi)
            if bar is not None:
                vmin, vmax, colors = bar
                used = D.paint_colorbar(
                    painter, side_x, top, bottom, vmin, vmax, colors, dpi, ink
                )
                side_x += used + E.mm_to_px(3.0, dpi)
            if show_groups:
                paint_paper_legend(
                    painter, groups, group_field, side_x, top, bottom, dpi, ink
                )
        finally:
            painter.end()
        return img

    def show_layer(self, layer, adaptive=False, fit_from=None):
        if isinstance(layer, (list, tuple)):
            layers = [lyr for lyr in layer if lyr is not None]
        else:
            layers = [layer] if layer is not None else []
        enabled = bool(layers)
        if hasattr(self, 'btn_zoom'):
            self.btn_zoom.setEnabled(enabled)
        if hasattr(self, 'btn_export'):
            self.btn_export.setEnabled(enabled)
        if not layers:
            self.canvas.setLayers([])
            self.canvas.refresh()
            self.overlay.update()
            return
        self.canvas.setDestinationCrs(layers[0].crs())
        self.canvas.setLayers(list(layers))
        if adaptive or self.canvas.extent().isEmpty():
            srcs = fit_from
            if srcs is None:
                srcs = layers
            elif not isinstance(srcs, (list, tuple)):
                srcs = [srcs]
            ext = L.padded_data_extent(srcs)
            if ext is None or ext.isEmpty():
                ext = L.union_extent(layers)
            if ext is not None and not ext.isEmpty():
                self.canvas.fit_data_extent(ext)
        self.canvas.refresh()
        self.overlay.update()


class ZoomWindow(QMainWindow):
    def __init__(self, pane, layer, parent=None):
        super().__init__(parent)
        self._force_close = False
        self._layer = layer
        self.setWindowTitle('ARSYSplotQGIS · Zoom · %s' % pane.title)
        self.setWindowFlag(Qt.Window, True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.resize(1100, 800)
        self.setMinimumSize(520, 400)
        self.setStyleSheet(
            'QMainWindow { background:#1c1916; }'
            'QWidget { background:#1c1916; color:#fff5e6; }'
            'QPushButton { background:#2a2520; color:#fff5e6; border:1px solid #3a342e;'
            '  border-radius:6px; padding:4px 10px; }'
            'QPushButton:hover { background:#3a342e; }'
            + TOOLTIP_CSS
        )
        bar = QHBoxLayout()
        hint = QLabel('Wheel zoom · drag pan · Esc closes')
        hint.setStyleSheet('color:rgba(255,245,230,0.55);')
        bar.addWidget(hint, 1)
        fit = QPushButton('Fit')
        fit.clicked.connect(self._fit)
        export_btn = QPushButton('Export PNG')
        export_btn.setToolTip('Export this view as PNG (with axes)')
        export_btn.clicked.connect(lambda: self.pane.export_image())
        close_btn = QPushButton('Close')
        close_btn.clicked.connect(self.close)
        bar.addWidget(fit)
        bar.addWidget(export_btn)
        bar.addWidget(close_btn)
        self.pane = PlotPane(
            pane.title, pane.h_axis, pane.v_axis, pane.h_label, pane.v_label
        )
        root = QWidget()
        col = QVBoxLayout(root)
        col.setContentsMargins(8, 8, 8, 8)
        col.addLayout(bar)
        col.addWidget(self.pane, 1)
        self.setCentralWidget(root)
        self.reload(layer, pane.canvas)

    def reload(self, layer, source_canvas=None):
        self._layer = layer
        self.pane.show_layer(layer, adaptive=False)
        if source_canvas is not None:
            QTimer.singleShot(60, lambda sc=source_canvas: self._clone_view(sc))

    def _clone_view(self, source_canvas):
        try:
            ext = source_canvas.extent()
        except Exception:
            return
        if ext is None or ext.isEmpty():
            if self._layer is not None:
                self.pane.show_layer(self._layer, adaptive=True)
            return
        dst = self.pane.canvas
        dst._data_ext = QgsRectangle(source_canvas._data_ext) if source_canvas._data_ext else QgsRectangle(ext)
        dst._user_view = True
        dst._fitting = True
        try:
            dst.setExtent(QgsRectangle(ext))
            dst.refresh()
            self.pane.overlay.update()
        finally:
            dst._fitting = False

    def _fit(self):
        ext = getattr(self.pane.canvas, '_data_ext', None)
        if ext is None or ext.isEmpty():
            ext = L.padded_data_extent(self.pane.canvas.layers())
        if ext is None or ext.isEmpty():
            ext = L.union_extent(self.pane.canvas.layers())
        if ext is not None and not ext.isEmpty():
            self.pane.canvas.fit_data_extent(ext)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        if self._force_close:
            event.accept()
            return
        event.ignore()
        self.hide()


class ARSYSDock(QMainWindow):
    def __init__(self, iface):
        super().__init__(iface.mainWindow())
        self.iface = iface
        self.source = None
        self.line_layer = None
        self.long_layer = None
        self.trans_layer = None
        self.long_line_layer = None
        self.trans_line_layer = None
        self.display_mode = 'points'
        self._user_picked_draw = False
        self.group_field = 'group'
        self.active_groups = set()
        self.colors = {}
        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.timeout.connect(self._apply_filters_now)
        self._building = False
        self._force_close = False
        self.point_size = 2.2
        self.arrow_size = L.ARROW_MM_DEFAULT
        self.density_on = False
        self.density_mode = 'heatmap'
        self.density_fill = 'bands'
        self._density = {'plan': (None, None), 'long': (None, None), 'trans': (None, None)}
        self._density_timer = QTimer(self)
        self._density_timer.setSingleShot(True)
        self._density_timer.timeout.connect(self._rebuild_density)
        self._stretch_timer = QTimer(self)
        self._stretch_timer.setSingleShot(True)
        self._stretch_timer.timeout.connect(self._apply_density_stretch)
        self._dens_stretch_user = False
        self._zoom_windows = {}

        self.setWindowTitle('ARSYSplotQGIS')
        self.setObjectName('ARSYSplotQGISWindow')
        for name in ('ArcheIcon.png', 'icon.png', 'icon.svg'):
            path = os.path.join(PLUGIN_DIR, name)
            if os.path.isfile(path):
                self.setWindowIcon(QIcon(path))
                break
        self.setWindowFlag(Qt.Window, True)
        self.resize(1280, 840)
        self.setMinimumSize(720, 520)

        spin_up = os.path.join(PLUGIN_DIR, 'spin_up.svg').replace('\\', '/')
        spin_down = os.path.join(PLUGIN_DIR, 'spin_down.svg').replace('\\', '/')
        root = QWidget()
        root.setStyleSheet(
            'QWidget { background:#1c1916; color:%s; font-size:12px; }'
            'QPushButton { background:#2a2520; color:%s; border:1px solid #3a342e;'
            '  border-radius:6px; padding:4px 8px; }'
            'QPushButton:hover { background:#3a342e; }'
            'QPushButton:disabled { color:#6b645c; }'
            'QComboBox { background:#2a2520; color:%s; border:1px solid #3a342e; padding:2px; }'
            'QDoubleSpinBox, QSpinBox { background:#2a2520; color:%s; border:1px solid #3a342e;'
            '  padding:2px 18px 2px 4px; }'
            'QDoubleSpinBox::up-button, QSpinBox::up-button,'
            'QDoubleSpinBox::down-button, QSpinBox::down-button {'
            '  subcontrol-origin: border; width:16px; background:#4a443c;'
            '  border:none; }'
            'QDoubleSpinBox::up-button, QSpinBox::up-button {'
            '  subcontrol-position: top right; }'
            'QDoubleSpinBox::down-button, QSpinBox::down-button {'
            '  subcontrol-position: bottom right; }'
            'QDoubleSpinBox::up-button:hover, QSpinBox::up-button:hover,'
            'QDoubleSpinBox::down-button:hover, QSpinBox::down-button:hover {'
            '  background:#d97726; }'
            'QDoubleSpinBox::up-arrow, QSpinBox::up-arrow {'
            '  image: url("%s"); width:8px; height:5px; }'
            'QDoubleSpinBox::down-arrow, QSpinBox::down-arrow {'
            '  image: url("%s"); width:8px; height:5px; }'
            'QPushButton:checked { background:#d97726; border-color:#f0a15a; }'
            'QGroupBox { border:1px solid #3a342e; border-radius:6px; margin-top:10px; }'
            'QGroupBox::title { subcontrol-origin: margin; left:8px; padding:0 4px; }'
            'QScrollArea { border: none; }'
            'QSlider::groove:horizontal { background:#2a2520; height:6px; border-radius:3px; }'
            'QSlider::handle:horizontal { background:#d97726; width:12px; margin:-4px 0;'
            '  border-radius:6px; }'
            'QToolTip { background-color:#fff8ee; color:#1a1816;'
            '  border:1px solid #8a8178; padding:5px 8px; }'
            % (INK, INK, INK, INK, spin_up, spin_down)
        )
        split = QSplitter(Qt.Horizontal)
        split.addWidget(self._make_side())
        split.addWidget(self._make_stage())
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([280, 900])
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(split)
        self.setCentralWidget(root)

    def closeEvent(self, event):
        if self._force_close:
            for win in list(getattr(self, '_zoom_windows', {}).values()):
                try:
                    win._force_close = True
                    win.close()
                except Exception:
                    pass
            self._drop_plugin_layers()
            event.accept()
            return
        event.ignore()
        self.hide()

    def showEvent(self, event):
        super().showEvent(event)
        if self.source:
            QTimer.singleShot(0, self._refresh_canvases)

    def _make_side(self):
        side = QWidget()
        side.setMinimumWidth(240)
        col = QVBoxLayout(side)
        title = QLabel('ARSYSplot<strong>QGIS</strong>')
        title.setTextFormat(Qt.RichText)
        title.setStyleSheet('font-size:16px;')
        col.addWidget(title)

        self.lbl_file = QLabel('No layer')
        self.lbl_count = QLabel('0 / 0 points')
        col.addWidget(self.lbl_file)
        col.addWidget(self.lbl_count)

        self.btn_import = QPushButton('Import CSV')
        self.btn_import.clicked.connect(self.import_csv)
        self.btn_sample = QPushButton('Load sample')
        self.btn_sample.setToolTip('Load the bundled sample.csv (no need to browse).')
        self.btn_sample.clicked.connect(self.load_sample)
        self.btn_use = QPushButton('Use selected layer')
        self.btn_use.clicked.connect(self.use_selected_layer)
        col.addWidget(self.btn_import)
        col.addWidget(self.btn_sample)
        col.addWidget(self.btn_use)

        gbox = QGroupBox('Group')
        gcol = QVBoxLayout(gbox)
        self.cmb_group = QComboBox()
        self.cmb_group.currentTextChanged.connect(self._on_group_field)
        row = QHBoxLayout()
        self.btn_all = QPushButton('All')
        self.btn_none = QPushButton('None')
        self.btn_all.clicked.connect(lambda: self._set_all_groups(True))
        self.btn_none.clicked.connect(lambda: self._set_all_groups(False))
        row.addWidget(self.btn_all)
        row.addWidget(self.btn_none)
        self.group_wrap = QWidget()
        self.group_layout = QGridLayout(self.group_wrap)
        self.group_layout.setContentsMargins(0, 0, 0, 0)
        self.group_layout.setHorizontalSpacing(3)
        self.group_layout.setVerticalSpacing(2)
        self.group_layout.setColumnStretch(0, 1)
        self.group_layout.setColumnStretch(1, 1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.group_wrap)
        scroll.setMinimumHeight(120)
        gcol.addWidget(QLabel('Field'))
        gcol.addWidget(self.cmb_group)
        gcol.addLayout(row)
        gcol.addWidget(scroll, 1)
        col.addWidget(gbox, 1)

        opt = QGroupBox('Options')
        ocol = QVBoxLayout(opt)
        self.chk_adaptive = ToggleSwitch('Adaptive frame')
        self.chk_adaptive.setToolTip(
            'Off: keep full extent. On: zoom canvases to the filtered cloud.'
        )
        self.chk_adaptive.toggled.connect(self._refresh_canvases)
        ocol.addWidget(self.chk_adaptive)
        size_row = QHBoxLayout()
        size_row.addWidget(QLabel('Point size'))
        self.sld_size = QSlider(Qt.Horizontal)
        self.sld_size.setRange(8, 80)
        self.sld_size.setSingleStep(1)
        self.sld_size.setPageStep(5)
        self.sld_size.setValue(22)
        self.sld_size.setTracking(True)
        self.sld_size.valueChanged.connect(self._on_point_size)
        self.lbl_size = QLabel('2.2')
        self.lbl_size.setMinimumWidth(28)
        size_row.addWidget(self.sld_size, 1)
        size_row.addWidget(self.lbl_size)
        ocol.addLayout(size_row)
        arrow_row = QHBoxLayout()
        arrow_row.addWidget(QLabel('Arrow size'))
        self.sld_arrow = QSlider(Qt.Horizontal)
        self.sld_arrow.setRange(0, L.ARROW_SLIDER_MAX)
        self.sld_arrow.setSingleStep(1)
        self.sld_arrow.setPageStep(5)
        self.sld_arrow.setValue(L.arrow_slider_from_mm(L.ARROW_MM_DEFAULT))
        self.sld_arrow.setTracking(True)
        self.sld_arrow.setEnabled(False)
        self.sld_arrow.setToolTip(
            'Vector arrow head. Fine control at small sizes; the top of the scale stays modest.'
        )
        self.sld_arrow.valueChanged.connect(self._on_arrow_size)
        self.lbl_arrow = QLabel('%.2f' % L.ARROW_MM_DEFAULT)
        self.lbl_arrow.setMinimumWidth(36)
        arrow_row.addWidget(self.sld_arrow, 1)
        arrow_row.addWidget(self.lbl_arrow)
        ocol.addLayout(arrow_row)
        draw_row = QHBoxLayout()
        draw_row.setSpacing(3)
        draw_row.addWidget(QLabel('Draw'))
        self.btn_draw_points = QPushButton('Points')
        self.btn_draw_vectors = QPushButton('Vectors')
        self.btn_draw_both = QPushButton('Both')
        self.btn_draw_none = QPushButton('None')
        self._draw_group = QButtonGroup(self)
        self._draw_group.setExclusive(True)
        for btn in (
            self.btn_draw_points, self.btn_draw_vectors,
            self.btn_draw_both, self.btn_draw_none,
        ):
            btn.setCheckable(True)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            btn.setStyleSheet(COMPACT_BTN_CSS)
            self._draw_group.addButton(btn)
        self.btn_draw_points.setChecked(True)
        self.btn_draw_points.setToolTip('P1: object centre.')
        self.btn_draw_vectors.setToolTip('P2→P3 (or P1→P2 if P3 is missing).')
        self.btn_draw_both.setToolTip('Centre point and axis of each object.')
        self.btn_draw_none.setToolTip(
            'Hide points and vectors so the density surface is fully visible.'
        )
        self.btn_draw_vectors.setEnabled(False)
        self.btn_draw_both.setEnabled(False)
        self.btn_draw_points.clicked.connect(lambda: self._set_draw_mode('points'))
        self.btn_draw_vectors.clicked.connect(lambda: self._set_draw_mode('vectors'))
        self.btn_draw_both.clicked.connect(lambda: self._set_draw_mode('both'))
        self.btn_draw_none.clicked.connect(lambda: self._set_draw_mode('none'))
        draw_row.addWidget(self.btn_draw_points)
        draw_row.addWidget(self.btn_draw_vectors)
        draw_row.addWidget(self.btn_draw_both)
        draw_row.addWidget(self.btn_draw_none)
        ocol.addLayout(draw_row)

        dens_box = QGroupBox('Density')
        dcol = QVBoxLayout(dens_box)
        self.chk_density = ToggleSwitch('On')
        self.chk_density.setToolTip(
            'Kernel density of the filtered points: heatmap and/or isolines. '
            'Stays inside the plugin (not on the QGIS map). Use Draw → None to see it alone.'
        )
        self.chk_density.toggled.connect(self._on_density_toggled)
        self.chk_density.setEnabled(False)
        dcol.addWidget(self.chk_density)
        dens_mode = QHBoxLayout()
        dens_mode.setSpacing(3)
        dens_mode.addWidget(QLabel('Show'))
        self.btn_dens_heat = QPushButton('Heatmap')
        self.btn_dens_iso = QPushButton('Isolines')
        self.btn_dens_both = QPushButton('Both')
        self._dens_mode_group = QButtonGroup(self)
        self._dens_mode_group.setExclusive(True)
        for btn, mode in (
            (self.btn_dens_heat, 'heatmap'),
            (self.btn_dens_iso, 'contours'),
            (self.btn_dens_both, 'both'),
        ):
            btn.setCheckable(True)
            btn.setEnabled(False)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            btn.setStyleSheet(COMPACT_BTN_CSS)
            self._dens_mode_group.addButton(btn)
            btn.clicked.connect(lambda _on, m=mode: self._set_density_mode(m))
            dens_mode.addWidget(btn)
        self.btn_dens_heat.setChecked(True)
        self.btn_dens_heat.setToolTip('Filled density surface (Cloud or Bands).')
        self.btn_dens_iso.setToolTip('Contour lines of the density surface.')
        self.btn_dens_both.setToolTip('Heatmap with isolines on top.')
        dcol.addLayout(dens_mode)
        fill_row = QHBoxLayout()
        fill_row.setSpacing(3)
        fill_row.addWidget(QLabel('Fill'))
        self.btn_dens_cloud = QPushButton('Cloud')
        self.btn_dens_bands = QPushButton('Bands')
        self._dens_fill_group = QButtonGroup(self)
        self._dens_fill_group.setExclusive(True)
        for btn, fill in (
            (self.btn_dens_cloud, 'cloud'),
            (self.btn_dens_bands, 'bands'),
        ):
            btn.setCheckable(True)
            btn.setEnabled(False)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            btn.setStyleSheet(COMPACT_BTN_CSS)
            self._dens_fill_group.addButton(btn)
            btn.clicked.connect(lambda _on, f=fill: self._set_density_fill(f))
            fill_row.addWidget(btn)
        self.btn_dens_bands.setChecked(True)
        self.btn_dens_cloud.setToolTip(
            'Continuous interpolated colour (smooth cloud). Same KDE, different paint.'
        )
        self.btn_dens_bands.setToolTip(
            'Discrete hypsometric bands. Class breaks match the isolines.'
        )
        dcol.addLayout(fill_row)
        pal_row = QHBoxLayout()
        pal_row.addWidget(QLabel('Colour'))
        self.cmb_dens_scheme = QComboBox()
        self.cmb_dens_scheme.setIconSize(QSize(72, 14))
        for sid, label, _stops in D.COLOR_SCHEMES:
            self.cmb_dens_scheme.addItem(D.scheme_icon(sid), label, sid)
        idx = self.cmb_dens_scheme.findData(D.DEFAULT_SCHEME)
        if idx >= 0:
            self.cmb_dens_scheme.setCurrentIndex(idx)
        self.cmb_dens_scheme.setEnabled(False)
        self.cmb_dens_scheme.setToolTip(
            'Colour model of the density surface (heatmap and isolines).'
        )
        self.cmb_dens_scheme.currentIndexChanged.connect(self._on_density_scheme)
        pal_row.addWidget(self.cmb_dens_scheme, 1)
        dcol.addLayout(pal_row)
        rng_row = QHBoxLayout()
        rng_row.setSpacing(4)
        lbl_min = QLabel('Min')
        lbl_max = QLabel('Max')
        for lab in (lbl_min, lbl_max):
            lab.setStyleSheet('font-size:10px;')
            lab.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        rng_row.addWidget(lbl_min)
        self.spn_dens_min = QDoubleSpinBox()
        self.spn_dens_min.setDecimals(4)
        self.spn_dens_min.setRange(0.0, 1.0e9)
        self.spn_dens_min.setSingleStep(0.1)
        self.spn_dens_min.setValue(0.0)
        self.spn_dens_min.setEnabled(False)
        _tune_clip_spin(self.spn_dens_min)
        self.spn_dens_min.setToolTip(
            'Lower bound of the colour stretch (real KDE values). '
            'Values below Min are not drawn (QGIS clip + additional no-data).'
        )
        self.spn_dens_min.valueChanged.connect(self._on_density_clip)
        rng_row.addWidget(self.spn_dens_min, 1)
        rng_row.addWidget(lbl_max)
        self.spn_dens_max = QDoubleSpinBox()
        self.spn_dens_max.setDecimals(4)
        self.spn_dens_max.setRange(0.0, 1.0e9)
        self.spn_dens_max.setSingleStep(0.1)
        self.spn_dens_max.setValue(1.0)
        self.spn_dens_max.setEnabled(False)
        _tune_clip_spin(self.spn_dens_max)
        self.spn_dens_max.setToolTip(
            'Upper bound of the colour stretch. Defaults to the raster maximum.'
        )
        self.spn_dens_max.valueChanged.connect(self._on_density_clip)
        rng_row.addWidget(self.spn_dens_max, 1)
        self.btn_dens_cut = QPushButton('Auto')
        self.btn_dens_cut.setStyleSheet(COMPACT_BTN_CSS)
        self.btn_dens_cut.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.btn_dens_cut.setEnabled(False)
        self.btn_dens_cut.setToolTip(
            'QGIS cumulative count cut: Min = 2% of positive cells, Max = raster maximum.'
        )
        self.btn_dens_cut.clicked.connect(self._auto_density_stretch)
        rng_row.addWidget(self.btn_dens_cut)
        dcol.addLayout(rng_row)
        rad_row = QHBoxLayout()
        rad_row.addWidget(QLabel('Radius'))
        self.spn_dens_radius = QDoubleSpinBox()
        self.spn_dens_radius.setDecimals(2)
        self.spn_dens_radius.setRange(0.05, 80.0)
        self.spn_dens_radius.setSingleStep(0.05)
        self.spn_dens_radius.setValue(0.50)
        self.spn_dens_radius.setSuffix(' m')
        self.spn_dens_radius.setEnabled(False)
        self.spn_dens_radius.setToolTip(
            'Kernel bandwidth in map units. Larger = smoother, broader concentrations.'
        )
        self.spn_dens_radius.valueChanged.connect(self._schedule_density)
        rad_row.addWidget(self.spn_dens_radius, 1)
        self.btn_dens_auto = QPushButton('Auto')
        self.btn_dens_auto.setEnabled(False)
        self.btn_dens_auto.setToolTip('Set radius and cell from the current filtered extent.')
        self.btn_dens_auto.clicked.connect(lambda: self._auto_density_params(True))
        rad_row.addWidget(self.btn_dens_auto)
        dcol.addLayout(rad_row)
        cell_row = QHBoxLayout()
        cell_row.addWidget(QLabel('Cell'))
        self.spn_dens_cell = QDoubleSpinBox()
        self.spn_dens_cell.setDecimals(3)
        self.spn_dens_cell.setRange(0.005, 20.0)
        self.spn_dens_cell.setSingleStep(0.01)
        self.spn_dens_cell.setValue(0.05)
        self.spn_dens_cell.setSuffix(' m')
        self.spn_dens_cell.setEnabled(False)
        self.spn_dens_cell.setToolTip(
            'Raster cell size used to compute the surface. Display is interpolated '
            '(smooth density cloud). Smaller = slower to rebuild.'
        )
        self.spn_dens_cell.valueChanged.connect(self._schedule_density)
        cell_row.addWidget(self.spn_dens_cell, 1)
        dcol.addLayout(cell_row)
        ker_row = QHBoxLayout()
        ker_row.addWidget(QLabel('Kernel'))
        self.cmb_dens_kernel = QComboBox()
        for label, val in D.KERNELS:
            self.cmb_dens_kernel.addItem(label, val)
        self.cmb_dens_kernel.setEnabled(False)
        self.cmb_dens_kernel.setToolTip(
            'QGIS KDE shape: Quartic, Triangular, Uniform, Triweight, Epanechnikov.'
        )
        self.cmb_dens_kernel.currentIndexChanged.connect(self._schedule_density)
        ker_row.addWidget(self.cmb_dens_kernel, 1)
        dcol.addLayout(ker_row)
        iso_row = QHBoxLayout()
        iso_row.addWidget(QLabel('Isolines'))
        self.spn_dens_levels = QSpinBox()
        self.spn_dens_levels.setRange(3, 16)
        self.spn_dens_levels.setValue(8)
        self.spn_dens_levels.setEnabled(False)
        self.spn_dens_levels.setToolTip('Number of contour intervals on the density surface.')
        self.spn_dens_levels.valueChanged.connect(self._schedule_density_stretch)
        iso_row.addWidget(self.spn_dens_levels, 1)
        self.chk_dens_labels = ToggleSwitch('Labels')
        self.chk_dens_labels.setEnabled(False)
        self.chk_dens_labels.setToolTip(
            'Write density values on the isolines.'
        )
        self.chk_dens_labels.toggled.connect(self._on_density_labels)
        iso_row.addWidget(self.chk_dens_labels)
        dcol.addLayout(iso_row)
        op_row = QHBoxLayout()
        op_row.addWidget(QLabel('Opacity'))
        self.sld_dens_op = QSlider(Qt.Horizontal)
        self.sld_dens_op.setRange(20, 100)
        self.sld_dens_op.setValue(70)
        self.sld_dens_op.setEnabled(False)
        self.sld_dens_op.setToolTip(
            'Fill opacity of the density surface. 100% is a solid colour '
            '(empty cells stay clear). Lower values make a translucent cloud.'
        )
        self.sld_dens_op.valueChanged.connect(self._on_density_opacity)
        self.lbl_dens_op = QLabel('70%')
        self.lbl_dens_op.setMinimumWidth(36)
        op_row.addWidget(self.sld_dens_op, 1)
        op_row.addWidget(self.lbl_dens_op)
        dcol.addLayout(op_row)
        ocol.addWidget(dens_box)

        self.btn_reset = QPushButton('Reset')
        self.btn_reset.setToolTip(
            'Restore groups, XYZ range, point size, arrow size, zoom and frame to the initial view.'
        )
        self.btn_reset.clicked.connect(self.reset_view)
        self.btn_reset.setEnabled(False)
        ocol.addWidget(self.btn_reset)
        col.addWidget(opt)

        self.btn_3d = QPushButton('Open 3D view')
        self.btn_3d.clicked.connect(self.open_3d)
        self.btn_3d.setEnabled(False)
        col.addWidget(self.btn_3d)
        col.addStretch(0)
        return side

    def _make_stage(self):
        stage = QWidget()
        grid = QGridLayout(stage)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(1)
        self.plan = PlotPane('Plan · X / Y', 'x', 'y', 'X', 'Y', on_zoom=self._open_zoom)
        self.longp = PlotPane('Longitudinal · X / Z', 'x', 'z', 'X', 'Z', on_zoom=self._open_zoom)
        self.transp = PlotPane('Transversal · Y / Z', 'y', 'z', 'Y', 'Z', on_zoom=self._open_zoom)
        filters = QWidget()
        filters.setStyleSheet('background:%s;' % DARK)
        fl = QVBoxLayout(filters)
        lab = QLabel('Filters · X Y Z')
        lab.setStyleSheet('color:rgba(255,245,230,0.55);')
        fl.addWidget(lab)
        self.rng_x = RangeSliders('x', self.schedule_filter)
        self.rng_y = RangeSliders('y', self.schedule_filter)
        self.rng_z = RangeSliders('z', self.schedule_filter)
        fl.addWidget(self.rng_x)
        fl.addWidget(self.rng_y)
        fl.addWidget(self.rng_z)
        btn_reset = QPushButton('Reset')
        btn_reset.setToolTip('Restore groups, XYZ range, point size, zoom and frame.')
        btn_reset.clicked.connect(self.reset_view)
        fl.addWidget(btn_reset)
        fl.addStretch(1)
        grid.addWidget(self.plan, 0, 0)
        grid.addWidget(self.longp, 0, 1)
        grid.addWidget(self.transp, 1, 0)
        grid.addWidget(filters, 1, 1)
        grid.setRowStretch(0, 1)
        grid.setRowStretch(1, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        return stage

    def schedule_filter(self):
        self._filter_timer.start(120)

    def import_csv(self):
        dlg = importer.ImportCsvDialog(self)
        exec_fn = getattr(dlg, 'exec', None) or dlg.exec_
        if exec_fn() != dlg.Accepted:
            return
        mapping = dlg.result_mapping()
        if not mapping:
            return
        try:
            layer, skipped = importer.build_pointz_layer(
                mapping['path'], mapping['x'], mapping['y'], mapping['z'],
                mapping['group'],
                p2x_field=mapping.get('p2x') or '',
                p2y_field=mapping.get('p2y') or '',
                p2z_field=mapping.get('p2z') or '',
                p3x_field=mapping.get('p3x') or '',
                p3y_field=mapping.get('p3y') or '',
                p3z_field=mapping.get('p3z') or '',
            )
        except Exception as exc:
            QMessageBox.warning(self, 'Import', str(exc))
            return
        self._attach_source(layer, os.path.basename(mapping['path']))
        extra = ' (%d rows skipped)' % skipped if skipped else ''
        self.iface.messageBar().pushInfo('ARSYSplotQGIS', 'Loaded %d points%s.' % (
            layer.featureCount(), extra
        ))

    def load_sample(self):
        path = importer.SAMPLE_CSV
        if not os.path.isfile(path):
            QMessageBox.warning(
                self, 'Sample',
                'sample.csv was not found in the plugin folder.'
            )
            return
        try:
            layer, skipped = importer.build_pointz_layer(
                path, 'p1x', 'p1y', 'p1z', 'material'
            )
        except Exception as exc:
            QMessageBox.warning(self, 'Sample', str(exc))
            return
        self._attach_source(layer, 'sample.csv')
        extra = ' (%d rows skipped)' % skipped if skipped else ''
        self.iface.messageBar().pushInfo(
            'ARSYSplotQGIS', 'Loaded sample: %d points%s.' % (
                layer.featureCount(), extra
            )
        )

    def use_selected_layer(self):
        layer = self.iface.activeLayer()
        if layer is None or not hasattr(layer, 'wkbType'):
            QMessageBox.warning(self, 'Layer', 'Select a vector point layer.')
            return
        if QgsWkbTypes.geometryType(layer.wkbType()) != QgsWkbTypes.PointGeometry:
            QMessageBox.warning(self, 'Layer', 'Need a point layer.')
            return
        names = [f.name() for f in layer.fields()]
        if 'p1x' not in names or 'p1y' not in names:
            QMessageBox.information(
                self, 'Layer',
                'This layer has no p1x/p1y/p1z fields. Sections still use the '
                'geometry; XYZ sliders need those fields (import a CSV).'
            )
        self._attach_source(layer, layer.name())

    def _drop_plugin_layers(self, keep_source=None):
        self._drop_density_layers()
        for lyr in (
            self.long_layer, self.trans_layer,
            self.line_layer, self.long_line_layer, self.trans_line_layer,
        ):
            L.release_private(lyr)
        src = self.source
        if (
            src is not None
            and src is not keep_source
            and src.customProperty('arsysplotqgis') == 'source'
        ):
            L.release_private(src)
        self.long_layer = None
        self.trans_layer = None
        self.line_layer = None
        self.long_line_layer = None
        self.trans_line_layer = None

    def _attach_source(self, layer, label):
        self._drop_plugin_layers(keep_source=layer)
        L.clear_plugin_legend()
        self.source = layer
        if layer.customProperty('arsysplotqgis') == 'source':
            L.keep_private(layer)
        align_project_to_layer(layer)
        self.group_field = 'group' if layer.fields().lookupField('group') >= 0 else layer.fields()[0].name()
        self.long_layer = L.make_section_layer(layer.name() + ' · XZ', layer.crs(), layer.fields())
        self.trans_layer = L.make_section_layer(layer.name() + ' · YZ', layer.crs(), layer.fields())
        self.line_layer = L.make_line_layer(layer.name() + ' · vec', layer.crs(), layer.fields())
        self.long_line_layer = L.make_section_line_layer(
            layer.name() + ' · XZ vec', layer.crs(), layer.fields()
        )
        self.trans_line_layer = L.make_section_line_layer(
            layer.name() + ' · YZ vec', layer.crs(), layer.fields()
        )
        for lyr in (
            self.long_layer, self.trans_layer,
            self.line_layer, self.long_line_layer, self.trans_line_layer,
        ):
            L.keep_private(lyr)
        self.display_mode = 'points'
        self._user_picked_draw = False
        self.btn_draw_points.setChecked(True)
        self.lbl_file.setText(label)
        self.btn_3d.setEnabled(True)
        self.btn_reset.setEnabled(True)
        self.chk_density.setEnabled(True)
        self._fill_group_combo()
        self._reset_range_bounds()
        self._rebuild_group_buttons()
        self._set_all_groups(True)
        self._apply_filters_now()
        self.plan.show_layer(
            self._pane_layers(self.plan), adaptive=True,
            fit_from=self._pane_fit_layers(self.plan),
        )
        self.longp.show_layer(
            self._pane_layers(self.longp), adaptive=True,
            fit_from=self._pane_fit_layers(self.longp),
        )
        self.transp.show_layer(
            self._pane_layers(self.transp), adaptive=True,
            fit_from=self._pane_fit_layers(self.transp),
        )

    def _fill_group_combo(self):
        self.cmb_group.blockSignals(True)
        self.cmb_group.clear()
        for f in self.source.fields():
            self.cmb_group.addItem(f.name())
        idx = self.cmb_group.findText(self.group_field)
        if idx >= 0:
            self.cmb_group.setCurrentIndex(idx)
        self.cmb_group.blockSignals(False)

    def _on_group_field(self, name):
        if not self.source or not name:
            return
        self.group_field = name
        self._rebuild_group_buttons()
        self._set_all_groups(True)
        if self.line_layer is not None:
            L.style_lines_by_group(
                self.line_layer, self.group_field,
                width=self._line_width(), head=self.arrow_size, cmap=self.colors,
            )
            L.copy_renderer(self.line_layer, self.long_line_layer)
            L.copy_renderer(self.line_layer, self.trans_line_layer)
        self.schedule_filter()

    def _rebuild_group_buttons(self):
        while self.group_layout.count():
            item = self.group_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        for r in range(self.group_layout.rowCount()):
            self.group_layout.setRowStretch(r, 0)
        if not self.source:
            return
        values = L.unique_groups(self.source, self.group_field)
        self.colors = L.style_by_group(
            self.source, self.group_field, size=self.point_size, values=values,
        )
        self._group_btns = {}
        for i, val in enumerate(values):
            btn = QPushButton(val)
            btn.setCheckable(True)
            btn.setChecked(True)
            btn.setToolTip(val)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            color = self.colors.get(val, QColor('#888'))
            hexcol = css_hex(color)
            btn.setStyleSheet(
                'QPushButton { background:%s; color:#fff; text-align:left;'
                '  font-size:10px; padding:1px 4px; border-radius:3px;'
                '  min-height:16px; max-height:18px; }'
                'QPushButton:checked { background:%s; }'
                'QPushButton:!checked { background:#5a554e; color:#c8c2b8; }'
                % (hexcol, hexcol)
            )
            btn.toggled.connect(lambda _on, v=val: self._toggle_group(v))
            self.group_layout.addWidget(btn, i // 2, i % 2)
            self._group_btns[val] = btn
        rows = (len(values) + 1) // 2
        if rows:
            self.group_layout.setRowStretch(rows, 1)
        self.active_groups = set(values)

    def _toggle_group(self, val):
        btn = self._group_btns.get(val)
        if btn is None:
            return
        if btn.isChecked():
            self.active_groups.add(val)
        else:
            self.active_groups.discard(val)
        self.schedule_filter()

    def _set_all_groups(self, on):
        if not getattr(self, '_group_btns', None):
            return
        for val, btn in self._group_btns.items():
            btn.blockSignals(True)
            btn.setChecked(on)
            btn.blockSignals(False)
        self.active_groups = set(self._group_btns) if on else set()
        self.schedule_filter()

    def _reset_range_bounds(self):
        if not self.source:
            return
        ext = L.xyz_extent(self.source)
        self.rng_x.set_bounds(*ext['x'])
        self.rng_y.set_bounds(*ext['y'])
        self.rng_z.set_bounds(*ext['z'])

    def reset_ranges(self):
        self.rng_x.reset(notify=False)
        self.rng_y.reset(notify=False)
        self.rng_z.reset(notify=False)

    def reset_view(self):
        if not self.source:
            return
        self._filter_timer.stop()
        self.chk_adaptive.blockSignals(True)
        self.chk_adaptive.setChecked(False)
        self.chk_adaptive.blockSignals(False)
        self.sld_size.blockSignals(True)
        self.sld_size.setValue(22)
        self.sld_size.blockSignals(False)
        self.point_size = 2.2
        self.lbl_size.setText('2.2')
        self.sld_arrow.blockSignals(True)
        self.sld_arrow.setValue(L.arrow_slider_from_mm(L.ARROW_MM_DEFAULT))
        self.sld_arrow.blockSignals(False)
        self.arrow_size = L.ARROW_MM_DEFAULT
        self.lbl_arrow.setText('%.2f' % self.arrow_size)
        self._user_picked_draw = False
        if getattr(self, '_group_btns', None):
            for btn in self._group_btns.values():
                btn.blockSignals(True)
                btn.setChecked(True)
                btn.blockSignals(False)
            self.active_groups = set(self._group_btns)
        self.reset_ranges()
        L.style_by_group(
            self.source, self.group_field, size=self.point_size,
            cmap=self.colors,
            values=list(self._group_btns) if getattr(self, '_group_btns', None) else None,
        )
        self._apply_filters_now()
        for pane in (self.plan, self.longp, self.transp):
            ext = L.padded_data_extent(self._pane_fit_layers(pane))
            if ext is not None and not ext.isEmpty():
                pane.canvas.fit_data_extent(ext)
        for win in list(getattr(self, '_zoom_windows', {}).values()):
            try:
                if win.isVisible() and win._layer is not None:
                    win._fit()
            except Exception:
                pass
        for dlg in list(getattr(self.iface, '_arsysplotqgis_3d', [])):
            try:
                if dlg.isVisible():
                    dlg.reload(
                        self.group_field, keep_camera=False,
                        display_mode=self._draw_mode_for_3d(),
                        arrow_size=self.arrow_size,
                    )
            except Exception:
                pass

    def _apply_filters_now(self):
        if not self.source:
            return
        ranges = {
            'x': self.rng_x.values(),
            'y': self.rng_y.values(),
            'z': self.rng_z.values(),
        }
        groups = self.active_groups
        if not getattr(self, '_group_btns', None):
            groups = None
        L.apply_subset(self.source, groups, ranges, self.group_field)
        if getattr(self, '_group_btns', None) and self.colors:
            L.style_by_group(
                self.source, self.group_field, size=self.point_size,
                cmap=self.colors, values=list(self._group_btns),
            )
        L.rebuild_section(self.source, self.long_layer, 'long')
        L.rebuild_section(self.source, self.trans_layer, 'trans')
        L.copy_renderer(self.source, self.long_layer)
        L.copy_renderer(self.source, self.trans_layer)
        nvec = L.rebuild_vectors(self.source, self.line_layer)
        L.rebuild_section_lines(self.source, self.long_line_layer, 'long')
        L.rebuild_section_lines(self.source, self.trans_line_layer, 'trans')
        L.style_lines_by_group(
            self.line_layer, self.group_field,
            width=self._line_width(),
            head=self.arrow_size,
            values=list(self._group_btns) if getattr(self, '_group_btns', None) else None,
            cmap=self.colors,
        )
        L.copy_renderer(self.line_layer, self.long_line_layer)
        L.copy_renderer(self.line_layer, self.trans_line_layer)
        self._sync_draw_buttons()
        vis = self.source.featureCount()
        total = self.source.dataProvider().featureCount()
        self.lbl_count.setText('%d / %d points · %d vectors' % (vis, total, nvec))
        if self.density_on:
            self._rebuild_density(refresh=False)
        self._refresh_canvases()
        view3d.refresh_open_views(
            self.iface, self.source, self.group_field,
            display_mode=self._draw_mode_for_3d(),
            arrow_size=self.arrow_size,
        )

    def _on_point_size(self, value):
        self.point_size = int(value) / 10.0
        self.lbl_size.setText('%.1f' % self.point_size)
        if self.source is None:
            return
        L.apply_marker_size(self.source, self.point_size)
        L.apply_marker_size(self.long_layer, self.point_size)
        L.apply_marker_size(self.trans_layer, self.point_size)
        width = self._line_width()
        L.apply_line_width(self.line_layer, width)
        L.apply_line_width(self.long_line_layer, width)
        L.apply_line_width(self.trans_line_layer, width)
        self.plan.canvas.refresh()
        self.longp.canvas.refresh()
        self.transp.canvas.refresh()
        self._refresh_zooms()

    def _on_arrow_size(self, value):
        self.arrow_size = L.arrow_mm_from_slider(value)
        self.lbl_arrow.setText('%.2f' % self.arrow_size)
        if self.line_layer is None:
            return
        L.apply_arrow_size(self.line_layer, self.arrow_size)
        L.apply_arrow_size(self.long_line_layer, self.arrow_size)
        L.apply_arrow_size(self.trans_line_layer, self.arrow_size)
        self.plan.canvas.refresh()
        self.longp.canvas.refresh()
        self.transp.canvas.refresh()
        self._refresh_zooms()
        view3d.apply_open_arrow_size(self.iface, self.arrow_size)

    def _density_widgets(self):
        return (
            self.btn_dens_heat, self.btn_dens_iso, self.btn_dens_both,
            self.btn_dens_cloud, self.btn_dens_bands,
            self.spn_dens_radius, self.btn_dens_auto, self.spn_dens_cell,
            self.cmb_dens_kernel, self.cmb_dens_scheme,
            self.spn_dens_min, self.spn_dens_max, self.btn_dens_cut,
            self.spn_dens_levels, self.chk_dens_labels, self.sld_dens_op,
        )

    def _sync_density_controls(self):
        on = bool(self.density_on and self.source is not None)
        for w in self._density_widgets():
            w.setEnabled(on)
        if on:
            iso_on = self.density_mode in ('contours', 'both')
            self.spn_dens_levels.setEnabled(iso_on)
            self.chk_dens_labels.setEnabled(iso_on)
            self.sld_dens_op.setEnabled(self.density_mode in ('heatmap', 'both'))
            fill_on = self.density_mode in ('heatmap', 'both')
            self.btn_dens_cloud.setEnabled(fill_on)
            self.btn_dens_bands.setEnabled(fill_on)
            self.cmb_dens_scheme.setEnabled(True)

    def _on_density_toggled(self, on):
        self.density_on = bool(on)
        self._select_draw_mode('none' if self.density_on else 'points')
        if self.density_on and self.source is not None:
            self._auto_density_params(rebuild=False)
        self._sync_density_controls()
        if self.density_on:
            self._rebuild_density()
        else:
            self._drop_density_layers()
            self._refresh_canvases()
        view3d.refresh_open_views(
            self.iface, self.source, self.group_field,
            display_mode=self._draw_mode_for_3d(),
            arrow_size=self.arrow_size,
        )

    def _set_density_mode(self, mode):
        self.density_mode = mode
        self._sync_density_controls()
        if self.density_on:
            self._rebuild_density()

    def _set_density_fill(self, fill):
        self.density_fill = 'cloud' if fill == 'cloud' else 'bands'
        if self.density_on:
            self._apply_density_stretch()

    def _schedule_density(self, *_args):
        if not self.density_on:
            return
        # New KDE (kernel / radius / cell) → Min/Max must follow the new raster.
        self._dens_stretch_user = False
        self._density_timer.start(280)

    def _auto_density_params(self, rebuild=True):
        if self.source is None:
            return
        radius, pixel = D.suggest_params(self.source)
        self.spn_dens_radius.blockSignals(True)
        self.spn_dens_cell.blockSignals(True)
        self.spn_dens_radius.setValue(radius)
        self.spn_dens_cell.setValue(pixel)
        self.spn_dens_radius.blockSignals(False)
        self.spn_dens_cell.blockSignals(False)
        if rebuild and self.density_on:
            self._rebuild_density()

    def _density_scheme(self):
        sid = self.cmb_dens_scheme.currentData()
        return sid if sid else D.DEFAULT_SCHEME

    def _density_clip(self):
        return float(self.spn_dens_min.value()), float(self.spn_dens_max.value())

    def _on_density_clip(self, *_args):
        self._dens_stretch_user = True
        mn = self.spn_dens_min.value()
        mx = self.spn_dens_max.value()
        if mx <= mn:
            self.spn_dens_max.blockSignals(True)
            self.spn_dens_max.setValue(mn)
            self.spn_dens_max.blockSignals(False)
        self._schedule_density_stretch()

    def _plan_density_raster(self):
        rst, _ctr = self._density.get('plan', (None, None))
        return rst

    def _first_density_raster(self):
        rst = self._plan_density_raster()
        if rst is not None:
            return rst
        for key in ('long', 'trans'):
            rst, _ctr = self._density.get(key, (None, None))
            if rst is not None:
                return rst
        return None

    def _clip_for_raster(self, rst):
        user_min, user_max = self._density_clip()
        ref = D.raster_limits(self._plan_density_raster())
        dest = D.raster_limits(rst)
        return D.map_clip(user_min, user_max, ref, dest)

    def _sync_density_range(self, rlayer, reset=False):
        """Fit Min/Max spinboxes to the real KDE range; Auto = 2% cut."""
        if rlayer is None:
            rlayer = self._first_density_raster()
        limits = D.raster_limits(rlayer) if rlayer is not None else None
        if limits is None:
            return
        dmax = float(limits['max'])
        if dmax <= 0:
            return
        if dmax < 1:
            decimals, step = 4, max(dmax / 200.0, 0.0001)
        elif dmax < 20:
            decimals, step = 3, max(dmax / 200.0, 0.001)
        elif dmax < 200:
            decimals, step = 2, max(dmax / 200.0, 0.01)
        else:
            decimals, step = 1, max(dmax / 200.0, 0.1)
        apply_auto = reset or not self._dens_stretch_user
        self.spn_dens_min.blockSignals(True)
        self.spn_dens_max.blockSignals(True)
        ceiling = max(
            dmax,
            float(self.spn_dens_min.value() or 0.0),
            float(self.spn_dens_max.value() or 0.0),
            1.0,
        )
        for spn in (self.spn_dens_min, self.spn_dens_max):
            spn.setRange(0.0, ceiling)
            spn.setDecimals(decimals)
            spn.setSingleStep(step)
        if apply_auto:
            self.spn_dens_min.setValue(float(limits['cut_low']))
            self.spn_dens_max.setValue(dmax)
            self._dens_stretch_user = False
        else:
            mn = min(max(0.0, self.spn_dens_min.value()), dmax)
            mx = min(max(self.spn_dens_max.value(), mn), dmax)
            if mx <= mn:
                mx = dmax
            self.spn_dens_min.setValue(mn)
            self.spn_dens_max.setValue(mx)
        for spn in (self.spn_dens_min, self.spn_dens_max):
            spn.setRange(0.0, dmax)
        self.spn_dens_min.blockSignals(False)
        self.spn_dens_max.blockSignals(False)
        self.spn_dens_min.setToolTip(
            'Lower bound of the colour stretch on the plan KDE (max = %.4g). '
            'Sections use the same relative cut. Values below Min are not drawn.'
            % dmax
        )

    def _auto_density_stretch(self):
        self._dens_stretch_user = False
        self._sync_density_range(self._first_density_raster(), reset=True)
        self._apply_density_stretch()

    def _schedule_density_stretch(self, *_args):
        if not self.density_on:
            return
        has_raster = any(rst is not None for rst, _ctr in self._density.values())
        if has_raster:
            self._stretch_timer.start(160)
        else:
            self._schedule_density()

    def _apply_density_stretch(self):
        if not self.density_on:
            return
        scheme = self._density_scheme()
        opacity = max(0.15, self.sld_dens_op.value() / 100.0)
        levels = self.spn_dens_levels.value()
        labels = self._density_labels_on()
        mode = self.density_mode
        styled = False
        for key, (rst, ctr) in list(self._density.items()):
            if rst is None:
                continue
            clip_min, clip_max = self._clip_for_raster(rst)
            self._density[key] = D.restyle_pair(
                rst, ctr, mode, levels, opacity, scheme=scheme,
                labels=labels, clip_min=clip_min, clip_max=clip_max,
                fill=self.density_fill,
            )
            styled = True
        if styled:
            self._refresh_canvases()

    def _on_density_scheme(self, *_args):
        if not self.density_on:
            return
        scheme = self._density_scheme()
        opacity = max(0.15, self.sld_dens_op.value() / 100.0)
        with_heat = self.density_mode in ('heatmap', 'both')
        styled = False
        for rst, ctr in self._density.values():
            if rst is not None:
                clip_min, clip_max = self._clip_for_raster(rst)
                D.style_heatmap(
                    rst, opacity=opacity, scheme=scheme,
                    levels=self.spn_dens_levels.value(),
                    clip_min=clip_min, clip_max=clip_max,
                    fill=self.density_fill,
                )
                styled = True
            if ctr is not None:
                D.style_contours(
                    ctr, with_heatmap=with_heat, scheme=scheme,
                    labels=self._density_labels_on(),
                )
                styled = True
        if styled:
            self.plan.canvas.refresh()
            self.longp.canvas.refresh()
            self.transp.canvas.refresh()
            self._refresh_zooms()

    def _density_labels_on(self):
        return bool(self.chk_dens_labels.isChecked())

    def _on_density_labels(self, *_args):
        if not self.density_on:
            return
        on = self._density_labels_on()
        for _rst, ctr in self._density.values():
            if ctr is not None:
                D.style_contour_labels(ctr, on=on)
        self.plan.canvas.refresh()
        self.longp.canvas.refresh()
        self.transp.canvas.refresh()
        self._refresh_zooms()

    def _on_density_opacity(self, value):
        self.lbl_dens_op.setText('%d%%' % int(value))
        op = max(0.15, int(value) / 100.0)
        for rst, _ctr in self._density.values():
            if rst is not None:
                rst.setOpacity(op)
                rst.triggerRepaint()
        if self.density_on:
            self.plan.canvas.refresh()
            self.longp.canvas.refresh()
            self.transp.canvas.refresh()

    def _drop_density_layers(self):
        self._density_timer.stop()
        self._stretch_timer.stop()
        for key, pair in list(self._density.items()):
            D.release_pair(*pair)
            self._density[key] = (None, None)

    def _rebuild_density(self, refresh=True):
        if not self.density_on or self.source is None:
            self._drop_density_layers()
            if refresh:
                self._refresh_canvases()
            return
        radius = self.spn_dens_radius.value()
        pixel = self.spn_dens_cell.value()
        kernel = self.cmb_dens_kernel.currentData()
        if kernel is None:
            kernel = 0
        levels = self.spn_dens_levels.value()
        opacity = max(0.15, self.sld_dens_op.value() / 100.0)
        mode = self.density_mode
        jobs = (
            ('plan', self.source),
            ('long', self.long_layer),
            ('trans', self.trans_layer),
        )
        new_pairs = {}
        try:
            for key, lyr in jobs:
                if lyr is None or lyr.featureCount() < 2:
                    new_pairs[key] = (None, None)
                    continue
                rad, pix = D.adapt_kernel(
                    lyr, radius, pixel,
                    None if key == 'plan' else self.source,
                )
                new_pairs[key] = D.build_pair(
                    lyr, rad, pix, kernel, mode, levels, opacity,
                    scheme=self._density_scheme(),
                    labels=self._density_labels_on(),
                    clip_min=None, clip_max=None,
                    fill=self.density_fill,
                )
        except Exception as exc:
            self._drop_density_layers()
            QMessageBox.warning(
                self, 'Density',
                'Could not build the density surface.\n%s' % exc
            )
            self.chk_density.blockSignals(True)
            self.chk_density.setChecked(False)
            self.chk_density.blockSignals(False)
            self.density_on = False
            self._sync_density_controls()
            if refresh:
                self._refresh_canvases()
            return
        self._drop_density_layers()
        self._density = new_pairs
        rst = self._first_density_raster()
        if rst is not None:
            self._dens_stretch_user = False
            self._sync_density_range(rst, reset=True)
            self._apply_density_stretch()
        elif refresh:
            self._refresh_canvases()

    def _line_width(self):
        return max(0.25, float(self.point_size) * 0.35)

    def _pane_fit_layers(self, pane):
        """Point (and visible vector) layers that define the data footprint."""
        if pane is self.plan:
            pts, lines = self.source, self.line_layer
        elif pane is self.longp:
            pts, lines = self.long_layer, self.long_line_layer
        elif pane is self.transp:
            pts, lines = self.trans_layer, self.trans_line_layer
        else:
            return []
        out = []
        if pts is not None:
            out.append(pts)
        if self.display_mode in ('vectors', 'both') and lines is not None:
            out.append(lines)
        return out

    def _pane_layers(self, pane):
        if pane is self.plan:
            pts, lines = self.source, self.line_layer
        elif pane is self.longp:
            pts, lines = self.long_layer, self.long_line_layer
        elif pane is self.transp:
            pts, lines = self.trans_layer, self.trans_line_layer
        else:
            return []
        mode = self.display_mode
        out = []
        if mode in ('points', 'both') and pts is not None:
            out.append(pts)
        if mode in ('vectors', 'both') and lines is not None:
            out.append(lines)
        if self.density_on:
            key = 'plan' if pane is self.plan else (
                'long' if pane is self.longp else 'trans'
            )
            rst, ctr = self._density.get(key, (None, None))
            if ctr is not None:
                out.append(ctr)
            if rst is not None and self.density_mode in ('heatmap', 'both'):
                out.append(rst)
        return out

    def _select_draw_mode(self, mode):
        self._user_picked_draw = True
        self.display_mode = mode
        mapping = {
            'points': self.btn_draw_points,
            'vectors': self.btn_draw_vectors,
            'both': self.btn_draw_both,
            'none': self.btn_draw_none,
        }
        btn = mapping.get(mode)
        if btn is None:
            return
        btn.blockSignals(True)
        btn.setChecked(True)
        btn.blockSignals(False)

    def _set_draw_mode(self, mode):
        self._select_draw_mode(mode)
        self._refresh_canvases()
        view3d.refresh_open_views(
            self.iface, self.source, self.group_field,
            display_mode=self._draw_mode_for_3d(),
            arrow_size=self.arrow_size,
        )

    def _draw_mode_for_3d(self):
        return 'points' if self.display_mode == 'none' else self.display_mode

    def _sync_draw_buttons(self):
        has = self.line_layer is not None and self.line_layer.featureCount() > 0
        self.btn_draw_vectors.setEnabled(has)
        self.btn_draw_both.setEnabled(has)
        self.sld_arrow.setEnabled(has)
        if not has and self.display_mode in ('vectors', 'both'):
            self.display_mode = 'points'
        mapping = {
            'points': self.btn_draw_points,
            'vectors': self.btn_draw_vectors,
            'both': self.btn_draw_both,
            'none': self.btn_draw_none,
        }
        btn = mapping.get(self.display_mode, self.btn_draw_points)
        if not btn.isEnabled():
            btn = self.btn_draw_points
            self.display_mode = 'points'
        btn.blockSignals(True)
        btn.setChecked(True)
        btn.blockSignals(False)

    def _layer_for_pane(self, pane):
        layers = self._pane_layers(pane)
        return layers[0] if layers else None

    def _open_zoom(self, pane):
        layers = self._pane_layers(pane)
        if not layers:
            return
        key = id(pane)
        win = self._zoom_windows.get(key)
        try:
            alive = win is not None
        except Exception:
            alive = False
        if alive:
            try:
                win.reload(layers, pane.canvas)
                win.show()
                win.raise_()
                win.activateWindow()
                return
            except Exception:
                pass
        win = ZoomWindow(pane, layers, parent=self)
        self._zoom_windows[key] = win
        win.show()
        win.raise_()
        win.activateWindow()

    def _refresh_zooms(self):
        kept = {}
        for key, win in list(self._zoom_windows.items()):
            try:
                visible = win.isVisible()
            except Exception:
                continue
            if not visible:
                kept[key] = win
                continue
            pane = None
            if key == id(self.plan):
                pane = self.plan
            elif key == id(self.longp):
                pane = self.longp
            elif key == id(self.transp):
                pane = self.transp
            if pane is not None:
                win.reload(self._pane_layers(pane), None)
            kept[key] = win
        self._zoom_windows = kept

    def _refresh_canvases(self):
        adaptive = self.chk_adaptive.isChecked()
        self.plan.show_layer(
            self._pane_layers(self.plan), adaptive=adaptive,
            fit_from=self._pane_fit_layers(self.plan),
        )
        self.longp.show_layer(
            self._pane_layers(self.longp), adaptive=adaptive,
            fit_from=self._pane_fit_layers(self.longp),
        )
        self.transp.show_layer(
            self._pane_layers(self.transp), adaptive=adaptive,
            fit_from=self._pane_fit_layers(self.transp),
        )
        self._refresh_zooms()

    def open_3d(self):
        view3d.open_3d_view(
            self.iface, self.source, parent=self,
            group_field=self.group_field,
            display_mode=self._draw_mode_for_3d(),
            arrow_size=self.arrow_size,
        )
