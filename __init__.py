# -*- coding: utf-8 -*-
"""
ARSYSplotQGIS
Copyright (C) 2026 Antoni Canals-Salomó

This program is free software; you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation; either version 2 of the License, or (at your option) any later
version.
"""


def classFactory(iface):
    from .plugin import ARSYSplotQGISPlugin
    return ARSYSplotQGISPlugin(iface)
