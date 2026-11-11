# -*- coding: utf-8 -*-
"""CSV / spreadsheet → PointZ memory layer (P1 point, optional P2→P3 vector).

Spreadsheets (.xlsx / .ods / .xls) use GDAL/OGR drivers shipped with QGIS —
no extra pip packages.
"""
import csv
import os

from qgis.core import (
    QgsFeature,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsPoint,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QMetaType, QVariant
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
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


SPREADSHEET_EXT = ('.xlsx', '.ods', '.xls')


def is_spreadsheet_path(path):
    return bool(path) and os.path.splitext(path)[1].lower() in SPREADSHEET_EXT


def spreadsheet_drivers():
    """Return OGR driver names available for spreadsheets (subset of XLSX/ODS/XLS)."""
    try:
        from osgeo import ogr
    except ImportError as exc:
        raise ValueError(
            'GDAL/OGR Python bindings are missing (expected with QGIS).'
        ) from exc
    found = []
    for name in ('XLSX', 'ODS', 'XLS'):
        if ogr.GetDriverByName(name) is not None:
            found.append(name)
    return found


def list_spreadsheet_sheets(path):
    """Sheet names via OGR (one OGR layer per sheet)."""
    try:
        from osgeo import gdal, ogr
    except ImportError as exc:
        raise ValueError(
            'GDAL/OGR Python bindings are missing (expected with QGIS).'
        ) from exc
    if not os.path.isfile(path):
        raise ValueError('File not found: %s' % path)
    ext = os.path.splitext(path)[1].lower()
    need = {'.xlsx': 'XLSX', '.ods': 'ODS', '.xls': 'XLS'}.get(ext)
    if need and ogr.GetDriverByName(need) is None:
        raise ValueError(
            'This QGIS build has no OGR %s driver — cannot open %s.'
            % (need, ext)
        )
    # Prefer first row as field names (Lite / CSV parity).
    for key in ('OGR_XLSX_HEADERS', 'OGR_ODS_HEADERS', 'OGR_XLS_HEADERS'):
        gdal.SetConfigOption(key, 'FORCE')
    ds = ogr.Open(path, 0)
    if ds is None:
        raise ValueError('OGR could not open spreadsheet: %s' % path)
    try:
        names = []
        for i in range(ds.GetLayerCount()):
            lyr = ds.GetLayer(i)
            if lyr is not None:
                names.append(lyr.GetName())
        if not names:
            raise ValueError('Spreadsheet has no sheets')
        return names
    finally:
        ds = None


def sniff_spreadsheet(path, sheet=None):
    """Return ``(headers, data_rows, sheet_name)`` using OGR XLSX/ODS/XLS."""
    try:
        from osgeo import gdal, ogr
    except ImportError as exc:
        raise ValueError(
            'GDAL/OGR Python bindings are missing (expected with QGIS).'
        ) from exc
    for key in ('OGR_XLSX_HEADERS', 'OGR_ODS_HEADERS', 'OGR_XLS_HEADERS'):
        gdal.SetConfigOption(key, 'FORCE')
    ds = ogr.Open(path, 0)
    if ds is None:
        raise ValueError('OGR could not open spreadsheet: %s' % path)
    try:
        layer = None
        if sheet:
            layer = ds.GetLayerByName(sheet)
        if layer is None:
            layer = ds.GetLayer(0)
        if layer is None:
            raise ValueError('No sheet found in spreadsheet')
        sheet_name = layer.GetName()
        defn = layer.GetLayerDefn()
        headers = []
        for i in range(defn.GetFieldCount()):
            name = defn.GetFieldDefn(i).GetNameRef()
            headers.append(str(name).strip() or 'col%d' % i)
        if not headers:
            raise ValueError('Sheet "%s" has no columns' % sheet_name)
        data = []
        layer.ResetReading()
        feat = layer.GetNextFeature()
        while feat is not None:
            row = []
            for i in range(len(headers)):
                val = feat.GetField(i)
                if val is None:
                    row.append('')
                else:
                    row.append(str(val))
            data.append(row)
            feat = layer.GetNextFeature()
        return headers, data, sheet_name
    finally:
        ds = None


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


def build_pointz_from_table(
    headers, data, x_field, y_field, z_field, group_field, crs=None,
    p2x_field='', p2y_field='', p2z_field='',
    p3x_field='', p3y_field='', p3z_field='',
    source_path='', layer_name='',
):
    """Build PointZ memory layer from in-memory header + row strings."""
    has_p1 = x_field in headers and y_field in headers
    has_p2 = p2x_field in headers and p2y_field in headers
    has_p3 = p3x_field in headers and p3y_field in headers
    if not has_p1 and not (has_p2 and has_p3):
        raise ValueError('Need P1 X/Y, or both P2 and P3 X/Y')
    crs = crs or site_crs()
    uri = 'PointZ?crs=%s' % (crs.authid() or 'EPSG:25831')
    name = (
        layer_name
        or (os.path.splitext(os.path.basename(source_path))[0] if source_path else '')
        or 'ARSYSplot_points'
    )
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
    if source_path:
        layer.setCustomProperty('arsysplotqgis_file', source_path)
    return layer, skipped


def build_pointz_layer(
    path, x_field, y_field, z_field, group_field, crs=None,
    p2x_field='', p2y_field='', p2z_field='',
    p3x_field='', p3y_field='', p3z_field='',
    sheet='',
):
    """CSV or spreadsheet path → PointZ memory layer."""
    if is_spreadsheet_path(path):
        headers, data, sheet_name = sniff_spreadsheet(path, sheet or None)
        name = '%s_%s' % (
            os.path.splitext(os.path.basename(path))[0] or 'sheet',
            sheet_name,
        )
    else:
        _enc, _delim, headers, data = sniff_csv(path)
        name = os.path.splitext(os.path.basename(path))[0] or 'ARSYSplot_points'
    return build_pointz_from_table(
        headers, data, x_field, y_field, z_field, group_field, crs=crs,
        p2x_field=p2x_field, p2y_field=p2y_field, p2z_field=p2z_field,
        p3x_field=p3x_field, p3y_field=p3y_field, p3z_field=p3z_field,
        source_path=path, layer_name=name,
    )


class ImportCsvDialog(QDialog):
    """Import CSV or spreadsheet (OGR XLSX/ODS/XLS) with column mapping."""

    # Explicit source kinds (Lite-style): user picks type, then browses that filter.
    KIND_CSV = 'csv'
    KIND_SHEET = 'sheet'

    def __init__(self, parent=None, start_path=''):
        super().__init__(parent)
        self.setWindowTitle('Import XYZ data')
        self.path = start_path or ''
        self.headers = []
        self._rows = []
        self._sheet = ''
        self._data_ok = False
        self._kind = self.KIND_CSV

        steps = QLabel(
            '<b>1.</b> Choose the file type &nbsp;→&nbsp; '
            '<b>2.</b> Open the file &nbsp;→&nbsp; '
            '<b>3.</b> (Spreadsheets) pick the sheet &nbsp;→&nbsp; '
            '<b>4.</b> Map P1 / P2 / P3 / Group &nbsp;→&nbsp; OK'
        )
        steps.setWordWrap(True)

        self.cmb_kind = QComboBox()
        self.cmb_kind.addItem('CSV / text table (.csv .txt .tsv)', self.KIND_CSV)
        self.cmb_kind.addItem(
            'Spreadsheet — Excel / LibreOffice (.xlsx .ods .xls)', self.KIND_SHEET
        )
        self.cmb_kind.currentIndexChanged.connect(self._on_kind_changed)
        self.lbl_kind_hint = QLabel('')
        self.lbl_kind_hint.setWordWrap(True)
        self.lbl_kind_hint.setStyleSheet('color:#888;')

        self.lbl_file = QLabel('No file selected')
        self.lbl_file.setStyleSheet('font-weight:600;')
        self.btn_browse = QPushButton('Choose CSV file…')
        self.btn_browse.clicked.connect(self._choose)
        file_wrap = QWidget()
        file_row = QHBoxLayout(file_wrap)
        file_row.setContentsMargins(0, 0, 0, 0)
        file_row.addWidget(self.lbl_file, 1)
        file_row.addWidget(self.btn_browse)

        self.lbl_sheet = QLabel('Sheet')
        self.cmb_sheet = QComboBox()
        self.cmb_sheet.setEnabled(False)
        self.cmb_sheet.currentIndexChanged.connect(self._on_sheet_changed)
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
            'Column layouts (per row):\n'
            '1. P1 only — point; no vector.\n'
            '2. P1 + P2 (no P3) — file vector P1→P2; stored as midpoint + P2→P3.\n'
            '3. P1 + P2 + P3 — unchanged (point = P1, vector = P2→P3).\n'
            'Spreadsheets use QGIS GDAL/OGR (no extra install).'
        )
        hint.setWordWrap(True)
        hint.setStyleSheet('color:#888;')

        form = QFormLayout()
        form.addRow('File type', self.cmb_kind)
        form.addRow('', self.lbl_kind_hint)
        form.addRow('File', file_wrap)
        form.addRow(self.lbl_sheet, self.cmb_sheet)
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

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btn_sample = buttons.addButton(
            'Sample data', QDialogButtonBox.ButtonRole.ActionRole
        )
        btn_sample.setToolTip(html_tooltip(
            'Load bundled **sample.csv** (switches type to CSV).',
        ))
        btn_sample.clicked.connect(self._use_sample)
        buttons.accepted.connect(self._ok)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(steps)
        layout.addLayout(form)
        layout.addWidget(hint)
        layout.addWidget(buttons)
        self.buttons = buttons
        self._on_kind_changed()
        if self.path:
            # Infer kind from extension when opened with a start path.
            if is_spreadsheet_path(self.path):
                idx = self.cmb_kind.findData(self.KIND_SHEET)
                if idx >= 0:
                    self.cmb_kind.setCurrentIndex(idx)
            self._load(self.path)

    def _on_kind_changed(self, _index=None):
        self._kind = self.cmb_kind.currentData() or self.KIND_CSV
        if self._kind == self.KIND_SHEET:
            self.btn_browse.setText('Choose spreadsheet…')
            self.lbl_kind_hint.setText(
                'Excel (.xlsx / .xls) or LibreOffice (.ods). '
                'After opening, select which sheet contains the XYZ columns.'
            )
            self.lbl_sheet.setEnabled(True)
            # Sheet combo stays disabled until a file is loaded.
        else:
            self.btn_browse.setText('Choose CSV file…')
            self.lbl_kind_hint.setText(
                'Plain text table with a header row. '
                'Delimiter (comma / semicolon / tab / pipe) is detected automatically.'
            )
            self.cmb_sheet.blockSignals(True)
            self.cmb_sheet.clear()
            self.cmb_sheet.addItem('(not used for CSV)', '')
            self.cmb_sheet.setEnabled(False)
            self.cmb_sheet.blockSignals(False)
            self.lbl_sheet.setEnabled(False)

    def _file_dialog_filter(self):
        if self._kind == self.KIND_SHEET:
            return (
                'Spreadsheets (*.xlsx *.ods *.xls);;'
                'Excel (*.xlsx *.xls);;'
                'OpenDocument (*.ods);;'
                'All files (*)'
            )
        return (
            'CSV / text (*.csv *.txt *.tsv);;'
            'All files (*)'
        )

    def _start_dir(self):
        if self.path:
            return os.path.dirname(self.path)
        return PLUGIN_DIR

    def _choose(self):
        title = (
            'Spreadsheet (Excel / ODS)'
            if self._kind == self.KIND_SHEET
            else 'CSV / text table'
        )
        path, _flt = QFileDialog.getOpenFileName(
            self, title, self._start_dir(), self._file_dialog_filter()
        )
        if not path:
            return
        # If the user picked the “wrong” family, switch kind to match the file.
        if is_spreadsheet_path(path) and self._kind != self.KIND_SHEET:
            idx = self.cmb_kind.findData(self.KIND_SHEET)
            if idx >= 0:
                self.cmb_kind.blockSignals(True)
                self.cmb_kind.setCurrentIndex(idx)
                self.cmb_kind.blockSignals(False)
                self._on_kind_changed()
        elif not is_spreadsheet_path(path) and self._kind == self.KIND_SHEET:
            idx = self.cmb_kind.findData(self.KIND_CSV)
            if idx >= 0:
                self.cmb_kind.blockSignals(True)
                self.cmb_kind.setCurrentIndex(idx)
                self.cmb_kind.blockSignals(False)
                self._on_kind_changed()
        self._load(path)

    def _use_sample(self):
        if not os.path.isfile(SAMPLE_CSV):
            QMessageBox.warning(
                self, 'Import',
                'sample.csv was not found next to the plugin.'
            )
            return
        idx = self.cmb_kind.findData(self.KIND_CSV)
        if idx >= 0:
            self.cmb_kind.setCurrentIndex(idx)
        self._load(SAMPLE_CSV)

    def _load(self, path):
        try:
            if is_spreadsheet_path(path):
                sheets = list_spreadsheet_sheets(path)
                self.path = path
                self.cmb_sheet.blockSignals(True)
                self.cmb_sheet.clear()
                for name in sheets:
                    self.cmb_sheet.addItem(name, name)
                self.cmb_sheet.setEnabled(len(sheets) > 0)
                self.cmb_sheet.setCurrentIndex(0)
                self.cmb_sheet.blockSignals(False)
                sheet = self.cmb_sheet.currentData() or sheets[0]
                headers, data, sheet_name = sniff_spreadsheet(path, sheet)
                self._sheet = sheet_name
                self._apply_headers(path, headers, data, sheet_name)
            else:
                self.cmb_sheet.blockSignals(True)
                self.cmb_sheet.clear()
                self.cmb_sheet.addItem('(CSV)', '')
                self.cmb_sheet.setEnabled(False)
                self.cmb_sheet.blockSignals(False)
                _enc, _d, headers, data = sniff_csv(path)
                self._sheet = ''
                self._apply_headers(path, headers, data, None)
        except Exception as exc:
            QMessageBox.warning(self, 'Import', str(exc))
            return

    def _on_sheet_changed(self, _index):
        if not self.path or not is_spreadsheet_path(self.path):
            return
        sheet = self.cmb_sheet.currentData()
        if not sheet:
            return
        try:
            headers, data, sheet_name = sniff_spreadsheet(self.path, sheet)
            self._apply_headers(self.path, headers, data, sheet_name)
        except Exception as exc:
            QMessageBox.warning(self, 'Import', str(exc))

    def _apply_headers(self, path, headers, data, sheet_name):
        self.path = path
        self.headers = headers
        self._rows = data
        self._sheet = sheet_name or ''
        label = os.path.basename(path)
        if sheet_name:
            label = '%s · %s' % (label, sheet_name)
        self.lbl_file.setText(label)
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
            QMessageBox.warning(self, 'Import', 'Choose a file first.')
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
            'sheet': self._sheet or (self.cmb_sheet.currentData() or ''),
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
