# TOD Asset Explorer

Browse the 3D models, textures and animations of **Total Overdose: A Gunslinger's Tale in
Mexico** (2005, PC) in your web browser, using your own copy of the game.

TOD Asset Explorer has two parts:

* an **extractor** (Python, standard library only) that reads the game's `blocks.naz` archive and
  writes every model, character animation and texture to standard files (`.glb` / `.dds`);
* a **viewer** (a small web app) that lists everything it finds and shows it in 3D.

It ships **without any game content**. You need your own legally obtained copy of the game.

<!-- Screenshots: none are committed, because they would show the game's assets.
     Take your own after extracting and add them here if you fork this. -->
> *Screenshot placeholder: the Geometry tab with a prop selected, and the Animation tab playing a character clip.*

## Features

* **Geometry mode**: every model in the game (~1,300), with its original textures, grouped by
  category (characters, props, vehicles, weapons, vegetation, world) and by map. Includes search.
* **Animation mode**: every character and animated creature with its skeleton and clips. The
  26 humanoid characters each carry the shared ~436-clip library, and the chicken has its own
  11 clips.
  * clip selector, play / pause, next clip, loop, speed (0.05x to 3x)
  * timeline scrubbing and single-frame stepping (1/30 s)
  * **skeleton overlay** (joints and bones, works for skeleton-only rigs too)
* Render options: **wireframe**, double-sided, grid, auto-rotate, three backgrounds, and
  "fit current pose".
* Model inspector: mesh, material, vertex, texture and clip counts, and file size.
* Everything you extract is a plain **glTF 2.0 binary** (`.glb`) that Blender and other 3D tools
  open directly. Textures are standard `.dds` (or `.png` with `--textures png`).

## Requirements

* Your own legal copy of **Total Overdose** for PC. The GOG release was used for validation (see
  [Tested with](#tested-with)).
* **Python 3.8 or newer**, from <https://www.python.org/downloads/>. On Windows, tick *Add
  python.exe to PATH* during setup. No extra packages are needed.
* A modern browser with WebGL (Chrome, Edge, Firefox).
* *Optional, for development only:* Node.js 18+.

## Quick start (Windows)

1. Download `tod-asset-explorer-<version>.zip` from the
   [Releases](../../releases) page and unzip it anywhere.
2. Double-click **`run.bat`**.
3. On first run it asks for your game folder, the one that contains `TOD.exe` and `blocks.naz`
   (for GOG usually `C:\GOG Games\Total Overdose`, which is detected automatically). Extraction
   takes about a minute and writes to `assets\` next to `run.bat`.
4. Your browser opens the viewer. Later runs skip extraction and open the viewer straight away.

You can also pass the folder directly: `run.bat "D:\Games\Total Overdose"`.

**Linux / macOS**: unzip, then run `./run.sh "/path/to/Total Overdose"`. You need a copy of the
game files, for example a Wine or Proton install folder.

## Manual steps

### 1. Extract

```
python extractor/tod_extract.py --game "C:\GOG Games\Total Overdose" --out assets
```

| Option | Meaning |
|---|---|
| `--game PATH` | the install folder (with `blocks.naz`), `blocks.naz` itself, or a folder containing an unpacked `data_pc/` tree |
| `--out DIR` | output folder (default `assets`) |
| `--only LIST` | any of `models,characters,textures` (default: all) |
| `--textures dds\|png\|none` | format for loose texture files (default `dds`; `png` is much slower) |
| `--filter TEXT` | only models whose path contains TEXT, e.g. `--filter chicken` |
| `--skip-existing` | keep `.glb` files that are already there |
| `--list` | list the asset blocks found and exit |
| `--unpack DIR` | just unpack the raw archive into DIR and exit |

Output layout:

```
assets/
  models/<category>/*.glb        every model, textured, bind pose
  characters/*.charanim.glb      humanoids: skinned mesh + skeleton + all compatible clips
  animated/*.charanim.glb        other rigs with their own clips (the chicken)
  textures/**/*.dds              every texture, by its in-game path
  extract_report.json            counts, plus every skipped asset and why
```

A model that fails to convert is skipped and listed in `extract_report.json`. One bad asset never
stops the run.

### 2. Serve the viewer

```
python serve.py --open
```

| Option | Meaning |
|---|---|
| `--assets DIR` | asset folder (default: `$TOD_ASSETS`, else `./assets`) |
| `--port N` | port (default 5190; the next free port is used if taken) |
| `--host ADDR` | bind address (default `127.0.0.1`, this computer only) |
| `--open` | open the browser |

`serve.py` serves the prebuilt viewer from `dist/`, your asset folder under `/assets/`, and a
`manifest.json` that it builds on the fly from whatever `.glb` files are there. Re-extract, reload
the page, and the new files appear.

## Development

```
npm install
npm run dev                                  # http://localhost:5190, hot reload
npm run dev -- --assets "D:\tod\assets"      # use another asset folder
TOD_ASSETS=/path/to/assets npm run dev       # same, via the environment
npm run build                                # production build into dist/
npm run release                              # build + dist-release/tod-asset-explorer-<version>.zip
```

The dev server provides the same `manifest.json` and `/assets/` routes as `serve.py`, from
`scripts/assets.mjs`. `npm run manifest` prints what the viewer would find.

Project layout:

```
extractor/tod_extract.py   command-line extractor
extractor/todx/            format readers: archive, block, model, anim, textures, gltf
serve.py                   no-Node server for the prebuilt viewer
src/                       viewer (React + three.js via @react-three/fiber)
scripts/assets.mjs         asset root + manifest for the dev server
tools/make_release.py      builds and checks the release zip
```

## How it works

1. **Archive**: `blocks.naz` is a stored zip with a changed end-of-directory signature, shifted
   directory fields and bit-rotated file names. The extractor reads it in place and writes
   nothing but the output.
2. **Asset blocks**: the game's `.main`, `.submap`, `.mission` and `.map` files hold compiled
   C++ objects with self-relative pointers. The extractor finds model, texture and animation
   records in them and follows their pointers.
3. **Models**: vertex and index buffers, per-submesh texture bindings, the bone hierarchy and
   skin weights are read and written as glTF. The most detailed LOD is kept.
4. **Animations**: quantized rotation and position tracks are decoded and bound to bones by name,
   the way the engine does it.
5. **Textures**: raw DXT1 / ARGB surfaces get a DDS header. For the `.glb` files they are decoded
   in pure Python and embedded as PNG.
6. **Viewer**: loads each `.glb` with three.js, forces diffuse-style materials, and plays clips
   with a CPU skinning pass.

The format details are in **[FORMATS.md](FORMATS.md)**.

## Tested with

* **GOG release** of Total Overdose (`blocks.naz`, 474,229,592 bytes). The original retail
  `blocks.naz` has the same size and the same asset data. The archives differ only in each level
  file's per-copy editor fingerprint, which the extractor skips.
* Full run on that data: **1,325 models, 26 animated humanoid characters (436 clips each), 1
  animated creature (11 clips) and 4,861 textures, all texture references resolved**, in about a
  minute. 10 engine placeholder models with no geometry are skipped.
* Windows 11, Python 3.12, Chrome/Edge. The extractor is pure Python and should run anywhere
  Python 3.8+ does.

Other releases (retail discs, other languages) use the same `blocks.naz` layout and should work.
If yours doesn't, please open an issue with the output of `--list`.

## Known limitations

* **Characters are mirrored.** Static models are converted to glTF's right-handed axes, but
  character bundles (`characters/`, `animated/`) keep the engine's left-handed coordinates so the
  skeleton and clips stay exactly as the game stores them. They therefore appear left/right
  mirrored, and their triangles face the other way. Double-sided rendering is on by default, so
  this is invisible in the viewer.
* Humanoid clips are matched to a character by skeleton size, so each character gets the whole
  shared library, including clips never used for that character in the game.
* **Materials are approximate.** The game uses fixed-function Direct3D 9 shading with baked
  lighting. The export uses a plain diffuse texture per mesh, with alpha cutout where the texture
  has transparency. Vertex colours, lightmaps, environment maps and texture variants beyond the
  default (paint colours, alternate faces) are not exported.
* Models are exported in bind pose at LOD 0. Level layouts (where each object sits in a map),
  terrain streaming, collision, particles, sounds and videos are not extracted.
* A few models that exist only inside level (`.map`) blocks read their data through runtime
  placeholder fields. They are exported without skin weights, and some may look incomplete.
* The CPU skinning in the viewer is deliberate (GPU skinning distorted these rigs) but is slower
  on very dense meshes.
* `--textures png` decodes in pure Python and takes several minutes for all ~4,900 textures.

## Troubleshooting

| Problem | Fix |
|---|---|
| `could not find Total Overdose game data` | `--game` must point at the folder with `blocks.naz`, not at `TOD.exe` or a parent folder |
| `not a Total Overdose .naz archive` | the file is damaged or from a different game. Verify the install (GOG Galaxy: *Verify / Repair*) |
| `Python was not found` (Windows) | install Python 3 with *Add python.exe to PATH*, or run `py -3 serve.py` |
| The viewer says "No assets yet" | run the extractor, or point the viewer at your folder with `--assets` / `TOD_ASSETS` |
| The viewer says it cannot load `manifest.json` | open it through `serve.py` / `run.bat` / `npm run dev`, not by double-clicking `index.html` |
| Port already in use | `serve.py` automatically tries the next 19 ports. Use `--port` to pick one |
| A model shows "Failed to load" | re-extract it (`--filter <name>`) and check `extract_report.json` |
| The canvas goes blank after many reloads | the browser lost the WebGL context. Reload the page once |
| Some assets were skipped | `extract_report.json` lists each one with the reason. Please report unexpected ones |

## Legal

TOD Asset Explorer is an unofficial fan project for studying and preserving a game you own. It is
**not affiliated with, authorized or endorsed by** the developers or publishers of Total Overdose,
or by the current rights holders.

**No game assets are distributed** with this project. Its repository and releases contain only
original code and documentation. You need your own legally obtained copy of the game, and
extracted files are for your personal use. Respect the game's license agreement and copyright
law. Don't redistribute extracted assets.

*Total Overdose* and all related names, logos and assets are trademarks or copyrighted material
of their respective owners.

## Credits

* File formats were worked out from the game's own data and code. The community reconstruction
  of the engine source, [TOD_tools](https://github.com/Michael0ne/TOD_tools), was a valuable
  reference for engine structure names.
* Viewer built with [three.js](https://threejs.org/),
  [React](https://react.dev/), [@react-three/fiber](https://github.com/pmndrs/react-three-fiber),
  [@react-three/drei](https://github.com/pmndrs/drei) and [Vite](https://vitejs.dev/).

## License

[MIT](LICENSE) © the tod-asset-explorer contributors. The license covers this project's code and
documentation only, not any game content you extract with it.
