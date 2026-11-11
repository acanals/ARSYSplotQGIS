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
from qgis.PyQt.QtCore import QVariant, Qt
from qgis.PyQt.QtGui import QColor

from .colors_util import color_map, qgis_color

# Ink for rich-text tooltips (inverse of UI: dark tip → cream, light tip → dark).
# Tip chrome (kept in sync with dock.tooltip_palette via set_tooltip_chrome).
TOOLTIP_BG = '#fff8ee'
TOOLTIP_INK = '#1a1816'


def set_tooltip_ink(color):
    """Back-compat: set tip text colour only."""
    global TOOLTIP_INK
    c = str(color or '').strip()
    TOOLTIP_INK = c if c else '#1a1816'


def set_tooltip_chrome(bg, ink):
    """Background + text for HTML tips (must match QToolTip / ToolTipBase)."""
    global TOOLTIP_BG, TOOLTIP_INK
    TOOLTIP_BG = str(bg or '').strip() or '#fff8ee'
    TOOLTIP_INK = str(ink or '').strip() or '#1a1816'


# Comfortable tip column for QTextDocument (≈ 48–52 chars at 11px).
TOOLTIP_MAX_WIDTH_PX = 340


def html_tooltip(*parts, width=None):
    """Compact QToolTip: **bold** markers, forced tip colours, natural wrap.

    Each argument is one sentence/paragraph (soft ``<br/>`` between them).
    Word wrapping is left to Qt via a fixed table width — do **not** insert
    hard breaks per character column (that re-wraps badly and leaves
    one-word lines when the tip window is narrower than the estimate).

    ``width`` is optional tip width in px (≥100) or approx. character columns.
    """
    cleaned = []
    for part in parts:
        if part is None:
            continue
        text = ' '.join(str(part).split())
        if text:
            cleaned.append(text)
    if not cleaned:
        return ''
    max_px = TOOLTIP_MAX_WIDTH_PX
    if width is not None:
        with suppress(TypeError, ValueError):
            w = int(width)
            if w >= 100:
                max_px = max(180, min(520, w))
            elif w > 0:
                max_px = max(180, min(520, w * 7))
    body = '<br/>'.join(_tooltip_markup(text) for text in cleaned)
    # Table width is the reliable wrap constraint for QToolTip rich text.
    return (
        '<html><body style="background-color:%s; color:%s; margin:0; padding:0;">'
        '<table width="%d" cellspacing="0" cellpadding="0" border="0">'
        '<tr><td style="font-size:11px; line-height:1.4; color:%s; '
        'white-space:normal;">%s</td></tr></table>'
        '</body></html>' % (TOOLTIP_BG, TOOLTIP_INK, max_px, TOOLTIP_INK, body)
    )


def _tooltip_markup(text):
    safe = (
        text.replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
        .replace('"', '&quot;')
    )
    out = []
    i = 0
    while True:
        a = safe.find('**', i)
        if a < 0:
            out.append(safe[i:])
            break
        b = safe.find('**', a + 2)
        if b < 0:
            out.append(safe[i:])
            break
        out.append(safe[i:a])
        out.append('<b>')
        out.append(safe[a + 2:b])
        out.append('</b>')
        i = b + 2
    return ''.join(out)


GROUP_NAME = 'ARSYSplotQGIS'
EMPTY_LABEL = '(empty)'
GROUP_FIELD_HINTS = (
    'group', 'material', 'nivell', 'level', 'categoria', 'taxo',
    'grup', 'classe', 'class', 'type', 'tipo',
)
MAX_GROUP_CHIPS = 80
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


def guess_group_field(layer):
    """Prefer a classification field, not a unique id (that freezes the chips)."""
    if layer is None:
        return 'group'
    names = [f.name() for f in layer.fields()]
    if not names:
        return 'group'
    lower = {n.lower(): n for n in names}
    for hint in GROUP_FIELD_HINTS:
        if hint in lower:
            return lower[hint]
    nfeat = max(1, int(layer.featureCount() or 0))
    best = names[0]
    best_n = nfeat + 1
    for f in layer.fields():
        idx = layer.fields().lookupField(f.name())
        nuniq = nfeat
        with suppress(AttributeError, RuntimeError, TypeError, ValueError):
            nuniq = len(layer.dataProvider().uniqueValues(idx) or [])
        if nuniq < best_n and nuniq <= MAX_GROUP_CHIPS:
            best = f.name()
            best_n = nuniq
            if nuniq <= 12:
                return best
    return best


def _match_field_name(names, hints):
    """Pick a field by exact then substring hint (case-insensitive)."""
    lower_map = {str(n).lower().strip(): n for n in names}
    for hint in hints:
        if hint in lower_map:
            return lower_map[hint]
    for hint in hints:
        if len(hint) < 2:
            continue
        for low, orig in lower_map.items():
            if hint in low:
                return orig
    return None


def resolve_xyz_field_map(layer):
    """Map canonical p1x…p3z keys to actual layer field names (CSV-style hints)."""
    from .importer import (
        P2X_HINTS, P2Y_HINTS, P2Z_HINTS,
        P3X_HINTS, P3Y_HINTS, P3Z_HINTS,
        X_HINTS, Y_HINTS, Z_HINTS,
    )
    names = [f.name() for f in layer.fields()] if layer is not None else []
    return {
        'p1x': _match_field_name(names, X_HINTS),
        'p1y': _match_field_name(names, Y_HINTS),
        'p1z': _match_field_name(names, Z_HINTS),
        'p2x': _match_field_name(names, P2X_HINTS),
        'p2y': _match_field_name(names, P2Y_HINTS),
        'p2z': _match_field_name(names, P2Z_HINTS),
        'p3x': _match_field_name(names, P3X_HINTS),
        'p3y': _match_field_name(names, P3Y_HINTS),
        'p3z': _match_field_name(names, P3Z_HINTS),
    }


def clone_as_private_source(layer, name=None):
    """Copy a project point layer into a private PointZ memory layer.

    The original map layer is not styled, filtered or otherwise changed.
    P1 is taken from coordinate fields (same hints as CSV import) when present,
    otherwise from the geometry. P2/P3 vector ends are detected the same way
    (``p2x``/``x2``, ``p3x``/``x3``, …) and normalised like CSV import.
    """
    from .importer import normalize_p123

    if layer is None:
        raise ValueError('No layer')
    crs = layer.crs()
    auth = (crs.authid() or '') if crs is not None and crs.isValid() else ''
    dest = QgsVectorLayer(
        'PointZ?crs=%s' % auth if auth else 'PointZ',
        name or layer.name(),
        'memory',
    )
    if not dest.isValid():
        dest = QgsVectorLayer('PointZ', name or layer.name(), 'memory')
    if not dest.isValid():
        raise ValueError('Could not create a private PointZ copy')
    if crs is not None and crs.isValid():
        dest.setCrs(crs)
    _copy_fields(dest, layer.fields())
    have = {f.name() for f in dest.fields()}
    extra = [
        QgsField(key, QVariant.Double)
        for key in (
            'p1x', 'p1y', 'p1z',
            'p2x', 'p2y', 'p2z',
            'p3x', 'p3y', 'p3z',
        )
        if key not in have
    ]
    if extra:
        dest.dataProvider().addAttributes(extra)
        dest.updateFields()
    src_names = {f.name() for f in layer.fields()}
    fmap = resolve_xyz_field_map(layer)

    def cell(feat, canon):
        """Read a coordinate by canonical key via resolved source field name."""
        src_key = fmap.get(canon)
        if not src_key or src_key not in src_names:
            return None
        return _num(feat[src_key])

    feats = []
    skipped = 0
    n_vectors = 0
    for src in layer.getFeatures():
        geom = src.geometry()
        x1, y1, z1 = cell(src, 'p1x'), cell(src, 'p1y'), cell(src, 'p1z')
        x2, y2, z2 = cell(src, 'p2x'), cell(src, 'p2y'), cell(src, 'p2z')
        x3, y3, z3 = cell(src, 'p3x'), cell(src, 'p3y'), cell(src, 'p3z')
        if (x1 is None or y1 is None) and geom is not None and not geom.isEmpty():
            pt = geom.constGet()
            with suppress(AttributeError, RuntimeError, TypeError, ValueError):
                x1 = float(pt.x()) if x1 is None else x1
                y1 = float(pt.y()) if y1 is None else y1
                if z1 is None:
                    z1 = float(pt.z()) if pt.is3D() else 0.0
        norm = normalize_p123(x1, y1, z1, x2, y2, z2, x3, y3, z3)
        if norm is None:
            skipped += 1
            continue
        p1, p2, p3 = norm
        if p2 is not None and p3 is not None:
            n_vectors += 1
        elif p2 is not None:
            # Legacy P1→P2 axis still counts as a drawable vector.
            n_vectors += 1
        feat = QgsFeature(dest.fields())
        feat.setGeometry(QgsGeometry(QgsPoint(p1[0], p1[1], p1[2])))
        attrs = []
        for field in dest.fields():
            key = field.name()
            if key == 'p1x':
                attrs.append(p1[0])
            elif key == 'p1y':
                attrs.append(p1[1])
            elif key == 'p1z':
                attrs.append(p1[2])
            elif key == 'p2x':
                attrs.append(None if p2 is None else p2[0])
            elif key == 'p2y':
                attrs.append(None if p2 is None else p2[1])
            elif key == 'p2z':
                attrs.append(None if p2 is None else p2[2])
            elif key == 'p3x':
                attrs.append(None if p3 is None else p3[0])
            elif key == 'p3y':
                attrs.append(None if p3 is None else p3[1])
            elif key == 'p3z':
                attrs.append(None if p3 is None else p3[2])
            elif key in src_names:
                attrs.append(src[key])
            else:
                attrs.append(None)
        feat.setAttributes(attrs)
        feats.append(feat)
    if not feats:
        raise ValueError('No plottable points in the selected layer')
    dest.dataProvider().addFeatures(feats)
    dest.updateExtents()
    dest.setCustomProperty('arsysplotqgis', 'source')
    dest.setCustomProperty('arsysplotqgis_from', layer.id())
    dest.setCustomProperty('arsysplotqgis_vectors', str(int(n_vectors)))
    dest.setSubsetString('')
    rend = layer.renderer()
    if rend is not None:
        with suppress(AttributeError, RuntimeError, TypeError, ValueError):
            dest.setRenderer(rend.clone())
    return dest, skipped


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
        layer.setFlags(layer.flags() | QgsMapLayer.LayerFlag.Private)
    if layer.id() not in project.mapLayers():
        project.addMapLayer(layer, False)
    return layer


def release_private(layer, project=None):
    if layer is None:
        return
    project = project or QgsProject.instance()
    if layer.id() in project.mapLayers():
        project.removeMapLayer(layer.id())


def publish_source_to_project(source, name=None, project=None):
    """Clone the plugin PointZ source into a normal QGIS project memory layer.

    Sends the **complete** attribute table and geometries (filters / subset on
    the private source are ignored for this copy). The layer is not Private, so
    it appears in the legend and can be used with Processing / GRASS. It stays
    a memory layer — the user decides whether to Save As / make permanent when
    closing the project. The plugin workspace copy is left unchanged.
    """
    if source is None or not source.isValid():
        raise ValueError('No data loaded in ARSYSplotQGIS yet.')
    project = project or QgsProject.instance()
    crs = source.crs()
    auth = (crs.authid() or '') if crs is not None and crs.isValid() else ''
    base = (name or source.name() or 'ARSYSplot').strip() or 'ARSYSplot'
    # Avoid colliding with the private name when both appear in debugging.
    out_name = base if base.endswith('(QGIS)') else '%s (QGIS)' % base

    dest = QgsVectorLayer(
        'PointZ?crs=%s' % auth if auth else 'PointZ',
        out_name,
        'memory',
    )
    if not dest.isValid():
        dest = QgsVectorLayer('PointZ', out_name, 'memory')
    if not dest.isValid():
        raise ValueError('Could not create a project memory layer')
    if crs is not None and crs.isValid():
        dest.setCrs(crs)
    _copy_fields(dest, source.fields())

    # Full table: temporarily clear subset used by Group / XYZ filters.
    prev_subset = ''
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        prev_subset = source.subsetString() or ''
    try:
        if prev_subset:
            source.setSubsetString('')
        feats = []
        for src in source.getFeatures():
            feat = QgsFeature(dest.fields())
            geom = src.geometry()
            if geom is not None and not geom.isEmpty():
                feat.setGeometry(QgsGeometry(geom))
            attrs = []
            for field in dest.fields():
                idx = src.fields().lookupField(field.name())
                attrs.append(src[idx] if idx >= 0 else NULL)
            feat.setAttributes(attrs)
            feats.append(feat)
    finally:
        if prev_subset:
            with suppress(AttributeError, RuntimeError, TypeError, ValueError):
                source.setSubsetString(prev_subset)

    if not feats:
        raise ValueError('Source layer has no features to send to QGIS.')
    dest.dataProvider().addFeatures(feats)
    dest.updateExtents()

    # Public project layer — not plugin-private.
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        flags = dest.flags()
        private = getattr(QgsMapLayer.LayerFlag, 'Private', None)
        if private is not None and (flags & private):
            dest.setFlags(flags & ~private)
    # Do not set arsysplotqgis=source (that marks private plugin layers).
    dest.setCustomProperty('arsysplotqgis_export', '1')
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        dest.setCustomProperty(
            'arsysplotqgis_export_from',
            str(source.customProperty('arsysplotqgis_file') or source.name()),
        )

    rend = source.renderer()
    if rend is not None:
        with suppress(AttributeError, RuntimeError, TypeError, ValueError):
            dest.setRenderer(rend.clone())

    project.addMapLayer(dest, True)
    return dest


def publish_vector_to_project(source, name=None, project=None):
    """Clone any vector layer into a public project memory layer (legend).

    Used for Profile LONG/TRANS section panes. Geometry and attributes are
    copied as currently stored (already projected to section axes). Honour the
    source subset string so Group ∩ Resources filters apply.
    """
    if source is None or not source.isValid():
        raise ValueError('No section layer to send to QGIS.')
    project = project or QgsProject.instance()
    crs = source.crs()
    auth = (crs.authid() or '') if crs is not None and crs.isValid() else ''
    out_name = (name or source.name() or 'ARSYSplot section').strip()
    if not out_name:
        out_name = 'ARSYSplot section'
    if not out_name.endswith('(QGIS)'):
        out_name = '%s (QGIS)' % out_name

    wkb = source.wkbType()
    geom_name = QgsWkbTypes.displayString(wkb) if wkb is not None else 'Point'
    uri = '%s?crs=%s' % (geom_name, auth) if auth else geom_name
    dest = QgsVectorLayer(uri, out_name, 'memory')
    if not dest.isValid():
        dest = QgsVectorLayer(geom_name, out_name, 'memory')
    if not dest.isValid():
        raise ValueError('Could not create a project memory layer')
    if crs is not None and crs.isValid():
        dest.setCrs(crs)
    _copy_fields(dest, source.fields())

    feats = []
    for src in source.getFeatures():
        feat = QgsFeature(dest.fields())
        geom = src.geometry()
        if geom is not None and not geom.isEmpty():
            feat.setGeometry(QgsGeometry(geom))
        attrs = []
        for field in dest.fields():
            idx = src.fields().lookupField(field.name())
            attrs.append(src[idx] if idx >= 0 else NULL)
        feat.setAttributes(attrs)
        feats.append(feat)
    if not feats:
        raise ValueError('Section layer has no features to send to QGIS.')
    dest.dataProvider().addFeatures(feats)
    dest.updateExtents()

    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        flags = dest.flags()
        private = getattr(QgsMapLayer.LayerFlag, 'Private', None)
        if private is not None and (flags & private):
            dest.setFlags(flags & ~private)
    dest.setCustomProperty('arsysplotqgis_export', '1')
    dest.setCustomProperty('arsysplotqgis_export_kind', 'profile_section')
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        dest.setCustomProperty(
            'arsysplotqgis_export_from',
            str(source.customProperty('arsysplotqgis_file') or source.name()),
        )
    for key in (
        'arsysplotqgis_z_stretch',
        'arsysplotqgis_profile',
        'arsysplotqgis_profile_long_axis',
    ):
        with suppress(AttributeError, RuntimeError, TypeError, ValueError):
            val = source.customProperty(key)
            if val not in (None, ''):
                dest.setCustomProperty(key, val)

    rend = source.renderer()
    if rend is not None:
        with suppress(AttributeError, RuntimeError, TypeError, ValueError):
            dest.setRenderer(rend.clone())

    project.addMapLayer(dest, True)
    return dest


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


def imported_layer_style(layer):
    """Classification field, colours and point size from a QGIS layer renderer."""
    style = {'field': None, 'cmap': {}, 'size': None}
    if layer is None:
        return style
    rend = layer.renderer()
    if rend is None:
        return style
    attr = ''
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        attr = (rend.classAttribute() or '').strip()
    if attr and layer.fields().lookupField(attr) >= 0:
        style['field'] = attr
    elif attr:
        for field in layer.fields():
            name = field.name()
            if '"%s"' % name in attr or name == attr:
                style['field'] = name
                break
    if isinstance(rend, QgsCategorizedSymbolRenderer):
        for cat in rend.categories():
            color = _qgs_symbol_color(cat.symbol())
            if color is None or not color.isValid():
                continue
            raw = cat.value()
            keys = [group_label(raw)]
            if raw is not None:
                text = str(raw).strip()
                if text and text not in keys:
                    keys.append(text)
                with suppress(TypeError, ValueError):
                    num = float(raw)
                    if num == int(num):
                        alias = str(int(num))
                        if alias not in keys:
                            keys.append(alias)
            lab = (cat.label() or '').strip()
            if lab and lab not in keys:
                keys.append(lab)
            for key in keys:
                style['cmap'][key] = QColor(color)
            if style['size'] is None:
                style['size'] = _qgs_symbol_size_mm(cat.symbol())
        return style
    ranges = None
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        ranges = list(rend.ranges())
    if ranges:
        for rng in ranges:
            color = _qgs_symbol_color(rng.symbol())
            if color is None or not color.isValid():
                continue
            lab = ''
            with suppress(AttributeError, RuntimeError, TypeError, ValueError):
                lab = (rng.label() or '').strip()
            if lab:
                style['cmap'][lab] = QColor(color)
            if style['size'] is None:
                style['size'] = _qgs_symbol_size_mm(rng.symbol())
        if style['field']:
            idx = layer.fields().lookupField(style['field'])
            nuniq = MAX_GROUP_CHIPS + 1
            with suppress(AttributeError, RuntimeError, TypeError, ValueError):
                nuniq = len(layer.dataProvider().uniqueValues(idx) or [])
            if nuniq > MAX_GROUP_CHIPS:
                style['field'] = None
        return style
    root = None
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        root = rend.rootRule()
    if root is not None:
        _collect_rule_style(root, style)
        return style
    sym = None
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        sym = rend.symbol()
    color = _qgs_symbol_color(sym)
    if color is not None and color.isValid():
        style['cmap']['__default__'] = QColor(color)
    if style['size'] is None:
        style['size'] = _qgs_symbol_size_mm(sym)
    return style


def _collect_rule_style(rule, style):
    if rule is None:
        return
    active = True
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        active = bool(rule.active())
    if active:
        sym = None
        with suppress(AttributeError, RuntimeError, TypeError, ValueError):
            sym = rule.symbol()
        color = _qgs_symbol_color(sym)
        lab = ''
        with suppress(AttributeError, RuntimeError, TypeError, ValueError):
            lab = (rule.label() or '').strip()
        if not lab:
            with suppress(AttributeError, RuntimeError, TypeError, ValueError):
                lab = (rule.filterExpression() or '').strip()
        if color is not None and color.isValid() and lab:
            style['cmap'][lab] = QColor(color)
        if style['size'] is None:
            style['size'] = _qgs_symbol_size_mm(sym)
    children = []
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        children = list(rule.children() or [])
    for child in children:
        _collect_rule_style(child, style)


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
    if len(out) > MAX_GROUP_CHIPS:
        out = out[:MAX_GROUP_CHIPS]
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


# QGIS simple-marker names → UI label.
# Same catalogue as ARSYSplotLite (GroupColors.VALID_SYMBOLS) — no losses either way.
MARKER_SHAPES = (
    ('circle', 'Circle'),
    ('square', 'Square'),
    ('diamond', 'Diamond'),
    ('triangle', 'Triangle'),
    ('triangle-inverted', 'Inverted triangle'),
    ('equilateral_triangle', 'Equilateral triangle'),
    ('pentagon', 'Pentagon'),
    ('hexagon', 'Hexagon'),
    ('octagon', 'Octagon'),
    ('star', 'Star'),
    ('cross', 'Cross'),
    ('cross2', 'X'),
)
DEFAULT_MARKER = 'circle'
_MARKER_IDS = {sid for sid, _lab in MARKER_SHAPES}
# Stroke-only QGIS markers (no fill) — colour must go on the outline.
_LINE_MARKERS = frozenset({'cross', 'cross2'})
# Dark rim eats triangle/star tips below this diameter (mm).
_OUTLINE_SIZE_FLOOR = 2.2
# Tolerant aliases for style files / typos (cros, start, …).
_SHAPE_ALIASES = {
    'cros': 'cross',
    'cruz': 'cross',
    '+': 'cross',
    'plus': 'cross',
    'x': 'cross2',
    'cross_2': 'cross2',
    'crossx': 'cross2',
    'start': 'star',
    'estrella': 'star',
    'tri': 'triangle',
    'trg': 'triangle',
    'eq': 'equilateral_triangle',
    'equilateral': 'equilateral_triangle',
    'equilateraltriangle': 'equilateral_triangle',
    'triangle_inverted': 'triangle-inverted',
    'inverted': 'triangle-inverted',
    'inverted_triangle': 'triangle-inverted',
    'invertedtriangle': 'triangle-inverted',
    'circ': 'circle',
    'o': 'circle',
    'sq': 'square',
    'rect': 'square',
    'dia': 'diamond',
    'rhombus': 'diamond',
    'penta': 'pentagon',
    'hexa': 'hexagon',
    'octa': 'octagon',
}


def resolve_marker_shape(name, fallback=DEFAULT_MARKER):
    """Map UI / file text → marker id. ``fallback=None`` → unknown stays None."""
    raw = str(name or '').strip()
    if not raw:
        return fallback
    key = raw.lower().replace(' ', '_').replace('-', '_')
    key = _SHAPE_ALIASES.get(key, key)
    if key in _MARKER_IDS:
        return key
    # Title-case enum leftovers: "Star" / "Cross2"
    key2 = _SHAPE_ALIASES.get(raw.casefold().replace(' ', '_'), raw.casefold())
    if key2 in _MARKER_IDS:
        return key2
    return fallback


def _filled_outline_mm(size_mm):
    """Dark outline width for filled markers; 0 when too small to stay crisp."""
    size_mm = max(0.0, float(size_mm))
    if size_mm < _OUTLINE_SIZE_FLOOR:
        return 0.0
    return min(0.18, size_mm * 0.07)


def _line_stroke_mm(size_mm):
    """Stroke width for Cross / X — scale with size, never dominate the glyph."""
    size_mm = max(0.0, float(size_mm))
    if size_mm <= 0.05:
        return 0.20
    # Keep a visible hairline; old floor was 0.35 mm and read heavy at small sizes.
    return max(0.20, min(0.45, size_mm * 0.18))


def _coerce_shape_id(name):
    """Map QGIS name/enum text → our lowercase marker id, or None."""
    raw = str(name or '').strip()
    if not raw:
        return None
    key = raw.lower().replace(' ', '_').replace('-', '_')
    aliases = {
        'cross_2': 'cross2',
        'x': 'cross2',
        'equilateraltriangle': 'equilateral_triangle',
        'equilateral_triangle': 'equilateral_triangle',
        'triangle_inverted': 'triangle-inverted',
        'inverted_triangle': 'triangle-inverted',
        'invertedtriangle': 'triangle-inverted',
    }
    key = aliases.get(key, key)
    if key in _MARKER_IDS:
        return key
    return None


def _layer_marker_angle(sl):
    if sl is None:
        return 0.0
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        if hasattr(sl, 'angle') and callable(sl.angle):
            return float(sl.angle())
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        props = sl.properties() if hasattr(sl, 'properties') else None
        if props and props.get('angle') not in (None, ''):
            return float(props.get('angle'))
    return 0.0


def _canonical_shape_from_layer(sid, angle):
    """triangle + ~180° ↔ Lite/plugin id triangle-inverted."""
    if sid == 'triangle' and abs(float(angle or 0.0) - 180.0) < 1.0:
        return 'triangle-inverted'
    return sid


def _qgis_simple_marker_name(shape):
    """Our id → QGIS simple-marker name (inverted triangle = triangle @ 180°)."""
    shape = resolve_marker_shape(shape)
    if shape == 'triangle-inverted':
        return 'triangle'
    return shape


def _qgis_simple_marker_angle(shape):
    shape = resolve_marker_shape(shape)
    return 180.0 if shape == 'triangle-inverted' else 0.0


def _layer_shape_id(sl):
    if sl is None:
        return None
    angle = _layer_marker_angle(sl)
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        if hasattr(sl, 'name') and callable(sl.name):
            sid = _coerce_shape_id(sl.name())
            if sid:
                return _canonical_shape_from_layer(sid, angle)
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        if hasattr(sl, 'properties'):
            sid = _coerce_shape_id((sl.properties() or {}).get('name'))
            if sid:
                return _canonical_shape_from_layer(sid, angle)
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        if hasattr(sl, 'shape') and callable(sl.shape):
            # Qgis.MarkerShape.Cross → "MarkerShape.Cross" / "Cross"
            sid = _coerce_shape_id(str(sl.shape()).split('.')[-1])
            if sid:
                return _canonical_shape_from_layer(sid, angle)
    return None


def _tune_marker_layer_stroke(sl, size_mm, shape, paint_color=None):
    """Scale outline and sharpen joins so small polygons stay readable."""
    if sl is None:
        return
    size_mm = max(0.0, float(size_mm))
    shape = resolve_marker_shape(shape)
    line_like = shape in _LINE_MARKERS
    if line_like:
        stroke = _line_stroke_mm(size_mm)
        oc = paint_color if (paint_color is not None and paint_color.isValid()) else None
        pen_style = Qt.PenStyle.SolidLine
    else:
        stroke = _filled_outline_mm(size_mm)
        if stroke > 0:
            oc = QColor(17, 17, 17, 255)
            pen_style = Qt.PenStyle.SolidLine
        else:
            oc = QColor(0, 0, 0, 0)
            pen_style = Qt.PenStyle.NoPen
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        if hasattr(sl, 'setStrokeWidth'):
            sl.setStrokeWidth(stroke)
        elif hasattr(sl, 'setOutlineWidth'):
            sl.setOutlineWidth(stroke)
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        if hasattr(sl, 'setStrokeStyle'):
            sl.setStrokeStyle(pen_style)
        elif hasattr(sl, 'setOutlineStyle'):
            sl.setOutlineStyle(pen_style)
    if oc is not None:
        with suppress(AttributeError, RuntimeError, TypeError, ValueError):
            if hasattr(sl, 'setStrokeColor'):
                sl.setStrokeColor(oc)
            if hasattr(sl, 'setOutlineColor'):
                sl.setOutlineColor(oc)
    # Sharp corners (triangle, star, …) instead of round blobs at small px.
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        if hasattr(sl, 'setPenJoinStyle'):
            sl.setPenJoinStyle(Qt.PenJoinStyle.MiterJoin)
        elif hasattr(sl, 'setStrokeJoinStyle'):
            sl.setStrokeJoinStyle(Qt.PenJoinStyle.MiterJoin)


def _apply_symbol_color(sym, color, shape=None):
    c = QColor(color)
    if sym is None or not c.isValid():
        return
    if shape:
        shape = resolve_marker_shape(shape)
    size_mm = 2.2
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        if hasattr(sym, 'size'):
            size_mm = float(sym.size())
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        sym.setColor(c)
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        for i in range(sym.symbolLayerCount()):
            sl = sym.symbolLayer(i)
            if sl is None:
                continue
            layer_shape = _layer_shape_id(sl)
            use_shape = shape or layer_shape or DEFAULT_MARKER
            line_like = use_shape in _LINE_MARKERS
            if hasattr(sl, 'setFillColor') and not line_like:
                with suppress(AttributeError, RuntimeError, TypeError, ValueError):
                    sl.setFillColor(c)
            if hasattr(sl, 'setColor'):
                with suppress(AttributeError, RuntimeError, TypeError, ValueError):
                    sl.setColor(c)
            # Cross / X are stroke-only — group colour must be on the outline.
            if line_like:
                with suppress(AttributeError, RuntimeError, TypeError, ValueError):
                    if hasattr(sl, 'setStrokeColor'):
                        sl.setStrokeColor(c)
                    if hasattr(sl, 'setOutlineColor'):
                        sl.setOutlineColor(c)
            _tune_marker_layer_stroke(sl, size_mm, use_shape, paint_color=c)


def _marker(color, size, shape=None):
    c = QColor(color)
    shape = resolve_marker_shape(shape)
    size = max(0.0, float(size))
    props = {
        'name': _qgis_simple_marker_name(shape),
        'angle': str(_qgis_simple_marker_angle(shape)),
        'color': qgis_color(c),
        'size': str(size),
    }
    if shape in _LINE_MARKERS:
        # Cross / X have no fill — group colour is the stroke.
        props['outline_color'] = qgis_color(c)
        props['outline_width'] = str(_line_stroke_mm(size))
    else:
        ow = _filled_outline_mm(size)
        if ow > 0:
            props['outline_color'] = '17,17,17,255'
            props['outline_width'] = str(ow)
        else:
            # No dark rim: fill alone reads sharper at small diameters.
            props['outline_color'] = '0,0,0,0'
            props['outline_width'] = '0'
            props['outline_style'] = 'no'
    sym = QgsMarkerSymbol.createSimple(props)
    _apply_symbol_color(sym, c, shape=shape)
    return sym


def _shape_for_value(val, default_shape, shapes=None):
    """Per-category shape from ``shapes`` map, else the global Point model."""
    default_shape = resolve_marker_shape(default_shape)
    if not shapes:
        return default_shape
    if val in shapes and shapes[val]:
        return resolve_marker_shape(shapes[val])
    want = str(val or '').casefold()
    for key, sid in shapes.items():
        if str(key or '').casefold() == want and sid:
            return resolve_marker_shape(sid)
    return default_shape


def style_by_group(layer, field='group', size=2.2, cmap=None, values=None,
                   shape=None, shapes=None):
    """Categorised markers. ``shapes`` optional map value → marker id."""
    if layer is None:
        return color_map(values or [], base=cmap)
    values = list(values) if values is not None else unique_groups(layer, field)
    cmap = color_map(values, base=cmap)
    size = max(0.0, float(size))
    default_shape = resolve_marker_shape(shape)
    shapes = dict(shapes) if shapes else {}
    cats = []
    for val in values:
        color = cmap.get(val, QColor('#888888'))
        sh = _shape_for_value(val, default_shape, shapes)
        cats.append(QgsRendererCategory(val, _marker(color, size, sh), val))
        if val == EMPTY_LABEL:
            for raw in (NULL, '', None):
                cats.append(QgsRendererCategory(
                    raw, _marker(color, size, sh), EMPTY_LABEL,
                ))
    if not cats:
        return cmap
    renderer = QgsCategorizedSymbolRenderer(group_class_attr(field), cats)
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        renderer.setClassAttribute(group_class_attr(field))
    if values:
        with suppress(AttributeError, RuntimeError, TypeError, ValueError):
            sh0 = _shape_for_value(values[0], default_shape, shapes)
            renderer.setSourceSymbol(
                _marker(cmap.get(values[0], QColor('#888888')), size, sh0)
            )
    layer.setRenderer(renderer)
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        layer.setCustomProperty('arsysplotqgis_group', str(field or ''))
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


def _qgs_symbol_color(sym):
    if sym is None:
        return QColor()
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        c = sym.color()
        if c is not None and c.isValid():
            return QColor(c)
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        if sym.symbolLayerCount() > 0:
            return _symbol_color(sym.symbolLayer(0))
    return QColor()


def _qgs_symbol_size_mm(sym):
    if sym is None:
        return None
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        if hasattr(sym, 'size'):
            size = float(sym.size())
            if size > 0:
                return size
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        if sym.symbolLayerCount() > 0:
            sl = sym.symbolLayer(0)
            if sl is not None and hasattr(sl, 'size'):
                size = float(sl.size())
                if size > 0:
                    return size
    return None


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
        return color_map(values or [], base=cmap)
    values = list(values) if values is not None else unique_groups(layer, field)
    cmap = color_map(values, base=cmap)
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


_MARKER_SHAPE_ENUM = {
    'circle': 'Circle',
    'square': 'Square',
    'diamond': 'Diamond',
    'triangle': 'Triangle',
    'triangle-inverted': 'Triangle',  # rendered as triangle @ 180°
    'equilateral_triangle': 'EquilateralTriangle',
    'pentagon': 'Pentagon',
    'hexagon': 'Hexagon',
    'octagon': 'Octagon',
    'star': 'Star',
    'cross': 'Cross',
    'cross2': 'Cross2',
}


def _set_symbol_marker_name(sym, shape):
    """Set the simple-marker shape on every marker layer of ``sym``."""
    if sym is None:
        return
    shape = resolve_marker_shape(shape)
    qname = _qgis_simple_marker_name(shape)
    angle = _qgis_simple_marker_angle(shape)
    enum_name = _MARKER_SHAPE_ENUM.get(shape, 'Circle')
    for i in range(sym.symbolLayerCount()):
        lyr = sym.symbolLayer(i)
        if lyr is None:
            continue
        with suppress(AttributeError, RuntimeError, TypeError, ValueError):
            if hasattr(lyr, 'setAngle'):
                lyr.setAngle(angle)
        done = False
        if hasattr(lyr, 'setName'):
            with suppress(AttributeError, RuntimeError, TypeError, ValueError):
                lyr.setName(qname)
                done = True
        if done:
            continue
        if hasattr(lyr, 'setShape'):
            with suppress(AttributeError, RuntimeError, TypeError, ValueError):
                from qgis.core import Qgis
                shapes = getattr(Qgis, 'MarkerShape', None)
                enum = getattr(shapes, enum_name, None) if shapes is not None else None
                if enum is not None:
                    lyr.setShape(enum)


def _symbol_marker_shape(sym):
    """Best-effort simple-marker name from an existing symbol."""
    if sym is None:
        return DEFAULT_MARKER
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        for i in range(sym.symbolLayerCount()):
            sid = _layer_shape_id(sym.symbolLayer(i))
            if sid:
                return sid
    return DEFAULT_MARKER


def _layer_stroke_color(sl):
    if sl is None:
        return None
    for getter in ('strokeColor', 'outlineColor'):
        with suppress(AttributeError, RuntimeError, TypeError, ValueError):
            if hasattr(sl, getter) and callable(getattr(sl, getter)):
                c = getattr(sl, getter)()
                if c is not None and c.isValid() and c.alpha() > 0:
                    return QColor(c)
    return None


def _symbol_paint_color(sym):
    """Visible tint: stroke for Cross/X, fill otherwise."""
    if sym is None:
        return QColor('#888888')
    shape = _symbol_marker_shape(sym)
    if shape in _LINE_MARKERS:
        with suppress(AttributeError, RuntimeError, TypeError, ValueError):
            for i in range(sym.symbolLayerCount()):
                c = _layer_stroke_color(sym.symbolLayer(i))
                if c is not None:
                    return c
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        c = sym.color()
        if c is not None and c.isValid() and c.alpha() > 0:
            return QColor(c)
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        for i in range(sym.symbolLayerCount()):
            sl = sym.symbolLayer(i)
            if sl is None:
                continue
            if hasattr(sl, 'fillColor') and callable(sl.fillColor):
                c = sl.fillColor()
                if c is not None and c.isValid() and c.alpha() > 0:
                    return QColor(c)
            c = _layer_stroke_color(sl)
            if c is not None:
                return c
    return QColor('#888888')


def _retune_marker_symbol_size(sym, size_mm):
    if sym is None:
        return
    size_mm = max(0.0, float(size_mm))
    # Capture paint colour *before* size/stroke tweaks (Cross stores it on stroke).
    paint = _symbol_paint_color(sym)
    shape = _symbol_marker_shape(sym)
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        sym.setSize(size_mm)
    # Full colour pass keeps Cross/X on SolidLine + group stroke (not NoPen/black).
    _apply_symbol_color(sym, paint, shape=shape)


def apply_marker_size(layer, size_mm):
    if layer is None:
        return
    renderer = layer.renderer()
    if renderer is None:
        return
    size_mm = max(0.0, float(size_mm))
    if isinstance(renderer, QgsCategorizedSymbolRenderer):
        for i in range(len(renderer.categories())):
            cat = renderer.categories()[i]
            sym = cat.symbol()
            if sym is None:
                continue
            cloned = sym.clone()
            _retune_marker_symbol_size(cloned, size_mm)
            renderer.updateCategorySymbol(i, cloned)
    else:
        sym = renderer.symbol() if hasattr(renderer, 'symbol') else None
        if sym is not None:
            _retune_marker_symbol_size(sym, size_mm)
    layer.triggerRepaint()


def apply_marker_shape(layer, shape):
    """Change point marker model (circle, cross, …) without rebuilding colours."""
    if layer is None:
        return
    renderer = layer.renderer()
    if renderer is None:
        return
    shape = resolve_marker_shape(shape)

    def _retune(sym):
        if sym is None:
            return
        # Read colour before shape swap (fill↔stroke roles change for Cross/X).
        col = _symbol_paint_color(sym)
        _set_symbol_marker_name(sym, shape)
        _apply_symbol_color(sym, col, shape=shape)

    if isinstance(renderer, QgsCategorizedSymbolRenderer):
        for i in range(len(renderer.categories())):
            cat = renderer.categories()[i]
            sym = cat.symbol()
            if sym is None:
                continue
            cloned = sym.clone()
            _retune(cloned)
            renderer.updateCategorySymbol(i, cloned)
        with suppress(AttributeError, RuntimeError, TypeError, ValueError):
            src = renderer.sourceSymbol()
            if src is not None:
                cloned = src.clone()
                _retune(cloned)
                renderer.setSourceSymbol(cloned)
    else:
        sym = renderer.symbol() if hasattr(renderer, 'symbol') else None
        if sym is not None:
            _retune(sym)
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
            QgsFeatureRequest().setFlags(QgsFeatureRequest.Flag.NoGeometry)
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


def _clamp_z_stretch(z_stretch):
    try:
        s = float(z_stretch)
    except (TypeError, ValueError):
        s = 1.0
    if s < 1.0:
        s = 1.0
    if s > 100.0:
        s = 100.0
    return s


def clear_section(section):
    """Remove all features from a section / section-line memory layer."""
    if section is None:
        return
    prov = section.dataProvider()
    ids = [
        f.id()
        for f in section.getFeatures(
            QgsFeatureRequest().setFlags(QgsFeatureRequest.Flag.NoGeometry)
        )
    ]
    if ids:
        prov.deleteFeatures(ids)
    section.updateExtents()
    section.triggerRepaint()


def rebuild_section(source, section, mode, z_stretch=1.0, profile=None):
    """mode: 'long' → Point(x,z); 'trans' → Point(y,z); profile uses plan axes.

    ``profile`` is ``{'frame': (...), 'wide_m': float}`` for Profile mode
    (finite XY profile; LONG = dominant plan axis of axial foot × Z,
    TRANS = other plan axis of each point × Z). ``None`` = site-wide XZ/YZ.

    ``z_stretch`` > 1 exaggerates Z on section canvases (display metres).
    Axis labels must divide by the same factor to show real Z.
    """
    if source is None or section is None:
        return
    from . import profile as P

    stretch = _clamp_z_stretch(z_stretch)
    frame = None
    wide_m = 0.0
    if profile:
        frame = profile.get('frame')
        try:
            wide_m = float(profile.get('wide_m') or 0.0)
        except (TypeError, ValueError):
            wide_m = 0.0
        if frame is None or wide_m <= 0.0:
            clear_section(section)
            return
    prov = section.dataProvider()
    ids = [f.id() for f in section.getFeatures(QgsFeatureRequest().setFlags(QgsFeatureRequest.Flag.NoGeometry))]
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
        if frame is not None:
            if not P.in_corridor(x, y, frame, wide_m):
                continue
            uv = P.to_uv(x, y, frame)
            if uv is None:
                continue
            u, _v = uv
            if mode == 'long':
                # Plan X or Y of the axial foot — ticks match Planta.
                h = P.long_h_from_uv(u, frame)
                if h is None:
                    continue
            else:
                # Other plan axis of the point (not profile offset).
                h = P.trans_h_from_xy(x, y, frame)
                if h is None:
                    continue
        else:
            h = x if mode == 'long' else y
        z_disp = z * stretch
        g = QgsGeometry(QgsPoint(h, z_disp))
        feat = QgsFeature(section.fields())
        feat.setGeometry(g)
        feat.setAttributes(src.attributes())
        feats.append(feat)
    if feats:
        prov.addFeatures(feats)
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        section.setCustomProperty('arsysplotqgis_z_stretch', '%.6g' % stretch)
        section.setCustomProperty(
            'arsysplotqgis_profile', '1' if frame is not None else '0',
        )
        if frame is not None and mode == 'long':
            section.setCustomProperty(
                'arsysplotqgis_profile_long_axis', P.long_plan_axis(frame),
            )
        if frame is not None and mode == 'trans':
            section.setCustomProperty(
                'arsysplotqgis_profile_trans_axis', P.trans_plan_axis(frame),
            )
    section.updateExtents()
    # Snap plan-axis section extent to whole metres when profiling.
    if frame is not None and section.featureCount() > 0:
        with suppress(AttributeError, RuntimeError, TypeError, ValueError):
            ext = section.extent()
            span = P.round_axis_bounds(ext.xMinimum(), ext.xMaximum())
            if span is not None:
                section.setExtent(QgsRectangle(
                    span[0], ext.yMinimum(), span[1], ext.yMaximum(),
                ))
    section.triggerRepaint()


def rebuild_section_lines(source, section, mode, z_stretch=1.0, profile=None):
    """Project P2→P3 (or P1→P2) onto XZ/YZ or profile UZ/VZ as 2D lines."""
    if source is None or section is None:
        return
    from . import profile as P

    stretch = _clamp_z_stretch(z_stretch)
    frame = None
    wide_m = 0.0
    if profile:
        frame = profile.get('frame')
        try:
            wide_m = float(profile.get('wide_m') or 0.0)
        except (TypeError, ValueError):
            wide_m = 0.0
        if frame is None or wide_m <= 0.0:
            clear_section(section)
            return
    feats = []
    for src in source.getFeatures():
        ends = vector_endpoints(src)
        if ends is None:
            continue
        a, b = ends
        # Keep vector if either endpoint (or midpoint) sits in the profile.
        if frame is not None:
            mid = (
                0.5 * (a[0] + b[0]),
                0.5 * (a[1] + b[1]),
            )
            if not (
                P.in_corridor(a[0], a[1], frame, wide_m)
                or P.in_corridor(b[0], b[1], frame, wide_m)
                or P.in_corridor(mid[0], mid[1], frame, wide_m)
            ):
                continue
            uva = P.to_uv(a[0], a[1], frame)
            uvb = P.to_uv(b[0], b[1], frame)
            if uva is None or uvb is None:
                continue
            if mode == 'long':
                ha = P.long_h_from_uv(uva[0], frame)
                hb = P.long_h_from_uv(uvb[0], frame)
                if ha is None or hb is None:
                    continue
                pa = (ha, a[2] * stretch, 0.0)
                pb = (hb, b[2] * stretch, 0.0)
            else:
                ha = P.trans_h_from_xy(a[0], a[1], frame)
                hb = P.trans_h_from_xy(b[0], b[1], frame)
                if ha is None or hb is None:
                    continue
                pa = (ha, a[2] * stretch, 0.0)
                pb = (hb, b[2] * stretch, 0.0)
        elif mode == 'long':
            pa = (a[0], a[2] * stretch, 0.0)
            pb = (b[0], b[2] * stretch, 0.0)
        else:
            pa = (a[1], a[2] * stretch, 0.0)
            pb = (b[1], b[2] * stretch, 0.0)
        if _len2(pa, pb) <= VECTOR_EPS * VECTOR_EPS:
            continue
        feat = QgsFeature(section.fields())
        feat.setGeometry(_line_geom(pa, pb, with_z=False))
        feat.setAttributes(src.attributes())
        feats.append(feat)
    _replace_features(section, feats)
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        section.setCustomProperty('arsysplotqgis_z_stretch', '%.6g' % stretch)
        section.setCustomProperty(
            'arsysplotqgis_profile', '1' if frame is not None else '0',
        )


def field_extent(layer, field):
    idx = layer.fields().lookupField(field)
    if idx < 0:
        return None
    mn, mx = None, None
    req = QgsFeatureRequest().setFlags(QgsFeatureRequest.Flag.NoGeometry).setSubsetOfAttributes([idx])
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
        if gtype == QgsWkbTypes.GeometryType.PointGeometry:
            pass
        elif include_lines and gtype == QgsWkbTypes.GeometryType.LineGeometry:
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
            if QgsWkbTypes.geometryType(lyr.wkbType()) == QgsWkbTypes.GeometryType.PointGeometry:
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
