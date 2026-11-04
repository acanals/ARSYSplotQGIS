# -*- coding: utf-8 -*-
"""Lite-style workspace: plan / longitudinal / transversal + filters."""
from contextlib import contextmanager, suppress
import math
import os

from qgis.core import (
    QgsMapRendererCustomPainterJob,
    QgsPointXY,
    QgsProject,
    QgsRectangle,
    QgsScopedProxyProgressTask,
    QgsWkbTypes,
)
from qgis.gui import QgsMapCanvas
from qgis.PyQt.QtCore import QByteArray, QPoint, QRect, QSize, Qt, QTimer
from qgis.PyQt.QtGui import (
    QBrush, QColor, QIcon, QImage, QPainter, QPalette, QPen, QFont, QPixmap,
)
from qgis.PyQt.QtWidgets import (
    QAbstractButton,
    QAbstractSpinBox,
    QApplication,
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

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))

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

# Active UI theme (dark by default). Widgets that paint by hand read UI_THEME.
THEMES = {
    'dark': {
        'name': 'dark',
        'bg': '#1c1916',
        'canvas': '#000000',
        'panel': '#161411',
        'ink': '#fff5e6',
        'muted': 'rgba(255,245,230,0.55)',
        'btn': '#2a2520',
        'btn_border': '#3a342e',
        'btn_hover': '#3a342e',
        'disabled': '#6b645c',
        'groove': '#2a2520',
        'track_off': '#3a342e',
        'track_off_border': '#8a8178',
        'handle_rim': '#1c1916',
        'handle_fill': '#fff5e6',
        'spin_btn': '#4a443c',
        'group_border': '#3a342e',
        'accent': '#d97726',
        'accent_border': '#f0a15a',
    },
    'light': {
        'name': 'light',
        'bg': '#f3f0ea',
        'canvas': '#ffffff',
        'panel': '#efebe3',
        'ink': '#1a1816',
        'muted': 'rgba(26,24,22,0.55)',
        'btn': '#e8e2d8',
        'btn_border': '#c8c0b4',
        'btn_hover': '#ddd5c8',
        'disabled': '#9a9288',
        'groove': '#ddd5c8',
        'track_off': '#c8c0b4',
        'track_off_border': '#9a9288',
        'handle_rim': '#c8c0b4',
        'handle_fill': '#fffdf8',
        'spin_btn': '#5a554e',
        'group_border': '#c8c0b4',
        'accent': '#d97726',
        'accent_border': '#f0a15a',
    },
}
UI_THEME = dict(THEMES['dark'])
DARK = UI_THEME['canvas']
INK = UI_THEME['ink']
TOOLTIP_CSS = (
    'QToolTip { background-color:#fff8ee; color:#1a1816;'
    '  border:1px solid #8a8178; padding:4px 7px; font-size:10px; }'
)


def _set_ui_theme(name):
    """Swap the active palette used by stylesheets and hand-painted chrome."""
    global UI_THEME, DARK, INK
    UI_THEME = dict(THEMES['light' if name == 'light' else 'dark'])
    DARK = UI_THEME['canvas']
    INK = UI_THEME['ink']


def compact_btn_css():
    t = UI_THEME
    return (
        'QPushButton { background:%(btn)s; color:%(ink)s; border:1px solid %(btn_border)s;'
        '  border-radius:6px; font-size:10px; padding:2px 4px; }'
        'QPushButton:hover { background:%(btn_hover)s; }'
        'QPushButton:disabled { color:%(disabled)s; background:%(btn)s;'
        '  border-color:%(btn_border)s; }'
        'QPushButton:checked { background:%(accent)s; border-color:%(accent_border)s; }'
        'QPushButton:checked:disabled { background:%(btn)s; border-color:%(btn_border)s;'
        '  color:%(disabled)s; }'
    ) % t


COMPACT_BTN_CSS = compact_btn_css()


@contextmanager
def _qgis_busy(text='ARSYSplotQGIS working'):
    """QGIS wait cursor and the status-bar task spinner. No extra libraries."""
    from qgis.utils import OverrideCursor
    task = None
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        task = QgsScopedProxyProgressTask(text)
    try:
        with OverrideCursor(Qt.WaitCursor):
            QApplication.processEvents()
            yield
    finally:
        task = None
        QApplication.processEvents()


def _tune_auto_btn(btn):
    """Indicator + action. Must not be the window default (Enter in a spinbox)."""
    btn.setCheckable(True)
    btn.setChecked(True)
    btn.setAutoDefault(False)
    btn.setDefault(False)
    btn.setFocusPolicy(Qt.NoFocus)
    btn.setStyleSheet(compact_btn_css())
    btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)


def _spin_line_css():
    return (
        'QLineEdit { font-size:11px; padding:0px; border:none;'
        '  background:%(btn)s; color:%(ink)s; selection-background-color:%(accent)s; }'
    ) % UI_THEME


_CLIP_SPIN_BTN = 14  # px; must match #arsysClipSpin::up/down-button width


def _clip_spin_css():
    """Min/Max only: digits flush to arrows — no spare padding strip."""
    t = UI_THEME
    spin_up = os.path.join(PLUGIN_DIR, 'spin_up.svg').replace('\\', '/')
    spin_down = os.path.join(PLUGIN_DIR, 'spin_down.svg').replace('\\', '/')
    return (
        'QDoubleSpinBox#arsysClipSpin {'
        '  background:%(btn)s; color:%(ink)s;'
        '  border:1px solid %(btn_border)s;'
        '  padding:1px %(btn_w)dpx 1px 3px;'
        '  min-height:24px; }'
        'QDoubleSpinBox#arsysClipSpin QLineEdit {'
        '  border:none; padding:0px; margin:0px;'
        '  background:%(btn)s; color:%(ink)s;'
        '  selection-background-color:%(accent)s; }'
        'QDoubleSpinBox#arsysClipSpin::up-button,'
        'QDoubleSpinBox#arsysClipSpin::down-button {'
        '  subcontrol-origin: border; width:%(btn_w)dpx;'
        '  background:%(spin_btn)s; border:none; }'
        'QDoubleSpinBox#arsysClipSpin::up-button {'
        '  subcontrol-position: top right; }'
        'QDoubleSpinBox#arsysClipSpin::down-button {'
        '  subcontrol-position: bottom right; }'
        'QDoubleSpinBox#arsysClipSpin::up-button:hover,'
        'QDoubleSpinBox#arsysClipSpin::down-button:hover {'
        '  background:%(accent)s; }'
        'QDoubleSpinBox#arsysClipSpin::up-arrow {'
        '  image: url("%(spin_up)s"); width:8px; height:5px; }'
        'QDoubleSpinBox#arsysClipSpin::down-arrow {'
        '  image: url("%(spin_down)s"); width:8px; height:5px; }'
    ) % dict(
        t, btn_w=_CLIP_SPIN_BTN, spin_up=spin_up, spin_down=spin_down,
    )


def _fit_clip_spin_width(spn):
    """Width = text for 2 decimals + arrow column only (no dead field)."""
    fm = spn.fontMetrics()
    sample = '8888.88'
    if hasattr(fm, 'horizontalAdvance'):
        text_w = int(fm.horizontalAdvance(sample))
    else:
        text_w = int(fm.width(sample))
    # text + arrow column + border/chrome
    spn.setFixedWidth(text_w + _CLIP_SPIN_BTN + 6)


def _tune_clip_spin(spn):
    """Hug content: only digits + +/- . Free row space stays outside the control."""
    spn.setObjectName('arsysClipSpin')
    spn.setButtonSymbols(QAbstractSpinBox.UpDownArrows)
    spn.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    spn.setDecimals(2)
    spn.setRange(0.0, 1.0e9)
    spn.setKeyboardTracking(False)
    spn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
    spn.setStyleSheet(_clip_spin_css())
    line = spn.lineEdit()
    if line is not None:
        line.setMaxLength(10)
        line.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    _fit_clip_spin_width(spn)


def _theme_palette():
    """Force editable controls off the QGIS/system Base (often white)."""
    t = UI_THEME
    bg = QColor(t['bg'])
    base = QColor(t['btn'])
    ink = QColor(t['ink'])
    accent = QColor(t['accent'])
    pal = QPalette()
    pal.setColor(QPalette.Window, bg)
    pal.setColor(QPalette.WindowText, ink)
    pal.setColor(QPalette.Base, base)
    pal.setColor(QPalette.AlternateBase, bg)
    pal.setColor(QPalette.Text, ink)
    pal.setColor(QPalette.Button, base)
    pal.setColor(QPalette.ButtonText, ink)
    pal.setColor(QPalette.Highlight, accent)
    pal.setColor(QPalette.HighlightedText, QColor('#fff8ee'))
    pal.setColor(QPalette.PlaceholderText, QColor(t['disabled']))
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        pal.setColor(QPalette.ToolTipBase, QColor('#fff8ee'))
        pal.setColor(QPalette.ToolTipText, QColor('#1a1816'))
    return pal


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
        t = UI_THEME
        p.setPen(QColor(t['ink'] if self.isEnabled() else t['disabled']))
        p.drawText(
            QRect(r.x(), r.y(), text_w, r.height()),
            Qt.AlignVCenter | Qt.AlignLeft,
            self.text(),
        )
        on = self.isChecked()
        if on:
            p.setBrush(QBrush(QColor(t['accent'])))
            p.setPen(QPen(QColor(t['accent_border']), 1))
        else:
            p.setBrush(QBrush(QColor(t['track_off'])))
            p.setPen(QPen(QColor(t['track_off_border']), 1))
        p.drawRoundedRect(track, th / 2.0, th / 2.0)
        kd = th - 6
        kx = track.right() - 3 - kd if on else track.x() + 3
        ky = track.y() + 3
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor(t['handle_fill'])))
        p.drawEllipse(kx, ky, kd, kd)


class DensityScaleBar(QWidget):
    """Horizontal density scale: one label at each colour-class boundary."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._colors = []
        self._bounds = []
        self.setMinimumHeight(56)
        self.setMaximumHeight(64)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setToolTip(L.html_tooltip(
            '**Density** colour scale. Each colour step is labelled with its value.',
        ))
        self.hide()

    def clear(self):
        self._colors = []
        self._bounds = []
        self.hide()
        self.update()

    def set_legend(self, legend):
        """legend is (vmin, vmax, colors, bounds) from density.heatmap_legend."""
        if not legend:
            self.clear()
            return
        if len(legend) >= 4:
            _vmin, _vmax, colors, bounds = legend[:4]
        else:
            _vmin, _vmax, colors = legend[:3]
            bounds = None
        if colors is None or len(colors) < 2:
            self.clear()
            return
        n = len(colors)
        if bounds is None or len(bounds) != n + 1:
            try:
                vmin = float(_vmin)
                vmax = float(_vmax)
            except (TypeError, ValueError):
                self.clear()
                return
            if not (math.isfinite(vmin) and math.isfinite(vmax)) or vmax <= vmin:
                self.clear()
                return
            bounds = D._equal_bounds(vmin, vmax, n)
        clean = []
        for b in bounds:
            try:
                bv = float(b)
            except (TypeError, ValueError):
                self.clear()
                return
            if not math.isfinite(bv):
                self.clear()
                return
            clean.append(bv)
        self._colors = list(colors)
        self._bounds = clean
        self.show()
        self.update()

    def paintEvent(self, _event):
        if len(self._colors) < 2 or len(self._bounds) != len(self._colors) + 1:
            return
        t = UI_THEME
        ink = QColor(t['ink'])
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)
        r = self.contentsRect().adjusted(4, 4, -4, -2)
        lab_h = 18
        gap = 3
        bar_h = 14
        if r.height() < bar_h + gap + lab_h:
            bar_h = max(8, r.height() - gap - lab_h)
        bar = QRect(r.x(), r.y(), r.width(), bar_h)
        n = len(self._colors)
        sw = bar.width() / float(max(n, 1))
        p.setPen(Qt.NoPen)
        for i, c in enumerate(self._colors):
            x0 = bar.x() + int(round(i * sw))
            x1 = bar.x() + int(round((i + 1) * sw))
            col = QColor(c)
            col.setAlpha(255)
            p.setBrush(QBrush(col))
            p.drawRect(x0, bar.y(), max(1, x1 - x0), bar.height())
        p.setPen(QPen(ink, 1))
        p.setBrush(Qt.NoBrush)
        p.drawRect(bar)
        font = QFont(self.font())
        font.setPixelSize(10 if n <= 8 else 9)
        p.setFont(font)
        p.setPen(ink)
        y_lab = bar.bottom() + gap
        for i, val in enumerate(self._bounds):
            lab = D._legend_fmt(val)
            if not lab:
                continue
            cx = bar.x() + int(round(i * sw))
            if i == 0:
                align = Qt.AlignLeft | Qt.AlignVCenter
                rect = QRect(cx, y_lab, max(36, int(sw)), lab_h)
            elif i == n:
                align = Qt.AlignRight | Qt.AlignVCenter
                rect = QRect(cx - max(36, int(sw)), y_lab, max(36, int(sw)), lab_h)
            else:
                align = Qt.AlignHCenter | Qt.AlignVCenter
                half = max(20, int(sw))
                rect = QRect(cx - half, y_lab, half * 2, lab_h)
            p.drawText(rect, align, lab)




def _themed_icon(filename, ink, size=14):
    """SVG icon with cream strokes remapped to the theme ink colour."""
    path = os.path.join(PLUGIN_DIR, filename)
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            raw = fh.read()
    except OSError:
        return QIcon(path)
    ink = str(ink or '#fff5e6')
    raw = raw.replace('#fff5e6', ink).replace('#FFF5E6', ink)
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    rendered = False
    with suppress(Exception):
        from qgis.PyQt.QtSvg import QSvgRenderer
        renderer = QSvgRenderer(QByteArray(raw.encode('utf-8')))
        if renderer.isValid():
            p = QPainter(pm)
            renderer.render(p)
            p.end()
            rendered = True
    if not rendered:
        return QIcon(path)
    return QIcon(pm)


def _pane_icon_btn_css(light):
    """Zoom / Export: black edge in light mode so they stay visible."""
    if light:
        return (
            'QPushButton { background:#ffffff; border:1px solid #000000;'
            '  border-radius:4px; padding:0; }'
            'QPushButton:hover { background:#f0f0f0; }'
            'QPushButton:disabled { background:#f5f5f5; border-color:#666666; }'
        )
    t = UI_THEME
    return (
        'QPushButton { background:%(btn)s; border:1px solid %(btn_border)s;'
        '  border-radius:4px; padding:0; }'
        'QPushButton:hover { background:%(btn_hover)s; }'
        'QPushButton:disabled { background:%(btn)s; border-color:%(btn_border)s; }'
    ) % t


def _icon_button(filename, tooltip):
    btn = QPushButton()
    btn._arsys_icon = filename
    btn.setIcon(_themed_icon(filename, UI_THEME.get('ink', '#fff5e6'), 14))
    btn.setIconSize(QSize(14, 14))
    btn.setFixedSize(24, 22)
    btn.setCursor(Qt.PointingHandCursor)
    btn.setToolTip(L.html_tooltip(tooltip))
    btn.setStyleSheet(_pane_icon_btn_css(UI_THEME.get('name') == 'light'))
    return btn


def _source_icon_button(filename, tooltip, height):
    """Icon-only source action; tooltip carries the full name."""
    btn = QPushButton()
    btn.setIcon(QIcon(os.path.join(PLUGIN_DIR, filename)))
    icon = max(12, min(16, int(height) - 8))
    btn.setIconSize(QSize(icon, icon))
    btn.setFixedHeight(int(height))
    btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    btn.setCursor(Qt.PointingHandCursor)
    btn.setToolTip(L.html_tooltip(tooltip))
    btn.setStyleSheet(compact_btn_css())
    btn.setFocusPolicy(Qt.TabFocus)
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
        t = UI_THEME
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(t['groove']))
        p.drawRoundedRect(QRect(x0, gy, max(x1 - x0, 1), 6), 3, 3)
        xa = int(round(self._t_to_x(self._a)))
        xb = int(round(self._t_to_x(self._b)))
        p.setBrush(QColor(t['accent']))
        p.drawRoundedRect(QRect(xa, gy, max(xb - xa, 2), 6), 3, 3)
        p.setPen(QPen(QColor(t['handle_rim']), 1))
        p.setBrush(QColor(t['handle_fill']))
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
        self._axis_lab = QLabel(axis.upper())
        self._axis_lab.setFixedWidth(16)
        self.v0 = QLabel('—')
        self.v1 = QLabel('—')
        self.v0.setMinimumWidth(64)
        self.v1.setMinimumWidth(64)
        self.bar = DualRangeBar(self._changed)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addWidget(self._axis_lab)
        row.addWidget(self.v0)
        row.addWidget(self.bar, 1)
        row.addWidget(self.v1)
        self.apply_theme()
        self.setToolTip(L.html_tooltip(
            'Keep objects on **%s** in this range.' % axis.upper(),
            'Unit: **metres (m)**, layer coordinates.',
        ))

    def apply_theme(self):
        ink = UI_THEME['ink']
        self._axis_lab.setStyleSheet('color:%s;font-weight:700;' % ink)
        self.v0.setStyleSheet('color:%s;' % ink)
        self.v1.setStyleSheet('color:%s;' % ink)
        self.bar.update()

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
        self.v0.setText('%.3f m' % a)
        self.v1.setText('%.3f m' % b)


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
            with suppress(AttributeError, RuntimeError, TypeError, ValueError):
                self.setLabelsVisible(True)
        nothing = getattr(QgsMapCanvas, 'WheelNothing', None)
        if nothing is not None and hasattr(self, 'setWheelAction'):
            with suppress(AttributeError, RuntimeError, TypeError, ValueError):
                self.setWheelAction(nothing)

    def fit_data_extent(self, ext):
        if ext is None or ext.isEmpty():
            return
        self._data_ext = QgsRectangle(ext)
        self._user_view = False
        # setExtent/refresh can emit extentsChanged after _fitting clears and
        # would flip _user_view back without undoing the zoom — block it.
        blocked = False
        with suppress(AttributeError, RuntimeError, TypeError, ValueError):
            self.blockSignals(True)
            blocked = True
        try:
            self._apply_fit()
        finally:
            if blocked:
                with suppress(AttributeError, RuntimeError, TypeError, ValueError):
                    self.blockSignals(False)
            self._user_view = False
        overlay = getattr(self, '_overlay', None)
        if overlay is not None:
            with suppress(AttributeError, RuntimeError, TypeError, ValueError):
                overlay.update()

    def _on_extents(self):
        if self._fitting:
            return
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
        self._title_lab = QLabel(title)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.addWidget(self._title_lab, 1)
        self.btn_export = _icon_button(
            'export.svg',
            'Export **PNG** with axes and legend.',
        )
        self.btn_export.setEnabled(False)
        self.btn_export.clicked.connect(self.export_image)
        head.addWidget(self.btn_export)
        self.btn_fit = _icon_button(
            'fit.svg',
            '**Fit** the view to the data frame (after zoom or pan).',
        )
        self.btn_fit.setEnabled(False)
        self.btn_fit.clicked.connect(self._fit_view)
        head.addWidget(self.btn_fit)
        self.btn_zoom = _icon_button(
            'zoom.svg',
            '**Zoom** this view. Wheel, drag, Esc closes.',
        )
        self.btn_zoom.setEnabled(False)
        self.btn_zoom.clicked.connect(self._emit_zoom)
        if on_zoom is None:
            self.btn_export.hide()
            self.btn_fit.hide()
            self.btn_zoom.hide()
        head.addWidget(self.btn_zoom)
        box = QVBoxLayout(self)
        box.setContentsMargins(6, 4, 6, 6)
        box.setSpacing(2)
        box.addLayout(head)
        box.addWidget(self.wrap, 1)
        self.apply_theme()

    def apply_theme(self):
        t = UI_THEME
        light = t.get('name') == 'light'
        ink = t.get('ink', '#1a1816' if light else '#fff5e6')
        self.canvas.setCanvasColor(QColor(t['canvas']))
        self._title_lab.setStyleSheet(
            'color:%s;font-size:11px;letter-spacing:0.04em;' % t['muted']
        )
        self.setStyleSheet('background:%s; %s' % (t['panel'], TOOLTIP_CSS))
        css = _pane_icon_btn_css(light)
        for btn in (
            getattr(self, 'btn_export', None),
            getattr(self, 'btn_fit', None),
            getattr(self, 'btn_zoom', None),
        ):
            if btn is None:
                continue
            btn.setStyleSheet(css)
            name = getattr(btn, '_arsys_icon', None)
            if name:
                btn.setIcon(_themed_icon(name, ink, 14))
        with suppress(AttributeError, RuntimeError, TypeError, ValueError):
            self.overlay.update()
        self.canvas.refresh()

    def _emit_zoom(self):
        if self._on_zoom:
            self._on_zoom(self)

    def _fit_view(self):
        """Re-frame to the current data extent (quick fit after zoom/pan)."""
        ext = getattr(self.canvas, '_data_ext', None)
        if ext is None or ext.isEmpty():
            fit_from = None
            dock = self._find_dock()
            if dock is not None and hasattr(dock, '_pane_fit_layers'):
                with suppress(AttributeError, RuntimeError, TypeError, ValueError):
                    fit_from = dock._pane_fit_layers(self)
            srcs = fit_from if fit_from else (self.canvas.layers() or [])
            ext = L.padded_data_extent(srcs)
        if ext is None or ext.isEmpty():
            ext = L.union_extent(self.canvas.layers() or [])
        if ext is not None and not ext.isEmpty():
            self.canvas.fit_data_extent(ext)
            with suppress(AttributeError, RuntimeError, TypeError, ValueError):
                self.overlay.update()

    def export_image(self):
        if self.wrap.width() < 20 or self.wrap.height() < 20:
            QMessageBox.warning(self, 'Export', 'The view is too small to export.')
            return
        layer_name = ''
        layers = self.canvas.layers()
        if layers:
            layer_name = layers[0].name()
        dock = self._find_dock()
        density_on = bool(dock is not None and getattr(dock, 'density_on', False))
        dlg = E.ExportImageDialog(
            self, title=self.title, subtitle=layer_name, bg=QColor('#ffffff'),
            label_size_pt=E.DEFAULT_LEVEL_LABEL_PT,
            density_on=density_on,
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

    def _find_dock(self):
        """Walk parents to the workspace (main pane or zoom window)."""
        w = self
        while w is not None:
            if hasattr(w, 'build_paper_density') and hasattr(w, '_pane_draw_layers'):
                return w
            w = w.parent()
        return None

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
        try:
            label_pt = int(opts.get('label_size_pt', E.DEFAULT_LEVEL_LABEL_PT))
        except (TypeError, ValueError):
            label_pt = E.DEFAULT_LEVEL_LABEL_PT
        label_pt = max(6, min(36, label_pt))
        ink = QColor('#1a1816') if E.is_light_color(bg) else QColor('#fff5e6')

        dock = self._find_dock()
        groups, group_field = self.overlay._legend_entries()
        show_groups = bool(groups)
        # Reserve legend space before the paper KDE exists.
        want_colorbar = bool(
            dock is not None
            and dock.density_on
            and dock.density_mode in ('heatmap', 'both')
        )

        margin = 10.0
        pad_l, pad_r, pad_t, pad_b = 18.0, 7.0, 5.0, 22.0
        extra_r = 0.0
        if want_colorbar:
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

        paper_rst = paper_ctr = None
        layers = []
        bar = None
        try:
            if dock is not None:
                layers.extend(dock._pane_draw_layers(self))
                if dock.density_on:
                    with _qgis_busy('ARSYSplotQGIS: paper density'):
                        paper_rst, paper_ctr = dock.build_paper_density(
                            self, (xmin, xmax, ymin, ymax), plot_w, plot_h,
                            label_size_pt=label_pt,
                        )
                    # Canvas order: first = topmost. Isolines above KDE fill.
                    if paper_ctr is not None:
                        layers.append(paper_ctr)
                    if (
                        dock.density_mode in ('heatmap', 'both')
                        and paper_rst is not None
                    ):
                        layers.append(paper_rst)
                    bar = (
                        D.heatmap_legend(paper_rst)
                        if paper_rst is not None else None
                    )
            if not layers:
                layers = [
                    lyr for lyr in (self.canvas.layers() or [])
                    if lyr is not None
                ]
                if bar is None:
                    for lyr in layers:
                        if lyr.customProperty('arsysplotqgis') == 'density-raster':
                            bar = D.heatmap_legend(lyr)
                            break

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
                    painter.setPen(
                        QColor('#5a554e') if E.is_light_color(bg) else ink
                    )
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
                with suppress(AttributeError, RuntimeError, TypeError, ValueError):
                    settings.setLayers(list(layers))
                with suppress(AttributeError, RuntimeError, TypeError, ValueError):
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

                paint_paper_axes(
                    painter, left, top, right, bottom,
                    xmin, xmax, ymin, ymax,
                    self.h_axis, self.v_axis, self.h_label, self.v_label, dpi,
                )
                side_x = right + E.mm_to_px(4.5, dpi)
                if bar is not None:
                    if len(bar) >= 4:
                        vmin, vmax, colors, bounds = bar[:4]
                    else:
                        vmin, vmax, colors = bar[:3]
                        bounds = None
                    used = D.paint_colorbar(
                        painter, side_x, top, bottom, vmin, vmax, colors, dpi, ink,
                        bounds=bounds,
                    )
                    side_x += used + E.mm_to_px(3.0, dpi)
                if show_groups:
                    paint_paper_legend(
                        painter, groups, group_field, side_x, top, bottom, dpi, ink
                    )
            finally:
                painter.end()
        finally:
            if paper_rst is not None or paper_ctr is not None:
                D.release_pair(paper_rst, paper_ctr)
        return img

    def show_layer(self, layer, adaptive=False, fit_from=None):
        if isinstance(layer, (list, tuple)):
            layers = [lyr for lyr in layer if lyr is not None]
        else:
            layers = [layer] if layer is not None else []
        enabled = bool(layers)
        if hasattr(self, 'btn_zoom'):
            self.btn_zoom.setEnabled(enabled)
        if hasattr(self, 'btn_fit'):
            self.btn_fit.setEnabled(enabled)
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
        bar = QHBoxLayout()
        self._hint = QLabel('Wheel zoom · drag pan · Esc closes')
        bar.addWidget(self._hint, 1)
        self.btn_fit = _icon_button(
            'fit.svg',
            '**Fit** the view to the data frame (after zoom or pan).',
        )
        self.btn_fit.clicked.connect(self._fit)
        bar.addWidget(self.btn_fit)
        self.btn_export = _icon_button(
            'export.svg',
            'Export **PNG** with axes and legend.',
        )
        self.btn_export.clicked.connect(lambda: self.pane.export_image())
        bar.addWidget(self.btn_export)
        self.btn_close = _icon_button(
            'close.svg',
            '**Close** this zoom window (Esc).',
        )
        self.btn_close.clicked.connect(self.close)
        bar.addWidget(self.btn_close)
        self.pane = PlotPane(
            pane.title, pane.h_axis, pane.v_axis, pane.h_label, pane.v_label
        )
        root = QWidget()
        col = QVBoxLayout(root)
        col.setContentsMargins(8, 8, 8, 8)
        col.addLayout(bar)
        col.addWidget(self.pane, 1)
        self.setCentralWidget(root)
        self.apply_theme()
        self.reload(layer, pane.canvas)

    def apply_theme(self):
        t = UI_THEME
        light = t.get('name') == 'light'
        ink = t.get('ink', '#1a1816' if light else '#fff5e6')
        self.setStyleSheet(
            'QMainWindow { background:%(bg)s; }'
            'QWidget { background:%(bg)s; color:%(ink)s; }'
            % t
            + TOOLTIP_CSS
        )
        self._hint.setStyleSheet('color:%s;' % t['muted'])
        css = _pane_icon_btn_css(light)
        for btn in (
            getattr(self, 'btn_fit', None),
            getattr(self, 'btn_export', None),
            getattr(self, 'btn_close', None),
        ):
            if btn is None:
                continue
            btn.setStyleSheet(css)
            name = getattr(btn, '_arsys_icon', None)
            if name:
                btn.setIcon(_themed_icon(name, ink, 14))
        self.pane.apply_theme()

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
        self._imported_cmap = {}
        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.timeout.connect(self._apply_filters_now)
        self._building = False
        self._force_close = False
        self.point_size = 2.2
        self.point_shape = L.DEFAULT_MARKER
        self.arrow_size = L.ARROW_MM_DEFAULT
        self.density_on = False
        self.density_mode = 'heatmap'
        self.density_fill = 'bands'
        self._density = {
            'plan': (None, None),
            'long': (None, None),
            'trans': (None, None),
        }
        self._density_timer = QTimer(self)
        self._density_timer.setSingleShot(True)
        self._density_timer.timeout.connect(self._rebuild_density)
        self._stretch_timer = QTimer(self)
        self._stretch_timer.setSingleShot(True)
        self._stretch_timer.timeout.connect(self._apply_density_stretch)
        self._dens_stretch_user = False
        self._dens_params_user = False
        self._home_extent = {}
        self._zoom_windows = {}
        self._legend_layer = None
        self.ui_theme = 'dark'
        self._theme_shown = False
        _set_ui_theme(self.ui_theme)
        self._watch_legend_layer()

        self.setWindowTitle('ARSYSplotQGIS')
        self.setObjectName('ARSYSplotQGISWindow')
        self.setWindowIcon(QIcon(os.path.join(PLUGIN_DIR, 'ArcheIcon.png')))
        self.setWindowFlag(Qt.Window, True)
        self.resize(1280, 840)
        self.setMinimumSize(720, 520)

        self._root = QWidget()
        split = QSplitter(Qt.Horizontal)
        split.addWidget(self._make_side())
        split.addWidget(self._make_stage())
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([280, 900])
        layout = QVBoxLayout(self._root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(split)
        self.setCentralWidget(self._root)
        self._apply_ui_theme()

    def closeEvent(self, event):
        if self._force_close:
            for win in list(getattr(self, '_zoom_windows', {}).values()):
                with suppress(AttributeError, RuntimeError, TypeError, ValueError):
                    win._force_close = True
                    win.close()
            self._drop_plugin_layers()
            event.accept()
            return
        event.ignore()
        self.hide()

    def showEvent(self, event):
        super().showEvent(event)
        # QGIS app style can repaint editable Base white on first expose.
        if not self._theme_shown:
            self._theme_shown = True
            QTimer.singleShot(0, self._apply_ui_theme)
        if self.source:
            QTimer.singleShot(0, self._refresh_canvases)

    def _on_theme_toggled(self, checked):
        self.ui_theme = 'dark' if checked else 'light'
        self._apply_ui_theme()

    def _root_stylesheet(self):
        t = UI_THEME
        spin_up = os.path.join(PLUGIN_DIR, 'spin_up.svg').replace('\\', '/')
        spin_down = os.path.join(PLUGIN_DIR, 'spin_down.svg').replace('\\', '/')
        return (
            'QMainWindow, QWidget { background:%(bg)s; color:%(ink)s; font-size:12px; }'
            'QPushButton { background:%(btn)s; color:%(ink)s;'
            '  border:1px solid %(btn_border)s; border-radius:6px; padding:4px 8px; }'
            'QPushButton:hover { background:%(btn_hover)s; }'
            'QPushButton:disabled { color:%(disabled)s; }'
            'QLineEdit, QAbstractSpinBox, QSpinBox, QDoubleSpinBox, QComboBox {'
            '  background:%(btn)s; color:%(ink)s;'
            '  border:1px solid %(btn_border)s; padding:2px 4px;'
            '  selection-background-color:%(accent)s; selection-color:#fff8ee; }'
            'QAbstractSpinBox { padding:2px 18px 2px 4px; }'
            'QAbstractSpinBox QLineEdit, QSpinBox QLineEdit, QDoubleSpinBox QLineEdit {'
            '  background:%(btn)s; color:%(ink)s; border:none; }'
            'QComboBox QAbstractItemView { background:%(btn)s; color:%(ink)s;'
            '  selection-background-color:%(accent)s; }'
            'QDoubleSpinBox::up-button, QSpinBox::up-button,'
            'QDoubleSpinBox::down-button, QSpinBox::down-button {'
            '  subcontrol-origin: border; width:16px; background:%(spin_btn)s;'
            '  border:none; }'
            'QDoubleSpinBox::up-button, QSpinBox::up-button {'
            '  subcontrol-position: top right; }'
            'QDoubleSpinBox::down-button, QSpinBox::down-button {'
            '  subcontrol-position: bottom right; }'
            'QDoubleSpinBox::up-button:hover, QSpinBox::up-button:hover,'
            'QDoubleSpinBox::down-button:hover, QSpinBox::down-button:hover {'
            '  background:%(accent)s; }'
            'QDoubleSpinBox::up-arrow, QSpinBox::up-arrow {'
            '  image: url("%(spin_up)s"); width:8px; height:5px; }'
            'QDoubleSpinBox::down-arrow, QSpinBox::down-arrow {'
            '  image: url("%(spin_down)s"); width:8px; height:5px; }'
            'QPushButton:checked { background:%(accent)s; border-color:%(accent_border)s; }'
            'QGroupBox { border:1px solid %(group_border)s; border-radius:6px;'
            '  margin-top:10px; background:%(bg)s; }'
            'QGroupBox::title { subcontrol-origin: margin; left:8px; padding:0 4px; }'
            'QScrollArea { border: none; background:%(bg)s; }'
            'QSlider { background:transparent; }'
            'QSlider::groove:horizontal { background:%(groove)s; height:6px;'
            '  border-radius:3px; }'
            'QSlider::handle:horizontal { background:%(accent)s; width:12px;'
            '  margin:-4px 0; border-radius:6px; }'
            'QSlider::groove:horizontal:disabled { background:%(groove)s; }'
            'QSlider::handle:horizontal:disabled { background:%(disabled)s; }'
            + TOOLTIP_CSS
        ) % dict(t, spin_up=spin_up, spin_down=spin_down)

    def _style_editable_controls(self):
        """Palette + local sheets so QGIS does not leave white Base on first show."""
        pal = _theme_palette()
        self.setPalette(pal)
        if getattr(self, '_root', None) is not None:
            self._root.setPalette(pal)
        line_css = _spin_line_css()
        for widget in self.findChildren(QWidget):
            if isinstance(widget, (QAbstractSpinBox, QSpinBox, QDoubleSpinBox, QComboBox, QSlider)):
                with suppress(AttributeError, RuntimeError, TypeError, ValueError):
                    widget.setPalette(pal)
                    widget.setAutoFillBackground(True)
            if isinstance(widget, QAbstractSpinBox):
                if widget.objectName() == 'arsysClipSpin':
                    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
                        widget.setStyleSheet(_clip_spin_css())
                        _fit_clip_spin_width(widget)
                    continue
                line = widget.lineEdit()
                if line is not None:
                    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
                        line.setPalette(pal)
                        line.setStyleSheet(line_css)

    def _apply_ui_theme(self):
        _set_ui_theme(self.ui_theme)
        global COMPACT_BTN_CSS
        COMPACT_BTN_CSS = compact_btn_css()
        sheet = self._root_stylesheet()
        self.setStyleSheet(sheet)
        if getattr(self, '_root', None) is not None:
            self._root.setStyleSheet(sheet)
        self._style_editable_controls()
        if getattr(self, '_lab_load', None) is not None:
            self._lab_load.setStyleSheet(
                '#arsysLoadDataLabel { color:%s; background:transparent; border:none;'
                '  padding:0; margin:0; }' % UI_THEME['ink']
            )
        css = compact_btn_css()
        for btn in (
            getattr(self, 'btn_dens_auto', None),
            getattr(self, 'btn_dens_cut', None),
            getattr(self, 'btn_dens_heat', None),
            getattr(self, 'btn_dens_iso', None),
            getattr(self, 'btn_dens_both', None),
            getattr(self, 'btn_dens_cloud', None),
            getattr(self, 'btn_dens_bands', None),
            getattr(self, 'btn_draw_points', None),
            getattr(self, 'btn_draw_vectors', None),
            getattr(self, 'btn_draw_both', None),
            getattr(self, 'btn_draw_none', None),
            getattr(self, 'btn_import', None),
            getattr(self, 'btn_sample', None),
            getattr(self, 'btn_use', None),
            getattr(self, 'btn_all', None),
            getattr(self, 'btn_none', None),
            getattr(self, 'btn_reset', None),
            getattr(self, 'btn_3d', None),
        ):
            if btn is not None:
                with suppress(AttributeError, RuntimeError, TypeError, ValueError):
                    btn.setStyleSheet(css)
        for pane in (
            getattr(self, 'plan', None),
            getattr(self, 'longp', None),
            getattr(self, 'transp', None),
        ):
            if pane is not None:
                pane.apply_theme()
        if getattr(self, '_filters_panel', None) is not None:
            t = UI_THEME
            self._filters_panel.setStyleSheet('background:%s;' % t['panel'])
            self._filters_lab.setStyleSheet('color:%s;' % t['muted'])
        if getattr(self, '_dens_scale', None) is not None:
            self._dens_scale.update()
        for rng in (
            getattr(self, 'rng_x', None),
            getattr(self, 'rng_y', None),
            getattr(self, 'rng_z', None),
        ):
            if rng is not None:
                rng.apply_theme()
        # Filter group uses the global QGroupBox sheet from _root_stylesheet.
        for win in list(getattr(self, '_zoom_windows', {}).values()):
            with suppress(AttributeError, RuntimeError, TypeError, ValueError):
                win.apply_theme()
        for sw in (
            getattr(self, 'chk_dark', None),
            getattr(self, 'chk_adaptive', None),
            getattr(self, 'chk_density', None),
            getattr(self, 'chk_dens_labels', None),
            getattr(self, 'chk_dens_invert', None),
        ):
            if sw is not None:
                sw.update()
        with suppress(AttributeError, RuntimeError, TypeError, ValueError):
            view3d.apply_open_theme(self.iface, self.ui_theme)

    def _make_side(self):
        side = QWidget()
        side.setMinimumWidth(240)
        col = QVBoxLayout(side)
        title_row = QHBoxLayout()
        title_row.setSpacing(6)
        self._title_lab = QLabel('ARSYSplot<strong>QGIS</strong>')
        self._title_lab.setTextFormat(Qt.RichText)
        self._title_lab.setStyleSheet('font-size:16px;')
        title_row.addWidget(self._title_lab, 1)
        self.chk_dark = ToggleSwitch('Dark')
        self.chk_dark.setChecked(True)
        self.chk_dark.setToolTip(L.html_tooltip(
            '**Dark / Light** workspace chrome, canvases and axes.',
            'Export PNG stays on a white paper background.',
        ))
        self.chk_dark.toggled.connect(self._on_theme_toggled)
        title_row.addWidget(self.chk_dark)
        col.addLayout(title_row)

        self.lbl_file = QLabel('No layer')
        self.lbl_count = QLabel('0 / 0 points')
        col.addWidget(self.lbl_file)
        col.addWidget(self.lbl_count)

        src_row = QHBoxLayout()
        src_row.setSpacing(4)
        src_row.setAlignment(Qt.AlignVCenter)
        self._lab_load = QLabel('Load\nData')
        self._lab_load.setObjectName('arsysLoadDataLabel')
        self._lab_load.setAlignment(Qt.AlignCenter)
        font = QFont()
        font.setPixelSize(12)
        self._lab_load.setFont(font)
        self._lab_load.setAutoFillBackground(False)
        self._lab_load.setAttribute(Qt.WA_TranslucentBackground, True)
        fm = self._lab_load.fontMetrics()
        try:
            text_w = max(fm.horizontalAdvance('Load'), fm.horizontalAdvance('Data'))
        except AttributeError:
            text_w = max(fm.width('Load'), fm.width('Data'))
        src_h = fm.lineSpacing() * 2
        self._lab_load.setFixedSize(QSize(text_w + 6, src_h))
        src_row.addWidget(self._lab_load)
        self.btn_import = _source_icon_button(
            'import.svg',
            'Import **CSV**. Map P1, P2, P3 and Group.',
            src_h,
        )
        self.btn_import.clicked.connect(self.import_csv)
        self.btn_sample = _source_icon_button(
            'sample.svg',
            'Load bundled **sample.csv**. No file to browse.',
            src_h,
        )
        self.btn_sample.clicked.connect(self.load_sample)
        self.btn_use = _source_icon_button(
            'layer.svg',
            'Use the selected QGIS **point layer**. Copies attributes, colours, size.',
            src_h,
        )
        self.btn_use.clicked.connect(self.use_selected_layer)
        src_row.addWidget(self.btn_import, 1)
        src_row.addWidget(self.btn_sample, 1)
        src_row.addWidget(self.btn_use, 1)
        col.addLayout(src_row)

        gbox = QGroupBox('Group')
        gcol = QVBoxLayout(gbox)
        self.cmb_group = QComboBox()
        self.cmb_group.setToolTip(L.html_tooltip(
            '**Field** used to colour and filter objects.',
            'Typical: group, material, level.',
        ))
        self.cmb_group.currentTextChanged.connect(self._on_group_field)
        row = QHBoxLayout()
        self.btn_all = QPushButton('All')
        self.btn_none = QPushButton('None')
        self.btn_all.setToolTip(L.html_tooltip('Show **every** group.'))
        self.btn_none.setToolTip(L.html_tooltip('Hide **every** group.'))
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
        self.chk_adaptive.setToolTip(L.html_tooltip(
            '**On:** zoom axes to the filtered cloud.',
            '**Off:** restore the original full-data axis frame.',
        ))
        self.chk_adaptive.toggled.connect(self._on_adaptive_toggled)
        ocol.addWidget(self.chk_adaptive)
        shape_row = QHBoxLayout()
        shape_row.addWidget(QLabel('Point model'))
        self.cmb_point_shape = QComboBox()
        for sid, label in L.MARKER_SHAPES:
            self.cmb_point_shape.addItem(label, sid)
        idx = self.cmb_point_shape.findData(L.DEFAULT_MARKER)
        if idx >= 0:
            self.cmb_point_shape.setCurrentIndex(idx)
        self.cmb_point_shape.setToolTip(L.html_tooltip(
            '**Point model** — marker shape for all points (plan and sections).',
        ))
        self.cmb_point_shape.currentIndexChanged.connect(self._on_point_shape)
        shape_row.addWidget(self.cmb_point_shape, 1)
        ocol.addLayout(shape_row)
        size_row = QHBoxLayout()
        size_row.addWidget(QLabel('Point size'))
        self.sld_size = QSlider(Qt.Horizontal)
        self.sld_size.setRange(0, 40)
        self.sld_size.setSingleStep(1)
        self.sld_size.setPageStep(5)
        self.sld_size.setValue(22)
        self.sld_size.setTracking(True)
        size_tip = L.html_tooltip(
            'Point diameter. Unit: **mm**. Range **0–3**.',
        )
        self.sld_size.setToolTip(size_tip)
        self.sld_size.valueChanged.connect(self._on_point_size)
        self.lbl_size = QLabel('2.2 mm')
        self.lbl_size.setToolTip(size_tip)
        self.lbl_size.setMinimumWidth(44)
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
        arrow_tip = L.html_tooltip(
            'Arrow-head size. Unit: **mm**. Fine steps at small sizes.',
        )
        self.sld_arrow.setToolTip(arrow_tip)
        self.sld_arrow.valueChanged.connect(self._on_arrow_size)
        self.lbl_arrow = QLabel('%.2f mm' % L.ARROW_MM_DEFAULT)
        self.lbl_arrow.setToolTip(arrow_tip)
        self.lbl_arrow.setMinimumWidth(52)
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
            btn.setStyleSheet(compact_btn_css())
            self._draw_group.addButton(btn)
        self.btn_draw_points.setChecked(True)
        self.btn_draw_points.setToolTip(L.html_tooltip(
            '**P1:** object centre.',
        ))
        self.btn_draw_vectors.setToolTip(L.html_tooltip(
            '**P2→P3** after import. If only P1→P2, that axis is used.',
        ))
        self.btn_draw_both.setToolTip(L.html_tooltip(
            '**Centre** and **axis** of each object.',
        ))
        self.btn_draw_none.setToolTip(L.html_tooltip(
            '**Hide** points and vectors so density is fully visible.',
        ))
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
        self.chk_density.setToolTip(L.html_tooltip(
            '**KDE** of filtered points: heatmap and/or isolines.',
            'Inside the plugin, not the QGIS map. Draw → **None** to see it alone.',
        ))
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
            btn.setStyleSheet(compact_btn_css())
            self._dens_mode_group.addButton(btn)
            btn.clicked.connect(lambda _on, m=mode: self._set_density_mode(m))
            dens_mode.addWidget(btn)
        self.btn_dens_heat.setChecked(True)
        self.btn_dens_heat.setToolTip(L.html_tooltip(
            'Filled density (**Cloud** or **Bands**).',
        ))
        self.btn_dens_iso.setToolTip(L.html_tooltip(
            'Contours of equal **raster-cell** KDE.',
        ))
        self.btn_dens_both.setToolTip(L.html_tooltip(
            '**Heatmap** with isolines on top.',
        ))
        dcol.addLayout(dens_mode)
        width_tip = L.html_tooltip(
            'Isoline stroke. Unit: **mm**. Range **0–1**.',
        )
        width_row = QHBoxLayout()
        lbl_width = QLabel('Line width')
        lbl_width.setToolTip(width_tip)
        width_row.addWidget(lbl_width)
        self.sld_dens_width = QSlider(Qt.Horizontal)
        self.sld_dens_width.setOrientation(Qt.Horizontal)
        self.sld_dens_width.setRange(0, 100)
        self.sld_dens_width.setValue(15)
        self.sld_dens_width.setMinimumHeight(22)
        self.sld_dens_width.setEnabled(False)
        self.sld_dens_width.setToolTip(width_tip)
        self.sld_dens_width.valueChanged.connect(self._on_density_width)
        self.lbl_dens_width = QLabel('0.15 mm')
        self.lbl_dens_width.setMinimumWidth(52)
        self.lbl_dens_width.setToolTip(width_tip)
        width_row.addWidget(self.sld_dens_width, 1)
        width_row.addWidget(self.lbl_dens_width)
        dcol.addLayout(width_row)
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
            btn.setStyleSheet(compact_btn_css())
            self._dens_fill_group.addButton(btn)
            btn.clicked.connect(lambda _on, f=fill: self._set_density_fill(f))
            fill_row.addWidget(btn)
        self.btn_dens_bands.setChecked(True)
        self.btn_dens_cloud.setToolTip(L.html_tooltip(
            '**Cloud:** smooth interpolated colour. Same KDE as Bands.',
        ))
        self.btn_dens_bands.setToolTip(L.html_tooltip(
            '**Bands:** discrete colour classes on the KDE raster (QGIS-style). '
            'Same breaks as isolines. Isolines are lines only, not the fill.',
        ))
        dcol.addLayout(fill_row)
        pal_row = QHBoxLayout()
        pal_row.addWidget(QLabel('Colour'))
        self.cmb_dens_scheme = QComboBox()
        self.cmb_dens_scheme.setIconSize(QSize(72, 14))
        self.density_invert = False
        for sid, label, _stops in D.COLOR_SCHEMES:
            self.cmb_dens_scheme.addItem(
                D.scheme_icon(sid, invert=False), label, sid,
            )
        idx = self.cmb_dens_scheme.findData(D.DEFAULT_SCHEME)
        if idx >= 0:
            self.cmb_dens_scheme.setCurrentIndex(idx)
        self.cmb_dens_scheme.setEnabled(False)
        self.cmb_dens_scheme.setToolTip(L.html_tooltip(
            '**Colour** of the density surface (heatmap and isolines).',
        ))
        self.cmb_dens_scheme.currentIndexChanged.connect(self._on_density_scheme)
        pal_row.addWidget(self.cmb_dens_scheme, 1)
        dcol.addLayout(pal_row)
        rng_row = QHBoxLayout()
        rng_row.setSpacing(8)
        rng_row.setContentsMargins(0, 0, 0, 0)
        self.lbl_dens_min = QLabel('Min')
        self.lbl_dens_max = QLabel('Max')
        for lab in (self.lbl_dens_min, self.lbl_dens_max):
            lab.setStyleSheet('font-size:10px;')
            lab.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        # Compact clusters: [Min + spin] … [Max + spin] … Auto
        # Spins hug digits+arrows; slack is only between clusters.
        rng_row.addWidget(self.lbl_dens_min, 0)
        self.spn_dens_min = QDoubleSpinBox()
        self.spn_dens_min.setRange(0.0, 1.0e9)
        self.spn_dens_min.setSingleStep(0.1)
        self.spn_dens_min.setValue(0.0)
        self.spn_dens_min.setEnabled(False)
        _tune_clip_spin(self.spn_dens_min)
        self.spn_dens_min.valueChanged.connect(self._on_density_clip)
        rng_row.addWidget(self.spn_dens_min, 0)
        rng_row.addSpacing(10)
        rng_row.addWidget(self.lbl_dens_max, 0)
        self.spn_dens_max = QDoubleSpinBox()
        self.spn_dens_max.setRange(0.0, 1.0e9)
        self.spn_dens_max.setSingleStep(0.1)
        self.spn_dens_max.setValue(1.0)
        self.spn_dens_max.setEnabled(False)
        _tune_clip_spin(self.spn_dens_max)
        self.spn_dens_max.valueChanged.connect(self._on_density_clip)
        self._set_clip_tooltips()
        rng_row.addWidget(self.spn_dens_max, 0)
        rng_row.addStretch(1)
        self.btn_dens_cut = QPushButton('Auto')
        _tune_auto_btn(self.btn_dens_cut)
        self.btn_dens_cut.setEnabled(False)
        self.btn_dens_cut.setToolTip(L.html_tooltip(
            '**On:** Min = 2% of positive plan cells; Max = peak cell.',
            '**Off:** you set Min/Max. Raster cells, not a point count.',
        ))
        self.btn_dens_cut.clicked.connect(self._auto_density_stretch)
        rng_row.addWidget(self.btn_dens_cut, 0)
        dcol.addLayout(rng_row)
        rad_row = QHBoxLayout()
        lbl_radius = QLabel('Radius')
        radius_tip = L.html_tooltip(
            'Kernel bandwidth. Unit: **metres (m)**. Larger = smoother.',
        )
        lbl_radius.setToolTip(radius_tip)
        rad_row.addWidget(lbl_radius)
        self.spn_dens_radius = QDoubleSpinBox()
        self.spn_dens_radius.setDecimals(2)
        self.spn_dens_radius.setRange(0.05, 80.0)
        self.spn_dens_radius.setSingleStep(0.05)
        self.spn_dens_radius.setValue(0.50)
        self.spn_dens_radius.setSuffix(' m')
        self.spn_dens_radius.setMinimumWidth(88)
        self.spn_dens_radius.setEnabled(False)
        self.spn_dens_radius.setToolTip(radius_tip)
        self.spn_dens_radius.valueChanged.connect(self._on_density_params)
        rad_row.addWidget(self.spn_dens_radius, 1)
        self.btn_dens_auto = QPushButton('Auto')
        _tune_auto_btn(self.btn_dens_auto)
        self.btn_dens_auto.setEnabled(False)
        self.btn_dens_auto.setToolTip(L.html_tooltip(
            '**On:** Radius and Cell follow the filtered extent (**m**).',
            '**Off:** you set them.',
        ))
        self.btn_dens_auto.clicked.connect(self._on_radius_auto)
        rad_row.addWidget(self.btn_dens_auto)
        dcol.addLayout(rad_row)
        ker_cell = QHBoxLayout()
        ker_cell.addWidget(QLabel('Kernel'))
        self.cmb_dens_kernel = QComboBox()
        for label, val in D.KERNELS:
            self.cmb_dens_kernel.addItem(label, val)
        self.cmb_dens_kernel.setEnabled(False)
        self.cmb_dens_kernel.setToolTip(L.html_tooltip(
            '**Kernel** shape on the raster: Quartic, Triangular, Uniform, Triweight, Epanechnikov.',
        ))
        self.cmb_dens_kernel.currentIndexChanged.connect(self._schedule_density)
        ker_cell.addWidget(self.cmb_dens_kernel, 1)
        cell_tip = L.html_tooltip(
            '**Raster cell** size for the density KDE. Unit: **metres (m)**.',
            'Smaller = finer grid (slower). Larger = coarser surface.',
            'Drives the rebuild. Clamped only for memory (too fine) or',
            'above the kernel **Radius** (too coarse).',
        )
        lbl_cell = QLabel('Cell')
        lbl_cell.setToolTip(cell_tip)
        ker_cell.addWidget(lbl_cell)
        self.spn_dens_cell = QDoubleSpinBox()
        self.spn_dens_cell.setDecimals(3)
        self.spn_dens_cell.setRange(0.005, 20.0)
        self.spn_dens_cell.setSingleStep(0.01)
        self.spn_dens_cell.setValue(0.05)
        self.spn_dens_cell.setSuffix(' m')
        self.spn_dens_cell.setMinimumWidth(88)
        self.spn_dens_cell.setEnabled(False)
        self.spn_dens_cell.setToolTip(cell_tip)
        self.spn_dens_cell.valueChanged.connect(self._on_density_params)
        self.spn_dens_cell.editingFinished.connect(self._on_density_params)
        self.spn_dens_radius.editingFinished.connect(self._on_density_params)
        ker_cell.addWidget(self.spn_dens_cell, 1)
        dcol.addLayout(ker_cell)
        iso_row = QHBoxLayout()
        iso_row.addWidget(QLabel('Isolines'))
        self.spn_dens_levels = QSpinBox()
        self.spn_dens_levels.setRange(3, 16)
        self.spn_dens_levels.setValue(8)
        self.spn_dens_levels.setEnabled(False)
        self.spn_dens_levels.setToolTip(L.html_tooltip(
            'Contour intervals between **Min** and **Max** cell values.',
        ))
        self.spn_dens_levels.valueChanged.connect(self._schedule_density_stretch)
        iso_row.addWidget(self.spn_dens_levels, 1)
        self.chk_dens_labels = ToggleSwitch('Labels')
        self.chk_dens_labels.setEnabled(False)
        self.chk_dens_labels.setToolTip(L.html_tooltip(
            'Write the **raster-cell** KDE value on each isoline.',
        ))
        self.chk_dens_labels.toggled.connect(self._on_density_labels)
        iso_row.addWidget(self.chk_dens_labels)
        dcol.addLayout(iso_row)
        op_row = QHBoxLayout()
        op_tip = L.html_tooltip(
            'Opacity of painted **raster cells**. **100%** = solid; empty stays clear.',
        )
        lbl_op = QLabel('Opacity')
        lbl_op.setToolTip(op_tip)
        op_row.addWidget(lbl_op)
        self.sld_dens_op = QSlider(Qt.Horizontal)
        self.sld_dens_op.setRange(20, 100)
        self.sld_dens_op.setValue(70)
        self.sld_dens_op.setEnabled(False)
        self.sld_dens_op.setToolTip(op_tip)
        self.sld_dens_op.valueChanged.connect(self._on_density_opacity)
        self.lbl_dens_op = QLabel('70%')
        self.lbl_dens_op.setMinimumWidth(36)
        self.lbl_dens_op.setToolTip(op_tip)
        op_row.addWidget(self.sld_dens_op, 1)
        op_row.addWidget(self.lbl_dens_op)
        dcol.addLayout(op_row)
        ocol.addWidget(dens_box)

        self.btn_reset = QPushButton('Reset')
        self.btn_reset.setToolTip(L.html_tooltip(
            '**Reset view:** all groups, full XYZ range, default sizes,',
            'Draw → Points, Adaptive off, and **re-fit** the three canvases.',
            'Does not change Density settings or Dark/Light.',
        ))
        self.btn_reset.clicked.connect(self.reset_view)
        self.btn_reset.setEnabled(False)
        ocol.addWidget(self.btn_reset)
        col.addWidget(opt)

        self.btn_3d = QPushButton('Open 3D view')
        self.btn_3d.setToolTip(L.html_tooltip(
            'Orbit the cloud in a separate window. Not QGIS 3D (avoids 3.40 crashes).',
        ))
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
        self._filters_panel = QWidget()
        fl = QVBoxLayout(self._filters_panel)
        fl.setSpacing(8)
        self._filters_lab = QLabel('Resources')
        fl.addWidget(self._filters_lab)
        # 1) Filter first (always): XYZ range
        self._filter_box = QGroupBox('Filter')
        fbox = QVBoxLayout(self._filter_box)
        fbox.setContentsMargins(8, 10, 8, 8)
        fbox.setSpacing(4)
        self.rng_x = RangeSliders('x', self.schedule_filter)
        self.rng_y = RangeSliders('y', self.schedule_filter)
        self.rng_z = RangeSliders('z', self.schedule_filter)
        fbox.addWidget(self.rng_x)
        fbox.addWidget(self.rng_y)
        fbox.addWidget(self.rng_z)
        btn_reset = QPushButton('Reset')
        btn_reset.setToolTip(L.html_tooltip(
            '**Reset view:** all groups, full XYZ range, default sizes,',
            'Draw → Points, Adaptive off, and **re-fit** the three canvases.',
            'Does not change Density settings or Dark/Light.',
        ))
        btn_reset.clicked.connect(self.reset_view)
        fbox.addWidget(btn_reset)
        fl.addWidget(self._filter_box)
        # 2) Below: content that appears / disappears (e.g. density scale)
        self._resources_dynamic = QWidget()
        dyn = QVBoxLayout(self._resources_dynamic)
        dyn.setContentsMargins(0, 0, 0, 0)
        dyn.setSpacing(6)
        self._dens_scale_row = QWidget(self._resources_dynamic)
        scale_row = QHBoxLayout(self._dens_scale_row)
        scale_row.setContentsMargins(0, 0, 0, 0)
        scale_row.setSpacing(8)
        self._dens_scale = DensityScaleBar(self._dens_scale_row)
        scale_row.addWidget(self._dens_scale, 1)
        self.chk_dens_invert = ToggleSwitch('Invert')
        self.chk_dens_invert.setEnabled(False)
        self.chk_dens_invert.hide()
        self.chk_dens_invert.setToolTip(L.html_tooltip(
            '**Invert** the colour ramp (low ↔ high).',
        ))
        self.chk_dens_invert.toggled.connect(self._on_density_invert)
        # Align with the colour strip (top), not the value labels below.
        inv_col = QWidget(self._dens_scale_row)
        inv_lay = QVBoxLayout(inv_col)
        inv_lay.setContentsMargins(0, 4, 0, 0)
        inv_lay.setSpacing(0)
        inv_lay.addWidget(self.chk_dens_invert, 0, Qt.AlignTop)
        inv_lay.addStretch(1)
        scale_row.addWidget(inv_col, 0, Qt.AlignTop)
        dyn.addWidget(self._dens_scale_row)
        fl.addWidget(self._resources_dynamic)
        fl.addStretch(1)
        grid.addWidget(self.plan, 0, 0)
        grid.addWidget(self.longp, 0, 1)
        grid.addWidget(self.transp, 1, 0)
        grid.addWidget(self._filters_panel, 1, 1)
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
            with _qgis_busy('ARSYSplotQGIS: importing CSV'):
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
                self._attach_source(layer, os.path.basename(mapping['path']))
        except Exception as exc:
            QMessageBox.warning(self, 'Import', str(exc))
            return
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
            with _qgis_busy('ARSYSplotQGIS: loading sample'):
                layer, skipped = importer.build_pointz_layer(
                    path, 'p1x', 'p1y', 'p1z', 'material',
                    p2x_field='p2x', p2y_field='p2y', p2z_field='p2z',
                    p3x_field='p3x', p3y_field='p3y', p3z_field='p3z',
                )
                self._attach_source(layer, 'sample.csv')
        except Exception as exc:
            QMessageBox.warning(self, 'Sample', str(exc))
            return
        extra = ' (%d rows skipped)' % skipped if skipped else ''
        self.iface.messageBar().pushInfo(
            'ARSYSplotQGIS', 'Loaded sample: %d points%s.' % (
                layer.featureCount(), extra
            )
        )

    def _is_user_layer(self, layer):
        if layer is None or not hasattr(layer, 'wkbType'):
            return False
        if layer.customProperty('arsysplotqgis'):
            return False
        return True

    def _layer_switch_on(self, layer):
        """Legend checkbox (the eye/switch), not the highlighted row."""
        if layer is None:
            return False
        root = QgsProject.instance().layerTreeRoot()
        node = root.findLayer(layer.id())
        if node is None:
            return True
        with suppress(AttributeError, RuntimeError, TypeError, ValueError):
            return bool(node.itemVisibilityChecked())
        return bool(node.isVisible())

    def _visible_user_point_layers(self):
        out = []
        root = QgsProject.instance().layerTreeRoot()
        for node in root.findLayers():
            lyr = node.layer()
            if not self._is_user_layer(lyr):
                continue
            if not self._layer_switch_on(lyr):
                continue
            if QgsWkbTypes.geometryType(lyr.wkbType()) != QgsWkbTypes.PointGeometry:
                continue
            out.append(lyr)
        return out

    def _remember_legend_layer(self, layer):
        if self._is_user_layer(layer):
            self._legend_layer = layer

    def _on_legend_selection(self, *_args):
        view = self.iface.layerTreeView()
        if view is None:
            return
        current = None
        with suppress(AttributeError, RuntimeError, TypeError, ValueError):
            current = view.currentLayer()
        if self._is_user_layer(current):
            self._remember_legend_layer(current)
            return
        for lyr in view.selectedLayers() or []:
            if self._is_user_layer(lyr):
                self._remember_legend_layer(lyr)
                return

    def _watch_legend_layer(self):
        self._remember_legend_layer(self.iface.activeLayer())
        with suppress(AttributeError, RuntimeError, TypeError, ValueError):
            self.iface.currentLayerChanged.connect(self._remember_legend_layer)
        view = self.iface.layerTreeView()
        if view is None:
            return
        with suppress(AttributeError, RuntimeError, TypeError, ValueError):
            view.currentLayerChanged.connect(self._remember_legend_layer)
        sel = view.selectionModel()
        if sel is not None:
            sel.selectionChanged.connect(self._on_legend_selection)
        self._on_legend_selection()

    def _selected_project_layer(self):
        """Prefer the layer with the legend switch ON, not only the focused row.

        Clicking a layer name (A) leaves it current even if its checkbox is
        off. Turning B on without clicking the name would otherwise still
        load A.
        """
        view = self.iface.layerTreeView()
        current = None
        if view is not None:
            with suppress(AttributeError, RuntimeError, TypeError, ValueError):
                current = view.currentLayer()
            if not self._is_user_layer(current):
                node = view.currentNode()
                if node is not None and hasattr(node, 'layer'):
                    current = node.layer()
        selected = []
        if view is not None:
            selected = list(view.selectedLayers() or [])
        visible = self._visible_user_point_layers()
        visible_ids = {lyr.id() for lyr in visible}

        def pick(*layers):
            for lyr in layers:
                if self._is_user_layer(lyr) and lyr.id() in visible_ids:
                    return lyr
            return None

        found = pick(current, *selected, self.iface.activeLayer(), self._legend_layer)
        if found is not None:
            return found
        if len(visible) == 1:
            return visible[0]
        if visible:
            return visible[0]
        if self._is_user_layer(current):
            return current
        if self._is_user_layer(self._legend_layer):
            return self._legend_layer
        return None

    def use_selected_layer(self):
        layer = self._selected_project_layer()
        if layer is None or not hasattr(layer, 'wkbType'):
            QMessageBox.warning(
                self, 'Layer',
                'Select a point layer in the QGIS layer list, then click '
                'Use selected layer.',
            )
            return
        if QgsWkbTypes.geometryType(layer.wkbType()) != QgsWkbTypes.PointGeometry:
            QMessageBox.warning(self, 'Layer', 'Need a point layer.')
            return
        try:
            with _qgis_busy('ARSYSplotQGIS: reading layer'):
                style = L.imported_layer_style(layer)
                clone, skipped = L.clone_as_private_source(layer)
                extra = ' (%d rows skipped)' % skipped if skipped else ''
                self._attach_source(clone, layer.name(), style=style)
        except Exception as exc:
            QMessageBox.warning(self, 'Layer', str(exc))
            return
        with suppress(AttributeError, RuntimeError, TypeError, ValueError):
            self.iface.setActiveLayer(layer)
        self._legend_layer = layer
        nvec = 0
        with suppress(AttributeError, RuntimeError, TypeError, ValueError):
            nvec = int(clone.customProperty('arsysplotqgis_vectors') or 0)
        vec_txt = (', %d vectors' % nvec) if nvec else ''
        self.iface.messageBar().pushInfo(
            'ARSYSplotQGIS',
            'Using a private copy of “%s”: %d points%s%s. '
            'The project layer is unchanged.' % (
                layer.name(), clone.featureCount(), vec_txt, extra,
            ),
        )

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

    def _attach_source(self, layer, label, style=None):
        self._drop_plugin_layers(keep_source=layer)
        L.clear_plugin_legend()
        self.source = layer
        if layer.customProperty('arsysplotqgis') == 'source':
            L.keep_private(layer)
        style = style or {}
        self._imported_cmap = dict(style.get('cmap') or {})
        if style.get('field'):
            self.group_field = style['field']
        else:
            self.group_field = L.guess_group_field(layer)
        imported_size = style.get('size')
        if imported_size:
            self.point_size = max(0.0, min(3.0, float(imported_size)))
            slider = max(0, min(30, int(round(self.point_size * 10))))
            self.sld_size.blockSignals(True)
            self.sld_size.setValue(slider)
            self.sld_size.blockSignals(False)
            self.lbl_size.setText('%.1f mm' % self.point_size)
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
        self._capture_home_extents()

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
        imported = getattr(self, '_imported_cmap', None) or {}
        self.colors = L.style_by_group(
            self.source, self.group_field, size=self.point_size,
            values=values, cmap=imported or None,
            shape=self._point_shape(),
        )
        self._group_btns = {}
        for i, val in enumerate(values):
            btn = QPushButton(val)
            btn.setCheckable(True)
            btn.setChecked(True)
            btn.setToolTip(L.html_tooltip(val))
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
        self.lbl_size.setText('2.2 mm')
        self.sld_arrow.blockSignals(True)
        self.sld_arrow.setValue(L.arrow_slider_from_mm(L.ARROW_MM_DEFAULT))
        self.sld_arrow.blockSignals(False)
        self.arrow_size = L.ARROW_MM_DEFAULT
        self.lbl_arrow.setText('%.2f mm' % self.arrow_size)
        self._select_draw_mode('points')
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
            shape=self._point_shape(),
        )
        self._apply_filters_now()
        # Force the same enquadram as first load (adaptive fit), even though
        # the Adaptive switch stays Off. Deferred once: density/setLayers can
        # emit extent changes after the synchronous pass.
        self._fit_main_views()
        self._capture_home_extents()
        QTimer.singleShot(0, self._fit_main_views)
        QTimer.singleShot(0, self._capture_home_extents)
        for win in list(getattr(self, '_zoom_windows', {}).values()):
            with suppress(AttributeError, RuntimeError, TypeError, ValueError):
                if win.isVisible() and win._layer is not None:
                    win._fit()
        for dlg in list(getattr(self.iface, '_arsysplotqgis_3d', [])):
            with suppress(AttributeError, RuntimeError, TypeError, ValueError):
                if dlg.isVisible():
                    dlg.reload(
                        self.group_field, keep_camera=False,
                        display_mode=self._draw_mode_for_3d(),
                        arrow_size=self.arrow_size,
                    )

    def _fit_main_views(self):
        """Re-fit plan / XZ / YZ to the filtered point footprint (axis frame)."""
        if self.source is None:
            return
        for pane in (self.plan, self.longp, self.transp):
            layers = self._pane_layers(pane)
            fit_from = self._pane_fit_layers(pane)
            pane.show_layer(layers, adaptive=True, fit_from=fit_from)
            with suppress(AttributeError, RuntimeError, TypeError, ValueError):
                pane.canvas._user_view = False
                pane.overlay.update()

    def _full_pane_extent(self, pane):
        """Padded full-data frame for a pane (ignores XYZ / group subset)."""
        if self.source is None:
            return None
        key, _pts = self._pane_key_and_points(pane)
        xyz = L.xyz_extent(self.source)
        if key == 'plan':
            (x0, x1), (y0, y1) = xyz['x'], xyz['y']
        elif key == 'long':
            (x0, x1), (y0, y1) = xyz['x'], xyz['z']
        elif key == 'trans':
            (x0, x1), (y0, y1) = xyz['y'], xyz['z']
        else:
            return None
        return L._pad_rect(QgsRectangle(float(x0), float(y0), float(x1), float(y1)))

    def _pane_home_key(self, pane):
        key, _pts = self._pane_key_and_points(pane)
        return key

    def _capture_home_extents(self):
        """Remember the original full-data axis frame (Adaptive Off target)."""
        if self.source is None:
            return
        home = {}
        for pane in (self.plan, self.longp, self.transp):
            key = self._pane_home_key(pane)
            if not key:
                continue
            ext = self._full_pane_extent(pane)
            if ext is None or ext.isEmpty():
                cur = getattr(pane.canvas, '_data_ext', None)
                if cur is not None and not cur.isEmpty():
                    ext = QgsRectangle(cur)
            if ext is not None and not ext.isEmpty():
                home[key] = QgsRectangle(ext)
        if home:
            self._home_extent = home

    def _force_pane_extent(self, pane, ext):
        """Set layers, then force the axis/data frame to ``ext``."""
        if pane is None or ext is None or ext.isEmpty():
            return
        layers = self._pane_layers(pane)
        pane.show_layer(layers, adaptive=False)
        canvas = pane.canvas
        canvas.fit_data_extent(QgsRectangle(ext))
        with suppress(AttributeError, RuntimeError, TypeError, ValueError):
            canvas._user_view = False
            canvas._data_ext = QgsRectangle(ext)
            canvas._apply_fit()
            pane.overlay.update()
        canvas.refresh()

    def _fit_filtered_views(self):
        """Adaptive On: zoom every pane to the filtered cloud."""
        if self.source is None:
            return
        for pane in (self.plan, self.longp, self.transp):
            layers = self._pane_layers(pane)
            fit_from = self._pane_fit_layers(pane)
            ext = L.padded_data_extent(fit_from)
            if ext is None or ext.isEmpty():
                ext = L.padded_data_extent(
                    [lyr for lyr in (fit_from or []) if lyr is not None]
                    or layers
                )
            if ext is None or ext.isEmpty():
                ext = L.union_extent(layers)
            if ext is not None and not ext.isEmpty():
                self._force_pane_extent(pane, ext)
            else:
                pane.show_layer(layers, adaptive=True, fit_from=fit_from)
        self._refresh_zooms()

    def _fit_full_extent_views(self):
        """Adaptive Off: restore the original full-data axis frame."""
        if self.source is None:
            return
        if not self._home_extent:
            self._capture_home_extents()
        for pane in (self.plan, self.longp, self.transp):
            key = self._pane_home_key(pane)
            ext = None
            if key and key in self._home_extent:
                ext = QgsRectangle(self._home_extent[key])
            if ext is None or ext.isEmpty():
                ext = self._full_pane_extent(pane)
            if ext is not None and not ext.isEmpty():
                self._force_pane_extent(pane, ext)
            else:
                layers = self._pane_layers(pane)
                pane.show_layer(layers, adaptive=False)
        self._refresh_zooms()

    def _on_adaptive_toggled(self, on):
        if self.source is None:
            return
        if on:
            self._fit_filtered_views()
            # setLayers / density can emit a late extent change — re-apply once.
            QTimer.singleShot(0, self._fit_filtered_views)
            return
        self._fit_full_extent_views()
        QTimer.singleShot(0, self._fit_full_extent_views)

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
                shape=self._point_shape(),
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
            if not self._dens_params_user:
                self._auto_density_params(rebuild=False)
            self._rebuild_density(refresh=False)
        self._refresh_canvases()
        view3d.refresh_open_views(
            self.iface, self.source, self.group_field,
            display_mode=self._draw_mode_for_3d(),
            arrow_size=self.arrow_size,
        )

    def _point_shape(self):
        cmb = getattr(self, 'cmb_point_shape', None)
        if cmb is not None:
            sid = cmb.currentData()
            if sid:
                return L.resolve_marker_shape(sid)
        return L.resolve_marker_shape(getattr(self, 'point_shape', L.DEFAULT_MARKER))

    def _on_point_shape(self, *_args):
        self.point_shape = self._point_shape()
        if self.source is None:
            return
        L.apply_marker_shape(self.source, self.point_shape)
        L.apply_marker_shape(self.long_layer, self.point_shape)
        L.apply_marker_shape(self.trans_layer, self.point_shape)
        self.plan.canvas.refresh()
        self.longp.canvas.refresh()
        self.transp.canvas.refresh()
        self._refresh_zooms()

    def _on_point_size(self, value):
        self.point_size = int(value) / 10.0
        self.lbl_size.setText('%.1f mm' % self.point_size)
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
        self.lbl_arrow.setText('%.2f mm' % self.arrow_size)
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
            self.chk_dens_invert,
            self.spn_dens_min, self.spn_dens_max, self.btn_dens_cut,
            self.spn_dens_levels, self.chk_dens_labels,
            self.sld_dens_width, self.sld_dens_op,
        )

    def _sync_density_controls(self):
        on = bool(self.density_on and self.source is not None)
        for w in self._density_widgets():
            w.setEnabled(on)
        if on:
            self.spn_dens_levels.setEnabled(True)
            self.chk_dens_labels.setEnabled(True)
            iso_on = self.density_mode in ('contours', 'both') or (
                self.chk_dens_labels.isChecked()
            )
            self.sld_dens_width.setEnabled(iso_on)
            self.sld_dens_op.setEnabled(self.density_mode in ('heatmap', 'both'))
            fill_on = self.density_mode in ('heatmap', 'both')
            self.btn_dens_cloud.setEnabled(fill_on)
            self.btn_dens_bands.setEnabled(fill_on)
            self.cmb_dens_scheme.setEnabled(True)
            self.chk_dens_invert.setEnabled(True)
        self._sync_auto_buttons()

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
            self._refresh_density_scale()
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
        else:
            self._refresh_density_scale()

    def _set_density_fill(self, fill):
        self.density_fill = 'cloud' if fill == 'cloud' else 'bands'
        if self.density_on:
            self._apply_density_stretch()

    def _sync_auto_buttons(self):
        pairs = (
            (self.btn_dens_cut, not self._dens_stretch_user),
            (self.btn_dens_auto, not self._dens_params_user),
        )
        for btn, on in pairs:
            btn.blockSignals(True)
            btn.setChecked(on)
            btn.blockSignals(False)

    def _schedule_density(self, *_args):
        if not self.density_on:
            return
        self._density_timer.start(280)

    def _on_density_params(self, *_args):
        self._dens_params_user = True
        self._sync_auto_buttons()
        self._schedule_density()

    def _on_radius_auto(self, *_args):
        self._auto_density_params(True)

    def _auto_density_params(self, rebuild=True):
        if self.source is None:
            return
        radius, pixel = D.suggest_params(self.source)
        # Auto aims for a smooth on-screen grid; manual Cell keeps the spin value.
        canvas = getattr(getattr(self, 'plan', None), 'canvas', None)
        if canvas is not None:
            cw = int(canvas.width() or 0)
            ch = int(canvas.height() or 0)
            dpr = 1.0
            with suppress(AttributeError, RuntimeError, TypeError, ValueError):
                dpr = float(canvas.devicePixelRatioF())
            if dpr < 1.0:
                with suppress(AttributeError, RuntimeError, TypeError, ValueError):
                    dpr = float(canvas.devicePixelRatio())
            dpr = max(1.0, dpr)
            prev = D.preview_pixel(
                self.source.extent(), cw, ch, radius, device_pixel_ratio=dpr,
            )
            pixel = min(float(pixel), float(prev))
        self.spn_dens_radius.blockSignals(True)
        self.spn_dens_cell.blockSignals(True)
        self.spn_dens_radius.setValue(radius)
        self.spn_dens_cell.setValue(pixel)
        self.spn_dens_radius.blockSignals(False)
        self.spn_dens_cell.blockSignals(False)
        self._dens_params_user = False
        self._sync_auto_buttons()
        if rebuild and self.density_on:
            self._rebuild_density()

    def _density_scheme(self):
        sid = self.cmb_dens_scheme.currentData()
        return sid if sid else D.DEFAULT_SCHEME

    def _density_invert(self):
        return bool(getattr(self, 'density_invert', False))

    def _refresh_scheme_icons(self):
        inv = self._density_invert()
        cmb = getattr(self, 'cmb_dens_scheme', None)
        if cmb is None:
            return
        cmb.blockSignals(True)
        for i in range(cmb.count()):
            sid = cmb.itemData(i)
            if sid:
                cmb.setItemIcon(i, D.scheme_icon(sid, invert=inv))
        cmb.blockSignals(False)

    def _on_density_invert(self, on):
        self.density_invert = bool(on)
        self._refresh_scheme_icons()
        if self.density_on:
            self._apply_density_stretch()

    def _density_clip(self):
        mn = float(self.spn_dens_min.value())
        mx = float(self.spn_dens_max.value())
        limits = D.raster_limits(self._plan_density_raster())
        if limits is not None:
            dmax = float(limits['max'])
            mn = min(max(0.0, mn), dmax)
            mx = min(max(mn, mx), dmax)
            if mx <= mn:
                mx = dmax
        return mn, mx

    def _clip_spins_busy(self):
        return bool(
            self.spn_dens_min.hasFocus() or self.spn_dens_max.hasFocus()
        )

    def _on_density_clip(self, *_args):
        self._dens_stretch_user = True
        self._sync_auto_buttons()
        mn = self.spn_dens_min.value()
        mx = self.spn_dens_max.value()
        if mx < mn:
            self.spn_dens_max.blockSignals(True)
            self.spn_dens_max.setValue(mn)
            self.spn_dens_max.blockSignals(False)
        self._schedule_density_stretch()

    def _plan_density_raster(self):
        rst, _ctr = D.split_pair(self._density.get('plan'))
        return rst

    def _first_density_raster(self):
        rst = self._plan_density_raster()
        if rst is not None:
            return rst
        for key in ('long', 'trans'):
            rst, _ctr = D.split_pair(self._density.get(key))
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
        if self._clip_spins_busy() and not reset:
            return
        if dmax < 1:
            step = max(dmax / 200.0, 0.01)
        elif dmax < 20:
            step = max(dmax / 200.0, 0.01)
        elif dmax < 200:
            step = max(dmax / 200.0, 0.01)
        else:
            step = max(dmax / 200.0, 0.1)
        apply_auto = reset or not self._dens_stretch_user
        self.spn_dens_min.blockSignals(True)
        self.spn_dens_max.blockSignals(True)
        for spn in (self.spn_dens_min, self.spn_dens_max):
            spn.setRange(0.0, 1.0e9)
            spn.setDecimals(2)
            spn.setSingleStep(step)
        if apply_auto:
            self.spn_dens_min.setValue(float(limits['cut_low']))
            self.spn_dens_max.setValue(dmax)
            self._dens_stretch_user = False
            self._sync_auto_buttons()
        self.spn_dens_min.blockSignals(False)
        self.spn_dens_max.blockSignals(False)
        self._set_clip_tooltips(dmax)

    def _set_clip_tooltips(self, plan_peak=None):
        """Min/Max are plan-absolute in the UI, applied as peak fractions."""
        peak = ''
        if plan_peak is not None and float(plan_peak) > 0:
            peak = 'Plan **peak cell** is now **%.4g** (reference for all views).' % (
                float(plan_peak),
            )
        min_tip = L.html_tooltip(
            '**Min** as a fraction of each view’s KDE peak (from the plan value).',
            'Same control for plan, X/Z and Y/Z. Below Min is not painted.',
            peak or '**Auto Min** ≈ 2% of positive plan cells.',
        )
        max_tip = L.html_tooltip(
            '**Max** as a fraction of each view’s KDE peak (from the plan value).',
            '**Auto Max** = 100% of each local peak (no section tip clipped).',
            peak or 'Lower Max = same % cut on plan, X/Z and Y/Z.',
        )
        for widget, tip in (
            (getattr(self, 'spn_dens_min', None), min_tip),
            (getattr(self, 'lbl_dens_min', None), min_tip),
            (getattr(self, 'spn_dens_max', None), max_tip),
            (getattr(self, 'lbl_dens_max', None), max_tip),
        ):
            if widget is not None:
                widget.setToolTip(tip)

    def _auto_density_stretch(self, *_args):
        self.btn_dens_cut.blockSignals(True)
        self.btn_dens_cut.setChecked(True)
        self.btn_dens_cut.blockSignals(False)
        self.spn_dens_min.blockSignals(True)
        self.spn_dens_max.blockSignals(True)
        self.spn_dens_min.clearFocus()
        self.spn_dens_max.clearFocus()
        self.spn_dens_min.blockSignals(False)
        self.spn_dens_max.blockSignals(False)
        self._dens_stretch_user = False
        rst = self._first_density_raster()
        if rst is None:
            if self.density_on:
                self._rebuild_density()
            return
        self._sync_density_range(rst, reset=True)
        self._apply_density_stretch()

    def _schedule_density_stretch(self, *_args):
        if not self.density_on:
            return
        has_raster = any(
            D.split_pair(pair)[0] is not None for pair in self._density.values()
        )
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
        for key, pair in list(self._density.items()):
            rst, ctr = D.split_pair(pair)
            if rst is None:
                continue
            clip_min, clip_max = self._clip_for_raster(rst)
            self._density[key] = D.restyle_pair(
                rst, ctr, mode, levels, opacity, scheme=scheme,
                labels=labels, clip_min=clip_min, clip_max=clip_max,
                fill=self.density_fill,
                line_width=self._isoline_width(),
                invert=self._density_invert(),
            )
            styled = True
        if styled:
            self._refresh_canvases()
            self._refresh_density_scale()

    def _refresh_density_scale(self):
        """Show/hide the horizontal density scale in the Resources panel."""
        bar = getattr(self, '_dens_scale', None)
        inv = getattr(self, 'chk_dens_invert', None)
        if bar is None:
            return
        if (
            not self.density_on
            or self.density_mode == 'contours'
            or self.source is None
        ):
            bar.clear()
            if inv is not None:
                inv.hide()
            return
        rst = self._plan_density_raster() or self._first_density_raster()
        legend = D.heatmap_legend(rst) if rst is not None else None
        bar.set_legend(legend)
        if inv is not None:
            inv.setVisible(bar.isVisible())
            inv.setEnabled(bool(self.density_on and self.source is not None))

    def _on_density_scheme(self, *_args):
        if not self.density_on:
            return
        scheme = self._density_scheme()
        opacity = max(0.15, self.sld_dens_op.value() / 100.0)
        with_heat = self.density_mode in ('heatmap', 'both')
        styled = False
        for pair in self._density.values():
            rst, ctr = D.split_pair(pair)
            if rst is not None:
                clip_min, clip_max = self._clip_for_raster(rst)
                D.style_heatmap(
                    rst, opacity=opacity, scheme=scheme,
                    levels=self.spn_dens_levels.value(),
                    clip_min=clip_min, clip_max=clip_max,
                    fill=self.density_fill,
                    invert=self._density_invert(),
                )
                styled = True
            if ctr is not None:
                D.style_contours(
                    ctr, with_heatmap=with_heat, scheme=scheme,
                    labels=self._density_labels_on(),
                    width=self._isoline_width(),
                    invert=self._density_invert(),
                )
                styled = True
        if styled:
            self.plan.canvas.refresh()
            self.longp.canvas.refresh()
            self.transp.canvas.refresh()
            self._refresh_zooms()
            self._refresh_density_scale()

    def _density_labels_on(self):
        return bool(self.chk_dens_labels.isChecked())

    def _on_density_labels(self, *_args):
        self._sync_density_controls()
        if not self.density_on:
            return
        on = self._density_labels_on()
        if self.density_mode == 'heatmap':
            self._apply_density_stretch()
            return
        for pair in self._density.values():
            _rst, ctr = D.split_pair(pair)
            if ctr is not None:
                D.style_contour_labels(ctr, on=on)
        self.plan.canvas.refresh()
        self.longp.canvas.refresh()
        self.transp.canvas.refresh()
        self._refresh_zooms()

    def _isoline_width(self):
        return max(0.0, min(1.0, int(self.sld_dens_width.value()) / 100.0))

    def _on_density_width(self, value):
        mm = max(0.0, min(1.0, int(value) / 100.0))
        self.lbl_dens_width.setText('%.2f mm' % mm)
        if not self.density_on:
            return
        with_heat = self.density_mode in ('heatmap', 'both')
        styled = False
        for pair in self._density.values():
            _rst, ctr = D.split_pair(pair)
            if ctr is not None:
                D.style_contours(
                    ctr, with_heatmap=with_heat, scheme=self._density_scheme(),
                    labels=self._density_labels_on(), width=mm,
                    invert=self._density_invert(),
                )
                styled = True
        if styled:
            self._refresh_canvases()

    def _on_density_opacity(self, value):
        self.lbl_dens_op.setText('%d%%' % int(value))
        op = max(0.15, int(value) / 100.0)
        for pair in self._density.values():
            rst, _ctr = D.split_pair(pair)
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
            self._refresh_density_scale()
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
            with _qgis_busy('ARSYSplotQGIS: density'):
                for key, lyr in jobs:
                    if lyr is None or lyr.featureCount() < 2:
                        new_pairs[key] = (None, None)
                        continue
                    rad, pix = D.adapt_kernel(
                        lyr, radius, pixel,
                        None if key == 'plan' else self.source,
                    )
                    # UI Cell drives the KDE grid. Safety bounds (crest / memory)
                    # stay inside build_heatmap → _clamp_pixel.
                    new_pairs[key] = D.build_pair(
                        lyr, rad, pix, kernel, mode, levels, opacity,
                        scheme=self._density_scheme(),
                        labels=self._density_labels_on(),
                        clip_min=None, clip_max=None,
                        fill=self.density_fill,
                        line_width=self._isoline_width(),
                        invert=self._density_invert(),
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
            self._refresh_density_scale()
            if refresh:
                self._refresh_canvases()
            return
        self._drop_density_layers()
        self._density = new_pairs
        # Reflect the cell actually used by KDE (after memory/radius clamps).
        plan_rst, _ = D.split_pair(self._density.get('plan'))
        if plan_rst is not None:
            with suppress(AttributeError, RuntimeError, TypeError, ValueError):
                raw = plan_rst.customProperty('arsysplotqgis_cell')
                if raw not in (None, ''):
                    eff = float(raw)
                    if abs(eff - float(self.spn_dens_cell.value())) > 1e-9:
                        self.spn_dens_cell.blockSignals(True)
                        self.spn_dens_cell.setValue(eff)
                        self.spn_dens_cell.blockSignals(False)
        rst = self._first_density_raster()
        if rst is not None:
            self._sync_density_range(rst, reset=not self._dens_stretch_user)
            # Restyle applies Min/Max; canvases refreshed below.
            scheme = self._density_scheme()
            opacity = max(0.15, self.sld_dens_op.value() / 100.0)
            levels = self.spn_dens_levels.value()
            labels = self._density_labels_on()
            mode = self.density_mode
            for key, pair in list(self._density.items()):
                r, c = D.split_pair(pair)
                if r is None:
                    continue
                clip_min, clip_max = self._clip_for_raster(r)
                self._density[key] = D.restyle_pair(
                    r, c, mode, levels, opacity, scheme=scheme,
                    labels=labels, clip_min=clip_min, clip_max=clip_max,
                    fill=self.density_fill,
                    line_width=self._isoline_width(),
                    invert=self._density_invert(),
                )
            self._refresh_density_scale()
        else:
            self._refresh_density_scale()
        if refresh:
            self._refresh_canvases()

    def _line_width(self):
        return max(0.25, float(self.point_size) * 0.35)

    def _pane_key_and_points(self, pane):
        """Map a pane (main or zoom clone) to density key + point layer."""
        h = getattr(pane, 'h_axis', None)
        v = getattr(pane, 'v_axis', None)
        if h == 'x' and v == 'y':
            return 'plan', self.source
        if h == 'x' and v == 'z':
            return 'long', self.long_layer
        if h == 'y' and v == 'z':
            return 'trans', self.trans_layer
        if pane is self.plan:
            return 'plan', self.source
        if pane is self.longp:
            return 'long', self.long_layer
        if pane is self.transp:
            return 'trans', self.trans_layer
        return None, None

    def _pane_fit_layers(self, pane):
        """Point (and visible vector) layers that define the data footprint."""
        key, pts = self._pane_key_and_points(pane)
        if key == 'plan':
            lines = self.line_layer
        elif key == 'long':
            lines = self.long_line_layer
        elif key == 'trans':
            lines = self.trans_line_layer
        else:
            return []
        out = []
        if pts is not None:
            out.append(pts)
        if self.display_mode in ('vectors', 'both') and lines is not None:
            out.append(lines)
        return out

    def _pane_draw_layers(self, pane):
        """Points / vectors only (no density) for the current Draw mode."""
        key, pts = self._pane_key_and_points(pane)
        if key == 'plan':
            lines = self.line_layer
        elif key == 'long':
            lines = self.long_line_layer
        elif key == 'trans':
            lines = self.trans_line_layer
        else:
            return []
        mode = self.display_mode
        out = []
        if mode in ('points', 'both') and pts is not None:
            out.append(pts)
        if mode in ('vectors', 'both') and lines is not None:
            out.append(lines)
        return out

    def build_paper_density(self, pane, world, plot_w, plot_h, label_size_pt=None):
        """Ephemeral paper-resolution (raster, isolines); caller must release."""
        if not self.density_on:
            return None, None
        key, pts = self._pane_key_and_points(pane)
        if pts is None or pts.featureCount() < 2:
            return None, None
        radius = self.spn_dens_radius.value()
        pixel_ui = self.spn_dens_cell.value()
        kernel = self.cmb_dens_kernel.currentData()
        if kernel is None:
            kernel = 0
        rad, _pix = D.adapt_kernel(
            pts, radius, pixel_ui,
            None if key == 'plan' else self.source,
        )
        pix = D.paper_pixel(world, plot_w, plot_h, rad)
        mode = self.density_mode
        levels = self.spn_dens_levels.value()
        opacity = max(0.15, self.sld_dens_op.value() / 100.0)
        scheme = self._density_scheme()
        labels = self._density_labels_on()
        fill = self.density_fill
        line_width = self._isoline_width()
        invert = self._density_invert()
        rst, ctr = D.build_paper_pair(
            pts, rad, pix, kernel, mode, levels, opacity,
            scheme=scheme, labels=labels,
            clip_min=None, clip_max=None,
            fill=fill, line_width=line_width, invert=invert,
        )
        if rst is None:
            return None, None
        clip_min, clip_max = self._clip_for_raster(rst)
        rst, ctr = D.restyle_pair(
            rst, ctr, mode, levels, opacity, scheme=scheme,
            labels=labels, clip_min=clip_min, clip_max=clip_max,
            fill=fill, line_width=line_width, invert=invert,
        )
        if labels and ctr is not None:
            D.style_contour_labels(ctr, on=True, size_pt=label_size_pt)
        return rst, ctr

    def _pane_layers(self, pane):
        key, _pts = self._pane_key_and_points(pane)
        out = list(self._pane_draw_layers(pane))
        if self.density_on and key is not None:
            rst, ctr = D.split_pair(self._density.get(key))
            # QgsMapCanvas: first = topmost. Isolines above KDE raster fill.
            if ctr is not None:
                out.append(ctr)
            if self.density_mode in ('heatmap', 'both') and rst is not None:
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
            with suppress(AttributeError, RuntimeError, TypeError, ValueError):
                win.reload(layers, pane.canvas)
                win.show()
                win.raise_()
                win.activateWindow()
                return
        win = ZoomWindow(pane, layers, parent=self)
        self._zoom_windows[key] = win
        win.show()
        win.raise_()
        win.activateWindow()

    def _refresh_zooms(self):
        kept = {}
        for key, win in list(self._zoom_windows.items()):
            _ok = False
            with suppress(AttributeError, RuntimeError, TypeError, ValueError):
                visible = win.isVisible()
                _ok = True
            if not _ok:
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
        with _qgis_busy('ARSYSplotQGIS: 3D view'):
            view3d.open_3d_view(
                self.iface, self.source, parent=self,
                group_field=self.group_field,
                display_mode=self._draw_mode_for_3d(),
                arrow_size=self.arrow_size,
            )
