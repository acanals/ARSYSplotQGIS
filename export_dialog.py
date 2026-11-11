# -*- coding: utf-8 -*-
"""Export dialog: PNG/SVG, paper, 1∶N scale, title, resolution."""
from qgis.PyQt.QtCore import QRect, Qt
from qgis.PyQt.QtGui import QColor, QFont, QPainter
from qgis.PyQt.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

SCREEN_DPI = 96.0

# ISO paper sizes in millimetres (portrait).
PAPER_MM = {
    'A5': (148.0, 210.0),
    'A4': (210.0, 297.0),
    'A3': (297.0, 420.0),
}

NICE_SCALES = (
    1, 2, 5, 10, 15, 20, 25, 30, 40, 50, 75, 100, 150, 200, 250,
    500, 750, 1000, 1500, 2000, 2500, 5000, 10000, 20000, 50000,
)

# Default level-label size (isoline values), typographic points.
DEFAULT_LEVEL_LABEL_PT = 9

# Default custom 1∶N (user can change freely; auto mode ignores this).
DEFAULT_SCALE_N = 20

# Paper plot-area margins — keep in sync with ARSYSplotLite ``layoutPlot``.
LAYOUT_MARGIN = 12.0
LAYOUT_AXIS_LABEL = 8.0
LAYOUT_TICK_PAD = 5.0
LAYOUT_SCALE_BAR_H = 10.0
LAYOUT_TITLE_H = 8.0
LAYOUT_SUB_H = 5.0
LAYOUT_HEADER_GAP = 4.0
LAYOUT_TOP_EXTRA = 2.0
LAYOUT_LEGEND_W = 38.0
LAYOUT_LEGEND_GAP = 6.0


def is_light_color(color):
    return (
        0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()
    ) >= 140


def png_dpm(dpi):
    """Pixels per metre for the PNG pHYs chunk (print resolution)."""
    return int(round(float(dpi) / 0.0254))


def apply_png_dpi(image, dpi):
    dpm = png_dpm(dpi)
    image.setDotsPerMeterX(dpm)
    image.setDotsPerMeterY(dpm)


def scale_for_dpi(dpi):
    return max(1.0, float(dpi) / SCREEN_DPI)


def mm_to_px(mm, dpi):
    return float(mm) * float(dpi) / 25.4


def mm_to_px_i(mm, dpi):
    return max(1, int(round(mm_to_px(mm, dpi))))


def pt_to_px(pt, dpi):
    return max(8, int(round(float(pt) * float(dpi) / 72.0)))


def paper_size_mm(fmt, orientation):
    """Return ``(width_mm, height_mm)`` for ISO paper + orientation."""
    base = PAPER_MM.get(str(fmt or 'A4').upper(), PAPER_MM['A4'])
    w, h = float(base[0]), float(base[1])
    if str(orientation or '').lower().startswith('land'):
        w, h = h, w
    return w, h


def pick_nice_scale(data_w_m, data_h_m, avail_w_mm, avail_h_mm):
    """Smallest nice 1∶N that fits the data into the available plot area."""
    dw = max(float(data_w_m), 1e-9)
    dh = max(float(data_h_m), 1e-9)
    aw = max(float(avail_w_mm), 1.0)
    ah = max(float(avail_h_mm), 1.0)
    # metres × 1000 / N ≤ available mm  →  N ≥ metres × 1000 / avail
    need = max(dw * 1000.0 / aw, dh * 1000.0 / ah)
    for n in NICE_SCALES:
        if n >= need - 1e-9:
            return int(n)
    return int(max(NICE_SCALES[-1], math_ceil(need)))


def math_ceil(x):
    import math
    return int(math.ceil(float(x)))


def resolve_scale_n(mode, custom_n, data_w_m, data_h_m, avail_w_mm, avail_h_mm):
    if str(mode or '').lower() == 'custom':
        try:
            n = int(round(float(custom_n)))
        except (TypeError, ValueError):
            n = DEFAULT_SCALE_N
        return max(1, n)
    return pick_nice_scale(data_w_m, data_h_m, avail_w_mm, avail_h_mm)


def plot_avail_mm(paper_w_mm, paper_h_mm, title='', subtitle='',
                  side_reserve_mm=0.0, below_reserve_mm=0.0):
    """Available data-frame area on paper (Lite ``layoutPlot`` parity).

    ``side_reserve_mm`` / ``below_reserve_mm`` cover colourbar or group legend
    beyond the base Lite legend slot (pass 0 when none).
    """
    title_h = LAYOUT_TITLE_H if (title or '').strip() else 0.0
    sub_h = LAYOUT_SUB_H if (subtitle or '').strip() else 0.0
    header_gap = LAYOUT_HEADER_GAP if (title_h or sub_h) else 0.0
    left = LAYOUT_MARGIN + LAYOUT_AXIS_LABEL + LAYOUT_TICK_PAD
    right = (
        float(paper_w_mm) - LAYOUT_MARGIN - float(side_reserve_mm or 0.0)
    )
    top = (
        LAYOUT_MARGIN + title_h + sub_h + header_gap + LAYOUT_TOP_EXTRA
    )
    bottom = (
        float(paper_h_mm) - LAYOUT_MARGIN - LAYOUT_AXIS_LABEL
        - LAYOUT_TICK_PAD - LAYOUT_SCALE_BAR_H - float(below_reserve_mm or 0.0)
    )
    return (
        max(40.0, right - left),
        max(40.0, bottom - top),
        {
            'left': left,
            'top': top,
            'margin': LAYOUT_MARGIN,
            'title_h': title_h,
            'sub_h': sub_h,
            'header_gap': header_gap,
        },
    )


def _dialog_stylesheet(theme):
    """Explicit radio indicators so QGIS Dark does not hide the circle."""
    t = theme or {}
    ink = t.get('ink', '#1a1816')
    bg = t.get('bg', '#f3f0ea')
    btn = t.get('btn', '#e8e2d8')
    border = t.get('btn_border', '#c8c0b4')
    accent = t.get('accent', '#d97726')
    accent_border = t.get('accent_border', '#f0a15a')
    muted = t.get('disabled', '#9a9288')
    return (
        'QDialog { background:%(bg)s; color:%(ink)s; }'
        'QLabel { color:%(ink)s; background:transparent; }'
        'QLineEdit, QSpinBox, QComboBox {'
        '  background:%(btn)s; color:%(ink)s;'
        '  border:1px solid %(border)s; padding:2px 4px; }'
        'QPushButton { background:%(btn)s; color:%(ink)s;'
        '  border:1px solid %(border)s; border-radius:6px; padding:4px 10px; }'
        'QRadioButton { color:%(ink)s; spacing:6px; background:transparent; }'
        'QRadioButton::indicator {'
        '  width:12px; height:12px; border-radius:6px;'
        '  border:1px solid %(ink)s; background:%(btn)s; }'
        'QRadioButton::indicator:hover { border-color:%(accent)s; }'
        'QRadioButton::indicator:checked {'
        '  background:%(accent)s; border:1px solid %(accent_border)s; }'
        'QRadioButton::indicator:disabled {'
        '  border-color:%(muted)s; background:%(bg)s; }'
        'QCheckBox { color:%(ink)s; spacing:6px; background:transparent; }'
        'QCheckBox::indicator {'
        '  width:12px; height:12px; border-radius:2px;'
        '  border:1px solid %(ink)s; background:%(btn)s; }'
        'QCheckBox::indicator:checked {'
        '  background:%(accent)s; border:1px solid %(accent_border)s; }'
    ) % {
        'ink': ink, 'bg': bg, 'btn': btn, 'border': border,
        'accent': accent, 'accent_border': accent_border, 'muted': muted,
    }


def header_height(title, subtitle, scale):
    h = 0
    if (title or '').strip():
        h += int(28 * scale)
    if (subtitle or '').strip():
        h += int(18 * scale)
    if h:
        h += int(16 * scale)
    return h


def draw_header(painter, width, title, subtitle, bg, scale):
    ink = QColor('#1a1816') if is_light_color(bg) else QColor('#fff5e6')
    y = int(8 * scale)
    title = (title or '').strip()
    subtitle = (subtitle or '').strip()
    if title:
        font = QFont()
        font.setPixelSize(max(12, int(16 * scale)))
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(ink)
        painter.drawText(
            QRect(int(12 * scale), y, width - int(24 * scale), int(24 * scale)),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            title,
        )
        y += int(26 * scale)
    if subtitle:
        font = QFont()
        font.setPixelSize(max(10, int(11 * scale)))
        painter.setFont(font)
        painter.setPen(ink)
        painter.drawText(
            QRect(int(12 * scale), y, width - int(24 * scale), int(16 * scale)),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            subtitle,
        )


class ExportImageDialog(QDialog):
    """Paper export: PNG or SVG, A5/A4/A3, auto/custom 1∶N, dpi for PNG."""

    def __init__(self, parent=None, title='', subtitle='', bg=None,
                 label_size_pt=None, density_on=False,
                 data_w_m=None, data_h_m=None, theme=None,
                 reserve_legend=False):
        super().__init__(parent)
        win_name = (title or '').strip()
        self.setWindowTitle(
            ('Export · %s' % win_name) if win_name else 'Export plot'
        )
        self._density_on = bool(density_on)
        self._reserve_legend = bool(reserve_legend)
        self._data_w_m = float(data_w_m) if data_w_m else 0.0
        self._data_h_m = float(data_h_m) if data_h_m else 0.0
        self._theme = dict(theme) if theme else {}
        self._bg = QColor(bg if bg is not None else '#ffffff')
        if not self._bg.isValid():
            self._bg = QColor('#ffffff')
        if self._theme:
            self.setStyleSheet(_dialog_stylesheet(self._theme))

        form = QFormLayout()

        # Format
        fmt_row = QHBoxLayout()
        self.rad_png = QRadioButton('PNG')
        self.rad_svg = QRadioButton('SVG')
        self.rad_png.setChecked(True)
        fmt_grp = QButtonGroup(self)
        fmt_grp.addButton(self.rad_png)
        fmt_grp.addButton(self.rad_svg)
        fmt_row.addWidget(self.rad_png)
        fmt_row.addWidget(self.rad_svg)
        fmt_row.addStretch(1)
        form.addRow('Format', fmt_row)

        # Paper + orientation
        self.cmb_paper = QComboBox()
        for pid in ('A5', 'A4', 'A3'):
            self.cmb_paper.addItem(pid, pid)
        self.cmb_paper.setCurrentIndex(1)
        orient_row = QHBoxLayout()
        self.rad_portrait = QRadioButton('Portrait')
        self.rad_landscape = QRadioButton('Landscape')
        self.rad_landscape.setChecked(True)
        orient_grp = QButtonGroup(self)
        orient_grp.addButton(self.rad_portrait)
        orient_grp.addButton(self.rad_landscape)
        orient_row.addWidget(self.rad_portrait)
        orient_row.addWidget(self.rad_landscape)
        orient_row.addStretch(1)
        paper_wrap = QVBoxLayout()
        paper_wrap.setContentsMargins(0, 0, 0, 0)
        paper_wrap.setSpacing(4)
        paper_wrap.addWidget(self.cmb_paper)
        paper_wrap.addLayout(orient_row)
        self.lbl_paper_info = QLabel('')
        muted0 = self._theme.get('disabled', '#888888')
        self.lbl_paper_info.setStyleSheet('color:%s;' % muted0)
        paper_wrap.addWidget(self.lbl_paper_info)
        paper_w = QWidget()
        paper_w.setLayout(paper_wrap)
        form.addRow('Paper', paper_w)

        # Scale
        scale_col = QVBoxLayout()
        scale_col.setContentsMargins(0, 0, 0, 0)
        scale_col.setSpacing(4)
        scale_row = QHBoxLayout()
        self.rad_scale_auto = QRadioButton('Automatic (fit paper)')
        self.rad_scale_custom = QRadioButton('Custom 1∶N')
        self.rad_scale_auto.setChecked(True)
        scale_grp = QButtonGroup(self)
        scale_grp.addButton(self.rad_scale_auto)
        scale_grp.addButton(self.rad_scale_custom)
        scale_row.addWidget(self.rad_scale_auto)
        scale_row.addWidget(self.rad_scale_custom)
        scale_row.addStretch(1)
        scale_col.addLayout(scale_row)
        n_row = QHBoxLayout()
        n_row.addWidget(QLabel('N ='))
        self.spn_scale_n = QSpinBox()
        self.spn_scale_n.setRange(1, 100000)
        self.spn_scale_n.setValue(DEFAULT_SCALE_N)
        self.spn_scale_n.setEnabled(False)
        self.spn_scale_n.setMinimumHeight(28)
        self.spn_scale_n.setMinimumWidth(100)
        n_row.addWidget(self.spn_scale_n)
        n_row.addStretch(1)
        scale_col.addLayout(n_row)
        self.lbl_scale_hint = QLabel('')
        self.lbl_scale_hint.setWordWrap(True)
        self.lbl_scale_hint.setMaximumHeight(52)
        muted = self._theme.get('disabled', '#888888')
        self.lbl_scale_hint.setStyleSheet('color:%s;' % muted)
        scale_col.addWidget(self.lbl_scale_hint)
        scale_w = QWidget()
        scale_w.setLayout(scale_col)
        scale_w.setMinimumHeight(96)
        form.addRow('Scale', scale_w)

        # Title / subtitle / background
        self.ed_title = QLineEdit(title or '')
        self.ed_sub = QLineEdit(subtitle or '')
        self.btn_bg = QPushButton()
        self.btn_bg.setFixedSize(72, 24)
        self.btn_bg.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_bg.clicked.connect(self._pick_bg)
        self._sync_bg_btn()
        bg_row = QHBoxLayout()
        bg_row.setContentsMargins(0, 0, 0, 0)
        bg_row.addWidget(self.btn_bg)
        bg_row.addWidget(QLabel('Click to choose'), 1)

        self.chk_legend = QCheckBox('Include legend')
        self.chk_legend.setChecked(True)
        self.chk_legend.setToolTip(
            'Group legend beside or under the drawing (auto placement). '
            'Density colour bar is separate and stays when density is on.'
        )
        self.chk_legend.toggled.connect(self._sync_scale_hint)

        form.addRow('Title', self.ed_title)
        form.addRow('Subtitle', self.ed_sub)
        form.addRow('Legend', self.chk_legend)
        form.addRow('Background', bg_row)

        try:
            pt0 = int(label_size_pt) if label_size_pt is not None else DEFAULT_LEVEL_LABEL_PT
        except (TypeError, ValueError):
            pt0 = DEFAULT_LEVEL_LABEL_PT
        self.spn_label_pt = QSpinBox()
        self.spn_label_pt.setRange(6, 36)
        self.spn_label_pt.setSingleStep(1)
        self.spn_label_pt.setValue(max(6, min(36, pt0)))
        self.spn_label_pt.setSuffix(' pt')
        self.spn_label_pt.setToolTip(
            'Size of isoline level labels on the figure (typographic points).'
        )
        if self._density_on:
            form.addRow('Level labels', self.spn_label_pt)
        else:
            self.spn_label_pt.hide()

        self.cmb_dpi = QComboBox()
        for dpi, label in (
            (96, '96 dpi · screen'),
            (150, '150 dpi · draft print'),
            (300, '300 dpi · print'),
            (600, '600 dpi · high'),
        ):
            self.cmb_dpi.addItem(label, dpi)
        self.cmb_dpi.setCurrentIndex(2)
        form.addRow('Resolution', self.cmb_dpi)

        if self._density_on:
            hint = QLabel(
                'True-scale paper figure (data frame). '
                'PNG uses the chosen dpi; SVG is vector (dpi still drives density sampling). '
                'Scale auto picks a nice 1∶N; custom sets N. '
                'The scale bar prefers 50 cm; adapts if that would be '
                'too small or large on paper.'
            )
        else:
            hint = QLabel(
                'True-scale paper figure (data frame). '
                'PNG uses the chosen dpi; SVG is vector. '
                'Scale auto picks a nice 1∶N; custom sets N. '
                'The scale bar prefers 50 cm; adapts if that would be '
                'too small or large on paper.'
            )
        hint.setWordWrap(True)
        hint.setStyleSheet('color:%s;' % muted0)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(hint)
        layout.addWidget(buttons)

        self.rad_png.toggled.connect(self._sync_format_fields)
        self.rad_svg.toggled.connect(self._sync_format_fields)
        self.rad_scale_auto.toggled.connect(self._sync_scale_fields)
        self.rad_scale_custom.toggled.connect(self._sync_scale_fields)
        self.cmb_paper.currentIndexChanged.connect(self._sync_paper_info)
        self.rad_portrait.toggled.connect(self._sync_paper_info)
        self.rad_landscape.toggled.connect(self._sync_paper_info)
        self.spn_scale_n.valueChanged.connect(self._sync_scale_hint)
        self.ed_title.textChanged.connect(self._sync_scale_hint)
        self.ed_sub.textChanged.connect(self._sync_scale_hint)
        self._sync_format_fields()
        self._sync_scale_fields()
        self._sync_paper_info()
        self.setMinimumSize(500, 560 if self._density_on else 520)
        self.resize(520, 600 if self._density_on else 560)

    def _sync_bg_btn(self):
        self.btn_bg.setStyleSheet(
            'background:%s; border:1px solid #888; border-radius:4px;'
            % self._bg.name()
        )
        self.btn_bg.setText(self._bg.name())

    def _pick_bg(self):
        color = QColorDialog.getColor(self._bg, self, 'Background colour')
        if color.isValid():
            self._bg = QColor(color)
            self._sync_bg_btn()

    def _sync_format_fields(self, *_args):
        # SVG is vector; dpi still useful for density raster sampling.
        svg = self.rad_svg.isChecked()
        self.cmb_dpi.setEnabled(True)
        tip = (
            'PNG: output pixel density. SVG: density heatmap sampling only.'
            if svg else
            'PNG pixel density (print resolution).'
        )
        self.cmb_dpi.setToolTip(tip)

    def _sync_scale_fields(self, *_args):
        self.spn_scale_n.setEnabled(self.rad_scale_custom.isChecked())
        self._sync_scale_hint()

    def _sync_paper_info(self, *_args):
        fmt = self.cmb_paper.currentData() or 'A4'
        orient = 'landscape' if self.rad_landscape.isChecked() else 'portrait'
        w, h = paper_size_mm(fmt, orient)
        self.lbl_paper_info.setText('%.0f × %.0f mm' % (w, h))
        self._sync_scale_hint()

    def _avail_plot_mm(self):
        """Plot area for the fit-paper hint (Lite layoutPlot parity).

        Legend placement is smart (side or below); the hint uses full width so
        1∶N is not biased toward a side column.
        """
        fmt = self.cmb_paper.currentData() or 'A4'
        orient = 'landscape' if self.rad_landscape.isChecked() else 'portrait'
        paper_w, paper_h = paper_size_mm(fmt, orient)
        avail_w, avail_h, _meta = plot_avail_mm(
            paper_w, paper_h,
            self.ed_title.text(), self.ed_sub.text(),
        )
        return avail_w, avail_h

    def _sync_scale_hint(self, *_args):
        if self._data_w_m <= 0 or self._data_h_m <= 0:
            self.lbl_scale_hint.setText('')
            return
        avail_w, avail_h = self._avail_plot_mm()
        auto_n = pick_nice_scale(
            self._data_w_m, self._data_h_m, avail_w, avail_h,
        )
        if self.rad_scale_custom.isChecked():
            n = max(1, int(self.spn_scale_n.value()))
            drawn_w = self._data_w_m * 1000.0 / float(n)
            drawn_h = self._data_h_m * 1000.0 / float(n)
            fits = drawn_w <= avail_w + 1e-6 and drawn_h <= avail_h + 1e-6
            note = (
                'Fit paper ≈ 1∶%d · your selection 1∶%d'
                ' (frame ≈ %.0f × %.0f mm)'
                % (auto_n, n, drawn_w, drawn_h)
            )
            if not fits:
                note += ' — larger than plot area'
            self.lbl_scale_hint.setText(note)
        else:
            self.lbl_scale_hint.setText('→ 1∶%d' % auto_n)

    def values(self):
        dpi = self.cmb_dpi.currentData()
        try:
            dpi = int(dpi)
        except (TypeError, ValueError):
            dpi = 300
        out = {
            'format': 'svg' if self.rad_svg.isChecked() else 'png',
            'paper': self.cmb_paper.currentData() or 'A4',
            'orientation': (
                'landscape' if self.rad_landscape.isChecked() else 'portrait'
            ),
            'scale_mode': (
                'custom' if self.rad_scale_custom.isChecked() else 'auto'
            ),
            'scale_n': int(self.spn_scale_n.value()),
            'title': self.ed_title.text().strip(),
            'subtitle': self.ed_sub.text().strip(),
            'show_legend': bool(self.chk_legend.isChecked()),
            'bg': QColor(self._bg),
            'dpi': dpi,
        }
        if self._density_on:
            out['label_size_pt'] = int(self.spn_label_pt.value())
        return out
