"""TEXTURE assets (type 0): locate them in blocks, rebuild .dds files, decode to RGBA / PNG.

  CompiledTextureAsset: +0x20 TextureInfo ptr, +0x28 GfxTexture ptr
  GfxTexture: +0x14 width, +0x18 height, +0x1C format (index into FORMATS), +0x28 mip count (u8)
"""
import os
import struct
import zlib

TEXTURE = 0

from .block import u32, i32, cstr, deref

FORMATS = ["R8G8B8", "A8R8G8B8", "R5G6B5", "A1R5G5B5", "A4R4G4B4", "P8", "UNKNOWN",
           "DXT1", "DXT2", "DXT3", "DXT4", "DXT5"]
_BYTES_PER_PIXEL = {0: 3, 1: 4, 2: 2, 3: 2, 4: 2, 5: 1}


def _level_size(w, h, fmt):
    if fmt == 7:
        return max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * 8
    if fmt in (8, 9, 10, 11):
        return max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * 16
    return w * h * _BYTES_PER_PIXEL.get(fmt, 4)


def payload_sizes(w, h, fmt):
    """Possible data-buffer sizes: the full mip chain down to 1x1 (the normal case - the stored
    mip-count field is not reliable), or just the top level."""
    total, ww, hh = 0, w, h
    while True:
        total += _level_size(ww, hh, fmt)
        if ww == 1 and hh == 1:
            break
        ww, hh = max(1, ww >> 1), max(1, hh >> 1)
    return total, _level_size(w, h, fmt)


def mip_count(w, h):
    n = 1
    while w > 1 or h > 1:
        w, h = max(1, w >> 1), max(1, h >> 1)
        n += 1
    return n


def iter_textures(block):
    """Yield (name, width, height, format_index, mips, data_offset, data_size) for every texture.

    Texture records are found by shape: a 16-aligned record of type 0 whose name is a '/...'
    path, with TextureInfo (+0x20) and GfxTexture (+0x28) pointing just after it and a sane
    width/height/format in the GfxTexture. Pixel data lives in the block's data buffers, in asset
    order, so records (in info-buffer order) are paired with the next data buffer whose size is
    exactly that texture's payload size. On blocks where the asset records can be walked one by
    one this pairing is identical to the walk; unlike the walk it does not lose its place in
    level blocks full of record types whose size is not known.
    """
    info = block.info
    n = len(info)
    cands = []
    for p in range(0, n - 0x30, 16):
        if u32(info, p) != TEXTURE:
            continue
        nm = deref(info, p + 4)
        if nm is None or nm >= n or info[nm:nm + 1] != b'/':
            continue
        g = (p + 0x28 + u32(info, p + 0x28)) & 0xFFFFFFFF
        ti = (p + 0x20 + u32(info, p + 0x20)) & 0xFFFFFFFF
        if not (p < g < p + 0x10000 and g + 0x29 <= n and p < ti < p + 0x10000):
            continue
        w, h, fmt = u32(info, g + 0x14), u32(info, g + 0x18), i32(info, g + 0x1C)
        if not (0 < w <= 8192 and 0 < h <= 8192 and 0 <= fmt < len(FORMATS)):
            continue
        cands.append((cstr(info, nm), w, h, fmt))
    j = 0
    for (name, w, h, fmt) in cands:
        want = payload_sizes(w, h, fmt)
        k = j
        while k < len(block.sizes) and block.sizes[k] not in want:
            k += 1
        if k >= len(block.sizes):
            continue
        off, size = block.bufs[k]
        mips = mip_count(w, h) if size == want[0] else 1
        yield name, w, h, fmt, mips, off, size
        j = k + 1


def dds_header(w, h, fmt, mips, datasize):
    flags = 0x1 | 0x2 | 0x4 | 0x1000 | (0x8 if fmt == 1 else 0x80000) | (0x20000 if mips > 1 else 0)
    pitch = 4 if fmt == 1 else datasize
    pf_flags = (0x40 | 0x1) if fmt == 1 else 0x4
    fourcc = b'\0\0\0\0' if fmt == 1 else (FORMATS[fmt].encode('ascii') + b'\0\0\0\0')[:4]
    rgb = 32 if fmt == 1 else 0
    rm, gm, bm, am = (0x00ff0000, 0x0000ff00, 0x000000ff, 0xFF000000) if fmt == 1 else (0, 0, 0, 0)
    hd = struct.pack('<7I', 124, flags, h, w, pitch, 0, mips)
    hd += b'\0' * 44
    hd += struct.pack('<2I', 32, pf_flags) + fourcc + struct.pack('<5I', rgb, rm, gm, bm, am)
    caps = 0x1000 | (0x400008 if mips > 1 else 0)
    hd += struct.pack('<5I', caps, 0, 0, 0, 0)
    return b'DDS ' + hd


# ---------------------------------------------------------------- DDS -> RGBA (pure Python)

def _rgb565(c):
    r = (c >> 11) & 0x1f; g = (c >> 5) & 0x3f; b = c & 0x1f
    return ((r * 527 + 23) >> 6, (g * 259 + 33) >> 6, (b * 527 + 23) >> 6)


def decode_dds(d):
    """DDS bytes -> (width, height, rgba bytes). DXT1/3/5 and uncompressed RGB(A)."""
    if d[:4] != b'DDS ':
        raise ValueError('not a DDS')
    h = struct.unpack_from('<I', d, 12)[0]
    w = struct.unpack_from('<I', d, 16)[0]
    fourcc = d[84:88]
    off = 128
    px = bytearray(w * h * 4)

    def putblock(bx, by, colors, cidx, alphas=None):
        for py in range(4):
            y = by * 4 + py
            if y >= h:
                continue
            for pxl in range(4):
                x = bx * 4 + pxl
                if x >= w:
                    continue
                k = py * 4 + pxl
                r, g, b = colors[(cidx >> (2 * k)) & 3]
                o = (y * w + x) * 4
                px[o] = r; px[o + 1] = g; px[o + 2] = b
                px[o + 3] = 255 if alphas is None else alphas[k]

    bxs = (w + 3) // 4
    bys = (h + 3) // 4
    if fourcc == b'DXT1':
        for by in range(bys):
            for bx in range(bxs):
                c0, c1, idx = struct.unpack_from('<HHI', d, off); off += 8
                a, b = _rgb565(c0), _rgb565(c1)
                if c0 > c1:
                    c2 = tuple((2 * a[k] + b[k]) // 3 for k in range(3))
                    c3 = tuple((a[k] + 2 * b[k]) // 3 for k in range(3))
                    putblock(bx, by, [a, b, c2, c3], idx)
                else:
                    c2 = tuple((a[k] + b[k]) // 2 for k in range(3))
                    putblock(bx, by, [a, b, c2, (0, 0, 0)], idx)
    elif fourcc in (b'DXT3', b'DXT5', b'DXT2', b'DXT4'):
        for by in range(bys):
            for bx in range(bxs):
                ablock = d[off:off + 8]; off += 8
                c0, c1, idx = struct.unpack_from('<HHI', d, off); off += 8
                a, b = _rgb565(c0), _rgb565(c1)
                c2 = tuple((2 * a[k] + b[k]) // 3 for k in range(3))
                c3 = tuple((a[k] + 2 * b[k]) // 3 for k in range(3))
                if fourcc in (b'DXT3', b'DXT2'):
                    bits = int.from_bytes(ablock, 'little')
                    alphas = [((bits >> (4 * i)) & 0xf) * 17 for i in range(16)]
                else:
                    a0, a1 = ablock[0], ablock[1]
                    abits = int.from_bytes(ablock[2:], 'little')
                    al = [a0, a1]
                    if a0 > a1:
                        for i in range(1, 7): al.append(((7 - i) * a0 + i * a1) // 7)
                    else:
                        for i in range(1, 5): al.append(((5 - i) * a0 + i * a1) // 5)
                        al += [0, 255]
                    alphas = [al[(abits >> (3 * i)) & 7] for i in range(16)]
                putblock(bx, by, [a, b, c2, c3], idx, alphas)
    elif fourcc == b'\0\0\0\0' or struct.unpack_from('<I', d, 80)[0] & 0x40:
        bpp = struct.unpack_from('<I', d, 88)[0] or 32
        rm, gm, bm, am = struct.unpack_from('<IIII', d, 92)

        def shift(mask):
            if not mask:
                return None
            s = 0
            while not (mask >> s) & 1:
                s += 1
            return s
        sr, sg, sb, sa = shift(rm), shift(gm), shift(bm), shift(am)
        bypp = bpp // 8
        for y in range(h):
            for x in range(w):
                o = off + (y * w + x) * bypp
                v = int.from_bytes(d[o:o + bypp], 'little')
                po = (y * w + x) * 4
                px[po] = (v & rm) >> sr if sr is not None else 0
                px[po + 1] = (v & gm) >> sg if sg is not None else 0
                px[po + 2] = (v & bm) >> sb if sb is not None else 0
                px[po + 3] = (v & am) >> sa if sa is not None else 255
    else:
        raise ValueError('unsupported DDS format %r' % fourcc)
    return w, h, bytes(px)


def rgba_to_png(w, h, rgba):
    raw = bytearray()
    row = w * 4
    for y in range(h):
        raw.append(0)
        raw += rgba[y * row:(y + 1) * row]

    def chunk(t, dat):
        return struct.pack('>I', len(dat)) + t + dat + struct.pack('>I', zlib.crc32(t + dat) & 0xffffffff)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(bytes(raw), 6)) + chunk(b'IEND', b''))


def has_transparency(rgba):
    mn = 255
    for i in range(3, len(rgba), 4 * 5):
        if rgba[i] < mn:
            mn = rgba[i]
            if mn < 16:
                return True
    return mn < 200


# ---------------------------------------------------------------- texture index across blocks

def _key(name):
    return os.path.splitext(name.lstrip('/').replace('\\', '/'))[0].lower()


class TextureIndex:
    """Every texture record in the game, looked up by the reference strings models carry.

    Resolution order for a model's texture reference (e.g. '/data/textures/x/civil_face_1.bmp'):
      1. exact path (without extension);
      2. variant: '<path>_*' - vehicles/props reference a base name, the data holds paint variants;
      3. same file name anywhere - a few props reference a folder that differs from the data.
    """
    def __init__(self, src, log=print):
        self.src = src
        self.entries = {}          # key -> (block name, name, w, h, fmt, mips, off, size)
        self._by_base = {}
        self._cache = {}
        self._png = {}
        self._blocks = {}          # small LRU of raw block bytes

    def add_block(self, block_name, block):
        n = 0
        for (name, w, h, fmt, mips, off, size) in iter_textures(block):
            k = _key(name)
            if k not in self.entries:
                self.entries[k] = (block_name, name, w, h, fmt, mips, off, size)
                self._by_base.setdefault(os.path.basename(k), k)
                n += 1
        return n

    def _sorted_keys(self):
        if not hasattr(self, '_sk'):
            self._sk = sorted(self.entries)
        return self._sk

    def resolve(self, ref):
        if not ref:
            return None
        k = _key(ref)
        if k in self.entries:
            return k
        import bisect
        keys = self._sorted_keys()
        for prefix in (k + '_', k):
            i = bisect.bisect_left(keys, prefix)
            if i < len(keys) and keys[i].startswith(prefix):
                return keys[i]
        bn = os.path.basename(k)
        if bn in self._by_base:
            return self._by_base[bn]
        for b, kk in self._by_base.items():
            if b.startswith(bn + '_'):
                return kk
        return None

    def dds(self, key):
        """Rebuilt .dds bytes for an index key."""
        block_name, _name, w, h, fmt, mips, off, size = self.entries[key]
        data = self._blocks.pop(block_name, None)
        if data is None:
            data = self.src.read(block_name)
        self._blocks[block_name] = data
        while len(self._blocks) > 6:
            self._blocks.pop(next(iter(self._blocks)))
        return dds_header(w, h, fmt, mips, size) + data[off:off + size]

    def png_for_ref(self, ref):
        """-> (png bytes or None, has_alpha, resolved key or None). Cached per key."""
        key = self.resolve(ref)
        if key is None:
            return None, False, None
        if key not in self._png:
            try:
                w, h, rgba = decode_dds(self.dds(key))
                self._png[key] = (rgba_to_png(w, h, rgba), has_transparency(rgba))
            except Exception:
                self._png[key] = (None, False)
        png, alpha = self._png[key]
        return png, alpha, key

    def rel_path(self, key, ext):
        return key + ext
