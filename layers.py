# -*- coding: utf-8 -*-
from contextlib import suppress
from qgis.core import (
    NULL,
    QgsCategorizedSymbolRenderer,
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsFeatureRequest,
    QgsField,
    QgsGeometry,
    QgsLineSymbol,
    QgsMapLayer,
    QgsMarkerLineSymbolLayer,
    QgsMarkerSymbol,
    QgsPoint,
    QgsPointXY,
    QgsProject,
    QgsRectangle,
    QgsRendererCategory,
    QgsSimpleLineSymbolLayer,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtGui import QColor

from .colors_util import color_map, qgis_color

GROUP_NAME = 'ARSYSplotQGIS'
EMPTY_LABEL = '(empty)'
VECTOR_EPS = 1e-4
ARROW_SLIDER_MAX = 100
ARROW_MM_MIN = 0.35
ARROW_MM_MAX = 4.2
ARROW_MM_DEFAULT = 1.6
ARROW_SLIDER_GAMMA = 1.75


def arrow_mm_from_slider(value):
    t = max(0.0, min(1.0, int(value) / float(ARROW_SLIDER_MAX)))
    mm = ARROW_MM_MIN + (ARROW_MM_MAX - ARROW_MM_MIN) * (t ** ARROW_SLIDER_GAMMA)
    return round(mm, 2)


def arrow_slider_from_mm(mm):
    mm = max(ARROW_MM_MIN, min(ARROW_MM_MAX, float(mm)))
    t = (mm - ARROW_MM_MIN) / (ARROW_MM_MAX - ARROW_MM_MIN)
    t = t ** (1.0 / ARROW_SLIDER_GAMMA)
    return int(round(t * ARROW_SLIDER_MAX))


def arrow_px_from_mm(mm):
    return max(2.0, float(mm) * 5.0)


def _num(value):
    if value is None:
        return None
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        if value == NULL or value is NULL:
            return None
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        if hasattr(value, 'isNull') and value.isNull():
            return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def xyz_from_prefix(feat, prefix):
    fields = feat.fields()
    ix = fields.lookupField(prefix + 'x')
    iy = fields.lookupField(prefix + 'y')
    if ix < 0 or iy < 0:
        return None
    x = _num(feat[prefix + 'x'])
    y = _num(feat[prefix + 'y'])
    if x is None or y is None:
        return None
    z = 0.0
    iz = fields.lookupField(prefix + 'z')
    if iz >= 0:
        vz = _num(feat[prefix + 'z'])
        if vz is not None:
            z = vz
    return x, y, z


def _len2(a, b):
    dx = b[0] - a[0]
    dy = b[1] - a[1]
    dz = b[2] - a[2]
    return dx * dx + dy * dy + dz * dz


def vector_endpoints(feat):
    """P2→P3 after import. Legacy P1→P2 if P3 is still missing. None if no axis."""
    p1 = xyz_from_prefix(feat, 'p1')
    p2 = xyz_from_prefix(feat, 'p2')
    p3 = xyz_from_prefix(feat, 'p3')
    if p2 is not None and p3 is not None:
        if _len2(p2, p3) > VECTOR_EPS * VECTOR_EPS:
            return p2, p3
        return None
    if p1 is not None and p2 is not None:
        if _len2(p1, p2) > VECTOR_EPS * VECTOR_EPS:
            return p1, p2
    return None


def _line_geom(a, b, with_z=True):
    if with_z:
        p0 = QgsPoint(float(a[0]), float(a[1]), float(a[2]))
        p1 = QgsPoint(float(b[0]), float(b[1]), float(b[2]))
        with suppress(AttributeError, RuntimeError, TypeError, ValueError):
            return QgsGeometry.fromPolyline([p0, p1])
    return QgsGeometry.fromPolylineXY([
        QgsPointXY(float(a[0]), float(a[1])),
        QgsPointXY(float(b[0]), float(b[1])),
    ])


def is_empty_group(value):
    if value is None:
        return True
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        if value == NULL or value is NULL:
            return True
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        if hasattr(value, 'isNull') and value.isNull():
            return True
    s = str(value).strip()
    return s == '' or s.lower() in ('none', 'null', 'nan')


def group_label(value):
    return EMPTY_LABEL if is_empty_group(value) else str(value).strip()


def _empty_filter_clause(field):
    f = '"%s"' % field.replace('"', '""')
    return (
        '(%s IS NULL OR trim(to_string(%s)) = \'\' OR %s = \'%s\')'
        % (f, f, f, EMPTY_LABEL)
    )


def keep_private(layer, project=None):
    """Register the layer for the plugin canvases, not the QGIS map or legend."""
    if layer is None:
        return None
    project = project or QgsProject.instance()
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        layer.setFlags(layer.flags() | QgsMapLayer.Private)
    if layer.id() not in project.mapLayers():
        project.addMapLayer(layer, False)
    return layer


def release_private(layer, project=None):
    if layer is None:
        return
    project = project or QgsProject.instance()
    if layer.id() in project.mapLayers():
        project.removeMapLayer(layer.id())


def clear_plugin_legend(project=None):
    """Drop leftover ARSYSplotQGIS legend nodes from older versions."""
    project = project or QgsProject.instance()
    root = project.layerTreeRoot()
    group = root.findGroup(GROUP_NAME)
    if group is None:
        return
    ids = []
    for node in group.findLayers():
        lyr = node.layer()
        if lyr is not None:
            ids.append(lyr.id())
    root.removeChildNode(group)
    for lid in ids:
        lyr = project.mapLayer(lid)
        if lyr is None:
            continue
        owned = bool(lyr.customProperty('arsysplotqgis'))
        name = lyr.name()
        if owned or name.endswith(' · XZ') or name.endswith(' · YZ'):
            project.removeMapLayer(lid)


def add_layer_to_group(layer, project=None):
    """Back-compat: keep layers off the main canvas."""
    return keep_private(layer, project)


def unique_groups(layer, field='group'):
    idx = layer.fields().lookupField(field)
    if idx < 0:
        return []
    try:
        values = layer.dataProvider().uniqueValues(idx)
    except Exception:
        values = layer.uniqueValues(idx)
    out = []
    seen = set()
    for v in values:
        key = group_label(v)
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
    out.sort(key=lambda s: (s == EMPTY_LABEL, s.lower()))
    return out


def group_class_attr(field):
    """Expression so categories match trimmed labels, not raw QVariant types."""
    f = (field or 'group').replace('"', '""')
    empty = EMPTY_LABEL.replace("'", "''")
    return (
        'CASE'
        ' WHEN "%s" IS NULL OR trim(to_string("%s")) = \'\''
        ' OR lower(trim(to_string("%s"))) IN (\'none\',\'null\',\'nan\')'
        ' THEN \'%s\''
        ' ELSE trim(to_string("%s"))'
        ' END' % (f, f, f, empty, f)
    )


def _apply_symbol_color(sym, color):
    c = QColor(color)
    if sym is None or not c.isValid():
        return
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        sym.setColor(c)
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        for i in range(sym.symbolLayerCount()):
            sl = sym.symbolLayer(i)
            if sl is None:
                continue
            if hasattr(sl, 'setFillColor'):
                with suppress(AttributeError, RuntimeError, TypeError, ValueError):
                    sl.setFillColor(c)
            if hasattr(sl, 'setColor'):
                with suppress(AttributeError, RuntimeError, TypeError, ValueError):
                    sl.setColor(c)


def _marker(color, size):
    c = QColor(color)
    sym = QgsMarkerSymbol.createSimple({
        'name': 'circle',
        'color': qgis_color(c),
        'outline_color': '17,17,17,255',
        'outline_width': '0.2',
        'size': str(size),
    })
    _apply_symbol_color(sym, c)
    return sym


def style_by_group(layer, field='group', size=2.2, cmap=None, values=None):
    if layer is None:
        return cmap or {}
    values = list(values) if values is not None else unique_groups(layer, field)
    cmap = dict(cmap) if cmap else color_map(values)
    size = max(0.4, float(size))
    cats = []
    for val in values:
        color = cmap.get(val, QColor('#888888'))
        cats.append(QgsRendererCategory(val, _marker(color, size), val))
        if val == EMPTY_LABEL:
            for raw in (NULL, '', None):
                cats.append(QgsRendererCategory(raw, _marker(color, size), EMPTY_LABEL))
    if not cats:
        return cmap
    renderer = QgsCategorizedSymbolRenderer(group_class_attr(field), cats)
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        renderer.setClassAttribute(group_class_attr(field))
    if values:
        with suppress(AttributeError, RuntimeError, TypeError, ValueError):
            renderer.setSourceSymbol(_marker(cmap.get(values[0], QColor('#888888')), size))
    layer.setRenderer(renderer)
    layer.triggerRepaint()
    return cmap


def _place_marker_at_end(ml):
    last = getattr(ml, 'LastVertex', None)
    if last is None:
        try:
            from qgis.core import Qgis
            last = Qgis.MarkerLinePlacement.LastVertex
        except Exception:
            return
    if hasattr(ml, 'setPlacements'):
        with suppress(AttributeError, RuntimeError, TypeError, ValueError):
            ml.setPlacements(last)
            return
    if hasattr(ml, 'setPlacement'):
        with suppress(AttributeError, RuntimeError, TypeError, ValueError):
            ml.setPlacement(last)


def _arrow_marker(color, head_mm):
    c = QColor(color)
    sym = QgsMarkerSymbol.createSimple({
        'name': 'filled_arrowhead',
        'color': qgis_color(c),
        'outline_style': 'no',
        'outline_width': '0',
        'size': str(max(ARROW_MM_MIN, float(head_mm))),
        'size_unit': 'MM',
    })
    _apply_symbol_color(sym, c)
    return sym


def _symbol_color(lyr):
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        sub = lyr.subSymbol() if hasattr(lyr, 'subSymbol') else None
        if sub is not None and hasattr(sub, 'color'):
            c = sub.color()
            if c is not None and c.isValid():
                return c
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        c = lyr.color()
        if c is not None and c.isValid():
            return c
    return QColor('#888888')


def _set_marker_size(sym, head_mm):
    if sym is None:
        return False
    if hasattr(sym, 'setSize'):
        with suppress(AttributeError, RuntimeError, TypeError, ValueError):
            sym.setSize(head_mm)
            return True
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        for i in range(sym.symbolLayerCount()):
            sl = sym.symbolLayer(i)
            if sl is not None and hasattr(sl, 'setSize'):
                sl.setSize(head_mm)
                return True
    return False


def _line_sym(color, width, head=None):
    width = max(0.2, float(width))
    head = max(ARROW_MM_MIN, float(ARROW_MM_DEFAULT if head is None else head))
    c = QColor(color)
    sym = QgsLineSymbol.createSimple({
        'line_color': qgis_color(c),
        'line_width': str(width),
        'line_width_unit': 'MM',
        'capstyle': 'round',
        'joinstyle': 'round',
    })
    _apply_symbol_color(sym, c)
    ml = QgsMarkerLineSymbolLayer()
    ml.setSubSymbol(_arrow_marker(color, head))
    if hasattr(ml, 'setRotateSymbols'):
        ml.setRotateSymbols(True)
    if hasattr(ml, 'setAverageAngleLength'):
        with suppress(AttributeError, RuntimeError, TypeError, ValueError):
            ml.setAverageAngleLength(0)
    _place_marker_at_end(ml)
    sym.appendSymbolLayer(ml)
    return sym


def _scale_line_symbol(sym, width_mm=None, head_mm=None):
    if sym is None:
        return
    if width_mm is not None:
        width_mm = max(0.2, float(width_mm))
    if head_mm is not None:
        head_mm = max(ARROW_MM_MIN, float(head_mm))
    for i in range(sym.symbolLayerCount()):
        lyr = sym.symbolLayer(i)
        if lyr is None:
            continue
        if width_mm is not None and isinstance(lyr, QgsSimpleLineSymbolLayer):
            lyr.setWidth(width_mm)
        if head_mm is None:
            continue
        if type(lyr).__name__ != 'QgsMarkerLineSymbolLayer':
            continue
        if _set_marker_size(lyr.subSymbol() if hasattr(lyr, 'subSymbol') else None, head_mm):
            continue
        with suppress(AttributeError, RuntimeError, TypeError, ValueError):
            lyr.setSubSymbol(_arrow_marker(_symbol_color(lyr), head_mm))


def style_lines_by_group(layer, field='group', width=0.6, head=None, values=None, cmap=None):
    if layer is None:
        return {}
    values = list(values) if values is not None else unique_groups(layer, field)
    cmap = dict(cmap) if cmap else color_map(values)
    width = max(0.2, float(width))
    head = max(ARROW_MM_MIN, float(ARROW_MM_DEFAULT if head is None else head))
    cats = []
    for val in values:
        color = cmap.get(val, QColor('#888888'))
        cats.append(QgsRendererCategory(val, _line_sym(color, width, head), val))
        if val == EMPTY_LABEL:
            for raw in (NULL, '', None):
                cats.append(QgsRendererCategory(raw, _line_sym(color, width, head), EMPTY_LABEL))
    if not cats:
        return cmap
    renderer = QgsCategorizedSymbolRenderer(group_class_attr(field), cats)
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        renderer.setClassAttribute(group_class_attr(field))
    layer.setRenderer(renderer)
    layer.triggerRepaint()
    return cmap


def _apply_line_symbol_scale(layer, width_mm=None, head_mm=None):
    if layer is None:
        return
    renderer = layer.renderer()
    if renderer is None:
        return
    if isinstance(renderer, QgsCategorizedSymbolRenderer):
        for i in range(len(renderer.categories())):
            cat = renderer.categories()[i]
            sym = cat.symbol()
            if sym is None:
                continue
            cloned = sym.clone()
            _scale_line_symbol(cloned, width_mm=width_mm, head_mm=head_mm)
            renderer.updateCategorySymbol(i, cloned)
    else:
        sym = renderer.symbol() if hasattr(renderer, 'symbol') else None
        if sym is not None:
            _scale_line_symbol(sym, width_mm=width_mm, head_mm=head_mm)
    layer.triggerRepaint()


def apply_line_width(layer, width_mm):
    _apply_line_symbol_scale(layer, width_mm=width_mm)


def apply_arrow_size(layer, head_mm):
    _apply_line_symbol_scale(layer, head_mm=head_mm)


def apply_marker_size(layer, size_mm):
    if layer is None:
        return
    renderer = layer.renderer()
    if renderer is None:
        return
    size_mm = max(0.4, float(size_mm))
    if isinstance(renderer, QgsCategorizedSymbolRenderer):
        for i in range(len(renderer.categories())):
            cat = renderer.categories()[i]
            sym = cat.symbol()
            if sym is None:
                continue
            cloned = sym.clone()
            cloned.setSize(size_mm)
            renderer.updateCategorySymbol(i, cloned)
    else:
        sym = renderer.symbol() if hasattr(renderer, 'symbol') else None
        if sym is not None:
            sym.setSize(size_mm)
    layer.triggerRepaint()


def copy_renderer(src, dst):
    """Keep section canvases in the same group colours as the plan."""
    if src is None or dst is None:
        return
    renderer = src.renderer()
    if renderer is None:
        return
    dst.setRenderer(renderer.clone())
    dst.triggerRepaint()


def apply_subset(layer, active_groups, ranges, group_field='group'):
    """Filter the source PointZ layer. ranges: {x:(min,max), y:..., z:...}."""
    if layer is None:
        return
    clauses = []
    if active_groups is not None and layer.fields().lookupField(group_field) >= 0:
        if not active_groups:
            clauses.append('0=1')
        else:
            named = [str(g) for g in active_groups]
            include_empty = EMPTY_LABEL in named
            quoted = []
            for g in named:
                if g == EMPTY_LABEL:
                    continue
                quoted.append("'%s'" % g.replace("'", "''"))
            f = '"%s"' % group_field.replace('"', '""')
            trimmed = 'trim(to_string(%s))' % f
            parts = []
            if quoted:
                parts.append('%s IN (%s)' % (trimmed, ','.join(quoted)))
            if include_empty:
                parts.append(_empty_filter_clause(group_field))
            if parts:
                clauses.append('(%s)' % ' OR '.join(parts) if len(parts) > 1 else parts[0])
            else:
                clauses.append('0=1')
    if ranges:
        names = [f.name() for f in layer.fields()]
        for key, col in (('x', 'p1x'), ('y', 'p1y'), ('z', 'p1z')):
            if key not in ranges or col not in names:
                continue
            lo, hi = ranges[key]
            clauses.append('"%s" >= %s AND "%s" <= %s' % (col, float(lo), col, float(hi)))
    layer.setSubsetString(' AND '.join(clauses) if clauses else '')
    layer.triggerRepaint()


def make_line_layer(name, crs, fields_template):
    auth = crs.authid() if crs and crs.isValid() else ''
    uri = 'LineStringZ?crs=%s' % (auth or 'EPSG:25831')
    layer = QgsVectorLayer(uri, name, 'memory')
    if not layer.isValid():
        layer = QgsVectorLayer('LineString?crs=%s' % (auth or 'EPSG:25831'), name, 'memory')
    if not layer.isValid():
        layer = QgsVectorLayer('LineString', name, 'memory')
    _copy_fields(layer, fields_template)
    layer.setCustomProperty('arsysplotqgis', 'vectors')
    return layer


def make_section_line_layer(name, crs, fields_template):
    auth = crs.authid() if crs and crs.isValid() else ''
    uri = 'LineString?crs=%s' % (auth or 'EPSG:25831')
    layer = QgsVectorLayer(uri, name, 'memory')
    if not layer.isValid():
        layer = QgsVectorLayer('LineString', name, 'memory')
    _copy_fields(layer, fields_template)
    layer.setCustomProperty('arsysplotqgis', 'section-line')
    return layer


def _copy_fields(layer, fields_template):
    prov = layer.dataProvider()
    attrs = []
    existing = set()
    for f in fields_template:
        if f.name() in existing:
            continue
        existing.add(f.name())
        attrs.append(QgsField(f))
    if attrs:
        prov.addAttributes(attrs)
        layer.updateFields()


def _replace_features(layer, feats):
    prov = layer.dataProvider()
    ids = [
        f.id()
        for f in layer.getFeatures(
            QgsFeatureRequest().setFlags(QgsFeatureRequest.NoGeometry)
        )
    ]
    if ids:
        prov.deleteFeatures(ids)
    if feats:
        prov.addFeatures(feats)
    layer.updateExtents()
    layer.triggerRepaint()


def rebuild_vectors(source, dest):
    """LineStringZ P2→P3 (or P1→P2) for rows that have an axis."""
    if source is None or dest is None:
        return 0
    feats = []
    for src in source.getFeatures():
        ends = vector_endpoints(src)
        if ends is None:
            continue
        feat = QgsFeature(dest.fields())
        feat.setGeometry(_line_geom(ends[0], ends[1], with_z=True))
        feat.setAttributes(src.attributes())
        feats.append(feat)
    _replace_features(dest, feats)
    return len(feats)


def make_section_layer(name, crs, fields_template):
    auth = crs.authid() if crs and crs.isValid() else ''
    uri = 'Point?crs=%s' % (auth or 'EPSG:25831')
    layer = QgsVectorLayer(uri, name, 'memory')
    if not layer.isValid():
        layer = QgsVectorLayer('Point', name, 'memory')
    prov = layer.dataProvider()
    attrs = []
    existing = set()
    for f in fields_template:
        if f.name() in existing:
            continue
        existing.add(f.name())
        attrs.append(QgsField(f))
    if attrs:
        prov.addAttributes(attrs)
        layer.updateFields()
    layer.setCustomProperty('arsysplotqgis', 'section')
    return layer


def rebuild_section(source, section, mode):
    """mode: 'long' → Point(x,z); 'trans' → Point(y,z)."""
    if source is None or section is None:
        return
    prov = section.dataProvider()
    ids = [f.id() for f in section.getFeatures(QgsFeatureRequest().setFlags(QgsFeatureRequest.NoGeometry))]
    if ids:
        prov.deleteFeatures(ids)
    feats = []
    for src in source.getFeatures():
        geom = src.geometry()
        if geom is None or geom.isEmpty():
            continue
        pt = geom.constGet()
        _ok = False
        with suppress(AttributeError, RuntimeError, TypeError, ValueError):
            x, y, z = float(pt.x()), float(pt.y()), float(pt.z()) if pt.is3D() else 0.0
            _ok = True
        if not _ok:
            continue
        if mode == 'long':
            g = QgsGeometry(QgsPoint(x, z))
        else:
            g = QgsGeometry(QgsPoint(y, z))
        feat = QgsFeature(section.fields())
        feat.setGeometry(g)
        feat.setAttributes(src.attributes())
        feats.append(feat)
    if feats:
        prov.addFeatures(feats)
    section.updateExtents()
    section.triggerRepaint()


def rebuild_section_lines(source, section, mode):
    """Project P2→P3 (or P1→P2) onto XZ or YZ as 2D lines."""
    if source is None or section is None:
        return
    feats = []
    for src in source.getFeatures():
        ends = vector_endpoints(src)
        if ends is None:
            continue
        a, b = ends
        if mode == 'long':
            pa, pb = (a[0], a[2], 0.0), (b[0], b[2], 0.0)
        else:
            pa, pb = (a[1], a[2], 0.0), (b[1], b[2], 0.0)
        if _len2(pa, pb) <= VECTOR_EPS * VECTOR_EPS:
            continue
        feat = QgsFeature(section.fields())
        feat.setGeometry(_line_geom(pa, pb, with_z=False))
        feat.setAttributes(src.attributes())
        feats.append(feat)
    _replace_features(section, feats)


def field_extent(layer, field):
    idx = layer.fields().lookupField(field)
    if idx < 0:
        return None
    mn, mx = None, None
    req = QgsFeatureRequest().setFlags(QgsFeatureRequest.NoGeometry).setSubsetOfAttributes([idx])
    for f in layer.dataProvider().getFeatures(req):
        v = f[field]
        _ok = False
        with suppress(TypeError, ValueError):
            v = float(v)
            _ok = True
        if not _ok:
            continue
        mn = v if mn is None else min(mn, v)
        mx = v if mx is None else max(mx, v)
    if mn is None:
        return None
    if mn == mx:
        return mn - 0.5, mx + 0.5
    return mn, mx


def _merge_span(a, b):
    if a is None:
        return b
    if b is None:
        return a
    return min(a[0], b[0]), max(a[1], b[1])


def union_extent(layers):
    rect = None
    for lyr in layers or []:
        if lyr is None:
            continue
        ext = lyr.extent()
        if ext is None or ext.isEmpty():
            continue
        if rect is None:
            rect = QgsRectangle(ext)
        else:
            rect.combineExtentWith(ext)
    return rect


def feature_extent(layer):
    """Tight bbox of currently filtered features (honours subset string)."""
    if layer is None:
        return None
    rect = None
    try:
        feats = layer.getFeatures()
    except Exception:
        return None
    for feat in feats:
        geom = feat.geometry()
        if geom is None or geom.isEmpty():
            continue
        _ok = False
        with suppress(AttributeError, RuntimeError, TypeError, ValueError):
            box = geom.boundingBox()
            _ok = True
        if not _ok:
            continue
        if box is None or box.isEmpty():
            continue
        if rect is None:
            rect = QgsRectangle(box)
        else:
            rect.combineExtentWith(box)
    return rect


def _pad_rect(rect, fraction=0.03, min_pad=0.08, max_pad=0.35):
    if rect is None or rect.isEmpty():
        return None
    span = max(rect.width(), rect.height(), 0.2)
    pad = max(min_pad, min(max_pad, span * fraction))
    out = QgsRectangle(rect)
    try:
        out.grow(pad)
    except Exception:
        out = QgsRectangle(
            rect.xMinimum() - pad, rect.yMinimum() - pad,
            rect.xMaximum() + pad, rect.yMaximum() + pad,
        )
    if out.width() <= 0 or out.height() <= 0:
        out.grow(0.5)
    return out


def padded_feature_extent(layer, fraction=0.03, min_pad=0.08, max_pad=0.35):
    """Data-hug rectangle with a small margin. Ignores rasters / stale layer.extent()."""
    return _pad_rect(feature_extent(layer), fraction, min_pad, max_pad)


def padded_data_extent(layers, include_lines=True):
    """Tight bbox of point (and optional line) features. Skips rasters and empty layers."""
    rect = None
    for lyr in layers or []:
        if lyr is None or not hasattr(lyr, 'wkbType'):
            continue
        _ok = False
        with suppress(AttributeError, RuntimeError, TypeError, ValueError):
            gtype = QgsWkbTypes.geometryType(lyr.wkbType())
            _ok = True
        if not _ok:
            continue
        if gtype == QgsWkbTypes.PointGeometry:
            pass
        elif include_lines and gtype == QgsWkbTypes.LineGeometry:
            pass
        else:
            continue
        box = feature_extent(lyr)
        if box is None or box.isEmpty():
            continue
        if rect is None:
            rect = QgsRectangle(box)
        else:
            rect.combineExtentWith(box)
    return _pad_rect(rect)


def point_layer_for_fit(layers):
    for lyr in layers or []:
        if lyr is None or not hasattr(lyr, 'wkbType'):
            continue
        _ok = False
        with suppress(AttributeError, RuntimeError, TypeError, ValueError):
            if QgsWkbTypes.geometryType(lyr.wkbType()) == QgsWkbTypes.PointGeometry:
                return lyr
            _ok = True
        if not _ok:
            continue
    return None


def xyz_extent(layer):
    """Full XYZ bounds from p1/p2/p3 fields or PointZ geometry (ignores subset)."""
    fx = fy = fz = None
    for prefix in ('p1', 'p2', 'p3'):
        fx = _merge_span(fx, field_extent(layer, prefix + 'x'))
        fy = _merge_span(fy, field_extent(layer, prefix + 'y'))
        fz = _merge_span(fz, field_extent(layer, prefix + 'z'))
    if fx and fy:
        return {'x': fx, 'y': fy, 'z': fz or (0.0, 1.0)}
    xmin = ymin = zmin = None
    xmax = ymax = zmax = None
    for feat in layer.dataProvider().getFeatures():
        geom = feat.geometry()
        if geom is None or geom.isEmpty():
            continue
        pt = geom.constGet()
        _ok = False
        with suppress(AttributeError, RuntimeError, TypeError, ValueError):
            x, y = float(pt.x()), float(pt.y())
            z = float(pt.z()) if pt.is3D() else 0.0
            _ok = True
        if not _ok:
            continue
        xmin = x if xmin is None else min(xmin, x)
        xmax = x if xmax is None else max(xmax, x)
        ymin = y if ymin is None else min(ymin, y)
        ymax = y if ymax is None else max(ymax, y)
        zmin = z if zmin is None else min(zmin, z)
        zmax = z if zmax is None else max(zmax, z)
    if xmin is None:
        return {'x': (0.0, 1.0), 'y': (0.0, 1.0), 'z': (0.0, 1.0)}
    def span(a, b):
        return (a - 0.5, b + 0.5) if a == b else (a, b)
    return {'x': span(xmin, xmax), 'y': span(ymin, ymax), 'z': span(zmin, zmax)}
