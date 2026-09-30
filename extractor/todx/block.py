"""Compiled asset blocks (.main / .submap / .mission / .map / .playerdata).

Layout (little-endian; .map files have a 299-byte prefix, see MAP_PREFIX):
  24-byte header: timestamp, property-list checksum, command-list checksum,
                  resource count (i32), info-buffer size, max data-buffer size
  info buffer     compiled asset records (C++ objects with self-relative pointers)
  sizes table     resource count * i32, per-asset data-buffer size
  data buffers    concatenated raw payloads (texture surface bits etc.)

Self-relative pointer: abs = field_offset + (stored & ~3); 0 and 0x80000000 mean null.
"""
import struct

# .map level files start with an editor fingerprint before the normal header:
# 36-byte file key + 255-byte fingerprint + two u32 fields = 299 bytes.
MAP_PREFIX = 299


def u32(b, o): return struct.unpack_from('<I', b, o)[0]
def i32(b, o): return struct.unpack_from('<i', b, o)[0]
def u16(b, o): return struct.unpack_from('<H', b, o)[0]
def i16(b, o): return struct.unpack_from('<h', b, o)[0]
def f32(b, o): return struct.unpack_from('<f', b, o)[0]


class Block:
    """One asset block held in memory."""
    def __init__(self, data, name=''):
        for hdr in (0, MAP_PREFIX):
            if len(data) < hdr + 24:
                continue
            _ts, _pck, _cck, total, infosize, _maxbuf = struct.unpack_from('<IIIiII', data, hdr)
            if 0 < total < 100000 and 0 < infosize < len(data) - hdr - 24 - total * 4:
                break
        else:
            raise ValueError('not an asset block (unexpected header)')
        self.name = name
        self.data = data
        self.total = total
        self.info = data[hdr + 24:hdr + 24 + infosize]
        sz_off = hdr + 24 + infosize
        self.sizes = list(struct.unpack_from('<%di' % total, data, sz_off))
        o = sz_off + total * 4
        self.bufs = []
        for s in self.sizes:
            self.bufs.append((o, s))
            o += max(0, s)


def deref(info, field_abs):
    v = u32(info, field_abs)
    if v == 0 or v == 0x80000000:
        return None
    return (field_abs + (v & 0xFFFFFFFC)) & 0xFFFFFFFF


def cstr(info, off, n=256):
    # 256, not 64: long paths (e.g. vehicle and some character folders) were silently cut before
    # the extension with a shorter limit and the asset disappeared.
    if off is None or off < 0 or off >= len(info):
        return ''
    return info[off:off + n].split(b'\0', 1)[0].decode('latin-1', 'replace')


def find_records(info, type_id, suffix):
    """All 16-aligned asset records of `type_id` whose name is a '/...<suffix>' path."""
    recs = []
    n = len(info)
    for p in range(0, n - 8, 16):
        if u32(info, p) != type_id:
            continue
        npos = deref(info, p + 4)
        if npos is None or npos >= n or info[npos:npos + 1] != b'/':
            continue
        name = cstr(info, npos)
        if name.lower().endswith(suffix):
            recs.append((p, name))
    return recs
