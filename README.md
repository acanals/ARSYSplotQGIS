# ARSYSplotQGIS

A QGIS 3 plugin designed to **support archaeostratigraphic analysis and interpretation** through the visualisation and spatial analysis of archaeological excavation XYZ data.

ARSYSplotQGIS provides an **independent archaeostratigraphic workspace** with three linked 2D projections of the excavation data — plan (X/Y), longitudinal section (X/Z) and transversal section (Y/Z) — and an interactive 3D view.

Each 2D projection can display the spatial distribution of points and their **kernel-density distribution**, represented as heatmaps and contour lines. The 3D view provides an additional perspective for exploring the complete XYZ dataset.

All views share the same data filters and group selection. The plugin operates in its own workspace: it does not add layers to the QGIS map canvas or legend.

| View | Axes | Description |
| --- | --- | --- |
| Plan | X / Y | Horizontal distribution |
| Longitudinal section | X / Z | Longitudinal section |
| Transversal section | Y / Z | Cross-section |
| 3D | X, Y, Z | Interactive 3D scatter plot |

Filter data by **group** and **XYZ range**, display **points**, **orientation vectors**, or both, generate **kernel-density heatmaps** with contour lines, and export publication-ready **PNG figures** with axes and scale information.

**Licence:** [GNU GPL-2.0-or-later](LICENSE) · © 2026 Antoni Canals-Salomó (URV IPHES-CERCA)

Source code, issues and documentation: <https://github.com/acanals/ARSYSplotQGIS>

---

## Why ARSYSplotQGIS?

Archaeological fieldwork and laboratory analysis often require the **plan and both vertical sections to be examined together**, using the same data and filters. A conventional GIS map, focused on individual layers, does not provide this kind of integrated workspace.

ARSYSplotQGIS provides a dedicated environment for this purpose, directly within QGIS:

- **Three linked 2D views** — plan, longitudinal and transversal sections, working with the same dataset and filters.
- **Independent workspace** — plugin data and visualisations remain private to the plugin. Nothing is added to the QGIS project.
- **Lightweight 3D visualisation** — uses Qt painting rather than the QGIS 3D engine, avoiding compatibility issues encountered with QGIS 3.40.
- **No additional Python dependencies** — relies exclusively on Python libraries and Processing algorithms included with QGIS.

ARSYSplotQGIS is designed specifically for archaeostratigraphic data exploration. It is not a general-purpose GIS editor, a replacement for the QGIS 3D map view, or an alternative version of the browser-based ARSYSplotLite.

---

## Requirements

- QGIS **3.22 or later** (tested with **QGIS 3.40**).
- QGIS Processing algorithms:
  - Heatmap (Kernel Density Estimation).
  - Contour.
- No additional pip packages or external binaries.
- No internet connection required at runtime.

---

## Installation

### From the QGIS Plugin Repository

1. Open **Plugins → Manage and Install Plugins**.
2. Enable **Show also experimental plugins** (the first public release is classified as experimental).
3. Search for **ARSYSplotQGIS** and install it.
4. Open the plugin from:
   - **Plugins → Vector → ARSYSplotQGIS**.
   - The plugin toolbar icon.
   - **Help → Plugins → ARSYSplotQGIS** to access this documentation.

### From a ZIP file

Go to:

**Plugins → Manage and Install Plugins → Install from ZIP**

Select `ARSYSplotQGIS.<version>.zip`.

The ZIP archive must contain a folder named `ARSYSplotQGIS`, with `metadata.txt` inside it.

---

## Quick Start

1. Open ARSYSplotQGIS.
2. Click **Load sample** to load the bundled `sample.csv` file. No file selection dialog is required.

   Alternatively, use **Import CSV** to import your own data, or **Use selected layer** to work with an existing point layer in the QGIS project.

3. Use the coloured chips under **Group** to show or hide individual classes. **All** and **None** enable or disable all groups.
4. Adjust the **X, Y and Z** sliders to restrict the spatial extent of the displayed data.
5. Navigate the views:
   - Mouse wheel: zoom in/out.
   - Mouse drag: pan.
   - **Zoom**: open an enlarged view.
   - **Reset**: restore the initial settings.
6. Optionally, activate **Density → On** to generate a heatmap from the filtered points. Set **Draw → None** to display the density surface without the point cloud.
7. Optionally, click **Open 3D view** to explore the same filtered dataset in three dimensions.

---

## Data

### Import CSV

**Import CSV** automatically detects the file encoding (UTF-8 or Latin-1) and field delimiter (comma, semicolon, tab or pipe).

During import, map the CSV columns to the following fields:

| Field | Description |
| --- | --- |
| **P1 X / Y / Z** | Object centre coordinates |
| **P2 X / Y / Z** | Orientation vector start point (optional) |
| **P3 X / Y / Z** | Orientation vector end point (optional) |
| **Group** | Classification attribute used to colour the data (material, level, etc.) |

Coordinate interpretation:

- If P1 is missing but P2 and P3 are available, the object centre is calculated as the midpoint between P2 and P3.
- If P3 is missing, the orientation vector is defined by **P1 → P2**, as in older Arche10 files.
- If P3 is available, the orientation vector is defined by **P2 → P3**.

Imported coordinates are stored in a private **PointZ memory layer**. Additional CSV columns are preserved as attributes.

### Use selected layer

Select any point layer already loaded in the QGIS project.

ARSYSplotQGIS copies the required data into its private workspace. The original project layer is never modified.

### Sample data

The plugin includes `sample.csv`, containing example data from ArcheSite1 (2 500 points).

Its fields are:

`p1x | p1y | p1z | p2x | p2y | p2z | p3x | p3y | p3z | material | categoria | taxo | nivell`

- **P1** is the object centre on every row.
- **P2** and **P3** are the two ends of the orientation vector (**P2→P3**). They are filled only for records in **nivell 1** (500 points). Other levels leave those columns empty.
- **material**, **categoria**, **taxo** and **nivell** are classification fields. After **Load sample**, **Group** defaults to `material`.

Load it with **Load sample**. Set **Draw** to **Vectors** or **Both** to show the nivell 1 axes. To isolate them, set **Group → Field** to `nivell` and leave only **1** enabled.

**Import CSV** also accepts this file: map P1 as the centre and P2/P3 as the vector ends.

---

## Workspace

### Group

The Group panel controls how the archaeological data is classified and displayed.

- **Field** — selects the attribute used to colour the points. It defaults to `group` after CSV import, or to the column mapped during import.
- **Coloured chips** — one for each unique attribute value. Click a chip to show or hide that group.
- **All / None** — quickly enable or disable all groups.
- **Empty values** — missing or empty attributes are displayed as `(empty)`.

### XYZ Range

Three double sliders (**X**, **Y** and **Z**) restrict the spatial extent of the displayed data.

The initial limits are calculated from the available coordinates (P1, P2, P3 or geometry).

### Adaptive Frame

Controls how the views respond to filtering.

- **Off** — the views retain their original spatial extent. Filtering hides points without changing the frame.
- **On** — the views automatically adjust their extent to the filtered dataset.

### Draw

Select which elements are displayed in the three 2D views.

| Mode | Display |
| --- | --- |
| **Points** | P1 object centres (default) |
| **Vectors** | P2 → P3 orientation vectors (or P1 → P2) |
| **Both** | Object centres and orientation vectors |
| **None** | Neither points nor vectors. Useful when displaying density alone. |

**Point size** and **Arrow size** sliders control the appearance of the elements across all three 2D views.

Vector display options remain disabled until the imported data contains the required orientation coordinates (P2/P3 or P1/P2).

### Density

ARSYSplotQGIS can generate a kernel-density surface from the **currently filtered points**.

Density calculations use QGIS Processing. The resulting raster and contour lines remain within the plugin workspace and are not added to the QGIS project.

| Control | Description |
| --- | --- |
| **On** | Generate or remove the density surface |
| **Show** | Display Heatmap, Isolines or Both |
| **Colour** | Select the colour palette (Viridis, Plasma, Magma, Inferno, etc.) |
| **Min / Max** | Adjust the colour stretch using the actual KDE values. Values below Min are not displayed. |
| **Auto** | Automatically set Min to the 2% cumulative cut of positive cells and Max to the raster maximum |
| **Radius** | Kernel bandwidth, expressed in map units. **Auto** suggests a suitable radius and cell size based on the data extent. |
| **Cell** | Raster cell size |
| **Kernel** | Select the kernel function: Quartic, Triangular, Uniform, Triweight or Epanechnikov. Min/Max values are recalculated for each kernel. |
| **Isolines** | Set the number of contour intervals and optionally enable **Labels**. |
| **Opacity** | Control heatmap fill opacity. Empty raster cells remain transparent. |

Plan and section views share the same relative spatial clipping.

For section views, kernel dimensions are adjusted to prevent circular kernels from becoming excessively large along the thinner Z axis.

To examine the density surface without the original point cloud, set **Draw → None**.

### Zoom Windows and Export

Each view provides two options:

- **Zoom** — opens an enlarged view with a **Fit** option. Press **Esc** to close it.
- **Export** — exports the view as a PNG figure.

PNG export produces a **formatted figure of the data frame**, rather than a screenshot of the application window.

Available export settings include:

- Background colour.
- Title and subtitle.
- Resolution: **96, 150, 300 or 600 dpi**.
- Metric axes.
- Grid.
- Scale bar.
- Group and density legends.

The 3D window also supports PNG export of the scatter plot.

### 3D View

Click **Open 3D view** to explore the same filtered dataset in three dimensions.

Navigation:

- **Drag** — orbit around the data.
- **Pan** — move the viewing area.
- **Mouse wheel** — zoom in/out.
- **Fit** — fit the dataset to the viewing area.
- **Export** — save the 3D scatter plot as PNG.
- **Esc** — close the window.

The 3D view shares the group colours and drawing modes of the main workspace. Group visibility, point size and arrow size can also be adjusted.

The renderer is based on **Qt painting**. It does not initialise or use the QGIS 3D engine.

### Reset

**Reset** restores the initial display settings for the loaded dataset:

- All groups enabled.
- Original XYZ range.
- Default point and arrow sizes.
- Initial zoom and spatial extent.
- Default adaptive frame setting.

---

## Licence

ARSYSplotQGIS is distributed under the **GNU General Public License v2.0 or later (GPL-2.0-or-later)**.

The QGIS Plugin Repository requires a GPL-compatible licence.

---

## Not Yet Implemented

The following features are not available in this version:

- Identifying corresponding points across the different views.
- Saving and restoring sessions with embedded data.
- Excel and ODS import.
- Exporting or adding density isolines directly to the QGIS project.

See the [issue tracker](https://github.com/acanals/ARSYSplotQGIS/issues) for planned improvements and development updates.