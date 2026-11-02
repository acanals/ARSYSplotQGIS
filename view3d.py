# -*- coding: utf-8 -*-
"""
3D viewer inside the plugin.

Native QGIS 3D copies the main canvas / crashes 3.40.
Matplotlib 3D scatter blanks and freezes when point size changes.
This viewer projects the PointZ cloud with Qt (orbit / pan / zoom).
"""
from contextlib import suppress
import math

from qgis.core import QgsCategorizedSymbolRenderer
from qgis.PyQt.QtCore import Qt, QPointF
from qgis.PyQt.QtGui import (
    QBrush,
    QColor,
    QImage,
    QMatrix4x4,
    QPainter,
    QPen,
    QPolygonF,
    QVector3D,
)
from qgis.PyQt.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from . import export_dialog as E
from .colors_util import color_for_index, css_hex
from .layers import (
    ARROW_MM_DEFAULT,
    ARROW_MM_MIN,
    ARROW_SLIDER_MAX,
    EMPTY_LABEL,
    arrow_mm_from_slider,
    arrow_px_from_mm,
    arrow_slider_from_mm,
    group_label,
    html_tooltip,
    vector_endpoints,
)


SIZE_SLIDER_MAX = 100
SIZE_PX_MIN = 0.8
SIZE_PX_MAX = 10.0
SIZE_PX_DEFAULT = 3.5
SIZE_SLIDER_GAMMA = 1.7


def size_px_from_slider(value):
    t = max(0.0, min(1.0, int(value) / float(SIZE_SLIDER_MAX)))
    px = SIZE_PX_MIN + (SIZE_PX_MAX - SIZE_PX_MIN) * (t ** SIZE_SLIDER_GAMMA)
    return round(px, 2)


def size_slider_from_px(px):
    px = max(SIZE_PX_MIN, min(SIZE_PX_MAX, float(px)))
    t = (px - SIZE_PX_MIN) / (SIZE_PX_MAX - SIZE_PX_MIN)
    t = t ** (1.0 / SIZE_SLIDER_GAMMA)
    return int(round(t * SIZE_SLIDER_MAX))


def _arrow_head_polygon(ax, ay, bx, by, size):
    dx = bx - ax
    dy = by - ay
    length = math.hypot(dx, dy)
    if length < 4.0 or size <= 0:
        return None
    ux, uy = dx / length, dy / length
    px, py = -uy, ux
    back = size
    wing = size * 0.55
    return QPolygonF([
        QPointF(bx, by),
        QPointF(bx - ux * back + px * wing, by - uy * back + py * wing),
        QPointF(bx - ux * back - px * wing, by - uy * back - py * wing),
    ])


def _feature_xyz(feat):
    geom = feat.geometry()
    if geom is None or geom.isEmpty():
        return None
    pt = geom.constGet()
    try:
        x, y = float(pt.x()), float(pt.y())
        z = float(pt.z()) if pt.is3D() else 0.0
    except Exception:
        return None
    if feat.fields().lookupField('p1z') >= 0:
        with suppress(AttributeError, RuntimeError, TypeError, ValueError):
            pz = feat['p1z']
            if pz is not None:
                z = float(pz)
    return x, y, z


def _group_value(feat, field=None):
    names = []
    if field:
        names.append(field)
    names.extend(('group', 'Material', 'material'))
    seen = set()
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        idx = feat.fields().lookupField(name)
        if idx < 0:
            continue
        return group_label(feat[name])
    return EMPTY_LABEL


def _color_lookup(layer):
    lookup = {}
    renderer = layer.renderer()
    if isinstance(renderer, QgsCategorizedSymbolRenderer):
        for cat in renderer.categories():
            keys = [group_label(cat.value()), group_label(cat.label())]
            sym = cat.symbol()
            color = QColor('#4a90d9')
            with suppress(AttributeError, RuntimeError, TypeError, ValueError):
                color = sym.color()
            for key in keys:
                if key:
                    lookup[key] = color
    return lookup


def _collect_points(layer, group_field=None):
    lookup = _color_lookup(layer)
    xs, ys, zs, cols, groups = [], [], [], [], []
    segs = []
    extra = 0
    for feat in layer.getFeatures():
        xyz = _feature_xyz(feat)
        g = _group_value(feat, group_field)
        color = lookup.get(g)
        if color is None:
            color = color_for_index(extra, 12)
            lookup[g] = color
            extra += 1
        if xyz is not None:
            x, y, z = xyz
            xs.append(x)
            ys.append(y)
            zs.append(z)
            cols.append(color)
            groups.append(g)
        ends = vector_endpoints(feat)
        if ends is not None:
            segs.append((ends[0], ends[1], color, g))
    return xs, ys, zs, cols, groups, lookup, segs


class CloudWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(480, 360)
        self.setMouseTracking(True)
        self._wx = []
        self._wy = []
        self._wz = []
        self._cols = []
        self._groups = []
        self._active = set()
        self._radius = SIZE_PX_DEFAULT
        self._yaw = -0.9
        self._pitch = 0.45
        self._dist = 12.0
        self._pan = QVector3D(0, 0, 0)
        self._center = QVector3D(0, 0, 0)
        self._radius_world = 1.0
        self._last = None
        self._drag = None
        self._sort_cache = None
        self._paper = False
        self._seg_a = []
        self._seg_b = []
        self._seg_cols = []
        self._seg_groups = []
        self._draw_points = True
        self._draw_vectors = True
        self._arrow = arrow_px_from_mm(ARROW_MM_DEFAULT)

    def set_draw_mode(self, mode):
        self._draw_points = mode in ('points', 'both', None)
        self._draw_vectors = mode in ('vectors', 'both')
        self.update()

    def set_cloud(self, xs, ys, zs, cols, groups, keep_camera=False, segs=None):
        segs = segs or []
        if not xs and not segs:
            self._wx = []
            self._wy = []
            self._wz = []
            self._cols = []
            self._groups = []
            self._seg_a = []
            self._seg_b = []
            self._seg_cols = []
            self._seg_groups = []
            self.update()
            return
        z_src = list(zs)
        for a, b, _c, _g in segs:
            z_src.append(a[2])
            z_src.append(b[2])
        z_floor = min(z_src) if z_src else 0.0
        wx = list(xs)
        wy = [z - z_floor for z in zs]
        wz = [-y for y in ys]
        all_x = list(wx)
        all_y = list(wy)
        all_z = list(wz)
        for a, b, _c, _g in segs:
            for pt in (a, b):
                all_x.append(pt[0])
                all_y.append(pt[2] - z_floor)
                all_z.append(-pt[1])
        n_all = max(len(all_x), 1)
        cx = sum(all_x) / n_all
        cy = sum(all_y) / n_all
        cz = sum(all_z) / n_all
        self._center = QVector3D(cx, cy, cz)
        self._wx = [v - cx for v in wx]
        self._wy = [v - cy for v in wy]
        self._wz = [v - cz for v in wz]
        self._cols = list(cols)
        self._groups = list(groups)
        self._active = set(groups)
        for _a, _b, _c, g in segs:
            self._active.add(g)
        self._seg_a = []
        self._seg_b = []
        self._seg_cols = []
        self._seg_groups = []
        for a, b, color, g in segs:
            va = QVector3D(a[0] - cx, a[2] - z_floor, -a[1] - cz)
            vb = QVector3D(b[0] - cx, b[2] - z_floor, -b[1] - cz)
            self._seg_a.append(va)
            self._seg_b.append(vb)
            self._seg_cols.append(color)
            self._seg_groups.append(g)
        hx = hy = hz = 0.0
        for i in range(len(self._wx)):
            hx = max(hx, abs(self._wx[i]))
            hy = max(hy, abs(self._wy[i]))
            hz = max(hz, abs(self._wz[i]))
        for vec in self._seg_a + self._seg_b:
            hx = max(hx, abs(vec.x()))
            hy = max(hy, abs(vec.y()))
            hz = max(hz, abs(vec.z()))
        self._radius_world = max(hx, hy, hz, 0.2)
        self._sort_cache = None
        if keep_camera:
            self.update()
            return
        self._pan = QVector3D(0, 0, 0)
        self.fit()

    def set_active(self, groups):
        self._active = set(groups)
        self._sort_cache = None
        self.update()

    def set_radius(self, px):
        self._radius = max(0.5, float(px))
        self.update()

    def set_arrow(self, px):
        self._arrow = max(2.0, float(px))
        self.update()

    def fit(self):
        self._pan = QVector3D(0, 0, 0)
        half_fov = math.radians(21.0)
        self._dist = max(
            self._radius_world / max(math.tan(half_fov), 1e-6) * 1.08,
            0.8,
        )
        self._sort_cache = None
        self.update()

    def _eye(self):
        cp = math.cos(self._pitch)
        sp = math.sin(self._pitch)
        cy = math.cos(self._yaw)
        sy = math.sin(self._yaw)
        return QVector3D(
            self._pan.x() + self._dist * cp * sy,
            self._pan.y() + self._dist * sp,
            self._pan.z() + self._dist * cp * cy,
        )

    def _mvp(self, w=None, h=None):
        w = max(w if w is not None else self.width(), 1)
        h = max(h if h is not None else self.height(), 1)
        proj = QMatrix4x4()
        proj.perspective(42.0, w / float(h), 0.02, max(self._dist * 20.0, 50.0))
        view = QMatrix4x4()
        view.lookAt(self._eye(), self._pan, QVector3D(0, 1, 0))
        return proj * view

    def paintEvent(self, _event):
        p = QPainter(self)
        bg = QColor('#ffffff') if self._paper else QColor('#141210')
        self._paint_cloud(p, self.width(), self.height(), bg, self._paper, 1.0)

    def _paint_cloud(self, p, w, h, bg, paper, scale):
        p.fillRect(0, 0, w, h, bg)
        n = len(self._wx)
        nseg = len(self._seg_a)
        if not n and not nseg:
            p.setPen(QColor('#444') if paper else QColor('#bbb'))
            p.drawText(0, 0, w, h, Qt.AlignCenter, 'No points')
            return
        mvp = self._mvp(w, h)
        items = []
        active = self._active
        if self._draw_points:
            for i in range(n):
                if self._groups[i] not in active:
                    continue
                v = mvp.map(QVector3D(self._wx[i], self._wy[i], self._wz[i]))
                if v.z() < -1.2 or v.z() > 1.2:
                    continue
                sx = (v.x() + 1.0) * 0.5 * w
                sy = (1.0 - v.y()) * 0.5 * h
                items.append((v.z(), 1, sx, sy, i))
        if self._draw_vectors:
            for i in range(nseg):
                if self._seg_groups[i] not in active:
                    continue
                va = mvp.map(self._seg_a[i])
                vb = mvp.map(self._seg_b[i])
                a_out = va.z() < -1.2 or va.z() > 1.2
                b_out = vb.z() < -1.2 or vb.z() > 1.2
                if a_out and b_out:
                    continue
                ax = (va.x() + 1.0) * 0.5 * w
                ay = (1.0 - va.y()) * 0.5 * h
                bx = (vb.x() + 1.0) * 0.5 * w
                by = (1.0 - vb.y()) * 0.5 * h
                items.append((0.5 * (va.z() + vb.z()), 0, ax, ay, bx, by, i))
        items.sort(key=lambda t: t[0], reverse=True)
        r = self._radius * scale
        line_w = max(1.0, self._radius * 0.45) * scale
        if self._drag is None:
            p.setRenderHint(QPainter.Antialiasing, True)
        for item in items:
            if item[1] == 0:
                _z, _k, ax, ay, bx, by, i = item
                col = self._seg_cols[i]
                p.setPen(QPen(col, line_w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                p.drawLine(QPointF(ax, ay), QPointF(bx, by))
                head = _arrow_head_polygon(ax, ay, bx, by, self._arrow * scale)
                if head is not None:
                    p.setPen(Qt.NoPen)
                    p.setBrush(QBrush(col))
                    p.drawPolygon(head)
            else:
                _z, _k, sx, sy, i = item
                p.setPen(Qt.NoPen)
                p.setBrush(self._cols[i])
                p.drawEllipse(QPointF(sx, sy), r, r)
        p.setBrush(Qt.NoBrush)
        origin = mvp.map(QVector3D(0, 0, 0))
        ox = (origin.x() + 1.0) * 0.5 * w
        oy = (1.0 - origin.y()) * 0.5 * h
        axis_len = max(self._radius_world * 0.18, 0.15)
        pen_w = max(1.0, 2.0 * scale)
        for vec, color in (
            (QVector3D(axis_len, 0, 0), QColor('#e07070')),
            (QVector3D(0, axis_len, 0), QColor('#70c070')),
            (QVector3D(0, 0, axis_len), QColor('#7090e0')),
        ):
            end = mvp.map(vec)
            p.setPen(QPen(color, pen_w))
            p.drawLine(
                QPointF(ox, oy),
                QPointF((end.x() + 1.0) * 0.5 * w, (1.0 - end.y()) * 0.5 * h),
            )

    def mousePressEvent(self, event):
        self._last = event.pos()
        if event.button() == Qt.LeftButton:
            self._drag = 'orbit'
        elif event.button() == Qt.RightButton:
            self._drag = 'pan'
        else:
            self._drag = None

    def mouseMoveEvent(self, event):
        if self._drag is None or self._last is None:
            return
        d = event.pos() - self._last
        self._last = event.pos()
        if self._drag == 'orbit':
            self._yaw += d.x() * 0.008
            self._pitch = max(-1.35, min(1.35, self._pitch + d.y() * 0.008))
        else:
            scale = self._dist * 0.0025
            cy = math.cos(self._yaw)
            sy = math.sin(self._yaw)
            right = QVector3D(cy, 0, -sy)
            up = QVector3D(0, 1, 0)
            self._pan = self._pan - right * (d.x() * scale) + up * (d.y() * scale)
        self.update()

    def mouseReleaseEvent(self, _event):
        self._drag = None
        self.update()

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta == 0:
            delta = event.pixelDelta().y()
        factor = 0.9 if delta > 0 else 1.1
        self._dist = max(self._radius_world * 0.15, min(self._radius_world * 30.0, self._dist * factor))
        self.update()


class Scatter3DDialog(QDialog):
    def __init__(self, layer, parent=None, group_field=None, display_mode='points', arrow_size=None):
        super().__init__(parent)
        self.layer = layer
        self._group_field = group_field
        self._display_mode = display_mode or 'points'
        self._arrow_size = max(ARROW_MM_MIN, float(arrow_size or ARROW_MM_DEFAULT))
        self.setWindowTitle('ARSYSplotQGIS · 3D')
        self.resize(980, 720)
        self.setStyleSheet(
            'QDialog { background:#1a1816; color:#fff5e6; }'
            'QWidget { background:#1a1816; color:#fff5e6; }'
            'QLabel { background:transparent; color:#ddd; }'
            'QPushButton { background:#2a2622; color:#fff5e6; border:1px solid #4a453e;'
            '  border-radius:4px; padding:4px 8px; }'
            'QPushButton:hover { background:#3a3530; }'
            'QPushButton:checked { background:#d97726; border-color:#f0a15a; color:#fff8ee; }'
            'QPushButton:disabled { color:#6b645c; }'
            'QScrollArea, QAbstractScrollArea, QAbstractScrollArea::viewport {'
            '  background:#1a1816; border:none; }'
            'QSlider::groove:horizontal { background:#2a2622; height:6px; border-radius:3px; }'
            'QSlider::handle:horizontal { background:#d97726; width:12px; margin:-4px 0;'
            '  border-radius:6px; }'
            'QToolTip { background-color:#fff8ee; color:#1a1816;'
            '  border:1px solid #8a8178; padding:4px 7px; font-size:10px; }'
        )

        bar = QHBoxLayout()
        bar.setSpacing(6)
        bar.addWidget(QLabel('Draw'))
        self.btn_draw_points = QPushButton('Points')
        self.btn_draw_vectors = QPushButton('Vectors')
        self.btn_draw_both = QPushButton('Both')
        self._draw_group = QButtonGroup(self)
        self._draw_group.setExclusive(True)
        for btn in (self.btn_draw_points, self.btn_draw_vectors, self.btn_draw_both):
            btn.setCheckable(True)
            self._draw_group.addButton(btn)
        self.btn_draw_points.setToolTip(html_tooltip('**P1:** object centre.'))
        self.btn_draw_vectors.setToolTip(html_tooltip(
            '**P2→P3** after import. If only P1→P2, that axis is used.',
        ))
        self.btn_draw_both.setToolTip(html_tooltip(
            '**Centre** and **axis** of each object.',
        ))
        self.btn_draw_vectors.setEnabled(False)
        self.btn_draw_both.setEnabled(False)
        self.btn_draw_points.clicked.connect(lambda: self.set_draw_mode('points'))
        self.btn_draw_vectors.clicked.connect(lambda: self.set_draw_mode('vectors'))
        self.btn_draw_both.clicked.connect(lambda: self.set_draw_mode('both'))
        bar.addWidget(self.btn_draw_points)
        bar.addWidget(self.btn_draw_vectors)
        bar.addWidget(self.btn_draw_both)

        bar.addWidget(QLabel('Size'))
        self._size_label = QLabel('%.2f px' % SIZE_PX_DEFAULT)
        self._size_label.setMinimumWidth(48)
        slider = QSlider(Qt.Horizontal)
        slider.setRange(0, SIZE_SLIDER_MAX)
        slider.setSingleStep(1)
        slider.setPageStep(5)
        slider.setValue(size_slider_from_px(SIZE_PX_DEFAULT))
        slider.setMinimumWidth(56)
        slider.setMaximumWidth(96)
        slider.setToolTip(html_tooltip(
            'Point radius. Unit: **px**. Fine below 4; max **10**.',
        ))
        slider.valueChanged.connect(self._on_size)
        bar.addWidget(slider)
        bar.addWidget(self._size_label)
        bar.addWidget(QLabel('Arrow'))
        self._arrow_label = QLabel('%.2f mm' % self._arrow_size)
        self._arrow_label.setMinimumWidth(48)
        self._arrow_slider = QSlider(Qt.Horizontal)
        self._arrow_slider.setRange(0, ARROW_SLIDER_MAX)
        self._arrow_slider.setSingleStep(1)
        self._arrow_slider.setPageStep(5)
        self._arrow_slider.setValue(arrow_slider_from_mm(self._arrow_size))
        self._arrow_slider.setMinimumWidth(56)
        self._arrow_slider.setMaximumWidth(96)
        self._arrow_slider.setToolTip(html_tooltip(
            'Arrow-head size. Unit: **mm**.',
        ))
        self._arrow_slider.valueChanged.connect(self._on_arrow)
        bar.addWidget(self._arrow_slider)
        bar.addWidget(self._arrow_label)
        bar.addStretch(1)
        fit = QPushButton('Fit')
        fit.clicked.connect(self._fit)
        bar.addWidget(fit)
        export_btn = QPushButton('Export PNG')
        export_btn.setToolTip(html_tooltip(
            'Export 3D **PNG** with axes.',
        ))
        export_btn.clicked.connect(self._export_image)
        bar.addWidget(export_btn)
        close_btn = QPushButton('Close')
        close_btn.clicked.connect(self.close)
        bar.addWidget(close_btn)

        filt = QHBoxLayout()
        filt.addWidget(QLabel('Group'))
        btn_all = QPushButton('All')
        btn_none = QPushButton('None')
        btn_inv = QPushButton('Invert')
        btn_all.clicked.connect(lambda: self._set_all(True))
        btn_none.clicked.connect(lambda: self._set_all(False))
        btn_inv.clicked.connect(self._invert)
        filt.addWidget(btn_all)
        filt.addWidget(btn_none)
        filt.addWidget(btn_inv)
        self._group_btns = {}
        gwrap = QWidget()
        gwrap.setStyleSheet('background:#1a1816;')
        self._group_layout = QHBoxLayout(gwrap)
        self._group_layout.setContentsMargins(0, 0, 0, 0)
        self._group_layout.setSpacing(4)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(gwrap)
        scroll.setFixedHeight(42)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            'QScrollArea { border:none; background:#1a1816; }'
            'QScrollArea > QWidget > QWidget { background:#1a1816; }'
        )
        scroll.viewport().setStyleSheet('background:#1a1816;')
        filt.addWidget(scroll, 1)

        self.cloud = CloudWidget()
        hint = QLabel(
            'Left-drag rotate · right-drag pan · wheel zoom. '
            'P1 = centre · vector = P2→P3.'
        )
        hint.setStyleSheet('color:#999;')

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addLayout(bar)
        layout.addLayout(filt)
        layout.addWidget(self.cloud, 1)
        layout.addWidget(hint)
        self.cloud.set_draw_mode(self._display_mode)
        self.set_arrow_size(self._arrow_size, sync_slider=False)
        self.reload(group_field, keep_camera=False)

    def set_draw_mode(self, mode):
        self._display_mode = mode or 'points'
        if hasattr(self, 'cloud'):
            self.cloud.set_draw_mode(self._display_mode)
        self._sync_draw_buttons()

    def _sync_draw_buttons(self):
        if not hasattr(self, 'btn_draw_points'):
            return
        mapping = {
            'points': self.btn_draw_points,
            'vectors': self.btn_draw_vectors,
            'both': self.btn_draw_both,
        }
        btn = mapping.get(self._display_mode, self.btn_draw_points)
        if not btn.isEnabled():
            btn = self.btn_draw_points
        btn.blockSignals(True)
        btn.setChecked(True)
        btn.blockSignals(False)

    def set_arrow_size(self, mm, sync_slider=True):
        self._arrow_size = max(ARROW_MM_MIN, float(mm))
        self.cloud.set_arrow(arrow_px_from_mm(self._arrow_size))
        if sync_slider and hasattr(self, '_arrow_slider'):
            self._arrow_slider.blockSignals(True)
            self._arrow_slider.setValue(arrow_slider_from_mm(self._arrow_size))
            self._arrow_slider.blockSignals(False)
            self._arrow_label.setText('%.2f mm' % self._arrow_size)

    def reload(self, group_field=None, keep_camera=True, display_mode=None, arrow_size=None):
        if group_field:
            self._group_field = group_field
        if display_mode is not None:
            self._display_mode = display_mode or 'points'
        if arrow_size is not None:
            self.set_arrow_size(arrow_size)
        xs, ys, zs, cols, groups, lookup, segs = _collect_points(
            self.layer, self._group_field
        )
        self._lookup = lookup
        self.cloud.set_cloud(
            xs, ys, zs, cols, groups, keep_camera=keep_camera, segs=segs
        )
        has_vectors = bool(segs)
        if hasattr(self, 'btn_draw_vectors'):
            self.btn_draw_vectors.setEnabled(has_vectors)
            self.btn_draw_both.setEnabled(has_vectors)
            if not has_vectors and self._display_mode in ('vectors', 'both'):
                self._display_mode = 'points'
            self.cloud.set_draw_mode(self._display_mode)
            self._sync_draw_buttons()
        filter_groups = list(groups)
        for _a, _b, _c, g in segs:
            filter_groups.append(g)
        self._rebuild_group_filters(filter_groups, lookup)

    def _rebuild_group_filters(self, groups, lookup):
        prev_active = {
            g for g, b in self._group_btns.items() if b.isChecked()
        }
        prev_keys = set(self._group_btns)
        while self._group_layout.count():
            item = self._group_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._group_btns = {}
        unique = []
        seen = set()
        for g in groups:
            if g not in seen:
                unique.append(g)
                seen.add(g)
        keep = prev_keys == set(unique) and bool(prev_keys)
        for val in unique:
            btn = QPushButton(val)
            btn.setCheckable(True)
            btn.setChecked((val in prev_active) if keep else True)
            color = lookup.get(val, QColor('#888'))
            hexcol = css_hex(color)
            btn.setStyleSheet(
                'QPushButton { background:%s; color:#fff; border:1px solid #4a453e;'
                '  border-radius:4px; padding:3px 8px; max-width:14em; }'
                'QPushButton:hover { border-color:#c8c2b8; }'
                'QPushButton:!checked { background:#5a554e; color:#c8c2b8;'
                '  border-color:#3a342e; }'
                % hexcol
            )
            btn.toggled.connect(lambda _on, v=val: self._sync_groups())
            self._group_layout.addWidget(btn)
            self._group_btns[val] = btn
        self._group_layout.addStretch(1)
        self._sync_groups()

    def _on_size(self, value):
        radius = size_px_from_slider(value)
        self._size_label.setText('%.2f px' % radius)
        self.cloud.set_radius(radius)

    def _on_arrow(self, value):
        self.set_arrow_size(arrow_mm_from_slider(value), sync_slider=False)
        self._arrow_label.setText('%.2f mm' % self._arrow_size)

    def _fit(self):
        self.cloud.fit()

    def _export_image(self):
        layer_name = self.layer.name() if self.layer is not None else ''
        dlg = E.ExportImageDialog(
            self, title='3D', subtitle=layer_name, bg=QColor('#ffffff')
        )
        exec_fn = getattr(dlg, 'exec', None) or dlg.exec_
        if exec_fn() != dlg.Accepted:
            return
        opts = dlg.values()
        path, _flt = QFileDialog.getSaveFileName(
            self, 'Export image', 'ARSYSplotQGIS_3D.png', 'PNG (*.png)'
        )
        if not path:
            return
        if not path.lower().endswith('.png'):
            path += '.png'
        dpi = opts['dpi']
        scale = E.scale_for_dpi(dpi)
        bg = opts['bg']
        paper = E.is_light_color(bg)
        src_w = max(self.cloud.width(), 1)
        src_h = max(self.cloud.height(), 1)
        out_w = max(1, int(round(src_w * scale)))
        out_h = max(1, int(round(src_h * scale)))
        head_h = E.header_height(opts['title'], opts['subtitle'], scale)
        img = QImage(out_w, out_h + head_h, QImage.Format_ARGB32_Premultiplied)
        E.apply_png_dpi(img, dpi)
        img.fill(bg)
        painter = QPainter(img)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        if head_h:
            E.draw_header(
                painter, out_w, opts['title'], opts['subtitle'], bg, scale
            )
        painter.translate(0, head_h)
        self.cloud._paint_cloud(painter, out_w, out_h, bg, paper, scale)
        painter.end()
        if img.isNull() or not img.save(path, 'PNG'):
            QMessageBox.warning(self, 'Export', 'Could not write %s' % path)

    def _sync_groups(self):
        active = [g for g, b in self._group_btns.items() if b.isChecked()]
        self.cloud.set_active(active)

    def _set_all(self, on):
        for btn in self._group_btns.values():
            btn.blockSignals(True)
            btn.setChecked(on)
            btn.blockSignals(False)
        self._sync_groups()

    def _invert(self):
        for btn in self._group_btns.values():
            btn.blockSignals(True)
            btn.setChecked(not btn.isChecked())
            btn.blockSignals(False)
        self._sync_groups()


def open_3d_view(iface, layer, parent=None, group_field=None, display_mode='points', arrow_size=None):
    if layer is None:
        QMessageBox.warning(parent, '3D', 'No point layer loaded.')
        return False
    live = []
    for dlg in getattr(iface, '_arsysplotqgis_3d', []):
        with suppress(AttributeError, RuntimeError, TypeError, ValueError):
            if dlg.isVisible() and dlg.layer == layer:
                live.append(dlg)
    if live:
        dlg = live[-1]
        dlg.reload(
            group_field, keep_camera=True,
            display_mode=display_mode, arrow_size=arrow_size,
        )
        dlg.raise_()
        dlg.activateWindow()
        return True
    dlg = Scatter3DDialog(
        layer, parent or iface.mainWindow(),
        group_field=group_field, display_mode=display_mode,
        arrow_size=arrow_size,
    )
    dlg.show()
    if not hasattr(iface, '_arsysplotqgis_3d'):
        iface._arsysplotqgis_3d = []
    iface._arsysplotqgis_3d.append(dlg)
    return True


def apply_open_arrow_size(iface, arrow_size):
    for dlg in getattr(iface, '_arsysplotqgis_3d', []):
        with suppress(AttributeError, RuntimeError, TypeError, ValueError):
            if dlg.isVisible():
                dlg.set_arrow_size(arrow_size)


def refresh_open_views(iface, layer, group_field=None, display_mode=None, arrow_size=None):
    kept = []
    for dlg in getattr(iface, '_arsysplotqgis_3d', []):
        _ok = False
        with suppress(AttributeError, RuntimeError, TypeError, ValueError):
            visible = dlg.isVisible()
            _ok = True
        if not _ok:
            continue
        if not visible:
            continue
        kept.append(dlg)
        if layer is None or dlg.layer == layer:
            dlg.reload(
                group_field, keep_camera=True,
                display_mode=display_mode, arrow_size=arrow_size,
            )
    if hasattr(iface, '_arsysplotqgis_3d'):
        iface._arsysplotqgis_3d = kept
