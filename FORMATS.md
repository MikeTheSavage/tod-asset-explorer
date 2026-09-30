# Total Overdose data formats (summary)

This is a short, practical summary of the file formats the extractor reads. It covers what you
need to follow the code in `extractor/todx/`. Offsets are hexadecimal and little-endian. Everything
here was worked out by studying the game's own data and code. No game data is reproduced.

## 1. `blocks.naz`: the archive

`blocks.naz` is an ordinary zip archive with every file *stored* (not compressed), plus a few
small changes:

| | normal zip | `.naz` |
|---|---|---|
| end-of-central-directory signature | `50 4B 05 06` | `50 5B ED 16` (u32 `0x16ED5B50`) |
| central-directory record size | 0x2E + name + extra + comment | same |
| uncompressed size / name length / extra length / comment length / local-header offset | +0x18 / +0x1C / +0x1E / +0x20 / +0x2A | **+0x10 / +0x14 / +0x16 / +0x18 / +0x22** |
| file names | plain | every byte rotated right by 2 bits (decode: `(b << 2 \| b >> 6) & 0xFF`) |

A file's data starts at `local_header_offset + 30 + name_length + extra_length`. The local headers
are scrambled too, but you never need to read them. The archive holds about 760 files under
`data_pc/`. The asset blocks we care about are in `data_pc/overdose_the_game/overdose/shared/`, and
the `de/ es/ fr/ it/ uk/` folders hold localized copies.

`archive.py` also accepts a regular zip made from a `.naz`, or a folder with an unpacked
`data_pc/` tree.

## 2. Asset blocks: `.main`, `.submap`, `.mission`, `.map`, `.playerdata`

These are compiled asset containers. The engine loads them almost directly into memory as C++
objects, then fixes up the pointers.

```
[24-byte header]   timestamp, property checksum, command checksum,
                   resource count N (i32), info size, max buffer size
[info buffer]      the compiled asset records
[sizes table]      N x i32: size of each asset's data buffer
[data buffers]     N buffers back to back, in asset order
```

`.map` (level) files have an extra 299-byte editor fingerprint before this header (a 36-byte key,
a 255-byte fingerprint and two u32s). The fingerprint differs between copies of the game. The rest
is identical.

**Pointers** inside the info buffer are *self-relative*: the absolute offset is
`field_offset + (stored_value & ~3)`, and `0` / `0x80000000` mean null. Uninitialized runtime
fields hold debug fill values such as `0xBAADF00D`, so always bounds-check.

Every asset record starts with `u32 type` and a pointer to its name, a path like
`/data/characters/ram/ram.model`. The types used here are 0 = texture, 3 = model and
9 = animation.

## 3. Textures (type 0)

```
TextureAsset  +0x20 -> TextureInfo     +0x28 -> GfxTexture
GfxTexture    +0x14 width   +0x18 height   +0x1C format   +0x28 mip count (u8, unreliable)
format index: 0 R8G8B8, 1 A8R8G8B8, 2 R5G6B5, 3 A1R5G5B5, 4 A4R4G4B4, 5 P8, 7 DXT1, 9 DXT3, 11 DXT5
```

The pixels are the raw surface bits in the block's data buffers, and usually include the whole mip
chain down to 1x1. The game only uses A8R8G8B8 and DXT1. Records are matched to data buffers in
order: each texture takes the next buffer whose size equals its exact payload size. Prepending a
standard 128-byte DDS header gives a normal `.dds` file.

## 4. Models (type 3)

```
ModelAsset
  +0x20  texture reference list (8-byte entries, name pointer at +4)
  +0x30  pivot list, +0x34 pivot count
pivot / bone (stride 0x7C)
  +0x00 position (3 floats)   +0x0C rotation quaternion x,y,z,w (4 floats)
  +0x1C name                  +0x24 mesh-buffer list, +0x28 count
  +0x58 parent pivot index    (not +0x4C: that field is always 0)
SkinnedMeshBuffer (stride 0x3C)
  +0x00 -> MeshBuffer
  +0x08 texture index vector {pointer, count}: entry 0 indexes the model's texture list
  +0x38 flags, low 5 bits = LOD level (0 = most detailed)
MeshBuffer
  +0x0C -> VertexBuffer  { +0x00 count, +0x0C byte length, +0x10 -> data, +0x14 stride (u16) }
  +0x10 -> IndexBuffer   { +0x00 count, +0x04 primitive type (0 = triangle strip), +0x0C -> u16 data }
  +0x44 -> skin records (96 bytes each), +0x48 -> u16 influence count per vertex
```

* **Vertices**: a 32-byte stride is position, normal, UV. With a 36-byte stride a diffuse colour
  sits at +0x18 and the UV moves to +0x1C. A 40-byte stride adds a second UV set.
* **Skinning** (humanoids): each 96-byte skin record has 4 bone indices (i32) at +0x20 and
  4 weights (floats) at +0x40. Skinned vertices are already in model space.
* **Rigid models** (props, the chicken): each mesh is in its pivot's local space and must be
  moved by that pivot's world transform.
* **Rotation convention**: the engine builds bone matrices from the *transpose* of the usual
  quaternion-to-matrix formula. Conjugate each stored quaternion (negate x, y, z) before using it
  in glTF, for bind poses and animation keys alike.
* **Handedness**: the engine is left-handed (Direct3D) and glTF is right-handed. Static models are
  exported with Z negated. That mirror alone turns D3D clockwise-front triangles into glTF
  counter-clockwise-front ones, so the index order is kept.
* Characters store several LODs of each body part. The exporter keeps the most detailed one.

## 5. Animations (type 9)

```
AnimationAsset  +0x28 frame count   +0x5C -> keyframe block
                +0x64 (u16) position stride   +0x66 (u16) rotation stride
keyframe block  +0x00 u32 channel count
                +0x04 one 12-byte record per channel:
                      [0] position data offset (low 24 bits, in 4-byte words; 0 = none)
                      [1] rotation data offset (low 24 bits, in 4-byte words; 0 = none)
                      [2] flags: 0x1000 position static, 0x2000 rotation static,
                          low 12 bits = channel name offset,
                          0x4000 = name is an index into a built-in bone-name table
```

* Position at frame F: 3 floats at `block + 4*(pos_off + (static ? 0 : pos_stride*F*3))`.
* Rotation at frame F: 4 int16 at `block + 4*(rot_off + (static ? 0 : rot_stride*F*2))`, stored in
  **w, x, y, z** order and scaled by 1/32767.
* Clips play at 30 frames per second.
* **Channels bind to bones by name**, case-insensitively. The engine builds a bone remap each time
  a clip starts, and assuming channel N drives bone N scrambles every humanoid. Humanoid clips
  refer to bones through a built-in table of 49 standard 3ds Max Biped names
  (`GamePivot, Bip, Pelvis, Spine, ... R Toe0`), stored in `extractor/todx/gamepivot_names.json`.
* Typically only the root has a position track. Every other bone is rotation-only.
* Humanoid rigs are pelvis-origin. The humanoid clip library (~436 clips) is in `overdose.main`
  and is shared by every biped character. Animal and prop clips are named after their model
  (`chicken_*`).
