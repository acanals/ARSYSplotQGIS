# -*- coding: utf-8 -*-
"""Personal group style book: field sections → value → colour + point model.

Text format (UTF-8), one entry per line::

    # comment
    silex;#ffffff;cross          # flat list (any active group field)

    material                     # section = attribute field name
    silex;#ffffff;cross
    calcaria;#8a4512;star

    categoria
    bloc;#e08745;circle

Value lines: ``name;colour`` or ``name;colour;shape``.
Colour: ``#rgb``, ``#rrggbb``, or ``r,g,b``. Shape: Point model id/alias.
"""
from contextlib import suppress

from qgis.PyQt.QtGui import QColor

from .layers import DEFAULT_MARKER, resolve_marker_shape


def parse_color(text):
    """Return a valid QColor or None."""
    raw = (text or '').strip()
    if not raw:
        return None
    if raw.startswith('#') and len(raw) in (4, 7):
        c = QColor(raw)
        return QColor(c) if c.isValid() else None
    if ',' in raw:
        parts = [p.strip() for p in raw.split(',')]
        if len(parts) >= 3:
            with suppress(ValueError, TypeError):
                r, g, b = (int(float(parts[0])), int(float(parts[1])), int(float(parts[2])))
                a = int(float(parts[3])) if len(parts) > 3 else 255
                c = QColor(r, g, b, a)
                return QColor(c) if c.isValid() else None
    c = QColor(raw)
    return QColor(c) if c.isValid() else None


def empty_book():
    return {
        'sections': {},
        'flat': {},
        'warnings': [],
        'path': '',
        'n_entries': 0,
    }


def _put_entry(target, value, color, shape, warnings, line_no):
    key = str(value)
    if not key:
        warnings.append('line %d: empty value name' % line_no)
        return False
    entry = {'color': color, 'shape': shape}
    prev = target.get(key)
    if prev is not None:
        warnings.append('line %d: duplicate value "%s" (replaced)' % (line_no, key))
    target[key] = entry
    return True


def parse_style_text(text, path=''):
    """Parse style text into a book dict."""
    book = empty_book()
    book['path'] = path or ''
    warnings = book['warnings']
    section = None  # None → flat; str → field section
    n = 0
    for line_no, raw_line in enumerate((text or '').splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith('#') or line.startswith(';'):
            continue
        if ';' not in line:
            # Field section header (optional [brackets]).
            name = line.strip('[]').strip()
            if not name:
                warnings.append('line %d: empty field name' % line_no)
                continue
            section = name
            book['sections'].setdefault(name, {})
            continue
        parts = [p.strip() for p in line.split(';')]
        value = parts[0] if parts else ''
        color_txt = parts[1] if len(parts) > 1 else ''
        shape_txt = parts[2] if len(parts) > 2 else ''
        color = parse_color(color_txt)
        if color_txt and color is None:
            warnings.append(
                'line %d: invalid colour "%s" for "%s"' % (line_no, color_txt, value)
            )
        shape = None
        if shape_txt:
            resolved = resolve_marker_shape(shape_txt, fallback=None)
            if resolved is None:
                warnings.append(
                    'line %d: unknown shape "%s" for "%s" (using Point model)'
                    % (line_no, shape_txt, value)
                )
            else:
                shape = resolved
        if color is None and shape is None and not color_txt and not shape_txt:
            warnings.append('line %d: no colour or shape for "%s"' % (line_no, value))
            continue
        if color is None and not shape:
            # Colour was required-ish but invalid and no shape — skip.
            continue
        bucket = book['flat'] if section is None else book['sections'][section]
        if _put_entry(bucket, value, color, shape, warnings, line_no):
            n += 1
    book['n_entries'] = n
    return book


def load_style_file(path):
    """Read UTF-8 (or latin-1 fallback) style file."""
    path = os_path(path)
    data = None
    last_err = None
    for enc in ('utf-8-sig', 'utf-8', 'latin-1'):
        try:
            with open(path, 'r', encoding=enc) as fh:
                data = fh.read()
            break
        except (OSError, UnicodeError) as exc:
            last_err = exc
    if data is None:
        raise OSError(str(last_err) if last_err else 'Cannot read style file')
    return parse_style_text(data, path=path)


def os_path(path):
    return str(path or '')


def _norm_key(name):
    return str(name or '').strip().casefold()


def _section_map(book, field_name):
    """Entries for ``field_name`` (case-insensitive section match), else flat."""
    if not book:
        return {}
    sections = book.get('sections') or {}
    want = _norm_key(field_name)
    if want:
        for name, entries in sections.items():
            if _norm_key(name) == want:
                return dict(entries or {})
    # No matching section → flat list (works with any selected group field).
    return dict(book.get('flat') or {})


def _lookup_entry(entries, value):
    if value in entries:
        return entries[value]
    want = _norm_key(value)
    for key, entry in entries.items():
        if _norm_key(key) == want:
            return entry
    return None


def maps_for_field(book, field_name):
    """Return ``(cmap, shapes)`` for the active group field.

    ``cmap`` maps value → QColor (only styled values).
    ``shapes`` maps value → marker id (only values with an explicit shape).
    """
    cmap = {}
    shapes = {}
    entries = _section_map(book, field_name)
    for key, entry in entries.items():
        if not entry:
            continue
        color = entry.get('color')
        if color is not None and getattr(color, 'isValid', lambda: False)():
            cmap[key] = QColor(color)
        shape = entry.get('shape')
        if shape:
            shapes[key] = resolve_marker_shape(shape)
    return cmap, shapes


def summary_message(book, field_name=None):
    """Short status line after load / apply."""
    if not book:
        return 'No style loaded.'
    n = int(book.get('n_entries') or 0)
    path = book.get('path') or 'style'
    base = os_basename(path)
    warn_n = len(book.get('warnings') or [])
    parts = ['Style %s: %d entr%s' % (base, n, 'y' if n == 1 else 'ies')]
    if field_name:
        cmap, shapes = maps_for_field(book, field_name)
        parts.append(
            'field "%s" → %d colour%s, %d shape%s'
            % (
                field_name,
                len(cmap), 's' if len(cmap) != 1 else '',
                len(shapes), 's' if len(shapes) != 1 else '',
            )
        )
    if warn_n:
        parts.append('%d warning%s' % (warn_n, 's' if warn_n != 1 else ''))
    return ' · '.join(parts)


def os_basename(path):
    import os
    return os.path.basename(path) if path else 'style'
