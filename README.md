# ARSYSplotQGIS

QGIS 3 plugin for **archaeostratigraphic** reading of excavation XYZ points.

It opens its **own window**. Nothing is added to the QGIS map canvas or legend.

Three linked 2D views plus an optional 3D scatter:

| View | Axes | What you see |
| --- | --- | --- |
| Plan | X / Y | Horizontal distribution |
| Longitudinal | X / Z | Long section |
| Transversal | Y / Z | Cross section |
| 3D | X, Y, Z | Orbit / pan / zoom scatter |

Filter by **group** and **XYZ range**, draw **points** and/or **orientation vectors**, overlay a **kernel-density** heatmap with isolines, and **export PNG** figures with axes.

Licence: [GNU GPL-2.0-or-later](LICENSE) · © 2026 Antoni Canals-Salomó (URV IPHES-CERCA)

Source, issues and this README: <https://github.com/acanals/ARSYSplotQGIS>

---

## Why this plugin

Field and lab work in archaeostratigraphy needs the **plan and the two sections at once**, with the same filters, not a GIS map of one layer.

ARSYSplotQGIS is that workspace inside QGIS:

- Layers used by the plugin stay **private** (plugin canvases only).
- 3D is a **Qt scatter**, not QGIS 3D (avoids crashes on QGIS 3.40).
- **No extra Python packages.** Only the Python and Processing algorithms that ship with QGIS.

It is **not** a general GIS editor, a replacement for the QGIS 3D map view, or the browser app ARSYSplotLite.

---

## Requirements

- QGIS **3.22** or later (tested on **3.40**)
- Processing algorithms **Heatmap (Kernel Density Estimation)** and **Contour** (included with QGIS)
- No pip packages, no binaries, no internet connection at runtime

---

## Install

### From the QGIS plugin repository

1. **Plugins → Manage and Install Plugins**
2. Enable **Show also experimental plugins** (this first public version is experimental)
3. Search for **ARSYSplotQGIS** and install
4. Open it from **Plugins → Vector → ARSYSplotQGIS**, the toolbar icon, or **Help → Plugins → ARSYSplotQGIS** for this documentation

### From a ZIP

**Plugins → Manage and Install Plugins → Install from ZIP** → `ARSYSplotQGIS.<version>.zip`

The zip must contain a folder named `ARSYSplotQGIS` with `metadata.txt` inside it.

---

## Quick start

1. Open the plugin.
2. Click **Load sample** (bundled `sample.csv`; no file dialog).
   Or **Import CSV** and map your columns, or **Use selected layer** on a point layer already in the project.
3. Colour chips under **Group** turn classes on and off (**All** / **None**).
4. Drag the **X Y Z** sliders to clip depth and plan extent.
5. Mouse **wheel** zooms a view; **drag** pans; **Zoom** opens that view large; **Reset** restores groups, ranges, size and frame.
6. Optional: **Density → On** for a heatmap of the filtered points. **Draw → None** to see the surface alone.
7. Optional: **Open 3D view** for the same filtered cloud.

---

## Data

### Import CSV

**Import CSV** auto-detects encoding (UTF-8, Latin-1) and delimiter (comma, semicolon, tab, pipe).

Map:

| Field | Meaning |
| --- | --- |
| **P1 X / Y / Z** | Object centre |
| **P2 X / Y / Z** | Start of the orientation vector (optional) |
| **P3 X / Y / Z** | End of the orientation vector (optional) |
| **Group** | Class used for colour (material, level, …) |

If P1 is missing but P2 and P3 exist, the centre is the midpoint of P2–P3.

If P3 is missing, the vector is **P1→P2** (older Arche10 files). Otherwise the vector is **P2→P3**.

Coordinates are stored as a **PointZ** memory layer. Extra CSV columns are kept as attributes.

### Use selected layer

Any point layer already in the QGIS project. The plugin copies what it needs into its private workspace; your project layer is not modified.

### Sample

`sample.csv` (ArcheSite1) is installed with the plugin:

`p1x | p1y | p1z | material | categoria | taxo | nivell`

**Load sample** or **Import CSV → Sample data**.

---

## Workspace

### Group

- **Field** — which attribute colours the points (defaults to `group` after CSV import, or the mapped column).
- Coloured chips — one per unique value. Click to show/hide. **All** / **None** for a quick empty or full set.
- Empty / missing values appear as `(empty)`.

### XYZ range

Three double sliders (**x**, **y**, **z**) clip the cloud. Bounds come from the data (P1 / P2 / P3 or geometry).

### Adaptive frame

- **Off** — canvases keep the full extent (filters hide points but the frame does not jump).
- **On** — canvases zoom to the filtered cloud.

### Draw

| Mode | Shows |
| --- | --- |
| **Points** | P1 centres (default) |
| **Vectors** | P2→P3 arrows (or P1→P2) |
| **Both** | Centres and arrows |
| **None** | Neither — use this with Density |

**Point size** and **Arrow size** sliders apply to all three 2D views. Vector buttons stay disabled until the file has P2/P3 (or P1/P2) axes.

### Density

Kernel density of the **currently filtered** points. Computed with QGIS Processing; the raster and isolines stay inside the plugin.

| Control | Role |
| --- | --- |
| **On** | Build / drop the surface |
| **Show** | Heatmap, Isolines, or Both |
| **Colour** | Palette (Viridis, Plasma, Magma, Inferno, …) |
| **Min / Max** | Colour stretch on real KDE values. Below Min is not drawn |
| **Auto** (next to Min/Max) | Min = 2 % cumulative cut of positive cells; Max = raster maximum |
| **Radius** | Kernel bandwidth (map units). **Auto** suggests radius and cell from the extent |
| **Cell** | Raster cell size |
| **Kernel** | Quartic, Triangular, Uniform, Triweight, Epanechnikov. Min/Max are recomputed for each kernel |
| **Isolines** | Number of contour intervals; optional **Labels** |
| **Opacity** | Heatmap fill (empty cells stay clear) |

Plan and sections share the same relative clip. Section kernels are scaled so a circular kernel is not oversized on a thin Z axis.

Turn **Draw → None** to read the density without the point cloud on top.

### Zoom windows and export

Each pane has **Zoom** (large window, Fit, Esc to close) and **Export**.

PNG export is a **paper figure of the data frame** (not the empty pane):

- background colour
- title and subtitle
- 96 / 150 / 300 / 600 dpi
- metre axes, grid, scale bar and group/density legend

The 3D window can export a PNG of the scatter as well.

### 3D view

**Open 3D view** — orbit (drag), pan, wheel zoom. Same group colours and draw mode as the 2D workspace. Group chips, size and arrow sliders, Fit, export. **Esc** closes.

Built with Qt painting. It does **not** start the QGIS 3D engine.

### Reset

Restores groups (all on), XYZ range, point size, arrow size, zoom and adaptive frame to the initial view of the loaded file.

---

## Licence

This QGIS plugin is **GNU GPL-2.0-or-later**. The QGIS plugin repository requires a GPL-2 compatible licence.

The browser tools ARSYSplot / ARSYSplotLite may use a different licence; this plugin does not.

---

## Build a ZIP for plugins.qgis.org

From this folder:

```bash
make zip
```

Output: `dist/ARSYSplotQGIS.<version>.zip`. Do not put `__pycache__`, `.git` or `dist/` in the upload. The ZIP and the public Git repository must be the same code.

---

## Not in this version

Identify-across-views, session files with embedded data, Excel/ODS import, and writing isolines into the QGIS project. See the issue tracker.
