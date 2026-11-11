# -*- coding: utf-8 -*-
"""In-app help dialog (loads bundled index.html — Lite-style modal)."""
from contextlib import suppress
import os

from qgis.PyQt.QtCore import QUrl, Qt
from qgis.PyQt.QtGui import QColor, QDesktopServices, QPalette
from qgis.PyQt.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

PLUGIN_DIR = os.path.dirname(__file__)

# Help HTML is authored for a light page. Keep the dialog light even when the
# dock is Dark — otherwise dark chrome + dark body text = unreadable.
_HELP_CSS = (
    'QDialog { background:#faf7f2; color:#1a1816; }'
    'QLabel { color:#1a1816; background:transparent; }'
    'QLabel#helpLead { color:#6b645c; }'
    'QPushButton {'
    '  background:#f2ece3; color:#1a1816; border:1px solid #c8c0b4;'
    '  border-radius:6px; padding:4px 10px; }'
    'QPushButton:hover { background:#ebe4d8; }'
    'QTextBrowser {'
    '  background:#ffffff; color:#1a1816; border:1px solid #c8c0b4;'
    '  border-radius:6px; padding:4px; }'
    'QDialogButtonBox QPushButton { min-width:72px; }'
)


def help_html_path():
    return os.path.realpath(os.path.join(PLUGIN_DIR, 'index.html'))


def open_help_external():
    """Fallback: open the help file in the system browser."""
    path = help_html_path()
    if not os.path.isfile(path):
        return False
    return QDesktopServices.openUrl(QUrl.fromLocalFile(path))


def _light_palette():
    pal = QPalette()
    bg = QColor('#faf7f2')
    paper = QColor('#ffffff')
    ink = QColor('#1a1816')
    muted = QColor('#6b645c')
    for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive,
                  QPalette.ColorGroup.Disabled):
        pal.setColor(group, QPalette.ColorRole.Window, bg)
        pal.setColor(group, QPalette.ColorRole.WindowText, ink)
        pal.setColor(group, QPalette.ColorRole.Base, paper)
        pal.setColor(group, QPalette.ColorRole.Text, ink)
        pal.setColor(group, QPalette.ColorRole.Button, QColor('#f2ece3'))
        pal.setColor(group, QPalette.ColorRole.ButtonText, ink)
        pal.setColor(group, QPalette.ColorRole.PlaceholderText, muted)
        pal.setColor(group, QPalette.ColorRole.Highlight, QColor('#b5651d'))
        pal.setColor(group, QPalette.ColorRole.HighlightedText, paper)
    return pal


def show_help_dialog(parent=None):
    """Modal browser with the same HTML as Help → Plugins → ARSYSplotQGIS."""
    path = help_html_path()
    if not os.path.isfile(path):
        return open_help_external()

    # Parentless so the dock's dark stylesheet does not cascade into the help.
    dlg = QDialog(None)
    dlg.setWindowTitle('ARSYSplotQGIS — Help')
    dlg.setMinimumSize(640, 480)
    dlg.resize(760, 580)
    dlg.setModal(True)
    dlg.setPalette(_light_palette())
    dlg.setStyleSheet(_HELP_CSS)
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        dlg.setAutoFillBackground(True)

    layout = QVBoxLayout(dlg)
    layout.setContentsMargins(10, 10, 10, 10)
    layout.setSpacing(8)

    head = QHBoxLayout()
    title = QLabel('How to use ARSYSplotQGIS')
    title.setStyleSheet('font-size:15px; font-weight:600; color:#1a1816;')
    head.addWidget(title, 1)
    btn_browser = QPushButton('Open in browser')
    btn_browser.setToolTip('Open the same help page in the system browser.')
    btn_browser.clicked.connect(lambda: open_help_external())
    head.addWidget(btn_browser)
    layout.addLayout(head)

    lead = QLabel(
        'Plugin guide (plain language). Same page as Help → Plugins → '
        'ARSYSplotQGIS — not the Lite browser “i” help.'
    )
    lead.setObjectName('helpLead')
    lead.setWordWrap(True)
    layout.addWidget(lead)

    browser = QTextBrowser(dlg)
    browser.setOpenExternalLinks(True)
    browser.setOpenLinks(True)
    browser.setPalette(_light_palette())
    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        browser.setSearchPaths([os.path.dirname(path)])
        browser.document().setDefaultStyleSheet(
            'body { color:#1a1816; background-color:#ffffff; }'
            'a { color:#245a8c; }'
            'th { background:#f4f1ec; color:#1a1816; }'
            'td { color:#1a1816; }'
            '.lead, .note { color:#444444; }'
        )
    browser.setSource(QUrl.fromLocalFile(path))
    layout.addWidget(browser, 1)

    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
    buttons.rejected.connect(dlg.reject)
    close_btn = buttons.button(QDialogButtonBox.StandardButton.Close)
    if close_btn is not None:
        close_btn.clicked.connect(dlg.accept)
    layout.addWidget(buttons)

    with suppress(AttributeError, RuntimeError, TypeError, ValueError):
        dlg.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)

    # Keep above the dock without inheriting its sheet (parent was None).
    if parent is not None:
        with suppress(AttributeError, RuntimeError, TypeError, ValueError):
            dlg.setWindowModality(Qt.WindowModality.ApplicationModal)

    dlg.exec()
    return True
