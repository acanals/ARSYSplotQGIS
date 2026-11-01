# -*- coding: utf-8 -*-
"""ARSYSplotQGIS plugin entry (Vector menu + toolbar + Help)."""
import os

from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction

from .dock import ARSYSDock

PLUGIN_DIR = os.path.dirname(__file__)
MENU_NAME = 'ARSYSplotQGIS'


class ARSYSplotQGISPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.help_action = None
        self.dock = None

    def initGui(self):
        icon = QIcon(os.path.join(PLUGIN_DIR, 'ArcheIcon.png'))
        self.action = QAction(icon, 'ARSYSplotQGIS', self.iface.mainWindow())
        self.action.setToolTip(
            'Archaeostratigraphic workspace: plan, sections, density and 3D'
        )
        self.action.setWhatsThis(
            'Plan, longitudinal and transversal views of excavation XYZ points, '
            'with group filters, kernel density and a 3D scatter. '
            'Opens its own window (not the QGIS map).'
        )
        self.action.triggered.connect(self.run)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu(MENU_NAME, self.action)
        self.iface.addPluginToVectorMenu(MENU_NAME, self.action)
        self.help_action = QAction(icon, 'ARSYSplotQGIS', self.iface.mainWindow())
        self.help_action.triggered.connect(self.show_help)
        try:
            self.iface.pluginHelpMenu().addAction(self.help_action)
        except Exception:
            self.help_action = None

    def unload(self):
        if self.help_action is not None:
            try:
                self.iface.pluginHelpMenu().removeAction(self.help_action)
            except Exception:
                pass
            self.help_action = None
        if self.action:
            self.iface.removeToolBarIcon(self.action)
            self.iface.removePluginMenu(MENU_NAME, self.action)
            self.iface.removePluginVectorMenu(MENU_NAME, self.action)
        if self.dock:
            self.dock._force_close = True
            self.dock.close()
            self.dock.deleteLater()
            self.dock = None

    def show_help(self):
        try:
            from qgis.utils import showPluginHelp
            showPluginHelp(packageName='ARSYSplotQGIS', filename='index')
        except Exception:
            from qgis.PyQt.QtCore import QUrl
            from qgis.PyQt.QtGui import QDesktopServices
            QDesktopServices.openUrl(
                QUrl.fromLocalFile(os.path.join(PLUGIN_DIR, 'index.html'))
            )

    def run(self):
        if self.dock is None:
            self.dock = ARSYSDock(self.iface)
        self.dock.show()
        self.dock.raise_()
        self.dock.activateWindow()
