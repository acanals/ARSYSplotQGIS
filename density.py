# -*- coding: utf-8 -*-
"""Kernel density from filtered points.

Fill is always the styled KDE raster (Bands = discrete classes, Cloud =
smooth), the same model as QGIS layer styling. Isolines are line overlays
only — never the fill surface.
"""
from contextlib import suppress
import math
import os
import tempfile

from qgis.core import (
    Qgis,
    QgsColorRampShader,
    QgsFeature,
    QgsGeometry,
    QgsGradientColorRamp,
    QgsLineSymbol,
    QgsProcessingFeedback,
    QgsSimpleLineSymbolLayer,
    QgsRasterBandStats,
    QgsRasterLayer,
    QgsRasterShader,
    QgsSingleBandPseudoColorRenderer,
    QgsSingleSymbolRenderer,
    QgsUnitTypes,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QRectF, Qt
from qgis.PyQt.QtGui import (
    QBrush,
    QColor,
    QFont,
    QIcon,
    QPainter,
    QPen,
    QPixmap,
)

from .layers import keep_private, release_private

KERNELS = (
    ('Quartic', 0),
    ('Triangular', 1),
    ('Uniform', 2),
    ('Triweight', 3),
    ('Epanechnikov', 4),
)

# (id, label, stops as (t, r, g, b) 0–1 / 0–255)
COLOR_SCHEMES = (
    ('viridis', 'Viridis', (
        (0.00, 68, 1, 84), (0.33, 49, 104, 142),
        (0.66, 53, 183, 121), (1.00, 253, 231, 37),
    )),
    ('magma', 'Magma', (
        (0.00, 0, 0, 4), (0.33, 128, 23, 93),
        (0.66, 240, 96, 53), (1.00, 252, 253, 191),
    )),
    ('inferno', 'Inferno', (
        (0.00, 0, 0, 4), (0.25, 87, 16, 110), (0.50, 188, 55, 84),
        (0.75, 249, 142, 9), (1.00, 252, 255, 164),
    )),
    ('plasma', 'Plasma', (
        (0.00, 13, 8, 135), (0.25, 126, 3, 168), (0.50, 204, 71, 120),
        (0.75, 248, 149, 64), (1.00, 240, 249, 33),
    )),
    ('cividis', 'Cividis', (
        (0.00, 0, 32, 77), (0.33, 60, 87, 113),
        (0.66, 162, 148, 89), (1.00, 253, 231, 37),
    )),
    ('hot', 'Hot', (
        (0.00, 16, 0, 0), (0.30, 180, 0, 0),
        (0.62, 255, 160, 0), (1.00, 255, 255, 230),
    )),
    ('vivid', 'Vivid', (
        (0.00, 0, 0, 255), (0.25, 0, 255, 255), (0.50, 0, 255, 0),
        (0.75, 255, 255, 0), (1.00, 255, 0, 0),
    )),
    ('thermal', 'Thermal', (
        (0.00, 12, 18, 72), (0.25, 28, 110, 180), (0.50, 56, 200, 170),
        (0.75, 240, 210, 60), (1.00, 220, 48, 32),
    )),
    ('ocean', 'Ocean', (
        (0.00, 240, 249, 255), (0.50, 107, 174, 214), (1.00, 8, 48, 107),
    )),
    ('terrain', 'Terrain', (
        (0.00, 8, 47, 92), (0.28, 34, 120, 94), (0.55, 168, 186, 74),
        (0.78, 196, 140, 58), (1.00, 140, 64, 32),
    )),
    ('earth', 'Earth', (
        (0.00, 236, 226, 208), (0.35, 196, 148, 92),
        (0.65, 148, 78, 48), (1.00, 72, 42, 28),
    )),
    # Mid greys only — distinct from full-range B&W.
    ('gray', 'Gray', (
        (0.00, 176, 176, 176), (0.35, 136, 136, 136),
        (0.65, 96, 96, 96), (1.00, 64, 64, 64),
    )),
    ('bw', 'B&W', (
        (0.00, 255, 255, 255), (0.50, 128, 128, 128), (1.00, 0, 0, 0),
    )),
    # Archaeology-oriented + extra density ramps (plugin-controlled, not QgsStyle).
    ('ochre', 'Ochre', (
        (0.00, 255, 248, 220), (0.30, 232, 184, 72),
        (0.60, 196, 108, 36), (1.00, 120, 40, 16),
    )),
    ('ash', 'Ash', (
        (0.00, 28, 24, 22), (0.35, 72, 64, 58),
        (0.65, 148, 140, 132), (1.00, 236, 232, 224),
    )),
    ('sediment', 'Sediment', (
        (0.00, 42, 36, 32), (0.25, 96, 72, 52),
        (0.50, 168, 132, 88), (0.75, 198, 176, 128),
        (1.00, 232, 220, 188),
    )),
    ('archeo', 'Archeo', (
        # Dense dark → cream (terrain × sediment); Invert flips light→dark.
        (0.00, 36, 58, 88), (0.20, 42, 128, 118),
        (0.40, 98, 168, 92), (0.58, 188, 186, 72),
        (0.75, 232, 168, 64), (0.90, 244, 206, 128),
        (1.00, 252, 236, 196),
    )),
    ('bone', 'Bone', (
        (0.00, 252, 246, 232), (0.40, 220, 198, 162),
        (0.70, 168, 132, 96), (1.00, 92, 64, 48),
    )),
    ('copper', 'Copper', (
        (0.00, 20, 16, 28), (0.30, 72, 48, 64),
        (0.55, 160, 88, 48), (0.80, 220, 160, 72),
        (1.00, 252, 236, 180),
    )),
    ('turbo', 'Turbo', (
        (0.00, 48, 18, 59), (0.20, 33, 144, 140),
        (0.40, 34, 167, 71), (0.55, 188, 200, 36),
        (0.70, 252, 166, 17), (0.85, 245, 79, 40),
        (1.00, 180, 4, 38),
    )),
)

_SCHEME_MAP = {sid: (label, stops) for sid, label, stops in COLOR_SCHEMES}
DEFAULT_SCHEME = 'archeo'


def resolve_scheme(name):
    if name in _SCHEME_MAP:
        return name
    return DEFAULT_SCHEME


def scheme_stops(name):
    return _SCHEME_MAP[resolve_scheme(name)][1]


def color_at(t, scheme='viridis', invert=False):
    t = max(0.0, min(1.0, float(t)))
    if invert:
        t = 1.0 - t
    stops = scheme_stops(scheme)
    if t <= stops[0][0]:
        _t, r, g, b = stops[0]
        return QColor(r, g, b)
    for i in range(len(stops) - 1):
        t0, r0, g0, b0 = stops[i]
        t1, r1, g1, b1 = stops[i + 1]
        if t <= t1:
            u = 0.0 if t1 <= t0 else (t - t0) / (t1 - t0)
            return QColor(
                int(round(r0 + (r1 - r0) * u)),
                int(round(g0 + (g1 - g0) * u)),
                int(round(b0 + (b1 - b0) * u)),
            )
    _t, r, g, b = stops[-1]
    return QColor(r, g, b)


def make_ramp(scheme='viridis', invert=False):
    stops = list(scheme_stops(scheme))
    if invert:
        stops = sorted(
            ((1.0 - float(t), r, g, b) for t, r, g, b in stops),
            key=lambda s: s[0],
        )
    c0 = QColor(stops[0][1], stops[0][2], stops[0][3])
    c1 = QColor(stops[-1][1], stops[-1][2], stops[-1][3])
    ramp = QgsGradientColorRamp(c0, c1)
    extra = []
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        from qgis.core import QgsGradientStop
        for t, r, g, b in stops[1:-1]:
            extra.append(QgsGradientStop(float(t), QColor(r, g, b)))
        if extra:
            ramp.setStops(extra)
    return ramp


def scheme_icon(scheme, width=72, height=14, invert=False):
    pm = QPixmap(max(24, int(width)), max(10, int(height)))
    p = QPainter(pm)
    w = pm.width()
    h = pm.height()
    for x in range(w):
        p.setPen(color_at(x / float(max(w - 1, 1)), scheme, invert=invert))
        p.drawLine(x, 0, x, h)
    p.end()
    return QIcon(pm)

_HEATMAP_IDS = (
    'qgis:heatmapkerneldensityestimation',
    'native:heatmapkerneldensityestimation',
)
_CONTOUR_IDS = (
    'gdal:contour',
    'native:contour',
)


def _processing():
    try:
        from qgis import processing
        return processing
    except ImportError:
        import processing
        return processing


# Cells across the kernel radius. Below this the peak crest is 1–2 px and the
# last isoline reads as a black hole on longitudinal / transversal views.
_MIN_RADIUS_CELLS = 12.0
# Interactive preview: Discrete class edges stair-step by 1 cell; need enough
# cells that those stairs are sub-pixel on a typical HiDPI pane.
_PREVIEW_MAX_CELLS = 2400.0
# Supersample vs logical canvas pixels so Bands edges stay sub-pixel.
_PREVIEW_OVERSAMPLE = 2.0
# Paper product: allow finer grids; hard stop so 600 dpi does not explode.
_PAPER_MAX_CELLS = 4000.0


def suggest_params(layer):
    """Radius and cell size in layer units from the current extent."""
    if layer is None:
        return 0.5, 0.05
    ext = layer.extent()
    if ext is None or ext.isEmpty():
        return 0.5, 0.05
    diag = math.hypot(ext.width(), ext.height())
    if diag <= 0:
        return 0.5, 0.05
    radius = max(0.12, min(diag * 0.045, diag * 0.2))
    # Finer of crest-safe max cell and preview target — never max() (that
    # picked radius/12 and forced a ~266-cell coarse grid).
    pixel = min(radius / _MIN_RADIUS_CELLS, diag / _PREVIEW_MAX_CELLS)
    pixel = max(pixel, 0.002)
    return round(radius, 3), round(pixel, 4)


def adapt_kernel(layer, radius, pixel, ref_layer=None):
    """Scale Radius and Cell for a section with the same short-axis factor.

    Plan keeps the UI values. Longitudinal / transversal shrink both by the
    same ``scale`` so Cell stays reactive on every pane (not only Plan).
    Memory bounds stay in ``_clamp_pixel``.
    """
    radius = max(0.05, float(radius))
    pixel = max(0.002, float(pixel))
    if layer is None or ref_layer is None or layer is ref_layer:
        return radius, pixel

    def _short(lyr):
        ext = lyr.extent()
        if ext is None or ext.isEmpty():
            return 0.0
        return min(float(ext.width()), float(ext.height()))

    ref_s = _short(ref_layer)
    lay_s = _short(layer)
    if ref_s <= 1e-9 or lay_s <= 1e-9:
        return radius, pixel
    # Same factor for Radius and Cell — Cell must track UI on all three views.
    scale = max(0.22, min(1.0, lay_s / ref_s))
    radius = max(0.05, radius * scale)
    pixel = max(0.002, pixel * scale)
    return radius, pixel


def map_clip(user_min, user_max, ref_limits, dest_limits):
    """Apply one Min/Max control to any density raster via peak fractions.

    The UI values are interpreted relative to the reference peak (plan KDE).
    On each view (XY, X/Z, Y/Z):

        f_min = user_min / ref_peak
        f_max = user_max / ref_peak
        vmin  = f_min * dest_peak
        vmax  = f_max * dest_peak

    Auto Max on the plan (user_max == ref_peak) therefore opens the peak on
    every section. Absolute KDE units are not shared across views — only the
    fraction of each local peak is.
    """
    if dest_limits is None:
        return user_min, user_max
    dmax = float(dest_limits['max'])
    if not math.isfinite(dmax) or dmax <= 0.0:
        return user_min, user_max
    umin = max(0.0, float(user_min))
    umax = max(umin, float(user_max))
    rmax = None
    if ref_limits is not None:
        with suppress(TypeError, ValueError):
            rmax = float(ref_limits['max'])
    if rmax is None or not math.isfinite(rmax) or rmax <= 0.0:
        # No reference peak: treat UI values as absolute on this raster.
        if umin >= dmax:
            return 0.0, dmax
        return umin, min(dmax, umax)
    fmin = max(0.0, min(1.0, umin / rmax))
    fmax = max(fmin, min(1.0, umax / rmax))
    vmin = fmin * dmax
    vmax = fmax * dmax
    if vmax <= vmin:
        return 0.0, dmax
    return vmin, vmax


def _extent_wh(extent):
    """Return (width, height) from (xmin, xmax, ymin, ymax) or QgsRectangle."""
    xmin = xmax = ymin = ymax = None
    with suppress(AttributeError, TypeError, ValueError):
        if hasattr(extent, 'xMinimum'):
            xmin = float(extent.xMinimum())
            xmax = float(extent.xMaximum())
            ymin = float(extent.yMinimum())
            ymax = float(extent.yMaximum())
        else:
            xmin, xmax, ymin, ymax = (
                float(extent[0]), float(extent[1]),
                float(extent[2]), float(extent[3]),
            )
    if xmin is None:
        return None, None
    return max(xmax - xmin, 1e-12), max(ymax - ymin, 1e-12)


def _device_pixel(extent, out_w, out_h, radius, max_cells):
    """~1 KDE cell per output pixel, then memory cap and crest floor."""
    width, height = _extent_wh(extent)
    radius = max(0.05, float(radius))
    if width is None:
        return max(0.002, radius / _MIN_RADIUS_CELLS)
    ow = max(int(out_w), 1)
    oh = max(int(out_h), 1)
    cell = max(width / float(ow), height / float(oh))
    longest = max(width, height)
    cell = max(cell, longest / float(max_cells), 0.002)
    max_cell = radius / _MIN_RADIUS_CELLS
    if cell > max_cell:
        cell = max(max_cell, 0.002)
    return cell


def _clamp_pixel(layer, radius, pixel, for_paper=False):
    """Bound cell size for memory only — keep the UI Cell whenever feasible.

    Previously also forced ``pixel <= radius/12`` (crest quality). That pinned
    Cell to a near-fixed value for typical radii, so spin changes never
    reached the KDE and the drawing looked frozen.
    """
    ext = layer.extent()
    pad = 2.0 * max(radius, 0.0)
    width = float(ext.width()) + pad
    height = float(ext.height()) + pad
    longest = max(width, height, 1.0)
    radius = max(0.05, float(radius))
    pixel = max(float(pixel), 0.002)
    max_cells = _PAPER_MAX_CELLS if for_paper else _PREVIEW_MAX_CELLS
    # Memory floor: refuse absurdly fine grids (longest side ≤ max_cells).
    min_pixel = longest / float(max_cells)
    if pixel < min_pixel:
        pixel = min_pixel
    # Coarse ceiling: cell larger than the kernel is meaningless for KDE.
    max_pixel = max(radius, min_pixel)
    if pixel > max_pixel:
        pixel = max_pixel
    return pixel


def preview_pixel(extent, canvas_w, canvas_h, radius, device_pixel_ratio=1.0):
    """Cell size so Discrete stairs stay sub-pixel on the canvas at fit.

    Rule: device pixels drive the density grid. Uses HiDPI ratio and
    ``_PREVIEW_OVERSAMPLE`` so one class edge step is finer than one screen
    pixel (Bands + nearest would otherwise read as dents de serra).
    """
    dpr = max(1.0, float(device_pixel_ratio) or 1.0)
    scale = dpr * _PREVIEW_OVERSAMPLE
    cw = max(int(round(float(canvas_w) * scale)), 1)
    ch = max(int(round(float(canvas_h) * scale)), 1)
    # Canvas may still be unset at first show — aim for a typical pane.
    if cw < int(40 * scale):
        cw = int(640 * scale)
    if ch < int(40 * scale):
        ch = int(400 * scale)
    return _device_pixel(extent, cw, ch, radius, _PREVIEW_MAX_CELLS)


def paper_pixel(extent, plot_w, plot_h, radius):
    """Cell size so the KDE grid matches paper output pixels.

    Rule: paper pixels drive the density grid; the screen never does.
    ~1 KDE cell per output pixel, then memory cap (~4000) and crest floor.
    ``extent`` is (xmin, xmax, ymin, ymax) or a QgsRectangle.
    """
    return _device_pixel(extent, plot_w, plot_h, radius, _PAPER_MAX_CELLS)


def _resampling_method(*names):
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        from qgis.core import Qgis
        enum = getattr(Qgis, 'RasterResamplingMethod', None)
        if enum is not None:
            for name in names:
                val = getattr(enum, name, None)
                if val is not None:
                    return val
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        from qgis.core import QgsRasterDataProvider
        enum = getattr(QgsRasterDataProvider, 'ResamplingMethod', None)
        if enum is not None:
            for name in names:
                val = getattr(enum, name, None)
                if val is not None:
                    return val
    return None


def _class_count(levels):
    try:
        n = int(levels)
    except (TypeError, ValueError):
        n = 8
    return max(3, min(16, n))


def _density_spec(vmin, vmax, levels, dmax=None):
    """Shared class breaks for the KDE raster shader and isoline levels.

    Matches QGIS Layer Styling → Singleband pseudocolor → Discrete →
    Equal interval → classifyColorRamp(): the last class upper bound is
    +inf so the peak cell is always coloured. Isolines use every finite
    class edge that is painted (first class included) — never a contour at
    the data peak when Max = peak.
    """
    vmin = max(0.0, float(vmin))
    vmax = max(vmin, float(vmax))
    n = _class_count(levels)
    interval = max(vmax - vmin, 1e-12) / float(n)
    # Finite equal-interval uppers (exclude the open last class at +inf).
    breaks = [vmin + interval * i for i in range(1, n)]
    if dmax is None:
        dmax = vmax
    else:
        dmax = float(dmax)
    # Max counts as "at peak" within half a class (spinbox / float / map_clip).
    # A stricter 0.99 rule left open_top False with Max slightly under dmax:
    # transparency then punched ONLY the global tip — secondary peaks looked fine.
    peak_slop = max(interval * 0.5, abs(dmax) * 1e-4, 1e-9)
    open_top = (dmax - vmax) <= peak_slop
    # Class uppers (e.g. 55 for band 0–55). Never skip the first upper.
    isolines = [float(b) for b in breaks if b > interval * 1e-6]
    if open_top and isolines:
        # Drop the boundary of the open last class: that ring frames the hole
        # when the global tip fails to paint.
        isolines = isolines[:-1]
    if not open_top and (not isolines or abs(isolines[-1] - vmax) > interval * 0.05):
        isolines.append(float(vmax))
    if not isolines:
        isolines = [float(vmin + interval)]
    # Outer edge of the first painted class (Min). Without this, the 0–55
    # band has no stroke against the empty background — only an inner ring
    # at the first upper. Contour at exact 0 is meaningless / noisy.
    floor_eps = _zero_density_eps(0.0, max(vmax, dmax))
    if vmin > floor_eps and (
        not isolines or abs(float(isolines[0]) - vmin) > interval * 0.05
    ):
        isolines.insert(0, float(vmin))
    return {
        'vmin': vmin,
        'vmax': vmax,
        'dmax': dmax,
        'interval': interval,
        'levels': n,
        'breaks': breaks,
        'isolines': isolines,
        'open_top': open_top,
        'paint_max': dmax if open_top else vmax,
    }


def _spec_for_raster(rlayer, clip_min, clip_max, levels):
    rng = _clip_range(rlayer, clip_min, clip_max)
    if rng is None:
        return None
    limits = raster_limits(rlayer)
    dmax = float(limits['max']) if limits is not None else rng[1]
    return _density_spec(rng[0], rng[1], levels, dmax=dmax)


def _zero_density_eps(vmin, vmax):
    """Values at/near 0 are empty KDE, not a class. Relative so sections stay valid."""
    span = max(abs(float(vmax) - float(vmin)), abs(float(vmax)), 1e-12)
    return max(span * 1e-6, 1e-12)


def _snap_level(val, allowed, tol):
    best = None
    best_d = None
    for item in allowed:
        try:
            target = float(item)
        except (TypeError, ValueError):
            continue
        dist = abs(float(val) - target)
        if dist <= tol and (best_d is None or dist < best_d):
            best, best_d = target, dist
    return best


def _enable_smooth_resample(rlayer):
    """Bilinear/cubic zoom so the KDE reads as a continuous field, not cells."""
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        rlayer.setResamplingEnabled(True)
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        from qgis.core import Qgis
        stage = getattr(Qgis, 'RasterResamplingStage', None)
        if stage is not None and hasattr(rlayer, 'setResamplingStage'):
            filt = getattr(stage, 'ResampleFilter', None)
            if filt is not None:
                rlayer.setResamplingStage(filt)
    cubic = _resampling_method('Cubic', 'CubicSpline', 'Bilinear')
    zoomed_out = _resampling_method('Bilinear', 'Average', 'Cubic')
    provider = rlayer.dataProvider()
    if provider is not None and cubic is not None:
        with suppress(AttributeError, RuntimeError, TypeError, ValueError):
            provider.setZoomedInResamplingMethod(cubic)
            if zoomed_out is not None:
                provider.setZoomedOutResamplingMethod(zoomed_out)
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        from qgis.core import QgsBilinearRasterResampler, QgsCubicRasterResampler
        filt = rlayer.resampleFilter()
        if filt is not None:
            try:
                filt.setZoomedInResampler(QgsCubicRasterResampler())
            except Exception:
                filt.setZoomedInResampler(QgsBilinearRasterResampler())
            with suppress(AttributeError, RuntimeError, TypeError, ValueError):
                filt.setZoomedOutResampler(QgsBilinearRasterResampler())
            if hasattr(filt, 'setMaxOversampling'):
                filt.setMaxOversampling(24.0)


def _run(alg_ids, params):
    processing = _processing()
    feedback = QgsProcessingFeedback()
    last = None
    for alg in alg_ids:
        try:
            return processing.run(alg, params, feedback=feedback)
        except Exception as exc:
            last = exc
    if last is not None:
        raise last
    raise RuntimeError('No density algorithm available')


def _kernel_index(kernel):
    try:
        idx = int(kernel)
    except (TypeError, ValueError):
        idx = 0
    return max(0, min(idx, len(KERNELS) - 1))


def build_heatmap(point_layer, radius, pixel, kernel=0, for_paper=False):
    if point_layer is None or point_layer.featureCount() < 2:
        return None
    radius = max(0.05, float(radius))
    pixel = _clamp_pixel(point_layer, radius, pixel, for_paper=for_paper)
    kernel = _kernel_index(kernel)
    params = {
        'INPUT': point_layer,
        'RADIUS': radius,
        'PIXEL_SIZE': pixel,
        'KERNEL': kernel,
        'DECAY': 0.0,
        'OUTPUT_VALUE': 0,
        'OUTPUT': 'TEMPORARY_OUTPUT',
    }
    try:
        result = _run(_HEATMAP_IDS, params)
    except Exception:
        alt = dict(params)
        alt['KERNEL'] = KERNELS[kernel][0]
        try:
            result = _run(_HEATMAP_IDS, alt)
        except Exception:
            result = _run(_HEATMAP_IDS, {
                'INPUT': point_layer,
                'RADIUS': radius,
                'PIXEL_SIZE': pixel,
                'KERNEL': kernel,
                'OUTPUT_VALUE': 0,
                'OUTPUT': 'TEMPORARY_OUTPUT',
            })
    path = result.get('OUTPUT')
    if not path:
        return None
    rlayer = QgsRasterLayer(path, point_layer.name() + ' · density')
    if not rlayer.isValid():
        return None
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        rlayer.reload()
    rlayer.setCustomProperty('arsysplotqgis', 'density-raster')
    rlayer.setCustomProperty('arsysplotqgis_cell', '%.8g' % float(pixel))
    rlayer.setCustomProperty('arsysplotqgis_radius', '%.8g' % float(radius))
    raster_limits(rlayer)
    _enable_smooth_resample(rlayer)
    return rlayer


def _raster_size(rlayer):
    w = h = 0
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        w = int(rlayer.width() or 0)
        h = int(rlayer.height() or 0)
    if w > 0 and h > 0:
        return w, h
    provider = rlayer.dataProvider() if rlayer is not None else None
    if provider is None:
        return 0, 0
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        w = int(provider.xSize() or 0)
        h = int(provider.ySize() or 0)
    return w, h


_LIMITS_KEY = 'arsysplotqgis_limits'


def _store_limits(rlayer, limits):
    if rlayer is None or not limits:
        return
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        rlayer.setCustomProperty(_LIMITS_KEY, '%.12g|%.12g|%.12g|%d' % (
            float(limits['min']),
            float(limits['max']),
            float(limits['cut_low']),
            int(limits.get('n') or 0),
        ))


def _load_limits(rlayer):
    if rlayer is None:
        return None
    raw = None
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        raw = rlayer.customProperty(_LIMITS_KEY)
    if not raw:
        return None
    parts = str(raw).split('|')
    if len(parts) < 3:
        return None
    try:
        return {
            'min': float(parts[0]),
            'max': float(parts[1]),
            'cut_low': float(parts[2]),
            'n': int(float(parts[3])) if len(parts) > 3 else 0,
        }
    except (TypeError, ValueError):
        return None


def _user_nodata(provider):
    if provider is None:
        return []
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        return list(provider.userNoDataValues(1) or [])
    return []


def _set_user_nodata(provider, ranges):
    if provider is None:
        return
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        provider.setUserNoDataValue(1, list(ranges or []))


def raster_limits(rlayer, lower_frac=0.02):
    """Raw KDE min/max and 2 percent cut. Cached before any Min clip / no-data."""
    cached = _load_limits(rlayer)
    if cached is not None:
        return cached
    measured = _measure_raster_limits(rlayer, lower_frac)
    if measured is not None:
        _store_limits(rlayer, measured)
    return measured


def _measure_raster_limits(rlayer, lower_frac=0.02):
    """Read the KDE once, ignoring the current Min no-data mask."""
    if rlayer is None:
        return None
    provider = rlayer.dataProvider()
    if provider is None:
        return None
    saved = _user_nodata(provider)
    _set_user_nodata(provider, [])
    w, h = _raster_size(rlayer)
    vmin_pos = None
    vmax = None
    samples = []
    n_pos = 0
    extent = rlayer.extent()

    def _ingest(block, rows, cols):
        nonlocal vmin_pos, vmax, n_pos
        if block is None or rows <= 0 or cols <= 0:
            return
        total = max(1, rows * cols)
        stride = max(1, total // 80000)
        idx = 0
        for row in range(rows):
            for col in range(cols):
                try:
                    val = float(block.value(row, col))
                except Exception:
                    idx += 1
                    continue
                idx += 1
                if not math.isfinite(val) or val <= 0.0:
                    continue
                n_pos += 1
                if vmax is None or val > vmax:
                    vmax = val
                if vmin_pos is None or val < vmin_pos:
                    vmin_pos = val
                if idx % stride == 0:
                    samples.append(val)

    try:
        stats_max = None
        stats_min = None
        with suppress(AttributeError, RuntimeError, TypeError, ValueError):
            stats = provider.bandStatistics(
                1, QgsRasterBandStats.Stats.Min | QgsRasterBandStats.Stats.Max,
                extent, 0,
            )
            stats_max = float(stats.maximumValue)
            stats_min = float(stats.minimumValue)
            if not math.isfinite(stats_max) or stats_max <= 0.0:
                stats_max = None
        if w > 0 and h > 0:
            rw, rh = w, h
            ncells = w * h
            if ncells > 500000:
                scale = math.sqrt(500000.0 / float(ncells))
                rw = max(48, int(w * scale))
                rh = max(48, int(h * scale))
            try:
                block = provider.block(1, extent, rw, rh)
            except Exception:
                block = None
            _ingest(block, rh, rw)
        if stats_max is not None:
            if vmax is None or stats_max > vmax:
                vmax = stats_max
            if vmin_pos is None and stats_min is not None and math.isfinite(stats_min) and stats_min > 0.0:
                vmin_pos = stats_min
        if vmax is None or vmax <= 0.0:
            return None
        if vmin_pos is None or vmin_pos < 0.0:
            vmin_pos = 0.0
        cut_low = vmin_pos
        if samples:
            samples.sort()
            frac = max(0.0, min(0.49, float(lower_frac)))
            k = int(round((len(samples) - 1) * frac))
            cut_low = float(samples[max(0, min(k, len(samples) - 1))])
            if cut_low >= vmax:
                cut_low = vmin_pos
        return {'min': vmin_pos, 'max': vmax, 'cut_low': cut_low, 'n': n_pos}
    finally:
        _set_user_nodata(provider, saved)


def _transparent_range(lo, hi, include_min=True, include_max=False):
    from qgis.core import QgsRasterTransparency
    px = QgsRasterTransparency.TransparentSingleValuePixel()
    if hasattr(px, 'minValue'):
        px.minValue = float(lo)
        px.maxValue = float(hi)
    else:
        px.min = float(lo)
        px.max = float(hi)
    if hasattr(px, 'includeMinimum'):
        px.includeMinimum = bool(include_min)
    if hasattr(px, 'includeMaximum'):
        px.includeMaximum = bool(include_max)
    px.percentTransparent = 100.0
    return px


def _clear_provider_user_nodata(rlayer):
    provider = rlayer.dataProvider() if rlayer is not None else None
    if provider is None:
        return
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        provider.setUserNoDataValue(1, [])


def _hide_outside_stretch(renderer, vmin, vmax, open_top):
    """Hide cells below Min only.

    Never use transparency for "above Max": that punches only the global
    peak tip and leaves secondary peaks painted (exactly the X/Z symptom).
    Intentional Max < peak is handled by a finite last class + shader clip.
    """
    from qgis.core import QgsRasterTransparency
    if renderer is None:
        return
    lo = max(0.0, float(vmin))
    pixels = [_transparent_range(0.0, lo, True, False)]
    trans = QgsRasterTransparency()
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        trans.setTransparentSingleValuePixelList(pixels)
        renderer.setRasterTransparency(trans)


def _apply_max_clip(renderer, vmax):
    """When Max is below the peak: close the last class at Max and clip above."""
    if renderer is None:
        return
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        shader = renderer.shader()
        fn = shader.rasterShaderFunction() if shader is not None else None
        if fn is None:
            return
        items = list(fn.colorRampItemList() or [])
        if not items:
            return
        last = items[-1]
        items[-1] = QgsColorRampShader.ColorRampItem(
            float(vmax), last.color, '%.4g' % float(vmax),
        )
        fn.setColorRampItemList(items)
        fn.setClip(True)
        fn.setMaximumValue(float(vmax))


def _clip_range(rlayer, clip_min=None, clip_max=None):
    """User Min/Max, clamped to the raster. Below Min is not drawn (QGIS clip)."""
    limits = raster_limits(rlayer)
    if limits is None:
        return None
    dmin, dmax = float(limits['min']), float(limits['max'])
    vmin = 0.0 if clip_min is None else float(clip_min)
    vmax = dmax if clip_max is None else float(clip_max)
    if not math.isfinite(vmin):
        vmin = 0.0
    if not math.isfinite(vmax):
        vmax = dmax
    vmin = max(0.0, vmin)
    vmax = min(dmax, max(vmax, vmin))
    if vmax <= vmin:
        vmax = dmax
    if vmax <= vmin:
        return None
    return vmin, vmax


def _force_open_last_class(renderer):
    """QGIS Discrete equal-interval uses +inf on the last class; keep it.

    A finite last bound equal to Max is what punches the peak black hole
    (shade() returns False for any cell above that bound).
    """
    if renderer is None:
        return
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        shader = renderer.shader()
        fn = shader.rasterShaderFunction() if shader is not None else None
        if fn is None:
            return
        items = list(fn.colorRampItemList() or [])
        if items and math.isfinite(float(items[-1].value)):
            last = items[-1]
            items[-1] = QgsColorRampShader.ColorRampItem(
                float('inf'), last.color, 'inf',
            )
            fn.setColorRampItemList(items)
        fn.setClip(False)


def style_heatmap(rlayer, opacity=0.7, scheme='viridis', levels=8,
                  clip_min=None, clip_max=None, fill='bands', invert=False):
    """Style the KDE raster via QgsSingleBandPseudoColorRenderer.createShader.

    Same path as Layer Properties → Singleband pseudocolor. Bands = Discrete
    + EqualInterval (last class +inf). Cloud = Linear Continuous. Both use
    bilinear resampling so thin longitudinal peaks stay visible.
    """
    if rlayer is None:
        return
    spec = _spec_for_raster(rlayer, clip_min, clip_max, levels)
    if spec is None:
        rlayer.setOpacity(0.0)
        rlayer.triggerRepaint()
        return
    vmin = float(spec['vmin'])
    vmax = float(spec['vmax'])
    paint_max = float(spec['paint_max'])
    open_top = bool(spec['open_top'])
    scheme = resolve_scheme(scheme)
    invert = bool(invert)
    opacity = max(0.0, min(1.0, float(opacity)))
    fill = 'cloud' if fill == 'cloud' else 'bands'
    levels_n = int(spec['levels'])

    # Drop leftover user-nodata masks from earlier contour runs.
    _clear_provider_user_nodata(rlayer)

    provider = rlayer.dataProvider()
    renderer = QgsSingleBandPseudoColorRenderer(provider, 1)
    renderer.setClassificationMin(vmin)
    renderer.setClassificationMax(paint_max)
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        renderer.setNodataColor(QColor(0, 0, 0, 0))

    ramp = make_ramp(scheme, invert=invert)
    if fill == 'cloud':
        ramp_type = (
            getattr(Qgis.ShaderInterpolationMethod, 'Linear', None)
            or Qgis.ShaderInterpolationMethod.Linear
        )
        class_mode = Qgis.ShaderClassificationMethod.Continuous
        n_classes = 0
    else:
        ramp_type = Qgis.ShaderInterpolationMethod.Discrete
        class_mode = Qgis.ShaderClassificationMethod.EqualInterval
        n_classes = levels_n

    # clip=False always: Discrete last class is +inf; clip is handled by
    # transparency when Max is below the peak (createShader+clip still paints
    # above Max when the last bound is +inf).
    created = False
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        renderer.createShader(
            ramp, ramp_type, class_mode, n_classes, False,
        )
        created = renderer.shader() is not None

    if not created:
        fn = QgsColorRampShader()
        if fill == 'cloud':
            with suppress(AttributeError, RuntimeError, TypeError, ValueError):
                fn.setColorRampType(QgsColorRampShader.Type.Interpolated)
        else:
            fn.setColorRampType(QgsColorRampShader.Type.Discrete)
            with suppress(AttributeError, RuntimeError, TypeError, ValueError):
                fn.setClassificationMode(
                    QgsColorRampShader.ClassificationMode.EqualInterval,
                )
        fn.setMinimumValue(vmin)
        fn.setMaximumValue(paint_max)
        fn.setSourceColorRamp(make_ramp(scheme, invert=invert))
        with suppress(AttributeError, RuntimeError, TypeError, ValueError):
            if fill != 'cloud':
                fn.classifyColorRamp(levels_n)
        if fill != 'cloud' and not fn.colorRampItemList():
            n = levels_n
            interval = max(paint_max - vmin, 1e-12) / float(n)
            items = []
            for i in range(1, n + 1):
                upper = float('inf') if i == n else (vmin + interval * i)
                t = (i - 1) / float(n - 1) if n > 1 else 0.5
                c = QColor(color_at(t, scheme, invert=invert))
                c.setAlpha(255)
                items.append(QgsColorRampShader.ColorRampItem(
                    upper, c, 'inf' if not math.isfinite(upper) else '%.4g' % upper,
                ))
            fn.setColorRampItemList(items)
        fn.setClip(False)
        shader = QgsRasterShader()
        shader.setRasterShaderFunction(fn)
        renderer.setShader(shader)

    if fill != 'cloud':
        if open_top:
            _force_open_last_class(renderer)
        else:
            # User Max clearly below peak: clip the tip on purpose (all peaks
            # above Max hide — not via transparency, which only nuked the tip).
            _apply_max_clip(renderer, vmax)
    _hide_outside_stretch(renderer, vmin, vmax, open_top)
    rlayer.setRenderer(renderer)
    # Always bilinear/cubic on a fine grid: Discrete class edges get ~1 px of
    # anti-alias instead of nearest-neighbour dents de serra. Coarse+bilinear
    # was the old "dirty" look; nearest on Discrete is sharp sawtooth. Crest
    # paintability comes from _MIN_RADIUS_CELLS, not from nearest.
    _enable_smooth_resample(rlayer)
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        rlayer.setCustomProperty('arsysplotqgis_fill', fill)
        rlayer.setCustomProperty('arsysplotqgis_scheme', scheme)
        rlayer.setCustomProperty('arsysplotqgis_invert', '1' if invert else '0')
        rlayer.setCustomProperty('arsysplotqgis_levels', str(int(levels_n)))
        last_v = 'cloud'
        if fill != 'cloud':
            try:
                last_v = str(
                    renderer.shader().rasterShaderFunction()
                    .colorRampItemList()[-1].value
                )
            except Exception:
                last_v = '?'
        rlayer.setCustomProperty('arsysplotqgis_last_class', last_v)
        rlayer.setCustomProperty(
            'arsysplotqgis_open_top', '1' if open_top else '0',
        )
    rlayer.setOpacity(opacity)
    rlayer.triggerRepaint()


def _contour_result_layer(result, name):
    path = result.get('OUTPUT') if result else None
    if not path:
        return None
    layer = path if isinstance(path, QgsVectorLayer) else QgsVectorLayer(
        str(path), name, 'ogr',
    )
    if not layer.isValid() or layer.featureCount() < 1:
        return None
    return layer


def _raster_gdal_path(rlayer):
    """Filesystem path GDAL can open for the KDE raster."""
    if rlayer is None:
        return ''
    src = ''
    with suppress(Exception):
        src = str(rlayer.source() or '')
    if not src:
        with suppress(Exception):
            src = str(rlayer.dataProvider().dataSourceUri() or '')
    if not src:
        return ''
    # Drop provider key prefixes ("/vsicurl/...", still ok; "Atrribute=..." not).
    if src.startswith('http://') or src.startswith('https://'):
        return src
    # Common QGIS form: path alone, or path with query options after '|'.
    path = src.split('|', 1)[0].strip()
    if path and (os.path.exists(path) or path.startswith('/vsi')):
        return path
    return path if path else ''


def _contour_via_fixed_levels(rlayer, isolines):
    """Build isolines at exact class edges (Min + every finite upper).

    Uses GDAL -fl so the first class (e.g. outer Min and upper 55) is never
    skipped by the interval rule ("first multiple greater than raster min").
    """
    if rlayer is None or not isolines:
        return None
    src_path = _raster_gdal_path(rlayer)
    if not src_path:
        return None
    try:
        from osgeo import gdal
        gdal.UseExceptions()
    except ImportError:
        return None
    levels = [float(v) for v in isolines]
    fd, out_path = tempfile.mkstemp(prefix='arsys_iso_', suffix='.shp')
    os.close(fd)
    # Shapefile is a set of sidecars; remove the empty stub before create.
    with suppress(OSError):
        os.unlink(out_path)
    opts = ['-a', 'ELEV', '-fl'] + ['%.10g' % v for v in levels]
    try:
        gdal.Contour(out_path, src_path, options=opts)
    except Exception:
        _unlink_shapefile(out_path)
        return None
    layer = QgsVectorLayer(out_path, rlayer.name() + ' · isolines', 'ogr')
    if not layer.isValid() or layer.featureCount() < 1:
        _unlink_shapefile(out_path)
        return None
    return layer


def _unlink_shapefile(path):
    if not path:
        return
    stem = os.path.splitext(path)[0]
    for suffix in ('.shp', '.dbf', '.shx', '.prj', '.cpg', '.qix'):
        with suppress(OSError):
            os.unlink(stem + suffix)


def _contour_via_gdal_fl(rlayer, isolines, interval):
    """QGIS gdal:contour with EXTRA -fl (when direct Contour API is unavailable)."""
    if rlayer is None or not isolines:
        return None
    fl = ' '.join('%.10g' % float(v) for v in isolines)
    # Huge -i so interval alone yields no in-range lines; -fl supplies edges.
    span = max(abs(float(isolines[-1])), abs(float(isolines[0])), float(interval), 1.0)
    params = {
        'INPUT': rlayer,
        'BAND': 1,
        'INTERVAL': span * 100.0 + 1.0,
        'FIELD_NAME': 'ELEV',
        'CREATE_3D': False,
        'IGNORE_NODATA': True,
        'OFFSET': 0.0,
        'EXTRA': '-fl %s' % fl,
        'OUTPUT': 'TEMPORARY_OUTPUT',
    }
    processing = _processing()
    feedback = QgsProcessingFeedback()
    name = rlayer.name() + ' · isolines'
    for drop_ignore in (False, True):
        run_params = dict(params)
        if drop_ignore:
            run_params.pop('IGNORE_NODATA', None)
        with suppress(Exception):
            result = processing.run('gdal:contour', run_params, feedback=feedback)
            layer = _contour_result_layer(result, name)
            if layer is not None:
                return layer
    return None


def _contour_via_interval(rlayer, isolines, interval):
    """Last resort: OFFSET+INTERVAL through gdal:contour / native:contour."""
    if rlayer is None or not isolines:
        return None
    params = {
        'INPUT': rlayer,
        'BAND': 1,
        'INTERVAL': max(float(interval), 1e-9),
        'FIELD_NAME': 'ELEV',
        'CREATE_3D': False,
        'IGNORE_NODATA': True,
        # Base at 0 so the first class upper (offset+1*interval when vmin~0)
        # is requested; fixed-level paths above are preferred.
        'OFFSET': float(isolines[0]),
        'OUTPUT': 'TEMPORARY_OUTPUT',
    }
    try:
        result = _run(_CONTOUR_IDS, params)
    except Exception:
        params.pop('IGNORE_NODATA', None)
        try:
            result = _run(_CONTOUR_IDS, params)
        except Exception:
            return None
    return _contour_result_layer(result, rlayer.name() + ' · isolines')


def build_contours(rlayer, levels=8, clip_min=None, clip_max=None):
    if rlayer is None:
        return None
    spec = _spec_for_raster(rlayer, clip_min, clip_max, levels)
    if spec is None or spec['interval'] <= 0:
        return None
    isolines = [float(v) for v in spec['isolines']]
    if not isolines:
        return None
    # Do not alter the display raster's nodata mask for contouring.
    layer = _contour_via_fixed_levels(rlayer, isolines)
    if layer is None:
        layer = _contour_via_gdal_fl(rlayer, isolines, spec['interval'])
    if layer is None:
        layer = _contour_via_interval(rlayer, isolines, spec['interval'])
    if layer is None:
        return None
    layer.setCustomProperty('arsysplotqgis', 'density-contour')
    layer = _merge_connected_isolines(layer)
    return _keep_contour_levels(layer, isolines, spec['interval'])


def _contour_elev_field(layer):
    if layer is None:
        return ''
    if layer.fields().lookupField('ELEV') >= 0:
        return 'ELEV'
    if layer.fields().count():
        return layer.fields()[0].name()
    return ''


def _keep_contour_levels(layer, allowed, interval):
    """Keep only isolines that match the shared class list."""
    if layer is None:
        return None
    field = _contour_elev_field(layer)
    if not field:
        return layer
    tol = max(float(interval) * 0.02, 1e-9)
    drop = []
    for feat in layer.getFeatures():
        try:
            val = float(feat[field])
        except (TypeError, ValueError):
            drop.append(feat.id())
            continue
        if _snap_level(val, allowed, tol) is None:
            drop.append(feat.id())
    if drop:
        with suppress(AttributeError, RuntimeError, TypeError, ValueError):
            layer.dataProvider().deleteFeatures(drop)
            layer.updateExtents()
    if layer.featureCount() < 1:
        return None
    layer.triggerRepaint()
    return layer

def _line_parts(geom):
    parts = []
    if geom is None or geom.isEmpty():
        return parts
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        if geom.isMultipart():
            for ring in geom.asMultiPolyline() or []:
                if ring and len(ring) >= 2:
                    piece = QgsGeometry.fromPolylineXY(ring)
                    if piece is not None and not piece.isEmpty():
                        parts.append(piece)
            if parts:
                return parts
        ring = geom.asPolyline()
        if ring and len(ring) >= 2:
            piece = QgsGeometry.fromPolylineXY(ring)
            if piece is not None and not piece.isEmpty():
                return [piece]
    parts.append(QgsGeometry(geom))
    return parts


def _cluster_touching(geoms, eps):
    n = len(geoms)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for i in range(n):
        for j in range(i + 1, n):
            if find(i) == find(j):
                continue
            touch = False
            with suppress(AttributeError, RuntimeError, TypeError, ValueError):
                if geoms[i].intersects(geoms[j]):
                    touch = True
                elif geoms[i].distance(geoms[j]) <= eps:
                    touch = True
            if touch:
                union(i, j)
    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(geoms[i])
    return list(groups.values())


def _collect_parts(geoms):
    if not geoms:
        return None
    merged = None
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        merged = QgsGeometry.collectGeometry(geoms)
    if merged is not None and not merged.isEmpty():
        return merged
    merged = geoms[0]
    for extra in geoms[1:]:
        with suppress(AttributeError, RuntimeError, TypeError, ValueError):
            combined = merged.combine(extra)
            if combined is not None and not combined.isEmpty():
                merged = combined
    return merged


def _merge_connected_isolines(layer):
    """One feature per continuous isoline: one label per line, not per fragment."""
    if layer is None:
        return None
    field = _contour_elev_field(layer)
    if not field:
        return layer
    grouped = {}
    for feat in layer.getFeatures():
        try:
            val = round(float(feat[field]), 6)
        except (TypeError, ValueError):
            continue
        for piece in _line_parts(feat.geometry()):
            grouped.setdefault(val, []).append(piece)
    if not grouped:
        return layer
    peak = max(abs(val) for val in grouped) if grouped else 0.0
    zero_eps = _zero_density_eps(0.0, peak)
    grouped = {
        val: geoms for val, geoms in grouped.items() if abs(val) > zero_eps
    }
    if not grouped:
        return None
    diag = 1.0
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        ext = layer.extent()
        diag = math.hypot(float(ext.width()), float(ext.height()))
    eps = max(diag * 0.002, 1e-9)
    mem = QgsVectorLayer('MultiLineString', layer.name(), 'memory')
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        mem.setCrs(layer.crs())
    provider = mem.dataProvider()
    provider.addAttributes(list(layer.fields()))
    mem.updateFields()
    i_elev = mem.fields().lookupField(field)
    extras = []
    for val, geoms in grouped.items():
        clusters = _cluster_touching(geoms, eps)
        for cluster in clusters:
            geom = _collect_parts(cluster)
            if geom is None or geom.isEmpty():
                continue
            nf = QgsFeature(mem.fields())
            nf.setGeometry(geom)
            attrs = [None] * mem.fields().count()
            if i_elev >= 0:
                attrs[i_elev] = float(val)
            nf.setAttributes(attrs)
            extras.append(nf)
    if extras:
        provider.addFeatures(extras)
        mem.updateExtents()
    mem.setCustomProperty('arsysplotqgis', 'density-contour')
    if mem.featureCount() < 1:
        return layer
    return mem


def _label_placement_line():
    """QGIS 3.40 moved Line from QgsPalLayerSettings to Qgis.LabelPlacement."""
    from qgis.core import QgsPalLayerSettings
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        from qgis.core import Qgis
        return Qgis.LabelPlacement.Line
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        return QgsPalLayerSettings.Placement.Line
    return None


# Isoline / level labels: typographic points (word-processor style).
_ISOLINE_LABEL_PT = 9.0


def style_contour_labels(layer, on=False, size_pt=None):
    """Toggle density-value labels along isolines.

    ``size_pt`` is typographic points (pt), as in a word processor.
    """
    if layer is None:
        return
    if not on:
        with suppress(AttributeError, RuntimeError, TypeError, ValueError):
            layer.setLabelsEnabled(False)
        with suppress(AttributeError, RuntimeError, TypeError, ValueError):
            layer.setLabeling(None)
        layer.triggerRepaint()
        return
    field = _contour_elev_field(layer)
    if not field:
        return
    from qgis.core import (
        Qgis,
        QgsPalLayerSettings,
        QgsTextBufferSettings,
        QgsTextFormat,
        QgsUnitTypes,
        QgsVectorLayerSimpleLabeling,
    )
    from qgis.PyQt.QtGui import QFont
    try:
        pt = float(size_pt) if size_pt is not None else float(_ISOLINE_LABEL_PT)
    except (TypeError, ValueError):
        pt = float(_ISOLINE_LABEL_PT)
    pt = max(6.0, min(36.0, pt))
    settings = QgsPalLayerSettings()
    settings.fieldName = field
    settings.isExpression = False
    settings.enabled = True
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        settings.drawLabels = True
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        settings.formatNumbers = True
        settings.decimals = 0
    placement = _label_placement_line()
    if placement is not None:
        settings.placement = placement
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        settings.layerType = Qgis.GeometryType.Line
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        settings.mergeLines = True
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        settings.labelPerPart = False
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        settings.repeatDistance = 0
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        settings.priority = 8
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        settings.obstacle = False
        obs = settings.obstacleSettings()
        if hasattr(obs, 'setIsObstacle'):
            obs.setIsObstacle(False)
        settings.setObstacleSettings(obs)
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        line = settings.lineSettings()
        flags = None
        flag_enum = getattr(Qgis, 'LabelLinePlacementFlag', None)
        if flag_enum is not None:
            # Above the stroke — OnLine reads as beads on the isoline.
            above = getattr(flag_enum, 'AboveLine', None)
            map_or = getattr(flag_enum, 'MapOrientation', None)
            if above is not None:
                flags = above
                if map_or is not None:
                    flags = flags | map_or
            else:
                on_line = getattr(flag_enum, 'OnLine', None)
                if on_line is not None:
                    flags = on_line
                    if map_or is not None:
                        flags = flags | map_or
        if flags is not None and hasattr(line, 'setPlacementFlags'):
            line.setPlacementFlags(flags)
        with suppress(AttributeError, RuntimeError, TypeError, ValueError):
            if hasattr(line, 'setDistExternal'):
                line.setDistExternal(0.6)
            elif hasattr(line, 'setDistance'):
                line.setDistance(0.6)
        settings.setLineSettings(line)
    fmt = QgsTextFormat()
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        fmt.setSize(pt)
        fmt.setSizeUnit(QgsUnitTypes.RenderUnit.RenderPoints)
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        font = QFont()
        font.setBold(False)
        fmt.setFont(font)
    fmt.setColor(QColor('#1a1816'))
    # No white halo / background — buffer reads as stains on the density fill.
    buf = QgsTextBufferSettings()
    buf.setEnabled(False)
    fmt.setBuffer(buf)
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        bg = fmt.background()
        bg.setEnabled(False)
        fmt.setBackground(bg)
    settings.setFormat(fmt)
    layer.setLabeling(QgsVectorLayerSimpleLabeling(settings))
    layer.setLabelsEnabled(True)
    layer.triggerRepaint()


def _line_symbol(color, width):
    """Opaque millimetre stroke. createSimple drops width; build the layer explicitly.

    Width 0 must not use QGIS hairline (cosmetic 1 px — reads thicker than
    0.10 mm). Invisible stroke instead.
    """
    width = max(0.0, min(1.0, float(width)))
    color = color if isinstance(color, QColor) else QColor(color)
    invisible = width <= 1e-9
    draw_w = 0.01 if invisible else width
    draw_c = QColor(0, 0, 0, 0) if invisible else QColor(color)
    sl = QgsSimpleLineSymbolLayer(draw_c, draw_w)
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        sl.setWidthUnit(QgsUnitTypes.RenderUnit.RenderMillimeters)
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        sl.setPenCapStyle(Qt.PenCapStyle.RoundCap)
        sl.setPenJoinStyle(Qt.PenJoinStyle.RoundJoin)
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        sl.setPenStyle(Qt.PenStyle.NoPen if invisible else Qt.PenStyle.SolidLine)
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        if invisible:
            sl.setColor(QColor(0, 0, 0, 0))
    sym = QgsLineSymbol()
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        if not sym.changeSymbolLayer(0, sl):
            extra = sl.clone() if hasattr(sl, 'clone') else sl
            sym.appendSymbolLayer(extra)
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        sym.setColor(draw_c)
        sym.setWidth(draw_w)
        sym.setWidthUnit(QgsUnitTypes.RenderUnit.RenderMillimeters)
        sym.setOpacity(0.0 if invisible else 1.0)
    return sym


def _contour_ink(for_paper=False, theme_name=None):
    """Light UI → black isolines; dark UI → white. Paper export always black."""
    if for_paper:
        return '#000000'
    name = theme_name
    if name is None:
        with suppress(Exception):
            from .dock import UI_THEME
            name = UI_THEME.get('name')
    return '#ffffff' if name == 'dark' else '#000000'


def style_contours(layer, with_heatmap=True, scheme='viridis', labels=False,
                   width=0.15, invert=False, for_paper=False, theme_name=None):
    """Isolines: black on light / paper; white on dark canvas."""
    if layer is None:
        return
    width = max(0.0, min(1.0, float(width)))
    # with_heatmap / scheme / invert kept for call-site compatibility.
    _ = (with_heatmap, scheme, invert)
    ink = _contour_ink(for_paper=for_paper, theme_name=theme_name)
    layer.setRenderer(QgsSingleSymbolRenderer(_line_symbol(ink, width)))
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        layer.setCustomProperty('arsysplotqgis_line_width', '%.3f' % width)
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        layer.setCustomProperty('arsysplotqgis_line_ink', ink)
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        layer.setOpacity(1.0)
    style_contour_labels(layer, on=labels, size_pt=None)


def split_pair(pair):
    """Return (raster, isolines)."""
    if not pair:
        return None, None
    rst = pair[0] if len(pair) > 0 else None
    ctr = pair[1] if len(pair) > 1 else None
    return rst, ctr


def _build_isolines(raster, mode, levels, scheme, labels, clip_min, clip_max,
                    line_width, invert=False, for_paper=False):
    """Isoline overlay for the current class breaks. Not a fill layer."""
    need_lines = mode in ('contours', 'both') or bool(labels)
    if not need_lines:
        return None
    contours = build_contours(
        raster, levels=levels, clip_min=clip_min, clip_max=clip_max,
    )
    if contours is None:
        return None
    style_contours(
        contours, with_heatmap=(mode != 'contours'),
        scheme=scheme, labels=labels, width=line_width, invert=invert,
        for_paper=for_paper,
    )
    keep_private(contours)
    return contours


def build_pair(point_layer, radius, pixel, kernel, mode, levels, opacity,
               scheme='viridis', labels=False, clip_min=None, clip_max=None,
               fill='bands', line_width=0.15, for_paper=False, invert=False):
    """Return (styled KDE raster, isolines). Fill is never a polygon layer."""
    need_raster = mode in ('heatmap', 'contours', 'both')
    raster = (
        build_heatmap(point_layer, radius, pixel, kernel, for_paper=for_paper)
        if need_raster else None
    )
    if raster is None:
        return None, None
    keep_private(raster)
    fill = 'cloud' if fill == 'cloud' else 'bands'
    invert = bool(invert)
    if mode in ('heatmap', 'both'):
        style_heatmap(
            raster, opacity=opacity, scheme=scheme, levels=levels,
            clip_min=clip_min, clip_max=clip_max, fill=fill, invert=invert,
        )
    contours = _build_isolines(
        raster, mode, levels, scheme, labels, clip_min, clip_max, line_width,
        invert=invert, for_paper=for_paper,
    )
    return raster, contours


def build_paper_pair(point_layer, radius, pixel, kernel, mode, levels, opacity,
                     scheme='viridis', labels=False, clip_min=None, clip_max=None,
                     fill='bands', line_width=0.15, invert=False):
    """Paper-resolution density product: same semantics as build_pair, finer grid.

    Skips the interactive ~720-cell clamp. Caller should pass ``pixel`` from
    :func:`paper_pixel` so the KDE sampling matches the PNG output size.
    """
    return build_pair(
        point_layer, radius, pixel, kernel, mode, levels, opacity,
        scheme=scheme, labels=labels, clip_min=clip_min, clip_max=clip_max,
        fill=fill, line_width=line_width, for_paper=True, invert=invert,
    )


def restyle_pair(raster, contours, mode, levels, opacity, scheme='viridis',
                 labels=False, clip_min=None, clip_max=None, fill='bands',
                 line_width=0.15, invert=False, for_paper=False):
    """Reclassify the KDE raster and rebuild isolines. No KDE recompute."""
    if raster is None:
        release_private(contours)
        return None, None
    fill = 'cloud' if fill == 'cloud' else 'bands'
    invert = bool(invert)
    if mode in ('heatmap', 'both'):
        style_heatmap(
            raster, opacity=opacity, scheme=scheme, levels=levels,
            clip_min=clip_min, clip_max=clip_max, fill=fill, invert=invert,
        )
    release_private(contours)
    new_ctr = _build_isolines(
        raster, mode, levels, scheme, labels, clip_min, clip_max, line_width,
        invert=invert, for_paper=for_paper,
    )
    return raster, new_ctr


def release_pair(raster, contours=None):
    release_private(contours)
    release_private(raster)


def _legend_fmt(val):
    try:
        v = float(val)
    except (TypeError, ValueError):
        return ''
    if not math.isfinite(v):
        return ''
    return '%d' % int(round(v))


def _equal_bounds(vmin, vmax, n_classes):
    """n_classes colour steps → n_classes+1 edges from vmin to vmax."""
    n = max(2, int(n_classes))
    span = float(vmax) - float(vmin)
    return [float(vmin) + span * (i / float(n)) for i in range(n + 1)]


def heatmap_legend(rlayer):
    """(vmin, vmax, colours low→high, bounds) from the styled KDE raster.

    ``bounds`` has len(colours)+1 edges so each colour change can be labelled.
    """
    if rlayer is None:
        return None
    fill = 'bands'
    scheme = DEFAULT_SCHEME
    levels_n = 8
    invert = False
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        fill = rlayer.customProperty('arsysplotqgis_fill') or fill
        scheme = rlayer.customProperty('arsysplotqgis_scheme') or scheme
        invert = str(rlayer.customProperty('arsysplotqgis_invert') or '0') == '1'
    try:
        rend = rlayer.renderer()
        shader = rend.shader()
        fn = shader.rasterShaderFunction()
        items = list(fn.colorRampItemList())
    except Exception:
        items = []
        rend = None
    try:
        vmin = float(rend.classificationMin())
        vmax = float(rend.classificationMax())
    except Exception:
        vmin = vmax = None
    if str(fill) == 'cloud':
        if vmin is None or vmax is None or vmax <= vmin:
            rng = _clip_range(rlayer)
            if rng is None:
                return None
            vmin, vmax = rng
        if vmax <= vmin:
            return None
        # Smooth ramp; annotate at Isolines-equivalent equal breaks.
        with suppress(AttributeError, RuntimeError, TypeError, ValueError):
            levels_n = _class_count(
                rlayer.customProperty('arsysplotqgis_levels') or levels_n,
            )
        if items:
            with suppress(Exception):
                levels_n = max(2, len(items))
        bounds = _equal_bounds(vmin, vmax, levels_n)
        colors = [
            color_at((i + 0.5) / float(levels_n), scheme, invert=invert)
            for i in range(levels_n)
        ]
        return vmin, vmax, colors, bounds
    # Discrete bands: one colour per class, edges from shader items.
    if not items:
        rng = _clip_range(rlayer)
        if rng is None:
            return None
        if vmin is None or vmax is None or vmax <= vmin:
            vmin, vmax = rng
        n = max(2, len(scheme_stops(scheme)))
        colors = [
            color_at((i + 0.5) / float(n), scheme, invert=invert)
            for i in range(n)
        ]
        bounds = _equal_bounds(vmin, vmax, len(colors))
        return vmin, vmax, colors, bounds
    items.sort(key=lambda it: float(it.value) if math.isfinite(float(it.value)) else 1e300)
    colors = []
    uppers = []
    for it in items:
        c = QColor(it.color)
        if c.alpha() < 8:
            continue
        c.setAlpha(255)
        colors.append(c)
        try:
            uv = float(it.value)
        except (TypeError, ValueError):
            uv = float('nan')
        uppers.append(uv)
    if len(colors) < 2:
        return None
    if vmin is None or not math.isfinite(vmin):
        vmin = 0.0
    if vmax is None or not math.isfinite(vmax):
        finite_u = [u for u in uppers if math.isfinite(u)]
        vmax = finite_u[-1] if finite_u else vmin + 1.0
    if vmax <= vmin:
        return None
    bounds = [float(vmin)]
    for i, uv in enumerate(uppers):
        if math.isfinite(uv):
            bounds.append(float(uv))
        else:
            # Open last class (+inf): close at Max.
            bounds.append(float(vmax) if i == len(uppers) - 1 else bounds[-1])
    # Align length: one edge past each colour.
    while len(bounds) < len(colors) + 1:
        bounds.append(float(vmax))
    if len(bounds) > len(colors) + 1:
        bounds = bounds[:len(colors)] + [float(vmax)]
    bounds[0] = float(vmin)
    bounds[-1] = float(vmax)
    return vmin, vmax, colors, bounds


def paint_colorbar(painter, x, top, bottom, vmin, vmax, colors, dpi, ink,
                   bounds=None):
    """Vertical density ramp with a label at each colour boundary.

    ``bounds`` if given must be len(colors)+1 edges (low→high). Returns width
    consumed in pixels. Tick text stays a fixed 7 pt (not the export isoline size).
    """
    def mm_to_px(mm, dpi=dpi):
        return float(mm) * float(dpi) / 25.4

    def pt_to_px(pt, dpi=dpi):
        return max(8, int(round(float(pt) * float(dpi) / 72.0)))

    bar_w = mm_to_px(3.4, dpi)
    gap = mm_to_px(1.6, dpi)
    lab_w = mm_to_px(18, dpi)
    h = bottom - top
    if h < 8 or not colors:
        return 0
    n = len(colors)
    if bounds is None or len(bounds) != n + 1:
        bounds = _equal_bounds(vmin, vmax, n)
    painter.setPen(QPen(ink, max(1.0, mm_to_px(0.16, dpi))))
    sl = h / float(max(n, 1))
    for i, c in enumerate(colors):
        y0 = bottom - (i + 1) * sl
        painter.setBrush(QBrush(QColor(c.red(), c.green(), c.blue())))
        painter.drawRect(QRectF(x, y0, bar_w, sl))
    font = QFont()
    font.setPixelSize(pt_to_px(7, dpi))
    painter.setFont(font)
    painter.setPen(ink)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    lx = x + bar_w + gap
    tick_w = mm_to_px(1.1, dpi)
    # Label every colour edge (n+1 ticks).
    for i, val in enumerate(bounds):
        t = i / float(n) if n else 0.0
        yy = bottom - t * h
        lab = _legend_fmt(val)
        if not lab:
            continue
        painter.setPen(QPen(ink, max(1.0, mm_to_px(0.16, dpi))))
        painter.drawLine(
            int(round(x + bar_w)), int(round(yy)),
            int(round(x + bar_w + tick_w)), int(round(yy)),
        )
        painter.drawText(
            QRectF(lx, yy - mm_to_px(2.1, dpi), lab_w, mm_to_px(4.2, dpi)),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            lab,
        )
    painter.save()
    painter.translate(lx + mm_to_px(13.5, dpi), (top + bottom) / 2.0)
    painter.rotate(-90)
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(
        QRectF(-mm_to_px(28, dpi), -mm_to_px(4, dpi), mm_to_px(56, dpi), mm_to_px(5, dpi)),
        Qt.AlignmentFlag.AlignCenter,
        'Density',
    )
    painter.restore()
    return bar_w + gap + lab_w + mm_to_px(4, dpi)
