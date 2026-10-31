# -*- coding: utf-8 -*-
from qgis.core import QgsCoordinateReferenceSystem, QgsProject


def local_metre_crs():
    """Engineering metre grid. Never inherit EPSG:3857/4326 (site XY are metres)."""
    crs = QgsCoordinateReferenceSystem()
    for wkt in (
        'LOCAL_CS["ARSYS site metres",UNIT["metre",1.0,AUTHORITY["EPSG","9001"]]]',
        'ENGCRS["ARSYS site metres",'
        'EDATUM["Local"],'
        'CS[Cartesian,2],'
        'AXIS["X (E)",east,ORDER[1]],'
        'AXIS["Y (N)",north,ORDER[2]],'
        'LENGTHUNIT["metre",1.0]]',
    ):
        if crs.createFromWkt(wkt) and crs.isValid():
            return crs
    crs = QgsCoordinateReferenceSystem.fromProj(
        '+proj=affine +xoff=0 +yoff=0 +units=m +no_defs'
    )
    if crs.isValid():
        return crs
    fallback = QgsCoordinateReferenceSystem.fromEpsgId(25831)
    return fallback if fallback.isValid() else QgsCoordinateReferenceSystem()


def site_crs():
    return local_metre_crs()


def is_web_or_geographic(crs):
    if crs is None or not crs.isValid():
        return True
    if crs.isGeographic():
        return True
    auth = (crs.authid() or '').upper()
    return auth in ('EPSG:3857', 'EPSG:4326', 'EPSG:900913')


def align_project_to_layer(layer):
    """3D uses the project CRS. Local XYZ must not sit at 14 m from Null Island."""
    if layer is None:
        return
    project = QgsProject.instance()
    if is_web_or_geographic(project.crs()) or is_web_or_geographic(layer.crs()):
        lcrs = layer.crs() if layer.crs().isValid() else local_metre_crs()
        if not is_web_or_geographic(lcrs):
            project.setCrs(lcrs)
        elif lcrs != local_metre_crs():
            project.setCrs(local_metre_crs())
