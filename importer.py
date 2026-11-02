# -*- coding: utf-8 -*-
"""CSV → PointZ memory layer (P1 point, optional P2→P3 vector)."""
import csv
import os

from qgis.core import (
    QgsFeature,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsPoint,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QMetaType, QVariant
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QLabel,
    QMessageBox,
    QVBoxLayout,
)

from .crs_util import site_crs
from .layers import html_tooltip

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
SAMPLE_CSV = os.path.join(PLUGIN_DIR, 'sample.csv')

X_HINTS = ('p1x', 'x1', 'x', 'east', 'easting')
Y_HINTS = ('p1y', 'y1', 'y', 'north', 'northing')
Z_HINTS = ('p1z', 'z1', 'z', 'elev', 'elevation', 'cota')
P2X_HINTS = ('p2x', 'x2')
P2Y_HINTS = ('p2y', 'y2')
P2Z_HINTS = ('p2z', 'z2')
P3X_HINTS = ('p3x', 'x3')
P3Y_HINTS = ('p3y', 'y3')
P3Z_HINTS = ('p3z', 'z3')
G_HINTS = ('material', 'grup', 'group', 'categoria', 'nivell', 'level')


def _guess(headers, hints):
    lower = [h.lower().strip() for h in headers]
    for hint in hints:
        for i, h in enumerate(lower):
            if h == hint:
                return headers[i]
    for hint in hints:
        if len(hint) < 2:
            continue
        for i, h in enumerate(lower):
            if hint in h:
                return headers[i]
    return headers[0] if headers else ''


def _guess_optional(headers, hints):
    lower = [h.lower().strip() for h in headers]
    for hint in hints:
        for i, h in enumerate(lower):
            if h == hint:
                return headers[i]
    for hint in hints:
        if len(hint) < 2:
            continue
        for i, h in enumerate(lower):
            if hint in h:
                return headers[i]
    return ''


def sniff_csv(path):
    raw = None
    encoding = None
    for enc in ('utf-8-sig', 'utf-8', 'latin-1'):
        try:
            with open(path, 'r', encoding=enc, newline='') as fh:
                raw = fh.read()
        except UnicodeDecodeError:
            raw = None
        if raw is not None:
            encoding = enc
            break
    if raw is None:
        raise ValueError('Cannot read file encoding')
    sample = raw[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=';,|\t')
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = '|' if sample.count('|') > sample.count(';') else ';'
        if sample.count(',') > sample.count(delimiter):
            delimiter = ','
    lines = raw.splitlines()
    if not lines:
        raise ValueError('Empty file')
    reader = csv.reader(lines, delimiter=delimiter)
    rows = list(reader)
    headers = [str(h).strip() or 'col%d' % i for i, h in enumerate(rows[0])]
    data = rows[1:]
    return encoding, delimiter, headers, data


def _field_kind(values):
    saw_float = False
    saw_int = True
    n = 0
    for v in values:
        s = (v or '').strip()
        if s == '':
            continue
        n += 1
        try:
            if '.' in s or ',' in s.replace(' ', ''):
                float(s.replace(',', '.'))
                saw_float = True
                saw_int = False
            else:
                int(s)
        except ValueError:
            return 'string'
        if n > 80:
            break
    if n == 0:
        return 'string'
    return 'double' if saw_float or not saw_int else 'int'


def _qgs_field(name, kind):
    """QGIS 3.38+ wants QMetaType; QVariant.Type QgsField() is deprecated."""
    type_name = {'double': 'double', 'int': 'integer', 'string': 'string'}[kind]
    try:
        qtype = {
            'double': QMetaType.Type.Double,
            'int': QMetaType.Type.Int,
            'string': QMetaType.Type.QString,
        }[kind]
        return QgsField(name, qtype, type_name)
    except Exception:
        qtype = {
            'double': QVariant.Double,
            'int': QVariant.Int,
            'string': QVariant.String,
        }[kind]
        return QgsField(name, qtype, type_name)


def _to_float(v):
    if v is None:
        return None
    s = str(v).strip().replace(',', '.')
    if s == '':
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _col_index(headers, name):
    if not name or name not in headers:
        return None
    return headers.index(name)


def _pt(x, y, z):
    return (x, y, 0.0 if z is None else z)


def normalize_p123(x1, y1, z1, x2, y2, z2, x3, y3, z3):
    """Canonical P1 (centre) and optional P2→P3 vector.

    Per row:
    1. P1 only — point, no vector.
    2. P1 and P2, no P3 — input is the vector P1→P2. Stored P2 is old P1,
       stored P3 is old P2, stored P1 is the midpoint.
    3. P1, P2 and P3 — unchanged. Point is P1, vector is P2→P3.
    If P1 is missing but P2 and P3 exist, P1 is the midpoint of P2→P3.
    """
    has1 = x1 is not None and y1 is not None
    has2 = x2 is not None and y2 is not None
    has3 = x3 is not None and y3 is not None
    if has1 and has2 and has3:
        return _pt(x1, y1, z1), _pt(x2, y2, z2), _pt(x3, y3, z3)
    if has1 and has2 and not has3:
        start = _pt(x1, y1, z1)
        end = _pt(x2, y2, z2)
        mid = (
            0.5 * (start[0] + end[0]),
            0.5 * (start[1] + end[1]),
            0.5 * (start[2] + end[2]),
        )
        return mid, start, end
    if has1:
        return _pt(x1, y1, z1), None, None
    if has2 and has3:
        start = _pt(x2, y2, z2)
        end = _pt(x3, y3, z3)
        mid = (
            0.5 * (start[0] + end[0]),
            0.5 * (start[1] + end[1]),
            0.5 * (start[2] + end[2]),
        )
        return mid, start, end
    return None


def build_pointz_layer(
    path, x_field, y_field, z_field, group_field, crs=None,
    p2x_field='', p2y_field='', p2z_field='',
    p3x_field='', p3y_field='', p3z_field='',
):
    encoding, delimiter, headers, data = sniff_csv(path)
    has_p1 = x_field in headers and y_field in headers
    has_p2 = p2x_field in headers and p2y_field in headers
    has_p3 = p3x_field in headers and p3y_field in headers
    if not has_p1 and not (has_p2 and has_p3):
        raise ValueError('Need P1 X/Y, or both P2 and P3 X/Y')
    crs = crs or site_crs()
    uri = 'PointZ?crs=%s' % (crs.authid() or 'EPSG:25831')
    name = os.path.splitext(os.path.basename(path))[0] or 'ARSYSplot_points'
    layer = QgsVectorLayer(uri, name, 'memory')
    if not layer.isValid():
        uri = 'PointZ?crs=WKT:%s' % crs.toWkt().replace(' ', '%20')
        layer = QgsVectorLayer(uri, name, 'memory')
    if not layer.isValid():
        raise ValueError('Could not create PointZ memory layer')

    samples = {h: [] for h in headers}
    for row in data[:120]:
        for i, h in enumerate(headers):
            if i < len(row):
                samples[h].append(row[i])

    fields = QgsFields()
    for key in (
        'p1x', 'p1y', 'p1z',
        'p2x', 'p2y', 'p2z',
        'p3x', 'p3y', 'p3z',
        'group',
    ):
        fields.append(_qgs_field(key, 'string' if key == 'group' else 'double'))
    used = {
        'p1x', 'p1y', 'p1z', 'p2x', 'p2y', 'p2z', 'p3x', 'p3y', 'p3z', 'group'
    }
    extra = []
    for h in headers:
        key = h
        n = 2
        while key in used:
            key = '%s_%d' % (h, n)
            n += 1
        used.add(key)
        kind = _field_kind(samples.get(h, []))
        extra.append((h, key, kind))
        fields.append(_qgs_field(key, kind))

    prov = layer.dataProvider()
    prov.addAttributes(list(fields))
    layer.updateFields()

    ix = _col_index(headers, x_field)
    iy = _col_index(headers, y_field)
    iz = _col_index(headers, z_field)
    i2x = _col_index(headers, p2x_field)
    i2y = _col_index(headers, p2y_field)
    i2z = _col_index(headers, p2z_field)
    i3x = _col_index(headers, p3x_field)
    i3y = _col_index(headers, p3y_field)
    i3z = _col_index(headers, p3z_field)
    ig = _col_index(headers, group_field)

    feats = []
    skipped = 0
    for row in data:
        def cell(i):
            return row[i] if i is not None and i < len(row) else ''

        x1 = _to_float(cell(ix))
        y1 = _to_float(cell(iy))
        z1 = _to_float(cell(iz))
        x2 = _to_float(cell(i2x))
        y2 = _to_float(cell(i2y))
        z2 = _to_float(cell(i2z))
        x3 = _to_float(cell(i3x))
        y3 = _to_float(cell(i3y))
        z3 = _to_float(cell(i3z))
        norm = normalize_p123(x1, y1, z1, x2, y2, z2, x3, y3, z3)
        if norm is None:
            skipped += 1
            continue
        p1, p2, p3 = norm
        x1, y1, z1 = p1
        if p2 is None:
            x2 = y2 = z2 = None
        else:
            x2, y2, z2 = p2
        if p3 is None:
            x3 = y3 = z3 = None
        else:
            x3, y3, z3 = p3
        g = str(cell(ig)).strip() if ig is not None else ''
        if not g:
            g = '(empty)'
        feat = QgsFeature(layer.fields())
        feat.setGeometry(QgsGeometry(QgsPoint(x1, y1, z1)))
        attrs = [x1, y1, z1, x2, y2, z2, x3, y3, z3, g]
        for src, _key, kind in extra:
            i = headers.index(src)
            raw = cell(i)
            if kind == 'double':
                attrs.append(_to_float(raw))
            elif kind == 'int':
                try:
                    attrs.append(int(str(raw).strip()))
                except ValueError:
                    attrs.append(None)
            else:
                attrs.append(str(raw) if raw is not None else '')
        feat.setAttributes(attrs)
        feats.append(feat)

    if not feats:
        raise ValueError('No plottable rows (need P1 X/Y, or both P2 and P3 X/Y)')
    prov.addFeatures(feats)
    layer.updateExtents()
    layer.setCustomProperty('arsysplotqgis', 'source')
    layer.setCustomProperty('arsysplotqgis_file', path)
    return layer, skipped


class ImportCsvDialog(QDialog):
    def __init__(self, parent=None, start_path=''):
        super().__init__(parent)
        self.setWindowTitle('Import XYZ CSV')
        self.path = start_path or ''
        self.headers = []
        self._data_ok = False

        self.lbl_file = QLabel('No file')
        self.cmb_x = QComboBox()
        self.cmb_y = QComboBox()
        self.cmb_z = QComboBox()
        self.cmb_p2x = QComboBox()
        self.cmb_p2y = QComboBox()
        self.cmb_p2z = QComboBox()
        self.cmb_p3x = QComboBox()
        self.cmb_p3y = QComboBox()
        self.cmb_p3z = QComboBox()
        self.cmb_g = QComboBox()
        self.cmb_g.addItem('(none)', '')

        hint = QLabel(
            'Three XYZ layouts (applied per row):\n'
            '1. P1 only — P1 is the point; no vector.\n'
            '2. P1 and P2 (no P3) — input is the vector P1→P2. '
            'Stored as P2 = old P1, P3 = old P2; P1 becomes the midpoint.\n'
            '3. P1, P2 and P3 — unchanged. P1 is the point; vector is P2→P3.'
        )
        hint.setWordWrap(True)
        hint.setStyleSheet('color:#888;')

        form = QFormLayout()
        form.addRow('File', self.lbl_file)
        form.addRow('P1 X', self.cmb_x)
        form.addRow('P1 Y', self.cmb_y)
        form.addRow('P1 Z', self.cmb_z)
        form.addRow('P2 X', self.cmb_p2x)
        form.addRow('P2 Y', self.cmb_p2y)
        form.addRow('P2 Z', self.cmb_p2z)
        form.addRow('P3 X', self.cmb_p3x)
        form.addRow('P3 Y', self.cmb_p3y)
        form.addRow('P3 Z', self.cmb_p3z)
        form.addRow('Group', self.cmb_g)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_open = buttons.addButton('Choose file…', QDialogButtonBox.ActionRole)
        btn_open.clicked.connect(self._choose)
        btn_sample = buttons.addButton('Sample data', QDialogButtonBox.ActionRole)
        btn_sample.setToolTip(html_tooltip(
            'Load bundled **sample.csv**. Works from ZIP or repository.',
        ))
        btn_sample.clicked.connect(self._use_sample)
        buttons.accepted.connect(self._ok)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(hint)
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.buttons = buttons
        if self.path:
            self._load(self.path)

    def _start_dir(self):
        if self.path:
            return os.path.dirname(self.path)
        return PLUGIN_DIR

    def _choose(self):
        path, _flt = QFileDialog.getOpenFileName(
            self, 'CSV', self._start_dir(),
            'CSV (*.csv *.txt *.tsv);;All files (*)'
        )
        if path:
            self._load(path)

    def _use_sample(self):
        if not os.path.isfile(SAMPLE_CSV):
            QMessageBox.warning(
                self, 'Import',
                'sample.csv was not found next to the plugin.'
            )
            return
        self._load(SAMPLE_CSV)

    def _load(self, path):
        try:
            _enc, _d, headers, _data = sniff_csv(path)
        except Exception as exc:
            QMessageBox.warning(self, 'Import', str(exc))
            return
        self.path = path
        self.headers = headers
        self.lbl_file.setText(os.path.basename(path))
        self._fill_optional(self.cmb_x, headers, X_HINTS)
        self._fill_optional(self.cmb_y, headers, Y_HINTS)
        self._fill_optional(self.cmb_z, headers, Z_HINTS)
        self._fill_optional(self.cmb_p2x, headers, P2X_HINTS)
        self._fill_optional(self.cmb_p2y, headers, P2Y_HINTS)
        self._fill_optional(self.cmb_p2z, headers, P2Z_HINTS)
        self._fill_optional(self.cmb_p3x, headers, P3X_HINTS)
        self._fill_optional(self.cmb_p3y, headers, P3Y_HINTS)
        self._fill_optional(self.cmb_p3z, headers, P3Z_HINTS)
        self.cmb_g.clear()
        self.cmb_g.addItem('(none)', '')
        for h in headers:
            self.cmb_g.addItem(h, h)
        g = _guess(headers, G_HINTS)
        idx = self.cmb_g.findText(g)
        if idx >= 0:
            self.cmb_g.setCurrentIndex(idx)
        self._data_ok = True

    def _fill_optional(self, cmb, headers, hints):
        cmb.blockSignals(True)
        cmb.clear()
        cmb.addItem('(none)', '')
        for h in headers:
            cmb.addItem(h, h)
        found = _guess_optional(headers, hints)
        if found:
            idx = cmb.findData(found)
            cmb.setCurrentIndex(idx if idx >= 0 else 0)
        else:
            cmb.setCurrentIndex(0)
        cmb.blockSignals(False)

    def _ok(self):
        if not self.path or not self._data_ok:
            QMessageBox.warning(self, 'Import', 'Choose a CSV first.')
            return
        has_p1 = bool(self.cmb_x.currentData() and self.cmb_y.currentData())
        has_p2 = bool(self.cmb_p2x.currentData() and self.cmb_p2y.currentData())
        has_p3 = bool(self.cmb_p3x.currentData() and self.cmb_p3y.currentData())
        if not has_p1 and not (has_p2 and has_p3):
            QMessageBox.warning(
                self, 'Import',
                'Map P1 X/Y, or both P2 and P3 X/Y.'
            )
            return
        self.accept()

    def result_mapping(self):
        if not self.path or not self._data_ok:
            return None
        return {
            'path': self.path,
            'x': self.cmb_x.currentData() or '',
            'y': self.cmb_y.currentData() or '',
            'z': self.cmb_z.currentData() or '',
            'p2x': self.cmb_p2x.currentData() or '',
            'p2y': self.cmb_p2y.currentData() or '',
            'p2z': self.cmb_p2z.currentData() or '',
            'p3x': self.cmb_p3x.currentData() or '',
            'p3y': self.cmb_p3y.currentData() or '',
            'p3z': self.cmb_p3z.currentData() or '',
            'group': self.cmb_g.currentData() or '',
        }
