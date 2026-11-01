# -*- coding: utf-8 -*-
from qgis.core import QgsCoordinateReferenceSystem


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
