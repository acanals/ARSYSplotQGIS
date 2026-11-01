# -*- coding: utf-8 -*-
"""Kernel density (heatmap + isolines) from the filtered plugin points."""
from contextlib import suppress
import math

from qgis.core import (
    QgsClassificationEqualInterval,
    QgsColorRampShader,
    QgsGradientColorRamp,
    QgsGraduatedSymbolRenderer,
    QgsLineSymbol,
    QgsProcessingFeedback,
    QgsRasterBandStats,
    QgsRasterLayer,
    QgsRasterShader,
    QgsSingleBandPseudoColorRenderer,
    QgsSingleSymbolRenderer,
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
    ('gray', 'Gray', (
        (0.00, 220, 220, 220), (1.00, 20, 20, 20),
    )),
)

_SCHEME_MAP = {sid: (label, stops) for sid, label, stops in COLOR_SCHEMES}
DEFAULT_SCHEME = 'viridis'


def resolve_scheme(name):
    if name in _SCHEME_MAP:
        return name
    return DEFAULT_SCHEME


def scheme_stops(name):
    return _SCHEME_MAP[resolve_scheme(name)][1]


def color_at(t, scheme='viridis'):
    t = max(0.0, min(1.0, float(t)))
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


def make_ramp(scheme='viridis'):
    stops = scheme_stops(scheme)
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


def scheme_icon(scheme, width=72, height=14):
    pm = QPixmap(max(24, int(width)), max(10, int(height)))
    p = QPainter(pm)
    w = pm.width()
    h = pm.height()
    for x in range(w):
        p.setPen(color_at(x / float(max(w - 1, 1)), scheme))
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
    pixel = max(radius / 36.0, diag / 360.0)
    return round(radius, 3), round(pixel, 4)


def adapt_kernel(layer, radius, pixel, ref_layer=None):
    """Scale XY radius/cell to a section so the circular kernel is not huge vs Z."""
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
    scale = max(0.12, min(1.0, lay_s / ref_s))
    return max(0.05, radius * scale), max(0.005, pixel * scale)


def map_clip(user_min, user_max, ref_limits, dest_limits):
    """Map plan Min/Max onto another view by peak density (sections stack points)."""
    if dest_limits is None:
        return user_min, user_max
    dmax = float(dest_limits['max'])
    if ref_limits is None:
        return max(0.0, float(user_min)), min(dmax, max(float(user_max), 0.0))
    rmax = float(ref_limits['max'])
    if rmax <= 1e-12 or dmax <= 1e-12:
        return user_min, user_max
    scale = dmax / rmax
    cmin = max(0.0, float(user_min) * scale)
    cmax = max(cmin, float(user_max) * scale)
    return cmin, min(cmax, dmax)


def _clamp_pixel(layer, radius, pixel):
    ext = layer.extent()
    pad = 2.0 * max(radius, 0.0)
    longest = max(ext.width() + pad, ext.height() + pad, 1.0)
    # Keep a usable grid, but do not force coarse cells that read as tiles.
    min_pixel = longest / 720.0
    return max(float(pixel), min_pixel, 0.002)


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


def _enable_crisp_resample(rlayer):
    """Nearest neighbour so discrete colour bands stay sharp (hypsometric style)."""
    nearest = _resampling_method('Nearest', 'NearestNeighbour')
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        rlayer.setResamplingEnabled(False)
    provider = rlayer.dataProvider()
    if provider is not None and nearest is not None:
        with suppress(AttributeError, RuntimeError, TypeError, ValueError):
            provider.setZoomedInResamplingMethod(nearest)
            provider.setZoomedOutResamplingMethod(nearest)
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        filt = rlayer.resampleFilter()
        if filt is not None:
            if hasattr(filt, 'setZoomedInResampler'):
                filt.setZoomedInResampler(None)
            if hasattr(filt, 'setZoomedOutResampler'):
                filt.setZoomedOutResampler(None)
            if hasattr(filt, 'setMaxOversampling'):
                filt.setMaxOversampling(1.0)


def _class_breaks(vmin, vmax, levels):
    levels = max(3, min(16, int(levels)))
    span = max(vmax - vmin, 1e-12)
    interval = span / float(levels)
    breaks = [vmin + interval * i for i in range(1, levels + 1)]
    breaks[-1] = vmax
    return interval, breaks


def _discrete_ramp_type():
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        return QgsColorRampShader.Discrete
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        from qgis.core import Qgis
        method = getattr(Qgis, 'ShaderInterpolationMethod', None)
        if method is not None:
            return method.Discrete
    return None


def _interpolated_ramp_type():
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        return QgsColorRampShader.Interpolated
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        from qgis.core import Qgis
        method = getattr(Qgis, 'ShaderInterpolationMethod', None)
        if method is None:
            return None
        return getattr(method, 'Linear', None) or getattr(method, 'Interpolated', None)
    return None


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
    processing = _processing()
    feedback = QgsProcessingFeedback()
    last = None
    for alg in alg_ids:
        try:
            return processing.run(alg, params, feedback=feedback)
        except Exception as exc:
            last = exc
            continue
    if last is not None:
        raise last
    raise RuntimeError('No density algorithm available')


def _kernel_index(kernel):
    try:
        idx = int(kernel)
    except (TypeError, ValueError):
        idx = 0
    return max(0, min(idx, len(KERNELS) - 1))


def build_heatmap(point_layer, radius, pixel, kernel=0):
    if point_layer is None or point_layer.featureCount() < 2:
        return None
    radius = max(0.05, float(radius))
    pixel = _clamp_pixel(point_layer, radius, pixel)
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
    _enable_crisp_resample(rlayer)
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


def raster_limits(rlayer, lower_frac=0.02):
    """Real KDE min/max and QGIS-style cumulative count cut of values > 0.

    Returns dict with min, max, cut_low — or None.
    """
    if rlayer is None:
        return None
    provider = rlayer.dataProvider()
    if provider is None:
        return None
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
    if vmax is None or not math.isfinite(vmax) or vmax <= 0.0:
        try:
            stats = provider.bandStatistics(
                1, QgsRasterBandStats.Min | QgsRasterBandStats.Max,
                extent, 0,
            )
            smin = float(stats.minimumValue)
            smax = float(stats.maximumValue)
        except Exception:
            return None
        if not math.isfinite(smax) or smax <= 0.0:
            return None
        vmax = smax
        if vmin_pos is None and math.isfinite(smin) and smin > 0.0:
            vmin_pos = smin
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


def _hide_below(rlayer, renderer, vmin):
    """QGIS additional no-data + transparency for values below Min (exclusive)."""
    from qgis.core import QgsRasterRange, QgsRasterTransparency
    provider = rlayer.dataProvider() if rlayer is not None else None
    lo = max(0.0, float(vmin))
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        if provider is None:
            pass
        elif lo <= 0.0:
            provider.setUserNoDataValue(1, [])
            if hasattr(rlayer, 'resetNoDataValue'):
                rlayer.resetNoDataValue(1)
        else:
            bounds = getattr(QgsRasterRange, 'IncludeMin', None)
            if bounds is not None:
                rng = QgsRasterRange(0.0, lo, bounds)
            else:
                rng = QgsRasterRange(0.0, max(0.0, lo - 1e-12))
            provider.setUserNoDataValue(1, [rng])
            if hasattr(rlayer, 'setNoDataValue'):
                rlayer.setNoDataValue(1, 0.0)
    trans = QgsRasterTransparency()
    if lo > 0.0:
        try:
            px = QgsRasterTransparency.TransparentSingleValuePixel()
            if hasattr(px, 'minValue'):
                px.minValue = 0.0
                px.maxValue = lo
            else:
                px.min = 0.0
                px.max = lo
            if hasattr(px, 'includeMinimum'):
                px.includeMinimum = True
            if hasattr(px, 'includeMaximum'):
                px.includeMaximum = False
            px.percentTransparent = 100.0
            trans.setTransparentSingleValuePixelList([px])
        except Exception:
            trans = QgsRasterTransparency()
    if renderer is None:
        return
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        renderer.setRasterTransparency(trans)


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


def style_heatmap(rlayer, opacity=0.7, scheme='viridis', levels=8,
                  clip_min=None, clip_max=None, fill='bands'):
    """Paint the KDE raster. fill: 'bands' (discrete) or 'cloud' (interpolated)."""
    if rlayer is None:
        return
    rng = _clip_range(rlayer, clip_min, clip_max)
    if rng is None:
        return
    vmin, vmax = rng
    scheme = resolve_scheme(scheme)
    opacity = max(0.0, min(1.0, float(opacity)))
    fill = 'cloud' if fill == 'cloud' else 'bands'
    fn = QgsColorRampShader()
    if fill == 'cloud':
        items = []
        for t, r, g, b in scheme_stops(scheme):
            val = vmin + float(t) * (vmax - vmin)
            c = QColor(r, g, b)
            c.setAlpha(255)
            items.append(QgsColorRampShader.ColorRampItem(val, c, '%.4g' % val))
        interp = _interpolated_ramp_type()
        if interp is not None:
            with suppress(AttributeError, RuntimeError, TypeError, ValueError):
                fn.setColorRampType(interp)
    else:
        _interval, breaks = _class_breaks(vmin, vmax, levels)
        items = []
        n = len(breaks)
        for i, upper in enumerate(breaks):
            t = (i + 0.5) / float(n)
            c = QColor(color_at(t, scheme))
            c.setAlpha(255)
            items.append(QgsColorRampShader.ColorRampItem(upper, c, '%.4g' % upper))
        discrete = _discrete_ramp_type()
        if discrete is not None:
            with suppress(AttributeError, RuntimeError, TypeError, ValueError):
                fn.setColorRampType(discrete)
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        fn.setSourceColorRamp(make_ramp(scheme))
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        fn.setClip(True)
    fn.setMinimumValue(vmin)
    fn.setMaximumValue(vmax)
    fn.setColorRampItemList(items)
    shader = QgsRasterShader()
    shader.setRasterShaderFunction(fn)
    renderer = QgsSingleBandPseudoColorRenderer(rlayer.dataProvider(), 1, shader)
    renderer.setClassificationMin(vmin)
    renderer.setClassificationMax(vmax)
    fn.setColorRampItemList(items)
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        renderer.setNodataColor(QColor(0, 0, 0, 0))
    _hide_below(rlayer, renderer, vmin)
    rlayer.setRenderer(renderer)
    if fill == 'cloud':
        _enable_smooth_resample(rlayer)
    else:
        _enable_crisp_resample(rlayer)
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        rlayer.setCustomProperty('arsysplotqgis_fill', fill)
        rlayer.setCustomProperty('arsysplotqgis_scheme', scheme)
    rlayer.setOpacity(opacity)
    rlayer.triggerRepaint()


def build_contours(rlayer, levels=8, clip_min=None, clip_max=None):
    if rlayer is None:
        return None
    rng = _clip_range(rlayer, clip_min, clip_max)
    if rng is None:
        return None
    vmin, vmax = rng
    _hide_below(rlayer, None, vmin)
    interval, breaks = _class_breaks(vmin, vmax, levels)
    if interval <= 0:
        return None
    params = {
        'INPUT': rlayer,
        'BAND': 1,
        'INTERVAL': interval,
        'FIELD_NAME': 'ELEV',
        'CREATE_3D': False,
        'IGNORE_NODATA': True,
        'OFFSET': vmin if vmin > 1e-9 else breaks[0],
        'OUTPUT': 'TEMPORARY_OUTPUT',
    }
    try:
        result = _run(_CONTOUR_IDS, params)
    except Exception:
        params.pop('OFFSET', None)
        params.pop('IGNORE_NODATA', None)
        result = _run(_CONTOUR_IDS, params)
    path = result.get('OUTPUT')
    if not path:
        return None
    from qgis.core import QgsVectorLayer
    layer = QgsVectorLayer(path, rlayer.name() + ' · isolines', 'ogr')
    if not layer.isValid() or layer.featureCount() < 1:
        return None
    layer.setCustomProperty('arsysplotqgis', 'density-contour')
    return layer


def style_contour_labels(layer, on=False):
    """Toggle density-value labels along isolines."""
    if layer is None:
        return
    if not on:
        with suppress(AttributeError, RuntimeError, TypeError, ValueError):
            layer.setLabelsEnabled(False)
        with suppress(AttributeError, RuntimeError, TypeError, ValueError):
            layer.setLabeling(None)
        layer.triggerRepaint()
        return
    field = 'ELEV' if layer.fields().lookupField('ELEV') >= 0 else (
        layer.fields()[0].name() if layer.fields().count() else ''
    )
    if not field:
        return
    from qgis.core import (
        QgsPalLayerSettings,
        QgsTextBufferSettings,
        QgsTextFormat,
        QgsUnitTypes,
        QgsVectorLayerSimpleLabeling,
    )
    settings = QgsPalLayerSettings()
    settings.enabled = True
    safe = field.replace('"', '')
    try:
        settings.fieldName = 'format_number("%s", 2)' % safe
        settings.isExpression = True
    except Exception:
        settings.fieldName = field
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        placement = getattr(QgsPalLayerSettings, 'Placement', None)
        settings.placement = placement.Line if placement is not None else QgsPalLayerSettings.Line
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        settings.mergeLines = True
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        settings.repeatDistance = 40
        settings.repeatDistanceUnit = QgsUnitTypes.RenderMillimeters
    fmt = QgsTextFormat()
    try:
        fmt.setSize(6.5)
        fmt.setSizeUnit(QgsUnitTypes.RenderPoints)
    except Exception:
        fmt.setSize(7)
    fmt.setColor(QColor('#1a1816'))
    buf = QgsTextBufferSettings()
    buf.setEnabled(True)
    buf.setSize(0.8)
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        buf.setSizeUnit(QgsUnitTypes.RenderMillimeters)
    buf.setColor(QColor('#ffffff'))
    fmt.setBuffer(buf)
    settings.setFormat(fmt)
    layer.setLabeling(QgsVectorLayerSimpleLabeling(settings))
    layer.setLabelsEnabled(True)
    layer.triggerRepaint()


def style_contours(layer, with_heatmap=True, scheme='viridis', labels=False):
    if layer is None:
        return
    field = 'ELEV' if layer.fields().lookupField('ELEV') >= 0 else (
        layer.fields()[0].name() if layer.fields().count() else ''
    )
    if with_heatmap or not field:
        layer.setRenderer(QgsSingleSymbolRenderer(QgsLineSymbol.createSimple({
            'line_color': '#2a2520',
            'line_width': '0.28',
            'line_width_unit': 'MM',
        })))
    else:
        ramp = make_ramp(scheme)
        renderer = QgsGraduatedSymbolRenderer(field)
        renderer.setSourceColorRamp(ramp)
        try:
            renderer.setClassificationMethod(QgsClassificationEqualInterval())
            renderer.updateClasses(layer, 6)
            for i in range(renderer.rangeCount()):
                rng = renderer.ranges()[i]
                color = rng.symbol().color() if rng.symbol() else QColor('#333')
                renderer.updateRangeSymbol(i, QgsLineSymbol.createSimple({
                    'line_color': color.name(),
                    'line_width': '0.45',
                    'line_width_unit': 'MM',
                }))
            layer.setRenderer(renderer)
        except Exception:
            layer.setRenderer(QgsSingleSymbolRenderer(QgsLineSymbol.createSimple({
                'line_color': '#3d348b',
                'line_width': '0.5',
                'line_width_unit': 'MM',
            })))
    style_contour_labels(layer, on=labels)


def build_pair(point_layer, radius, pixel, kernel, mode, levels, opacity,
               scheme='viridis', labels=False, clip_min=None, clip_max=None,
               fill='bands'):
    """Return (raster, contours) according to mode: heatmap / contours / both."""
    need_raster = mode in ('heatmap', 'contours', 'both')
    need_lines = mode in ('contours', 'both')
    raster = build_heatmap(point_layer, radius, pixel, kernel) if need_raster else None
    if raster is None:
        return None, None
    keep_private(raster)
    if mode in ('heatmap', 'both'):
        style_heatmap(
            raster, opacity=opacity, scheme=scheme, levels=levels,
            clip_min=clip_min, clip_max=clip_max, fill=fill,
        )
    contours = None
    if need_lines:
        contours = build_contours(
            raster, levels=levels, clip_min=clip_min, clip_max=clip_max,
        )
        if contours is not None:
            style_contours(
                contours, with_heatmap=(mode == 'both'),
                scheme=scheme, labels=labels,
            )
            keep_private(contours)
    return raster, contours


def restyle_pair(raster, contours, mode, levels, opacity, scheme='viridis',
                 labels=False, clip_min=None, clip_max=None, fill='bands'):
    """Reclassify an existing KDE raster and rebuild isolines. No KDE recompute."""
    if raster is None:
        release_private(contours)
        return None, None
    if mode in ('heatmap', 'both'):
        style_heatmap(
            raster, opacity=opacity, scheme=scheme, levels=levels,
            clip_min=clip_min, clip_max=clip_max, fill=fill,
        )
    release_private(contours)
    new_ctr = None
    if mode in ('contours', 'both'):
        new_ctr = build_contours(
            raster, levels=levels, clip_min=clip_min, clip_max=clip_max,
        )
        if new_ctr is not None:
            style_contours(
                new_ctr, with_heatmap=(mode == 'both'),
                scheme=scheme, labels=labels,
            )
            keep_private(new_ctr)
    return raster, new_ctr


def release_pair(raster, contours):
    release_private(contours)
    release_private(raster)


def heatmap_legend(rlayer):
    """(vmin, vmax, solid colours low→high) from the styled KDE raster, or None."""
    if rlayer is None:
        return None
    fill = 'bands'
    scheme = DEFAULT_SCHEME
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        fill = rlayer.customProperty('arsysplotqgis_fill') or fill
        scheme = rlayer.customProperty('arsysplotqgis_scheme') or scheme
    try:
        rend = rlayer.renderer()
        shader = rend.shader()
        fn = shader.rasterShaderFunction()
        items = list(fn.colorRampItemList())
    except Exception:
        items = []
        rend = None
    if str(fill) == 'cloud':
        rng = _clip_range(rlayer)
        if rng is None:
            return None
        vmin, vmax = rng
        with suppress(AttributeError, RuntimeError, TypeError, ValueError):
            vmin = float(rend.classificationMin())
            vmax = float(rend.classificationMax())
        if vmax <= vmin:
            return None
        colors = [color_at(i / 23.0, scheme) for i in range(24)]
        return vmin, vmax, colors
    if not items:
        rng = _clip_range(rlayer)
        if rng is None:
            return None
        vmin, vmax = rng
        stops = scheme_stops(scheme)
        colors = [QColor(r, g, b) for _t, r, g, b in stops]
        return vmin, vmax, colors
    items.sort(key=lambda it: float(it.value))
    colors = []
    for it in items:
        c = QColor(it.color)
        if c.alpha() < 8:
            continue
        c.setAlpha(255)
        colors.append(c)
    if len(colors) < 2:
        return None
    try:
        vmin = float(rend.classificationMin())
        vmax = float(rend.classificationMax())
    except Exception:
        vmin = float(items[0].value)
        vmax = float(items[-1].value)
    if vmax <= vmin:
        return None
    return vmin, vmax, colors


def paint_colorbar(painter, x, top, bottom, vmin, vmax, colors, dpi, ink):
    """Vertical density ramp. Returns width consumed in pixels."""
    def mm_to_px(mm, dpi=dpi):
        return float(mm) * float(dpi) / 25.4

    def pt_to_px(pt, dpi=dpi):
        return max(8, int(round(float(pt) * float(dpi) / 72.0)))

    bar_w = mm_to_px(3.4, dpi)
    gap = mm_to_px(1.6, dpi)
    lab_w = mm_to_px(16, dpi)
    h = bottom - top
    if h < 8 or not colors:
        return 0
    painter.setPen(QPen(ink, max(1.0, mm_to_px(0.16, dpi))))
    n = len(colors)
    sl = h / float(max(n, 1))
    for i, c in enumerate(colors):
        y0 = bottom - (i + 1) * sl
        painter.setBrush(QBrush(QColor(c.red(), c.green(), c.blue())))
        painter.drawRect(QRectF(x, y0, bar_w, sl))
    font = QFont()
    font.setPixelSize(pt_to_px(7, dpi))
    painter.setFont(font)
    painter.setPen(ink)
    painter.setBrush(Qt.NoBrush)
    lx = x + bar_w + gap
    tick_w = mm_to_px(1.1, dpi)
    span = float(vmax) - float(vmin)
    ticks = []
    for t in (0.0, 0.25, 0.5, 0.75, 1.0):
        val = float(vmin) + t * span
        if vmax <= 1.5 and vmin >= -0.05:
            lab = '%.2f' % val
        else:
            lab = '%.3g' % val
        ticks.append((t, lab))
    for t, lab in ticks:
        yy = bottom - t * h
        painter.setPen(QPen(ink, max(1.0, mm_to_px(0.16, dpi))))
        painter.drawLine(
            int(round(x + bar_w)), int(round(yy)),
            int(round(x + bar_w + tick_w)), int(round(yy)),
        )
        painter.drawText(
            QRectF(lx, yy - mm_to_px(2.1, dpi), lab_w, mm_to_px(4.2, dpi)),
            Qt.AlignLeft | Qt.AlignVCenter,
            lab,
        )
    painter.save()
    painter.translate(lx + mm_to_px(11.5, dpi), (top + bottom) / 2.0)
    painter.rotate(-90)
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(
        QRectF(-mm_to_px(28, dpi), -mm_to_px(4, dpi), mm_to_px(56, dpi), mm_to_px(5, dpi)),
        Qt.AlignCenter,
        'Density',
    )
    painter.restore()
    return bar_w + gap + lab_w + mm_to_px(4, dpi)
