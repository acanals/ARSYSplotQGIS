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
from qgis.PyQt.QtCore import QRect, QRectF, QSize, Qt, QPointF
from qgis.PyQt.QtGui import (
    QBrush,
    QColor,
    QFont,
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
from .axes_grid import (
    PAPER_BG,
    PAPER_FAINT,
    PAPER_FRAME_MM,
    PAPER_INK,
    PAPER_MUTED,
    paper_legend_below_height_mm,
    paper_legend_plan,
    paint_paper_legend,
)
from .layers import (
    ARROW_MM_DEFAULT,
    ARROW_MM_MIN,
    ARROW_SLIDER_MAX,
    DEFAULT_MARKER,
    EMPTY_LABEL,
    VECTOR_LEN_CM_DEFAULT,
    _symbol_marker_shape,
    arrow_mm_from_slider,
    arrow_px_from_mm,
    arrow_slider_from_mm,
    group_label,
    html_tooltip,
    resolve_marker_shape,
    set_tooltip_chrome,
    vector_draw_endpoints,
)


SIZE_SLIDER_MAX = 100
SIZE_PX_MIN = 0.8
SIZE_PX_MAX = 10.0
SIZE_PX_DEFAULT = 3.5
SIZE_SLIDER_GAMMA = 1.7

# Compass / box evaluation (no export-dialog toggle yet).
_COMPASS_NICE_M = (0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0)


def _fmt_metre(value):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return '?'
    if abs(v - round(v)) < 5e-3:
        return '%d' % int(round(v))
    if abs(v) >= 100:
        return '%.1f' % v
    return ('%.2f' % v).rstrip('0').rstrip('.')


def _pick_nice_metres(px_per_m, target_px=36.0):
    """Choose a round length (m) so that length×px/m ≈ target_px."""
    ppm = max(float(px_per_m), 1e-9)
    need = max(0.05, float(target_px) / ppm)
    for cand in _COMPASS_NICE_M:
        if cand >= need - 1e-12:
            return float(cand)
    return float(_COMPASS_NICE_M[-1])


_BOX_TICK_STEPS_M = (
    0.01, 0.02, 0.05, 0.1, 0.2, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 50.0, 100.0,
)


def _nice_box_tick_step(length_m, target_ticks=5):
    """Round metre step so an edge of ``length_m`` gets about ``target_ticks`` marks."""
    length_m = abs(float(length_m))
    if length_m < 1e-9:
        return 0.1
    raw = length_m / max(float(target_ticks), 1.0)
    for cand in _BOX_TICK_STEPS_M:
        if cand >= raw - 1e-12:
            return float(cand)
    return float(_BOX_TICK_STEPS_M[-1])


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
    # Fixed shafts can be short on screen; still draw a head (clamped to shaft).
    if length < 1.5 or size <= 0:
        return None
    ux, uy = dx / length, dy / length
    px, py = -uy, ux
    back = min(float(size), length * 0.9)
    wing = back * 0.55
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


def _shape_lookup(layer):
    """Point-model shapes from categorised symbols (legend / export)."""
    shapes = {}
    renderer = layer.renderer() if layer is not None else None
    if not isinstance(renderer, QgsCategorizedSymbolRenderer):
        return shapes
    for cat in renderer.categories():
        keys = [group_label(cat.value()), group_label(cat.label())]
        shape = DEFAULT_MARKER
        with suppress(AttributeError, RuntimeError, TypeError, ValueError):
            shape = resolve_marker_shape(_symbol_marker_shape(cat.symbol()))
        for key in keys:
            if key:
                shapes[key] = shape
    return shapes


def _collect_points(layer, group_field=None, vector_fixed=False, vector_len_cm=VECTOR_LEN_CM_DEFAULT):
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
        ends = vector_draw_endpoints(
            feat, fixed=vector_fixed, fixed_cm=vector_len_cm,
        )
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
        self._screen_bg = QColor('#141210')
        self._seg_a = []
        self._seg_b = []
        self._seg_cols = []
        self._seg_groups = []
        self._draw_points = True
        self._draw_vectors = True
        self._show_axes = True
        self._show_bbox = True
        self._show_bbox_labels = True
        self._box_min = None
        self._box_max = None
        self._anchor_cx = 0.0
        self._anchor_cy = 0.0
        self._anchor_cz = 0.0
        self._z_floor = 0.0
        self._arrow = arrow_px_from_mm(ARROW_MM_DEFAULT)
        self._last_compass_m = 1.0

    def set_screen_bg(self, color):
        self._screen_bg = QColor(color)
        self.update()

    def set_show_axes(self, on):
        self._show_axes = bool(on)
        self.update()

    def set_show_bbox(self, on):
        self._show_bbox = bool(on)
        self.update()

    def set_show_bbox_labels(self, on):
        self._show_bbox_labels = bool(on)
        self.update()

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
            self._box_min = None
            self._box_max = None
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
        self._anchor_cx = float(cx)
        self._anchor_cy = float(cy)
        self._anchor_cz = float(cz)
        self._z_floor = float(z_floor)
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
        bx0 = list(self._wx)
        by0 = list(self._wy)
        bz0 = list(self._wz)
        for vec in self._seg_a + self._seg_b:
            bx0.append(vec.x())
            by0.append(vec.y())
            bz0.append(vec.z())
        if bx0:
            self._box_min = QVector3D(min(bx0), min(by0), min(bz0))
            self._box_max = QVector3D(max(bx0), max(by0), max(bz0))
        else:
            self._box_min = self._box_max = None
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

    def _camera_state(self):
        return (
            float(self._yaw), float(self._pitch), float(self._dist),
            QVector3D(self._pan),
        )

    def _restore_camera(self, state):
        self._yaw, self._pitch, self._dist, self._pan = state
        self._sort_cache = None

    def _box_corners(self):
        b0, b1 = self._box_min, self._box_max
        if b0 is None or b1 is None:
            r = max(float(self._radius_world), 0.2)
            b0 = QVector3D(-r, -r, -r)
            b1 = QVector3D(r, r, r)
        x0, y0, z0 = float(b0.x()), float(b0.y()), float(b0.z())
        x1, y1, z1 = float(b1.x()), float(b1.y()), float(b1.z())
        return (
            QVector3D(x0, y0, z0), QVector3D(x1, y0, z0),
            QVector3D(x0, y1, z0), QVector3D(x1, y1, z0),
            QVector3D(x0, y0, z1), QVector3D(x1, y0, z1),
            QVector3D(x0, y1, z1), QVector3D(x1, y1, z1),
        )

    def _projected_ndc_bounds(self, w, h):
        """Axis-aligned NDC bounds of the data AABB, or None if not projectable."""
        mvp = self._mvp(w, h)
        xs, ys = [], []
        for corner in self._box_corners():
            v = mvp.map(corner)
            x, y = float(v.x()), float(v.y())
            if not (math.isfinite(x) and math.isfinite(y)):
                return None
            xs.append(x)
            ys.append(y)
        return min(xs), max(xs), min(ys), max(ys)

    def _box_fits_view(self, w, h, margin_ndc=0.04):
        """True if every AABB corner projects inside the NDC frame (with margin)."""
        lim = 1.0 - max(0.0, float(margin_ndc))
        bounds = self._projected_ndc_bounds(w, h)
        if bounds is None:
            return False
        xmin, xmax, ymin, ymax = bounds
        return (
            xmin >= -lim and xmax <= lim
            and ymin >= -lim and ymax <= lim
        )

    def _center_projected_box(self, w, h, rounds=5):
        """Pan so the projected AABB is centred in NDC (keep yaw/pitch/dist).

        Steps are clamped; non-finite projections abort so the camera never
        flies away and leaves an empty export.
        """
        cy = math.cos(self._yaw)
        sy = math.sin(self._yaw)
        right = QVector3D(cy, 0, -sy)
        up = QVector3D(0, 1, 0)
        max_step = max(float(self._dist) * 0.4, float(self._radius_world) * 0.75, 0.5)
        for _ in range(rounds):
            bounds = self._projected_ndc_bounds(w, h)
            if bounds is None:
                return False
            xmin, xmax, ymin, ymax = bounds
            ox = 0.5 * (xmin + xmax)
            oy = 0.5 * (ymin + ymax)
            if abs(ox) < 5e-4 and abs(oy) < 5e-4:
                return True
            mvp = self._mvp(w, h)
            p0 = mvp.map(self._pan)
            eps = max(float(self._dist) * 0.02, 0.05)
            pr = mvp.map(self._pan + right * eps)
            pu = mvp.map(self._pan + up * eps)
            vals = (
                float(p0.x()), float(p0.y()),
                float(pr.x()), float(pr.y()),
                float(pu.x()), float(pu.y()),
            )
            if not all(math.isfinite(v) for v in vals):
                return False
            sx_r = (vals[2] - vals[0]) / eps
            sy_r = (vals[3] - vals[1]) / eps
            sx_u = (vals[4] - vals[0]) / eps
            sy_u = (vals[5] - vals[1]) / eps
            det = sx_r * sy_u - sx_u * sy_r
            if abs(det) < 1e-9:
                return False
            a = (-ox * sy_u + oy * sx_u) / det
            b = (-oy * sx_r + ox * sy_r) / det
            if not (math.isfinite(a) and math.isfinite(b)):
                return False
            a = max(-max_step, min(max_step, a))
            b = max(-max_step, min(max_step, b))
            self._pan = self._pan + right * a + up * b
        return True

    def _fit_dist_to_box(self, w, h, margin_ndc):
        """Binary-search the *smallest* distance where the AABB still fits.

        Distance is seeded from data size — never from the live (possibly huge)
        screen ``_dist``. Otherwise ``lo = hi*0.05`` stays enormous after the
        user zooms out and the export keeps the “fly on paper” look.
        """
        half_fov = math.radians(21.0)
        seed = max(
            float(self._radius_world) / max(math.tan(half_fov), 1e-6) * 1.05,
            0.8,
        )
        max_hi = max(seed * 100.0, float(self._radius_world) * 100.0, 50.0)
        # Ignore live camera distance; start from a data-sized seed.
        hi = seed
        self._dist = hi
        if not self._box_fits_view(w, h, margin_ndc):
            for _ in range(48):
                hi = min(max_hi, hi * 1.08)
                self._dist = hi
                if self._box_fits_view(w, h, margin_ndc):
                    break
                if hi >= max_hi - 1e-9:
                    break
        # Zoom in from a *data-sized* floor, not from hi*0.05 (fly trap).
        lo = max(0.5, seed * 0.08)
        self._dist = lo
        if self._box_fits_view(w, h, margin_ndc):
            self._dist = max(0.8, float(lo))
            return
        for _ in range(28):
            mid = 0.5 * (lo + hi)
            self._dist = mid
            if self._box_fits_view(w, h, margin_ndc):
                hi = mid
            else:
                lo = mid
        self._dist = max(0.8, float(hi))

    def frame_for_export(self, w, h, margin_ndc=0.03):
        """Centre the data box and fill ``w×h`` as much as possible (keep yaw/pitch).

        Looks at the AABB centre, then tightens camera distance from a
        data-sized seed so the box nearly fills the frame.
        """
        state = self._camera_state()
        w = max(int(w), 1)
        h = max(int(h), 1)
        margin_ndc = max(0.02, min(0.12, float(margin_ndc)))
        corners = self._box_corners()
        mx = my = mz = 0.0
        for c in corners:
            mx += c.x()
            my += c.y()
            mz += c.z()
        n = float(len(corners))
        self._pan = QVector3D(mx / n, my / n, mz / n)
        self._fit_dist_to_box(w, h, margin_ndc)
        # Small pad for box edge labels/ticks.
        self._dist = max(0.8, float(self._dist) * 1.03)
        self._sort_cache = None
        return state

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
        bg = QColor('#ffffff') if self._paper else QColor(self._screen_bg)
        self._paint_cloud(p, self.width(), self.height(), bg, self._paper, 1.0)

    def _paint_cloud(self, p, w, h, bg, paper, scale, pad_frac=0.0):
        """Project the cloud into ``w×h``.

        ``pad_frac`` insets the projection so markers are not clipped by the
        paper frame. On paper, points get a thin rim and axes are labelled.
        """
        p.fillRect(0, 0, w, h, bg)
        n = len(self._wx)
        nseg = len(self._seg_a)
        if not n and not nseg:
            p.setPen(QColor('#444') if paper else QColor('#bbb'))
            p.drawText(0, 0, w, h, Qt.AlignmentFlag.AlignCenter, 'No points')
            return
        pad = max(0.0, min(0.12, float(pad_frac or 0.0)))
        ox0 = w * pad
        oy0 = h * pad
        vw = max(1.0, w * (1.0 - 2.0 * pad))
        vh = max(1.0, h * (1.0 - 2.0 * pad))
        mvp = self._mvp(vw, vh)

        def to_screen(v):
            return (
                ox0 + (v.x() + 1.0) * 0.5 * vw,
                oy0 + (1.0 - v.y()) * 0.5 * vh,
            )

        items = []
        active = self._active
        if self._draw_points:
            for i in range(n):
                if self._groups[i] not in active:
                    continue
                v = mvp.map(QVector3D(self._wx[i], self._wy[i], self._wz[i]))
                if v.z() < -1.2 or v.z() > 1.2:
                    continue
                sx, sy = to_screen(v)
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
                ax, ay = to_screen(va)
                bx, by = to_screen(vb)
                items.append((0.5 * (va.z() + vb.z()), 0, ax, ay, bx, by, i))
        items.sort(key=lambda t: t[0], reverse=True)
        r = max(0.8, self._radius * scale)
        line_w = max(1.0, self._radius * 0.45) * scale
        if paper or self._drag is None:
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        rim = QColor(28, 25, 22, 170) if paper else None
        rim_w = max(0.6, r * 0.16) if paper else 0.0
        for item in items:
            if item[1] == 0:
                _z, _k, ax, ay, bx, by, i = item
                col = self._seg_cols[i]
                p.setPen(QPen(
                    col, line_w, Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin,
                ))
                p.drawLine(QPointF(ax, ay), QPointF(bx, by))
                head = _arrow_head_polygon(ax, ay, bx, by, self._arrow * scale)
                if head is not None:
                    if rim is not None:
                        p.setPen(QPen(
                            rim, max(0.5, rim_w * 0.7),
                            Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap,
                            Qt.PenJoinStyle.RoundJoin,
                        ))
                    else:
                        p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(QBrush(col))
                    p.drawPolygon(head)
            else:
                _z, _k, sx, sy, i = item
                col = self._cols[i]
                if rim is not None:
                    p.setPen(QPen(
                        rim, rim_w, Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin,
                    ))
                else:
                    p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(col))
                p.drawEllipse(QPointF(sx, sy), r, r)
        p.setBrush(Qt.BrushStyle.NoBrush)
        # Data bounding box (+ Labels only when Box is On).
        if self._show_bbox:
            self._paint_data_box(p, mvp, to_screen, paper, scale)
        # Screen: triad at the model origin. Paper export draws a corner
        # metre-scaled compass separately (trial A).
        if self._show_axes and not paper:
            origin = mvp.map(QVector3D(0, 0, 0))
            ox, oy = to_screen(origin)
            axis_len = max(self._radius_world * 0.18, 0.15)
            pen_w = max(1.2, 2.0 * scale)
            self._paint_axes_triad(
                p, mvp, to_screen, ox, oy, axis_len, pen_w,
                labels=False, scale=scale,
            )

    def _paint_data_box(self, p, mvp, to_screen, paper, scale):
        """Wire AABB in XYZ colours; optional side lengths + metre ticks."""
        b0, b1 = self._box_min, self._box_max
        if b0 is None or b1 is None:
            return
        x0, y0, z0 = float(b0.x()), float(b0.y()), float(b0.z())
        x1, y1, z1 = float(b1.x()), float(b1.y()), float(b1.z())
        if abs(x1 - x0) < 1e-9 and abs(y1 - y0) < 1e-9 and abs(z1 - z0) < 1e-9:
            return
        corners = [
            QVector3D(x0, y0, z0), QVector3D(x1, y0, z0),
            QVector3D(x0, y1, z0), QVector3D(x1, y1, z0),
            QVector3D(x0, y0, z1), QVector3D(x1, y0, z1),
            QVector3D(x0, y1, z1), QVector3D(x1, y1, z1),
        ]
        # Same colours as the compass triad: X red, Z(height) green, Y blue.
        wire = (
            (QColor('#c04040'), ((0, 1), (2, 3), (4, 5), (6, 7))),  # ‖ X
            (QColor('#2e8b4a'), ((0, 2), (1, 3), (4, 6), (5, 7))),  # ‖ Z up
            (QColor('#3a6cc0'), ((0, 4), (1, 5), (2, 6), (3, 7))),  # ‖ Y
        )
        pen_w = max(1.0, (1.5 if paper else 1.2) * scale)
        p.setBrush(Qt.BrushStyle.NoBrush)
        if self._show_bbox:
            for color, edges in wire:
                col = QColor(color)
                if not paper:
                    col.setAlpha(210)
                p.setPen(QPen(
                    col, pen_w, Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin,
                ))
                for ia, ib in edges:
                    va = mvp.map(corners[ia])
                    vb = mvp.map(corners[ib])
                    if (va.z() < -1.2 or va.z() > 1.2) and (
                        vb.z() < -1.2 or vb.z() > 1.2
                    ):
                        continue
                    ax, ay = to_screen(va)
                    bx, by = to_screen(vb)
                    p.drawLine(QPointF(ax, ay), QPointF(bx, by))

        if not (self._show_bbox and self._show_bbox_labels):
            return

        # Side lengths (metres) — not absolute site coords (those were opaque).
        len_x = abs(x1 - x0)
        len_z = abs(y1 - y0)  # scene Y = height Z
        len_y = abs(z1 - z0)  # scene Z = map Y
        # Prefer the corner closest to the camera for three readable edges.
        best_i, best_z = 0, 1e9
        for i, c in enumerate(corners):
            v = mvp.map(c)
            if v.z() < best_z:
                best_z = v.z()
                best_i = i
        cx = best_i & 1
        cy = (best_i >> 1) & 1
        cz = (best_i >> 2) & 1
        label_edges = (
            (
                QVector3D(x0 if not cx else x1, y0 if not cy else y1, z0 if not cz else z1),
                QVector3D(x1 if not cx else x0, y0 if not cy else y1, z0 if not cz else z1),
                QColor('#c04040'),
                len_x,
                'X length %s m' % _fmt_metre(len_x),
            ),
            (
                QVector3D(x0 if not cx else x1, y0 if not cy else y1, z0 if not cz else z1),
                QVector3D(x0 if not cx else x1, y1 if not cy else y0, z0 if not cz else z1),
                QColor('#2e8b4a'),
                len_z,
                'Z height %s m' % _fmt_metre(len_z),
            ),
            (
                QVector3D(x0 if not cx else x1, y0 if not cy else y1, z0 if not cz else z1),
                QVector3D(x0 if not cx else x1, y0 if not cy else y1, z1 if not cz else z0),
                QColor('#3a6cc0'),
                len_y,
                'Y length %s m' % _fmt_metre(len_y),
            ),
        )
        mid_box = mvp.map(QVector3D(
            0.5 * (x0 + x1), 0.5 * (y0 + y1), 0.5 * (z0 + z1),
        ))
        cx_s, cy_s = to_screen(mid_box)
        font = QFont()
        font.setBold(True)
        font.setPixelSize(max(9, int(round((10 if paper else 11) * scale))))
        p.setFont(font)
        tick_pen_w = max(0.9, (1.2 if paper else 1.0) * scale)
        tick_len = max(5.0, 7.0 * scale)
        for a, b, col, edge_len, text in label_edges:
            va = mvp.map(a)
            vb = mvp.map(b)
            if (va.z() < -1.2 or va.z() > 1.2) and (vb.z() < -1.2 or vb.z() > 1.2):
                continue
            ax, ay = to_screen(va)
            bx, by = to_screen(vb)
            mx, my = 0.5 * (ax + bx), 0.5 * (ay + by)
            dx, dy = bx - ax, by - ay
            el = math.hypot(dx, dy) or 1.0
            # Outward screen-space normal (away from box centre).
            nx, ny = -dy / el, dx / el
            if (mx - cx_s) * nx + (my - cy_s) * ny < 0:
                nx, ny = -nx, -ny

            # Metre ticks along this edge (world-length step → screen lerp).
            step = _nice_box_tick_step(edge_len, target_ticks=5)
            if edge_len > 1e-9 and step > 0:
                pen_col = QColor(col)
                if not paper:
                    pen_col.setAlpha(220)
                p.setPen(QPen(
                    pen_col, tick_pen_w, Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin,
                ))
                n_steps = int(math.floor(edge_len / step + 1e-9))
                # Always include both ends; skip duplicate if step divides evenly.
                positions = [0.0]
                for k in range(1, n_steps + 1):
                    t_m = k * step
                    if t_m < edge_len - 1e-9:
                        positions.append(t_m)
                positions.append(edge_len)
                for t_m in positions:
                    t = t_m / edge_len
                    sx = ax + (bx - ax) * t
                    sy = ay + (by - ay) * t
                    end = True if (t_m <= 1e-12 or abs(t_m - edge_len) <= 1e-9) else False
                    half = tick_len * (1.15 if end else 0.85)
                    p.drawLine(
                        QPointF(sx, sy),
                        QPointF(sx + nx * half, sy + ny * half),
                    )

            off = max(12.0, 14.0 * scale)
            lx, ly = mx + nx * off, my + ny * off
            p.setPen(col)
            tw = max(72.0, 7.2 * len(text) * scale)
            th = max(14.0, 16.0 * scale)
            p.drawText(
                QRectF(lx - tw * 0.5, ly - th * 0.5, tw, th),
                Qt.AlignmentFlag.AlignCenter,
                text,
            )

    def _axis_defs(self, axis_len):
        """Scene axes: X (map), Z (height/up), Y (map) — CloudWidget remap."""
        return (
            (QVector3D(axis_len, 0, 0), QColor('#c04040'), 'X'),
            (QVector3D(0, axis_len, 0), QColor('#2e8b4a'), 'Z'),
            (QVector3D(0, 0, axis_len), QColor('#3a6cc0'), 'Y'),
        )

    def _paint_axes_triad(
        self, p, mvp, to_screen, ox, oy, axis_len, pen_w,
        labels=False, scale=1.0,
    ):
        """Draw XYZ triad from ``(ox, oy)`` using world vectors through ``mvp``."""
        if labels:
            font = QFont()
            font.setBold(True)
            font.setPixelSize(max(9, int(round(10 * scale))))
            p.setFont(font)
        for vec, color, lab in self._axis_defs(axis_len):
            end = mvp.map(vec)
            ex, ey = to_screen(end)
            p.setPen(QPen(
                color, pen_w, Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin,
            ))
            p.drawLine(QPointF(ox, oy), QPointF(ex, ey))
            if labels:
                dx = ex - ox
                dy = ey - oy
                ln = math.hypot(dx, dy) or 1.0
                lx = ex + dx / ln * max(6.0, 4.0 * scale)
                ly = ey + dy / ln * max(6.0, 4.0 * scale)
                p.setPen(color)
                p.drawText(
                    QRectF(lx - 10, ly - 8, 20, 16),
                    Qt.AlignmentFlag.AlignCenter,
                    lab,
                )

    def paint_orientation_triad(
        self, p, left, top, right, bottom,
        size_px=None, pen_w=None, label_px=9,
        centered=False, measure_w=None, measure_h=None,
    ):
        """Metre-scaled XYZ compass (arms ≈ round metres at model centre).

        ``centered``: triad in the middle of the rect (export panel outside the
        plot). Otherwise lower-left of the rect (legacy corner placement).
        ``measure_w`` / ``measure_h``: pixel size of the **plot** used for px/m
        (defaults to this rect — correct only when the triad sits in the plot).
        """
        left, top = float(left), float(top)
        right, bottom = float(right), float(bottom)
        avail_w = max(1.0, right - left)
        avail_h = max(1.0, bottom - top)
        label_px = max(7.0, float(label_px or 9))
        gap = max(4.0, label_px * 0.7)
        lab_r = max(5.5, label_px * 0.65)
        margin = 3.0
        if centered:
            # Fill the panel; leave room for X/Y/Z letter tips.
            half = min(avail_w, avail_h) * 0.5 - margin - lab_r - gap * 0.35
            half = max(10.0, half)
            ox = left + avail_w * 0.5
            oy = top + avail_h * 0.5
        else:
            want = float(size_px) if size_px else min(avail_w, avail_h) * 0.11
            cell = max(28.0, min(want * 2.35, min(avail_w, avail_h) * 0.18))
            ox = left + cell * 0.5
            oy = bottom - cell * 0.5
            half = cell * 0.5 - margin

        # Use the plot aspect so px/m matches the framed view.
        # Measure 1 m at the look-at point (pan), not at a stale scene origin.
        mw = max(float(measure_w if measure_w is not None else avail_w), 1.0)
        mh = max(float(measure_h if measure_h is not None else avail_h), 1.0)
        mvp = self._mvp(mw, mh)
        pivot = QVector3D(self._pan)

        def ndc_to_px(v):
            return (
                (v.x() + 1.0) * 0.5 * mw,
                (1.0 - v.y()) * 0.5 * mh,
            )

        ox_s, oy_s = ndc_to_px(mvp.map(pivot))
        dirs = []
        ppm_list = []
        for vec, color, lab in self._axis_defs(1.0):
            end = mvp.map(pivot + vec)
            ex_s, ey_s = ndc_to_px(end)
            dx, dy = ex_s - ox_s, ey_s - oy_s
            ln = math.hypot(dx, dy) or 1.0
            dirs.append((dx / ln, dy / ln, color, lab))
            ppm_list.append(ln)  # pixels for 1 scene-metre along this axis

        median_ppm = sorted(ppm_list)[len(ppm_list) // 2]
        nice_m = _pick_nice_metres(median_ppm, target_px=min(42.0, half * 0.85))
        # Per-axis arm lengths (foreshortening) then uniform shrink to fit cell.
        arms = [nice_m * ppm for ppm in ppm_list]
        max_reach = 0.0
        for (ux, uy, _c, _l), arm in zip(dirs, arms):
            reach = arm + gap + lab_r
            tx = half / max(abs(ux), 1e-6)
            ty = half / max(abs(uy), 1e-6)
            fit = min(tx, ty)
            if reach > fit:
                max_reach = max(max_reach, reach / fit)
            else:
                max_reach = max(max_reach, 1.0)
        shrink = 1.0 / max_reach if max_reach > 1.0 else 1.0
        if shrink < 1.0:
            # Prefer a smaller nice length over a fractional metre on the label.
            nice_m = _pick_nice_metres(median_ppm * shrink, target_px=28.0)
            arms = [nice_m * ppm * shrink for ppm in ppm_list]
            # Re-check fit after re-pick.
            for (ux, uy, _c, _l), arm in zip(dirs, arms):
                reach = arm + gap + lab_r
                fit = min(
                    half / max(abs(ux), 1e-6),
                    half / max(abs(uy), 1e-6),
                )
                if reach > fit > 1e-6:
                    arms = [a * (fit / reach) for a in arms]
                    break

        self._last_compass_m = float(nice_m)
        if pen_w is None:
            pen_w = max(1.0, (max(arms) if arms else 20.0) * 0.08)
        else:
            pen_w = max(1.0, float(pen_w))

        font = QFont()
        font.setBold(True)
        font.setPixelSize(max(7, int(round(label_px))))
        p.setFont(font)
        box = lab_r * 2.0
        for (ux, uy, color, lab), arm in zip(dirs, arms):
            arm = max(6.0, float(arm))
            ex = ox + ux * arm
            ey = oy + uy * arm
            p.setPen(QPen(
                color, pen_w, Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin,
            ))
            p.drawLine(QPointF(ox, oy), QPointF(ex, ey))
            lx = ex + ux * gap
            ly = ey + uy * gap
            p.setPen(color)
            p.drawText(
                QRectF(lx - box * 0.5, ly - box * 0.5, box, box),
                Qt.AlignmentFlag.AlignCenter,
                lab,
            )
        # Metre length is documented under the paper frame, not on the compass.

    def mousePressEvent(self, event):
        self._last = event.pos()
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag = 'orbit'
        elif event.button() == Qt.MouseButton.RightButton:
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
    def __init__(
        self, layer, parent=None, group_field=None, display_mode='points',
        arrow_size=None, vector_fixed=False, vector_len_cm=VECTOR_LEN_CM_DEFAULT,
    ):
        super().__init__(parent)
        self.layer = layer
        self._group_field = group_field
        self._display_mode = display_mode or 'points'
        self._arrow_size = max(ARROW_MM_MIN, float(arrow_size or ARROW_MM_DEFAULT))
        self._vector_fixed = bool(vector_fixed)
        try:
            self._vector_len_cm = max(0.5, float(vector_len_cm))
        except (TypeError, ValueError):
            self._vector_len_cm = VECTOR_LEN_CM_DEFAULT
        self.setWindowTitle('ARSYSplotQGIS · 3D')
        self.resize(1080, 720)
        self.setMinimumWidth(920)
        self._ui_theme = 'dark'
        self._gwrap = None
        self._group_scroll = None
        self._hint = None
        self._export_compass = True

        from .dock import ToggleSwitch, _icon_button

        def _bar_switch(title, checked, *tip_parts):
            """Compact label + track-only switch for the single toolbar row."""
            lab = QLabel(title)
            sw = ToggleSwitch('')
            sw.setChecked(bool(checked))
            sw.setToolTip(html_tooltip(*tip_parts))
            sw._bar_label = lab
            bar.addWidget(lab)
            bar.addWidget(sw)
            return sw

        bar = QHBoxLayout()
        bar.setSpacing(4)
        bar.setContentsMargins(0, 0, 0, 0)
        bar.addWidget(QLabel('Draw'))
        self.btn_draw_points = QPushButton('Points')
        self.btn_draw_vectors = QPushButton('Vectors')
        self.btn_draw_both = QPushButton('Both')
        self._draw_group = QButtonGroup(self)
        self._draw_group.setExclusive(True)
        for btn in (self.btn_draw_points, self.btn_draw_vectors, self.btn_draw_both):
            btn.setCheckable(True)
            btn.setObjectName('arsys3dCompact')
            self._draw_group.addButton(btn)
        self.btn_draw_points.setToolTip(html_tooltip('**P1:** object centre.'))
        self.btn_draw_vectors.setToolTip(html_tooltip(
            '**P2→P3** geometric axis after import (legacy P1→P2 if P3 missing).',
            'Arrow **sense** uses the improved method (adaptive flip from inclination).',
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
        self._size_label = QLabel('%.2f' % SIZE_PX_DEFAULT)
        self._size_label.setMinimumWidth(28)
        self._size_label.setToolTip(html_tooltip('Point radius (**px**).'))
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, SIZE_SLIDER_MAX)
        slider.setSingleStep(1)
        slider.setPageStep(5)
        slider.setValue(size_slider_from_px(SIZE_PX_DEFAULT))
        slider.setMinimumWidth(44)
        slider.setMaximumWidth(72)
        slider.setToolTip(html_tooltip(
            'Point radius. Unit: **px**. Fine below 4; max **10**.',
        ))
        slider.valueChanged.connect(self._on_size)
        bar.addWidget(slider)
        bar.addWidget(self._size_label)
        bar.addWidget(QLabel('Arrow'))
        self._arrow_label = QLabel('%.2f' % self._arrow_size)
        self._arrow_label.setMinimumWidth(28)
        self._arrow_label.setToolTip(html_tooltip('Arrow-head size (**mm**).'))
        self._arrow_slider = QSlider(Qt.Orientation.Horizontal)
        self._arrow_slider.setRange(0, ARROW_SLIDER_MAX)
        self._arrow_slider.setSingleStep(1)
        self._arrow_slider.setPageStep(5)
        self._arrow_slider.setValue(arrow_slider_from_mm(self._arrow_size))
        self._arrow_slider.setMinimumWidth(44)
        self._arrow_slider.setMaximumWidth(72)
        self._arrow_slider.setToolTip(html_tooltip(
            'Arrow-head size. Unit: **mm**.',
        ))
        self._arrow_slider.valueChanged.connect(self._on_arrow)
        bar.addWidget(self._arrow_slider)
        bar.addWidget(self._arrow_label)

        self.chk_axes = _bar_switch(
            'Axes', True,
            '**Screen:** XYZ triad at the model origin.',
            'Does not control the export corner compass (see **Compass**).',
        )
        self.chk_axes.toggled.connect(self._on_axes_toggled)
        self.chk_box = _bar_switch(
            'Box', True,
            '**Data box** wireframe (X/Y/Z colours).',
            'Shown in this window **and** included on paper export when On.',
        )
        self.chk_box.toggled.connect(self._on_box_toggled)
        self.chk_labels = _bar_switch(
            'Labels', True,
            '**Box edges:** side length (m) + metre ticks on the three front edges.',
            'Screen **and** paper export. Requires **Box** On.',
        )
        self.chk_labels.toggled.connect(self._on_labels_toggled)
        self.chk_compass = _bar_switch(
            'Compass', True,
            '**Export only:** metre-scaled XYZ compass in a **framed panel** '
            'under the plot (outside the drawing area).',
            'Independent of **Axes** (screen triad).',
        )
        self.chk_compass.toggled.connect(self._on_compass_toggled)

        bar.addStretch(1)
        # Same icon chrome as PlotPane / ZoomWindow (Fit · Export · Close).
        self.btn_fit = _icon_button(
            'fit.svg',
            '**Fit** the view to the data (after orbit / pan / zoom).',
        )
        self.btn_fit.clicked.connect(self._fit)
        bar.addWidget(self.btn_fit)
        self.btn_export = _icon_button(
            'export.svg',
            'Export a **paper** figure (PNG/SVG). '
            'Respects **Box**, **Labels** and **Compass** switches; title/legend in the dialog.',
        )
        self.btn_export.clicked.connect(self._export_image)
        bar.addWidget(self.btn_export)
        self.btn_close = _icon_button(
            'close.svg',
            '**Close** this 3D window.',
        )
        self.btn_close.clicked.connect(self.close)
        bar.addWidget(self.btn_close)

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
        self._gwrap = QWidget()
        self._group_layout = QHBoxLayout(self._gwrap)
        self._group_layout.setContentsMargins(0, 0, 0, 0)
        self._group_layout.setSpacing(4)
        self._group_scroll = QScrollArea()
        self._group_scroll.setWidgetResizable(True)
        self._group_scroll.setWidget(self._gwrap)
        self._group_scroll.setFixedHeight(42)
        self._group_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._group_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        filt.addWidget(self._group_scroll, 1)

        self.cloud = CloudWidget()
        self._hint = QLabel(
            'Left-drag rotate · right-drag pan · wheel zoom. '
            'P1 = centre · vector = P2→P3.'
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addLayout(bar)
        layout.addLayout(filt)
        layout.addWidget(self.cloud, 1)
        layout.addWidget(self._hint)
        self.cloud.set_draw_mode(self._display_mode)
        parent_theme = 'dark'
        with suppress(AttributeError, RuntimeError, TypeError, ValueError):
            parent_theme = getattr(parent, 'ui_theme', 'dark') or 'dark'
        self.apply_theme(parent_theme)
        self.set_arrow_size(self._arrow_size, sync_slider=False)
        self.reload(group_field, keep_camera=False)

    def apply_theme(self, name='dark'):
        """Match the plugin dock dark / light chrome (including tip contrast)."""
        light = name == 'light'
        self._ui_theme = 'light' if light else 'dark'
        if light:
            bg, ink, btn, border, hover = (
                '#f3f0ea', '#1a1816', '#e8e2d8', '#c8c0b4', '#ddd5c8',
            )
            muted, groove, cloud = '#6b645c', '#ddd5c8', '#faf8f4'
            # Same tip chrome as dock.tooltip_palette (not inverse).
            tip_bg, tip_ink, tip_border = '#fff8ee', '#1a1816', '#c8c0b4'
        else:
            bg, ink, btn, border, hover = (
                '#1a1816', '#fff5e6', '#2a2622', '#4a453e', '#3a3530',
            )
            muted, groove, cloud = '#999999', '#2a2622', '#141210'
            tip_bg, tip_ink, tip_border = '#1c1916', '#fff5e6', '#3a342e'
        set_tooltip_chrome(tip_bg, tip_ink)
        tip_css = (
            'QToolTip { background-color:%s; color:%s;'
            '  border:1px solid %s; padding:6px 9px; font-size:11px; }'
            % (tip_bg, tip_ink, tip_border)
        )
        self.setStyleSheet(
            'QDialog { background:%s; color:%s; }'
            'QWidget { background:%s; color:%s; }'
            'QLabel { background:transparent; color:%s; }'
            'QPushButton { background:%s; color:%s; border:1px solid %s;'
            '  border-radius:4px; padding:4px 8px; }'
            'QPushButton#arsys3dCompact { padding:2px 5px; font-size:11px; }'
            'QPushButton:hover { background:%s; }'
            'QPushButton:checked { background:#d97726; border-color:#f0a15a; color:#fff8ee; }'
            'QPushButton:disabled { color:#6b645c; }'
            'QScrollArea, QAbstractScrollArea, QAbstractScrollArea::viewport {'
            '  background:%s; border:none; }'
            'QSlider::groove:horizontal { background:%s; height:6px; border-radius:3px; }'
            'QSlider::handle:horizontal { background:#d97726; width:12px; margin:-4px 0;'
            '  border-radius:6px; }'
            % (
                bg, ink, bg, ink, muted, btn, ink, border, hover, bg, groove,
            )
            + tip_css
        )
        if self._gwrap is not None:
            self._gwrap.setStyleSheet('background:%s;' % bg)
        if self._group_scroll is not None:
            self._group_scroll.setStyleSheet(
                'QScrollArea { border:none; background:%s; }'
                'QScrollArea > QWidget > QWidget { background:%s; }'
                % (bg, bg)
            )
            self._group_scroll.viewport().setStyleSheet('background:%s;' % bg)
        if self._hint is not None:
            self._hint.setStyleSheet('color:%s;' % muted)
        if hasattr(self, 'cloud') and self.cloud is not None:
            self.cloud.set_screen_bg(cloud)
        # Re-apply pane icon chrome + tip CSS after the dialog-wide QPushButton sheet.
        with suppress(Exception):
            from .dock import _pane_icon_btn_css, _retint_html_tooltips, _themed_icon
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
            # HTML tips bake colour/background — align with dock tip chrome.
            _retint_html_tooltips(self, tip_ink, tip_bg)

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
            self._arrow_label.setText('%.2f' % self._arrow_size)

    def reload(
        self, group_field=None, keep_camera=True, display_mode=None,
        arrow_size=None, vector_fixed=None, vector_len_cm=None,
    ):
        if group_field:
            self._group_field = group_field
        if display_mode is not None:
            self._display_mode = display_mode or 'points'
        if arrow_size is not None:
            self.set_arrow_size(arrow_size)
        if vector_fixed is not None:
            self._vector_fixed = bool(vector_fixed)
        if vector_len_cm is not None:
            try:
                self._vector_len_cm = max(0.5, float(vector_len_cm))
            except (TypeError, ValueError):
                self._vector_len_cm = VECTOR_LEN_CM_DEFAULT
        xs, ys, zs, cols, groups, lookup, segs = _collect_points(
            self.layer, self._group_field,
            vector_fixed=bool(getattr(self, '_vector_fixed', False)),
            vector_len_cm=float(
                getattr(self, '_vector_len_cm', VECTOR_LEN_CM_DEFAULT)
                or VECTOR_LEN_CM_DEFAULT
            ),
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
        self._size_label.setText('%.2f' % radius)
        self.cloud.set_radius(radius)

    def _on_arrow(self, value):
        self.set_arrow_size(arrow_mm_from_slider(value), sync_slider=False)
        self._arrow_label.setText('%.2f' % self._arrow_size)

    def _on_axes_toggled(self, on):
        # Screen-only origin triad (export compass is chk_compass).
        self.cloud.set_show_axes(bool(on))

    def _on_box_toggled(self, on):
        # Screen + export data box; Labels only make sense with Box On.
        on = bool(on)
        self.cloud.set_show_bbox(on)
        self.chk_labels.setEnabled(on)
        lab = getattr(self.chk_labels, '_bar_label', None)
        if lab is not None:
            lab.setEnabled(on)
        if not on:
            if self.chk_labels.isChecked():
                self.chk_labels.setChecked(False)
            else:
                self.cloud.set_show_bbox_labels(False)

    def _on_labels_toggled(self, on):
        # Screen + export: side lengths and metre ticks (only with Box).
        if on and not self.chk_box.isChecked():
            self.chk_labels.blockSignals(True)
            self.chk_labels.setChecked(False)
            self.chk_labels.blockSignals(False)
            on = False
        self.cloud.set_show_bbox_labels(bool(on))

    def _on_compass_toggled(self, on):
        # Export-only corner compass.
        self._export_compass = bool(on)

    def _fit(self):
        self.cloud.fit()

    def _legend_entries(self):
        """Active groups with colour + point-model shape (paper legend)."""
        order = []
        if getattr(self, '_group_btns', None):
            for name, btn in self._group_btns.items():
                if btn.isChecked():
                    order.append(name)
        if not order:
            order = sorted(self.cloud._active) if self.cloud._active else []
        lookup = getattr(self, '_lookup', {}) or {}
        shapes = _shape_lookup(self.layer)
        items = []
        for name in order:
            color = lookup.get(name, QColor('#888888'))
            shape = shapes.get(name, DEFAULT_MARKER)
            items.append((name, QColor(color), resolve_marker_shape(shape)))
        return items, 'Legend'

    def _export_layout(self, opts):
        """Paper geometry for a framed 3D view (Lite/2D margin conventions)."""
        paper_bg = QColor(PAPER_BG)
        use_bg = bool(opts.get('use_background', False))
        plot_bg = QColor(opts.get('bg') or PAPER_BG)
        if not plot_bg.isValid() or not use_bg:
            plot_bg = QColor(PAPER_BG)
        dpi = max(72, int(opts.get('dpi') or 300))
        title = (opts.get('title') or '').strip()
        subtitle = (opts.get('subtitle') or '').strip()
        ink = QColor(PAPER_INK)
        groups, group_field = self._legend_entries()
        want_legend = bool(opts.get('show_legend', True))
        show_groups = bool(groups) and want_legend

        paper_w_mm, paper_h_mm = E.paper_size_mm(
            opts.get('paper') or 'A4',
            opts.get('orientation') or 'landscape',
        )
        type_scale = E.paper_type_scale(paper_w_mm, paper_h_mm)
        margin = E.LAYOUT_MARGIN
        pad_b = (
            E.LAYOUT_AXIS_LABEL + E.LAYOUT_TICK_PAD + E.LAYOUT_SCALE_BAR_H
        )
        side_gap_mm = E.LAYOUT_LEGEND_GAP
        # Framed compass lives *outside* the plot (under caption, before legend).
        compass_on = bool(getattr(self, '_export_compass', True))
        compass_mm = 16.0 * type_scale
        compass_gap_mm = 2.5 * type_scale
        caption_mm = 6.0 * type_scale

        def _avail(side_r=0.0, below_r=0.0):
            aw, ah, meta = E.plot_avail_mm(
                paper_w_mm, paper_h_mm, title, subtitle,
                side_reserve_mm=side_r, below_reserve_mm=below_r,
            )
            # Extra top band so scaled title/subtitle keep clear of the frame.
            extra_top = 0.0
            if title:
                extra_top += E.LAYOUT_TITLE_H * max(0.0, type_scale - 1.0)
            if subtitle:
                extra_top += E.LAYOUT_SUB_H * max(0.0, type_scale - 1.0)
            meta = dict(meta)
            meta['top'] = float(meta['top']) + extra_top
            ah = max(40.0, ah - extra_top)
            return aw, ah, meta

        # Viewport aspect from the live cloud widget (stable landscape frame).
        src_w = max(float(self.cloud.width()), 1.0)
        src_h = max(float(self.cloud.height()), 1.0)
        aspect = src_w / src_h

        def _bottom_band_mm(legend_h_mm=0.0):
            """Caption + row with optional compass and/or below-legend."""
            row = 0.0
            if compass_on:
                row = max(row, compass_mm)
            if legend_h_mm > 0.0:
                # Legend sits in the same row as the compass (to its right).
                row = max(row, float(legend_h_mm))
            if row <= 0.0 and not compass_on:
                return caption_mm
            return caption_mm + compass_gap_mm + row + compass_gap_mm

        avail_w, avail_h, lay = _avail()
        # Fit the largest framed viewport into the available area.
        if avail_w / aspect <= avail_h:
            inner_w_mm = avail_w
            inner_h_mm = avail_w / aspect
        else:
            inner_h_mm = avail_h
            inner_w_mm = avail_h * aspect
        plot_w = max(1, int(round(E.mm_to_px(inner_w_mm, dpi))))
        plot_h = max(1, int(round(E.mm_to_px(inner_h_mm, dpi))))

        # 3D: legend in the bottom paper strip, to the right of the XYZ panel
        # (the empty fringe under the frame — not the right margin of the sheet).
        compass_px = (
            max(24, int(round(E.mm_to_px(compass_mm, dpi)))) if compass_on else 0
        )
        gap_px = int(round(E.mm_to_px(max(side_gap_mm, 4.0) * type_scale, dpi)))
        legend_width_px = max(
            40,
            plot_w - (compass_px + gap_px if compass_on else 0),
        )

        legend_plan = None
        if show_groups:
            legend_plan = paper_legend_plan(
                groups, group_field, plot_h, legend_width_px, dpi,
                prefer_place='below',
                drawn_w_mm=inner_w_mm, drawn_h_mm=inner_h_mm,
                avail_w_mm=avail_w, avail_h_mm=avail_h,
                paper_w_mm=paper_w_mm, paper_h_mm=paper_h_mm,
                type_scale=type_scale,
            )
            # Never keep a side legend for 3D export.
            if legend_plan.get('place') != 'below':
                legend_plan = paper_legend_plan(
                    groups, group_field, plot_h, legend_width_px, dpi,
                    prefer_place='below',
                    type_scale=type_scale,
                )

        legend_h_mm = (
            paper_legend_below_height_mm(legend_plan, dpi)
            if legend_plan else 0.0
        )
        extra_r = 0.0
        extra_b = _bottom_band_mm(legend_h_mm)

        avail_w, avail_h, lay = _avail(extra_r, extra_b)
        if avail_w / aspect <= avail_h:
            inner_w_mm = avail_w
            inner_h_mm = avail_w / aspect
        else:
            inner_h_mm = avail_h
            inner_w_mm = avail_h * aspect
        plot_w = max(1, int(round(E.mm_to_px(inner_w_mm, dpi))))
        plot_h = max(1, int(round(E.mm_to_px(inner_h_mm, dpi))))
        legend_width_px = max(
            40,
            plot_w - (compass_px + gap_px if compass_on else 0),
        )
        if show_groups:
            legend_plan = paper_legend_plan(
                groups, group_field, plot_h, legend_width_px, dpi,
                prefer_place='below',
                drawn_w_mm=inner_w_mm, drawn_h_mm=inner_h_mm,
                avail_w_mm=avail_w, avail_h_mm=avail_h,
                paper_w_mm=paper_w_mm, paper_h_mm=paper_h_mm,
                type_scale=type_scale,
            )
            if legend_plan.get('place') != 'below':
                legend_plan = paper_legend_plan(
                    groups, group_field, plot_h, legend_width_px, dpi,
                    prefer_place='below',
                    type_scale=type_scale,
                )
            legend_h_mm = paper_legend_below_height_mm(legend_plan, dpi)
            need_b = _bottom_band_mm(legend_h_mm)
            if abs(need_b - extra_b) > 0.5:
                extra_b = need_b
                avail_w, avail_h, lay = _avail(extra_r, extra_b)
                if avail_w / aspect <= avail_h:
                    inner_w_mm = avail_w
                    inner_h_mm = avail_w / aspect
                else:
                    inner_h_mm = avail_h
                    inner_w_mm = avail_h * aspect
                plot_w = max(1, int(round(E.mm_to_px(inner_w_mm, dpi))))
                plot_h = max(1, int(round(E.mm_to_px(inner_h_mm, dpi))))
                legend_width_px = max(
                    40,
                    plot_w - (compass_px + gap_px if compass_on else 0),
                )
                legend_plan = paper_legend_plan(
                    groups, group_field, plot_h, legend_width_px, dpi,
                    prefer_place='below',
                    type_scale=type_scale,
                )

        free_w = max(0.0, avail_w - inner_w_mm)
        free_h = max(0.0, avail_h - inner_h_mm)
        # Centre the framed view — bottom strip holds compass + legend.
        left_mm = lay['left'] + free_w * 0.5
        top_mm = lay['top'] + free_h * 0.5
        left = int(round(E.mm_to_px(left_mm, dpi)))
        top = int(round(E.mm_to_px(top_mm, dpi)))
        right = left + plot_w
        bottom = top + plot_h
        out_w = max(1, int(round(E.mm_to_px(paper_w_mm, dpi))))
        out_h = max(1, int(round(E.mm_to_px(paper_h_mm, dpi))))

        # Caption, then a row: [XYZ panel | legend …] under the frame.
        cap_top = bottom + int(round(E.mm_to_px(2.0 * type_scale, dpi)))
        cap_h = int(round(E.mm_to_px(caption_mm, dpi)))
        row_top = cap_top + cap_h + int(round(E.mm_to_px(compass_gap_mm, dpi)))
        compass_rect = None
        if compass_on:
            c_size = max(24, int(round(E.mm_to_px(compass_mm, dpi))))
            compass_rect = QRect(left, row_top, c_size, c_size)
        legend_x = left
        if compass_rect is not None:
            legend_x = compass_rect.right() + 1 + gap_px
        legend_top = row_top if (compass_on or show_groups) else (
            bottom + int(round(E.mm_to_px(pad_b, dpi)))
        )

        return {
            'paper_bg': paper_bg,
            'plot_bg': plot_bg,
            'dpi': dpi,
            'ink': ink,
            'title': title,
            'subtitle': subtitle,
            'margin': margin,
            'pad_b': pad_b,
            'side_gap_mm': side_gap_mm,
            'plot_w': plot_w, 'plot_h': plot_h,
            'left': left, 'top': top, 'right': right, 'bottom': bottom,
            'out_w': out_w, 'out_h': out_h,
            'groups': groups,
            'group_field': group_field,
            'show_groups': show_groups,
            'legend_plan': legend_plan,
            'src_w': src_w, 'src_h': src_h,
            'type_scale': type_scale,
            'paper_w_mm': paper_w_mm,
            'paper_h_mm': paper_h_mm,
            'compass_on': compass_on,
            'compass_rect': compass_rect,
            'caption_top': cap_top,
            'caption_h': cap_h,
            'compass_below_mm': _bottom_band_mm(
                paper_legend_below_height_mm(legend_plan, dpi)
                if legend_plan else 0.0
            ),
            'legend_x': legend_x,
            'legend_top': legend_top,
        }

    def _paint_export(self, painter, layout, opts):
        paper_bg = layout['paper_bg']
        plot_bg = layout['plot_bg']
        dpi = layout['dpi']
        ink = layout['ink']
        title = layout['title']
        subtitle = layout['subtitle']
        margin = layout['margin']
        pad_b = layout['pad_b']
        side_gap_mm = layout['side_gap_mm']
        plot_w, plot_h = layout['plot_w'], layout['plot_h']
        left, top = layout['left'], layout['top']
        right, bottom = layout['right'], layout['bottom']
        out_w, out_h = layout['out_w'], layout['out_h']
        groups = layout['groups']
        group_field = layout['group_field']
        show_groups = layout['show_groups']
        legend_plan = layout['legend_plan']
        src_w = layout['src_w']
        ts = float(layout.get('type_scale') or 1.0)

        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.fillRect(0, 0, out_w, out_h, paper_bg)

        y = E.mm_to_px(margin, dpi)
        if title:
            font = QFont()
            font.setPixelSize(E.pt_to_px(13.0 * ts, dpi))
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(ink)
            band = E.mm_to_px(7.5 * ts, dpi)
            painter.drawText(
                QRect(
                    int(E.mm_to_px(margin, dpi)), int(y),
                    out_w - int(E.mm_to_px(margin * 2, dpi)),
                    int(band),
                ),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                title,
            )
            y += E.mm_to_px(8.0 * ts, dpi)
        if subtitle:
            font = QFont()
            font.setPixelSize(E.pt_to_px(9.0 * ts, dpi))
            painter.setFont(font)
            painter.setPen(QColor(PAPER_MUTED))
            band = E.mm_to_px(5.2 * ts, dpi)
            painter.drawText(
                QRect(
                    int(E.mm_to_px(margin, dpi)), int(y),
                    out_w - int(E.mm_to_px(margin * 2, dpi)),
                    int(band),
                ),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                subtitle,
            )

        compass_on = bool(layout.get('compass_on'))
        compass_rect = layout.get('compass_rect')
        cap_top = int(layout.get('caption_top') or (bottom + E.mm_to_px(2.0 * ts, dpi)))
        cap_h = int(layout.get('caption_h') or E.mm_to_px(5.0 * ts, dpi))

        # Supersample the cloud into the framed plot for cleaner circles/arrows.
        # Centre+fit the data box in the export aspect (keep yaw/pitch).
        ss = 2 if dpi >= 200 else 1
        hi_w = max(1, int(plot_w * ss))
        hi_h = max(1, int(plot_h * ss))
        scale = (hi_w / float(src_w)) if src_w > 0 else float(ss)
        # Frame with the same pixel size as the supersampled image. Keep the
        # export camera active until the triad is painted so orientation matches.
        cam = self.cloud.frame_for_export(hi_w, hi_h, margin_ndc=0.03)
        try:
            cloud_img = QImage(hi_w, hi_h, QImage.Format.Format_ARGB32_Premultiplied)
            cloud_img.fill(plot_bg)
            cp = QPainter(cloud_img)
            try:
                cp.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                cp.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
                self.cloud._paint_cloud(
                    cp, hi_w, hi_h, plot_bg, True, scale, pad_frac=0.015,
                )
            finally:
                cp.end()
            painter.drawImage(QRect(left, top, plot_w, plot_h), cloud_img)

            # Formal frame (same weight as 2D paper axes).
            axis_w = max(1.0, E.mm_to_px(PAPER_FRAME_MM, dpi))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(ink, axis_w))
            painter.drawRect(QRectF(left, top, plot_w, plot_h))

            # Outside the drawing area: framed compass with export orientation.
            if compass_on and compass_rect is not None and not compass_rect.isEmpty():
                pad = max(2.0, E.mm_to_px(1.2 * ts, dpi))
                panel = QRectF(compass_rect).adjusted(-pad, -pad, pad, pad)
                painter.setBrush(QBrush(QColor(PAPER_BG)))
                painter.setPen(QPen(ink, max(1.0, axis_w * 0.9)))
                painter.drawRect(panel)
                cr = QRectF(compass_rect)
                self.cloud.paint_orientation_triad(
                    painter,
                    cr.left(), cr.top(), cr.right(), cr.bottom(),
                    pen_w=max(1.0, E.mm_to_px(0.28 * ts, dpi)),
                    label_px=E.pt_to_px(7.0 * ts, dpi),
                    centered=True,
                    measure_w=plot_w,
                    measure_h=plot_h,
                )
        finally:
            self.cloud._restore_camera(cam)

        cap_bits = ['3D · perspective']
        if compass_on:
            compass_m = float(getattr(self.cloud, '_last_compass_m', 1.0) or 1.0)
            cap_bits.append(
                'each compass arm ≈ %s m at centre' % _fmt_metre(compass_m)
            )
        font = QFont()
        font.setPixelSize(E.pt_to_px(7.0 * ts, dpi))
        painter.setFont(font)
        painter.setPen(QColor(PAPER_MUTED))
        painter.drawText(
            QRect(int(left), int(cap_top), int(plot_w), int(cap_h)),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            ' · '.join(cap_bits),
        )

        # Page footer (2D parity, without 1∶N).
        n_pts = len(self.cloud._wx)
        paper = str(opts.get('paper') or 'A4')
        orient = str(opts.get('orientation') or 'landscape')
        foot = 'Made by ArcheSystem — ARSYSplotQGIS · 3D · %s %s' % (
            paper, orient,
        )
        if n_pts:
            foot += ' · %d pts' % n_pts
        font = QFont()
        font.setPixelSize(E.pt_to_px(6.0 * ts, dpi))
        painter.setFont(font)
        painter.setPen(QColor(PAPER_FAINT))
        painter.drawText(
            QRect(
                int(E.mm_to_px(margin, dpi)),
                int(out_h - E.mm_to_px(5.5 * ts, dpi)),
                out_w - int(E.mm_to_px(margin * 2, dpi)),
                int(E.mm_to_px(4.0 * ts, dpi)),
            ),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            foot,
        )

        if show_groups and legend_plan is not None:
            # Bottom strip: to the right of the XYZ panel (empty fringe under frame).
            leg_x = int(layout.get('legend_x') or left)
            leg_top = int(layout.get('legend_top') or (
                bottom + E.mm_to_px(float(pad_b), dpi)
            ))
            if compass_on and compass_rect is not None and not compass_rect.isEmpty():
                pad = max(2.0, E.mm_to_px(1.2 * ts, dpi))
                gap = E.mm_to_px(max(side_gap_mm, 4.0) * ts, dpi)
                leg_x = max(
                    leg_x,
                    int(math.ceil(compass_rect.right() + 1 + pad + gap)),
                )
                leg_top = min(leg_top, int(compass_rect.top()))
            plan = dict(legend_plan)
            plan['place'] = 'below'
            # Clip legend width to the remaining strip under the frame.
            max_w = max(40.0, float(right - leg_x))
            if float(plan.get('total_w') or 0) > max_w:
                plan['total_w'] = max_w
                plan['col_w'] = max_w / max(1, int(plan.get('n_cols') or 1))
            leg_bottom = leg_top + float(plan['total_h'])
            paint_paper_legend(
                painter, groups, group_field,
                leg_x, leg_top, leg_bottom, dpi, ink,
                plan=plan, type_scale=ts,
            )

    def _export_image(self):
        layer_name = self.layer.name() if self.layer is not None else ''
        groups, _field = self._legend_entries()
        theme = None
        with suppress(Exception):
            from .dock import UI_THEME
            theme = dict(UI_THEME)
        dlg = E.ExportImageDialog(
            self, title='3D', subtitle=layer_name, bg=QColor('#ffffff'),
            theme=theme, reserve_legend=bool(groups), for_3d=True,
        )
        exec_fn = getattr(dlg, 'exec', None) or dlg.exec_
        if exec_fn() != dlg.Accepted:
            return
        opts = dlg.values()
        fmt = str(opts.get('format') or 'png').lower()
        if fmt == 'svg':
            path, _flt = QFileDialog.getSaveFileName(
                self, 'Export SVG', 'ARSYSplotQGIS_3D.svg', 'SVG (*.svg)',
            )
            if not path:
                return
            if not path.lower().endswith('.svg'):
                path += '.svg'
            ok = self._render_export_svg(opts, path)
        else:
            path, _flt = QFileDialog.getSaveFileName(
                self, 'Export PNG', 'ARSYSplotQGIS_3D.png', 'PNG (*.png)',
            )
            if not path:
                return
            if not path.lower().endswith('.png'):
                path += '.png'
            img = self._render_export(opts)
            ok = bool(img is not None and not img.isNull() and img.save(path, 'PNG'))
        if not ok:
            QMessageBox.warning(self, 'Export', 'Could not write %s' % path)

    def _render_export(self, opts):
        layout = self._export_layout(opts)
        if layout is None:
            return None
        img = QImage(
            layout['out_w'], layout['out_h'],
            QImage.Format.Format_ARGB32_Premultiplied,
        )
        E.apply_png_dpi(img, layout['dpi'])
        img.fill(layout['paper_bg'])
        painter = QPainter(img)
        try:
            self._paint_export(painter, layout, opts)
        finally:
            painter.end()
        return img

    def _render_export_svg(self, opts, path):
        layout = self._export_layout(opts)
        if layout is None:
            return False
        try:
            from qgis.PyQt.QtSvg import QSvgGenerator
        except ImportError:
            return False
        gen = QSvgGenerator()
        gen.setFileName(path)
        gen.setSize(QSize(layout['out_w'], layout['out_h']))
        gen.setViewBox(QRect(0, 0, layout['out_w'], layout['out_h']))
        with suppress(AttributeError, RuntimeError, TypeError, ValueError):
            gen.setResolution(int(layout['dpi']))
        with suppress(AttributeError, RuntimeError, TypeError, ValueError):
            gen.setTitle((opts.get('title') or 'ARSYSplotQGIS · 3D'))
        painter = QPainter(gen)
        try:
            self._paint_export(painter, layout, opts)
        finally:
            painter.end()
        import os
        return os.path.isfile(path) and os.path.getsize(path) > 0

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


def open_3d_view(
    iface, layer, parent=None, group_field=None, display_mode='points',
    arrow_size=None, vector_fixed=False, vector_len_cm=VECTOR_LEN_CM_DEFAULT,
):
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
            vector_fixed=vector_fixed, vector_len_cm=vector_len_cm,
        )
        dlg.raise_()
        dlg.activateWindow()
        return True
    dlg = Scatter3DDialog(
        layer, parent or iface.mainWindow(),
        group_field=group_field, display_mode=display_mode,
        arrow_size=arrow_size,
        vector_fixed=vector_fixed, vector_len_cm=vector_len_cm,
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


def apply_open_theme(iface, theme_name):
    for dlg in getattr(iface, '_arsysplotqgis_3d', []):
        with suppress(AttributeError, RuntimeError, TypeError, ValueError):
            if dlg.isVisible():
                dlg.apply_theme(theme_name)


def refresh_open_views(
    iface, layer, group_field=None, display_mode=None, arrow_size=None,
    vector_fixed=None, vector_len_cm=None,
):
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
                vector_fixed=vector_fixed, vector_len_cm=vector_len_cm,
            )
    if hasattr(iface, '_arsysplotqgis_3d'):
        iface._arsysplotqgis_3d = kept
