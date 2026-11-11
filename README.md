# ARSYSplotQGIS

A QGIS 3 plugin designed to **support archaeostratigraphic analysis and interpretation** through the visualisation and spatial analysis of archaeological excavation XYZ data. 

ARSYSplotQGIS provides an **independent archaeostratigraphic workspace** with three linked 2D projections of the excavation data — plan (X/Y), longitudinal section (X/Z) and transversal section (Y/Z) — an optional **A–B profile**, and an interactive 3D view.

Each 2D projection can display the spatial distribution of points and their **kernel-density distribution**, represented as heatmaps and contour lines. The 3D view provides an additional perspective for exploring the complete XYZ dataset.

All views share the same data filters and group selection. The plugin operates in its own workspace: it does not add layers to the QGIS map canvas or legend (except when you explicitly use **To QGIS layer** / Profile → To QGIS).

| View | Axes | Description |
| --- | --- | --- |
| Plan | X / Y | Horizontal distribution |
| Longitudinal section | X / Z | Longitudinal section |
| Transversal section | Y / Z | Cross-section |
| 3D | X, Y, Z | Interactive 3D scatter plot |

Filter data by **group** and **XYZ range**, **Find** records by attribute words, cut an **A–B profile**, display **points**, **orientation vectors**, or both, generate **kernel-density heatmaps** with contour lines, and export publication-ready **PNG figures** with axes and scale information.

**Licence:** [GNU GPL-2.0-or-later](LICENSE) · © 2026 Antoni Canals-Salomó (URV IPHES-CERCA)

Source code, issues and documentation: <https://github.com/acanals/ARSYSplotQGIS>

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
2. Search for **ARSYSplotQGIS** and install it.
3. Open the plugin from:
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
6. Optionally, open **Options → Density** to generate a heatmap from the filtered points (opening the tab engages density and sets **Draw → None**).
7. Optionally, open **Options → Profile**, pick A then B on Plan, and inspect LONG/TRANS.
8. Optionally, click **Open 3D view** to explore the same filtered dataset in three dimensions.

---

## Data

### Import CSV / spreadsheet

**Import** accepts **CSV** (encoding UTF-8 or Latin-1; delimiter comma, semicolon, tab or pipe) and spreadsheets **`.xlsx` / `.ods` / `.xls`** through the **GDAL/OGR drivers shipped with QGIS** (no extra pip packages). For spreadsheets, choose the sheet, then map columns.

During import, map the columns to the following fields:

| Field | Description |
| --- | --- |
| **P1 X / Y / Z** | Point, or start of a P1→P2 vector |
| **P2 X / Y / Z** | End of a P1→P2 vector, or start of a P2→P3 vector (optional) |
| **P3 X / Y / Z** | End of a P2→P3 vector (optional) |
| **Group** | Classification attribute used to colour the data (material, level, etc.) |

The layout is interpreted **per row**:

1. **P1 only** — P1 is the point. No orientation vector.
2. **P1 and P2, no P3** — the file stores the vector **P1 → P2**. The plugin transposes it: stored P2 is the original P1, stored P3 is the original P2, and stored P1 is the **midpoint** (object centre).
3. **P1, P2 and P3** — coordinates are not modified. P1 is the point; the vector is **P2 → P3**.

If P1 is missing but P2 and P3 are present, P1 is calculated as the midpoint of P2→P3.

After import, drawing always uses **P1 as the point** and **P2 → P3 as the vector**. Mixed files are allowed (some rows points-only, others with axes).

Imported coordinates are stored in a private **PointZ memory layer**. Additional table columns are preserved as attributes.

### Use selected layer

Select any point layer already loaded in the QGIS project.

ARSYSplotQGIS copies the points, all attributes, and the layer style (classification field, colours, and point size) into its private workspace. The original project layer is never modified.

### Send to QGIS layer

After data are loaded, use **Options → To QGIS layer** (footer next to Reset / Open 3D) to add a **memory** PointZ layer to the project legend with the **complete** attribute table (plugin Group/XYZ filters are ignored). Suitable for Processing, GRASS, etc. The plugin workspace is unchanged. Save As / make permanent yourself if you need the layer after closing the project.

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
- **Load style…** — optional personal text file that sets **colour** and **Point model** per group value. **Clear** drops it. Bundled example: `sample_style.txt`.

Style file format (UTF-8):

```
# comment
material
lithic;#c9b896;cross
bone;#e8dcc8;circle

categoria
nucli;#5a6b7a;square
```

A bare line is a **field section** (matched to **Group → Field**, case-insensitive). Lines with `value;colour` or `value;colour;shape` are entries. A flat list (entries before any section) applies to the active field. Unknown shapes fall back to the Options **Point model**; invalid colours are skipped with a warning.

### XYZ Range

Three double sliders (**X**, **Y** and **Z**) restrict the spatial extent of the displayed data.

The initial limits are calculated from the available coordinates (P1, P2, P3 or geometry).

### Cross-view hover (Resources)

**Off by default.** With **Cross-view → On**, the point under the mouse on one main pane is marked on the other two (blue ring). Uses the same record in plan, longitudinal and transversal. Zoom windows are not driven by this.

### Stretch Z (Resources)

**Off by default.** Exaggerates the vertical axis on **Longitudinal (X/Z)** and **Transversal (Y/Z)** only. The plan stays isotropic.

- **On** — apply the **Factor** (1 = true scale; 2 = Z drawn twice as tall, …).
- Affects the on-screen sections, zoom windows and PNG export (including density on those panes).
- Axis tick labels stay in **real metres**; the Z axis title shows the factor (e.g. `Z ×5 (m)`).
- The 50 cm scale bar uses the horizontal axis only (true map scale).

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

Open the **Options → Density** tab to engage the surface (there is **no On switch**). Opening Density sets **Draw → None**. Density and **Profile** cannot show together: selecting one parks the other (A/B/Wide are kept). Opening **General** alone does not turn them off; use **General → Redraw** to park Density and Profile and show the loaded data.

Density calculations use QGIS Processing (**heatmap KDE**). The fill is the **styled KDE raster** — the same approach as QGIS layer styling — not contour polygons. Isolines are line overlays only (including the outer **Min** edge of the first class). Results stay in the plugin workspace and are not added to the QGIS project.

| Control | Description |
| --- | --- |
| **Show** | Display Heatmap, Isolines or Both |
| **Fill** | **Bands** = discrete colour classes on the raster; **Cloud** = smooth interpolated colour. Same KDE either way. |
| **Colour** | Select the colour palette (Archeo, Viridis, Plasma, Magma, Inferno, etc.). **Invert** is under Resources → Density scale. |
| **Min / Max** | One colour stretch for plan, X/Z and Y/Z. UI values are taken from the plan peak, then applied as **fractions of each view’s own peak** (Auto Max = 100% local peak). Below Min is not painted. |
| **Auto** | Automatically set Min to the 2% cumulative cut of positive plan cells and Max to the plan peak |
| **Radius** | Kernel bandwidth, expressed in map units. **Auto** suggests a suitable radius and cell size based on the data extent. |
| **Cell** | Raster cell size |
| **Kernel** | Select the kernel function: Quartic, Triangular, Uniform, Triweight or Epanechnikov. Min/Max values are recalculated for each kernel. |
| **Isolines** | Number of class breaks drawn as contour **lines** (optional **Labels**). |
| **Opacity** | Control heatmap fill opacity. Empty raster cells remain transparent. |

Plan and sections do **not** share absolute KDE units. The Min/Max spinboxes are set from the plan; each view then uses the same relative stretch against **its own** peak (so Auto Max fills the tip on XY, X/Z and Y/Z alike).

For section views, kernel dimensions are adjusted to prevent circular kernels from becoming excessively large along the thinner Z axis.

### Profile

**Options → Profile** cuts a vertical prism through the cloud using a line on Plan.

- **Wide** (cm) — full horizontal width of the strip, perpendicular to A→B (XY only; all Z included).
- Open the tab → pick **A** then **B** on Plan (or type X/Y). Drag A/B afterwards to adjust.
- **LONG** / **TRANS** show the profile sections; thin levels may auto-enable Stretch Z.
- **Resources → Profile export** — CSV of points in the profile, and optional To QGIS memory layers for LONG/TRANS.
- **New Profile** clears A/B. Density is parked while Profile is active.

### Find

**Options → Find** searches attributes with exact words (AND/OR). Hits appear in a table; click a row for a green ring on the three views and a detail card. **Clear selection** removes the ring without clearing the query.

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
- Full XYZ range.
- Default point and arrow sizes.
- Draw → Points; Adaptive frame off.
- Re-fit zoom on the three main canvases (and open Zoom / 3D windows).
- Density settings and Dark/Light are left unchanged.

---

## Licence

ARSYSplotQGIS is distributed under the **GNU General Public License v2.0 or later (GPL-2.0-or-later)**.

The QGIS Plugin Repository requires a GPL-compatible licence.

---

## Not Yet Implemented

The following features are not available in this version:

- Saving and restoring sessions with embedded data.
- Exporting or adding density isolines / the KDE raster directly to the QGIS project (use Profile → To QGIS or Options → To QGIS layer for points).

See the [issue tracker](https://github.com/acanals/ARSYSplotQGIS/issues) for planned improvements and development updates.

---

## More information

ARSYSplotQGIS is the **QGIS plugin counterpart** of [ARSYSplotLite](https://arche.iphes.cat), a browser-based viewer for archaeological XYZ data. Both tools display **points and orientation vectors**, and provide dedicated **kernel density estimation (KDE)** tools to generate density maps (heatmaps and isolines) from excavation data.

ARSYSplotLite is part of **ArcheSystem → Analytics**. It is the lightweight edition of **ARSYSplot**, the core archaeostratigraphic analysis and visualisation application in the suite.

**Explore the ArcheSystem suite:**

- **<a href="https://arche.iphes.cat" target="_blank" rel="noopener noreferrer">ArcheSystem – Main website</a>**
- **<a href="https://arche.iphes.cat/analytics" target="_blank" rel="noopener noreferrer">ArcheSystem – Analytics</a>** — ARSYSplot and ARSYSplotLite.


**ARSYSplot** focuses on archaeostratigraphy and spatial distribution, and also incorporates taphosedimentary analysis, including the dip and orientation of archaeological objects and other indicators of how materials accumulated and were subsequently reworked within the deposit.

All three tools share the same approach to archaeological data interpretation: examining plans and vertical sections together, applying group filters, and analysing spatial density. Each brings this approach to a different working environment: ARSYSplotQGIS within QGIS, ARSYSplotLite in a web browser, and ARSYSplot as the full Analytics application also in a web browser.

### Continuous development

**ARSYSplot**, the core application in the suite, is an ongoing development project. Its continuous evolution, including new analytical approaches, features and improvements, also benefits **ARSYSplotLite** and **ARSYSplotQGIS**. Although each application has its own interface and working environment, they share the same underlying approach to archaeostratigraphic analysis. Advances in the main application help guide and enrich the development of both complementary tools.

### Why ARSYSplotQGIS?

Archaeological fieldwork and laboratory research often require **the plan and both vertical sections to be examined simultaneously**, using the same dataset and filters. Conventional GIS interfaces, primarily organised around individual map layers, do not provide this kind of integrated archaeostratigraphic workspace.

ARSYSplotQGIS provides a dedicated environment for this type of analysis, directly within QGIS:

- **Three linked 2D views** — plan, longitudinal and transversal sections, all working with the same dataset and filters.
- **Independent workspace** — plugin data and visualisations remain within the plugin's own workspace. Nothing is added to the QGIS project, map canvas or layer legend.
- **Lightweight 3D visualisation** — based on Qt painting rather than the QGIS 3D engine, avoiding compatibility issues encountered with QGIS 3.40.
- **No additional Python dependencies** — relies exclusively on Python libraries and Processing algorithms already included with QGIS.

ARSYSplotQGIS is designed specifically for **archaeostratigraphic data exploration and interpretation**. It is neither a general-purpose GIS editor nor a replacement for the QGIS 3D map view.

### Why QGIS?

QGIS provides an **integrated working environment** in which archaeostratigraphic analysis can be carried out alongside the site's maps, raster data, vector layers and print layouts. ARSYSplotQGIS operates in its own workspace, without modifying the QGIS project, while the rest of the GIS environment remains readily accessible.

QGIS also provides a comprehensive set of **spatial analysis tools widely used in archaeological research**, without requiring additional software:

- Coordinate reference systems, georeferencing and the overlay of excavation grids, DEMs and orthophotos.
- Vector geoprocessing (clipping, buffering and intersection) and spatial queries on features recorded during fieldwork.
- Raster analysis and interpolation, as well as density estimation and contour generation through the Processing framework — including algorithms from the same family used by this plugin to produce heatmaps and isolines.
- Cartographic output through print layouts, together with an extensive plugin ecosystem for heritage management, databases and statistical analysis.

ARSYSplotQGIS is therefore **not simply a browser-based viewer reproduced inside QGIS**. It brings the ArcheSystem approach to archaeostratigraphic analysis directly into the GIS environment where the rest of the archaeological spatial work takes place.