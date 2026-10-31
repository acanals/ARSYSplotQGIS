# -*- coding: utf-8 -*-
"""Export PNG dialog: background, title, subtitle, resolution."""
from qgis.PyQt.QtCore import QRect, Qt
from qgis.PyQt.QtGui import QColor, QFont, QPainter
from qgis.PyQt.QtWidgets import (
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

SCREEN_DPI = 96.0


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
            Qt.AlignLeft | Qt.AlignVCenter,
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
            Qt.AlignLeft | Qt.AlignVCenter,
            subtitle,
        )


class ExportImageDialog(QDialog):
    def __init__(self, parent=None, title='', subtitle='', bg=None):
        super().__init__(parent)
        self.setWindowTitle('Export image')
        self._bg = QColor(bg if bg is not None else '#ffffff')
        if not self._bg.isValid():
            self._bg = QColor('#ffffff')

        self.ed_title = QLineEdit(title or '')
        self.ed_sub = QLineEdit(subtitle or '')
        self.btn_bg = QPushButton()
        self.btn_bg.setFixedSize(72, 24)
        self.btn_bg.setCursor(Qt.PointingHandCursor)
        self.btn_bg.clicked.connect(self._pick_bg)
        self._sync_bg_btn()
        bg_row = QHBoxLayout()
        bg_row.setContentsMargins(0, 0, 0, 0)
        bg_row.addWidget(self.btn_bg)
        bg_row.addWidget(QLabel('Click to choose'), 1)

        self.cmb_dpi = QComboBox()
        for dpi, label in (
            (96, '96 dpi · screen'),
            (150, '150 dpi · draft print'),
            (300, '300 dpi · print'),
            (600, '600 dpi · high'),
        ):
            self.cmb_dpi.addItem(label, dpi)
        self.cmb_dpi.setCurrentIndex(2)

        form = QFormLayout()
        form.addRow('Background', bg_row)
        form.addRow('Title', self.ed_title)
        form.addRow('Subtitle', self.ed_sub)
        form.addRow('Resolution', self.cmb_dpi)
        hint = QLabel(
            'Exports a paper figure of the data frame (not the empty pane). '
            'Higher dpi gives a larger, sharper PNG for print.'
        )
        hint.setWordWrap(True)
        hint.setStyleSheet('color:#888;')

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(hint)
        layout.addWidget(buttons)
        self.resize(420, 220)

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

    def values(self):
        dpi = self.cmb_dpi.currentData()
        try:
            dpi = int(dpi)
        except (TypeError, ValueError):
            dpi = 96
        return {
            'title': self.ed_title.text().strip(),
            'subtitle': self.ed_sub.text().strip(),
            'bg': QColor(self._bg),
            'dpi': dpi,
        }
