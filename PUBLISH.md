# Publicar ARSYSplotQGIS (GitHub + plugins.qgis.org)

Normes: [Releasing your plugin](https://docs.qgis.org/3.40/en/docs/pyqgis_developer_cookbook/plugins/releasing.html) · [How to publish](https://plugins.qgis.org/docs/publish) · [Approval](https://plugins.qgis.org/docs/approval)

Aquest fitxer és per a qui puja el plugin. No va dins del ZIP (`make zip` l’exclou). L’usuari llegeix el **README** (anglès), que és la `homepage`.

## Obligatori (si falta, el repositori oficial el rebutja)

| Requeriment | Estat |
| --- | --- |
| `metadata.txt` UTF-8: name, version, description, about, author, **email**, qgisMinimumVersion, **repository** | Omplert (0.2.2) |
| `about` i `description` en **anglès**, sense HTML | Sí |
| `LICENSE` **sense extensió**, GPL-2 o posterior | `LICENSE` = GPL-2.0-or-later |
| `__init__.py` amb `classFactory` | Sí |
| Carpeta `ARSYSplotQGIS` (ASCII, sense la paraula `plugin`) | Sí |
| Documentació mínima + dades de prova | `README.md`, `index.html` (Help), `sample.csv` |
| `homepage` = README d’ús; `tracker` = issues; `repository` = codi públic (no un ZIP) | URLs a `metadata.txt` |
| ZIP amb la carpeta a dins, sense `__pycache__`, `.git`, binaris | `make zip` |
| Sense dependències pip no declarades | Cap (només Processing de QGIS) |
| Mida &lt; 25 MB | OK |
| Icona PNG | `ArcheIcon.png` |
| Menú adequat | Vector (+ toolbar + Help → Plugins) |
| `experimental=False` (versió estable) | Sí |
| `changelog` amb el número de versió | 0.2.2 / 0.2.1 / 0.2.0 / 0.1.1 / 0.1.0 |
| El ZIP i el GitHub han de ser el **mateix** codi | Comprova abans de pujar |

**Llicència:** QGIS és GPL-2+. CC BY-NC-SA **no** és compatible i el plugin seria rebutjat. Aquest complement és GPL-2.0-or-later. ARSYSplot / ARSYSplotLite al navegador poden continuar amb una altra llicència.

**About:** el camp `about` de `metadata.txt` és el text que veu el revisor i el Plugin Manager. Ha de dir què fa el plugin, què **no** fa (no pinta al mapa de QGIS; el 3D no és QGIS 3D), requisits i llicència. El README amplia el mateix.

## Funcions que ha de reflectir la documentació (0.2.0)

- Finestra pròpia: plan X/Y, longitudinal X/Z, transversal Y/Z
- Import CSV (P1 centre, P2/P3 vector), Load sample, Use selected layer
- Filtres de grup (xips de color, All/None) i rang XYZ
- Adaptive frame, Draw (Points / Vectors / Both / None), mides
- Density: heatmap i/o isolines, paletes, Min/Max, Auto 2%, radius, cell, 5 kernels
- Zoom per vista, export PNG (eixos, llegenda, dpi)
- 3D Qt (òrbita / pan / zoom), sense QGIS 3D ni paquets pip
- Reset; capes privades (fora del mapa i la llegenda de QGIS)

## 1. Compte OSGeo

1. Crea un ID a <https://www.osgeo.org/community/getting-started-osgeo/osgeo_userid/>
2. El mateix usuari serveix a <https://plugins.qgis.org/>

## 2. Repositori GitHub públic

`metadata.txt` apunta a:

- <https://github.com/acanals/ARSYSplotQGIS>
- issues: `…/ARSYSplotQGIS/issues`

Crea **aquest** repositori públic (o canvia `repository`, `tracker` i `homepage`).

L’arrel del GitHub ha de ser **aquesta carpeta** (`metadata.txt` a l’arrel, no tot Analytics):

```bash
cd /path/to/ARSYSplotQGIS
git init
git add .
git commit -m "ARSYSplotQGIS 0.2.0"
git branch -M main
git remote add origin git@github.com:acanals/ARSYSplotQGIS.git
git push -u origin main
```

No hi pengis `__pycache__` ni ZIP (ja estan al `.gitignore`). Després de l’aprovació pots afegir captures a la fitxa de plugins.qgis.org.

## 3. ZIP per pujar a QGIS

```bash
cd /path/to/ARSYSplotQGIS
make zip
```

Surt `dist/ARSYSplotQGIS.0.2.2.zip`. Comprova:

```
ARSYSplotQGIS.0.2.2.zip
└── ARSYSplotQGIS/
    ├── metadata.txt
    ├── __init__.py
    ├── LICENSE
    ├── README.md
    ├── index.html
    ├── ArcheIcon.png
    ├── sample.csv
    └── …
```

`version=` a `metadata.txt` ha de coincidir amb el nom del ZIP. Cada pujada necessita un número **nou**.

## 4. Pujar a plugins.qgis.org

1. <https://plugins.qgis.org/plugins/upload/>
2. Puja el ZIP.
3. Deixa **experimental** desmarcat (el ZIP ja porta `experimental=False`).
4. Rebràs un correu de recepció i un altre de l’escaneig de seguretat.
5. Un voluntari aprova (minuts o dies; cap de setmana → dilluns). Si `homepage` no descriu l’ús, el rebutgen: el README de GitHub és l’enllaç correcte.

## 5. Versions següents

Actualitza `changelog` a `metadata.txt` i el README si canvia el comportament. Puja un ZIP nou; no reutilitzis el número de versió.
