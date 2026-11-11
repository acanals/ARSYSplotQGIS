#!/usr/bin/env python3
"""Write dist/ inventory from ARSYSplotQGIS.X.Y.Z.zip (source of truth for the hub).

Only writes inside dist/ so an SFTP of that folder stays self-consistent:
  - versions.json
  - index.html  (link list; works even without Apache directory listing)
"""
import html
import json
import re
import sys
from pathlib import Path

PLUGIN = 'ARSYSplotQGIS'
PAT = re.compile(r'^' + re.escape(PLUGIN) + r'\.(\d+)\.(\d+)\.(\d+)\.zip$')


def main():
    plugin_root = Path(__file__).resolve().parents[1]
    dist = plugin_root / 'dist'
    dist.mkdir(parents=True, exist_ok=True)

    items = []
    for path in sorted(dist.glob(PLUGIN + '.*.zip')):
        match = PAT.match(path.name)
        if not match:
            continue
        key = [int(x) for x in match.groups()]
        items.append({
            'version': '.'.join(match.groups()),
            'file': path.name,
            'key': key,
        })
    items.sort(key=lambda row: row['key'])

    payload = {
        'plugin': PLUGIN,
        'versions': [
            {'version': row['version'], 'file': row['file']} for row in items
        ],
    }
    (dist / 'versions.json').write_text(
        json.dumps(payload, indent=2) + '\n', encoding='utf-8'
    )

    rows = []
    for row in reversed(items):
        name = html.escape(row['file'])
        rows.append('<li><a href="%s">%s</a></li>' % (name, name))
    index = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>%s dist</title>
</head>
<body>
<h1>%s packages</h1>
<p>Versioned ZIP builds. The Analytics hub picks the highest version.</p>
<ul>
%s
</ul>
</body>
</html>
""" % (PLUGIN, PLUGIN, '\n'.join(rows) if rows else '<li>(none)</li>')
    (dist / 'index.html').write_text(index, encoding='utf-8')

    print('Wrote %s (%d version(s))' % (dist / 'versions.json', len(items)))
    print('Wrote %s' % (dist / 'index.html'))
    if items:
        print('Highest in dist/:', items[-1]['file'])
    else:
        print('Highest in dist/: (none)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
