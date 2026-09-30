"""ANIMATION assets (type 9): keyframe decode and the per-clip bone remap.

  AnimationAsset: +0x28 frame count, +0x5C keyframe block (self-relative, mask ~3),
                  +0x64 (u16) position-track stride, +0x66 (u16) orientation-track stride
  Keyframe block: +0 u32 channel count, then one 12-byte record per channel at +4:
      rec[0] u32: position data offset (low 24 bits, in 4-byte units; 0 = no position track)
      rec[1] u32: orientation data offset (low 24 bits, in 4-byte units; 0 = none)
      rec[2] u32: bit 0x1000 = position static, bit 0x2000 = orientation static,
                  low 12 bits = channel name offset from the block base,
                  bit 0x4000 = the low 12 bits index a builtin bone-name table instead
  Position(F):    3 floats at base + 4*(posOff + (static ? 0 : stride64*F*3))
  Orientation(F): 4 int16 at base + 4*(oriOff + (static ? 0 : stride66*F*2)), order w,x,y,z, /32767

Channels are bound to model bones by NAME (case-insensitive), exactly as the engine rebuilds its
bone remap each time a clip is set. Humanoid clips name their channels through a builtin table of
49 3ds Max Biped bone names (gamepivot_names.json).
"""
import json
import os
import struct

from .block import u16, u32, i32, i16, f32, deref, cstr, find_records

ANIMATION_TYPE = 9
FPS = 30.0

_GP_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'gamepivot_names.json')
try:
    with open(_GP_PATH) as _f:
        BUILTIN_BONE_NAMES = {i: n for i, n in enumerate(json.load(_f))}
except Exception:
    BUILTIN_BONE_NAMES = {0: 'GamePivot'}


def find_anim_records(info):
    return find_records(info, ANIMATION_TYPE, '.animation')


def frame_time_float32(frame, fps=FPS):
    """Frame time as float32 that never rounds above frame/fps (keeps importers from adding a
    phantom extra frame at the end of a clip)."""
    value = struct.unpack('<f', struct.pack('<f', frame / fps))[0]
    ratio = struct.unpack('<f', struct.pack('<f', value / (1.0 / fps)))[0]
    if ratio > frame:
        bits = struct.unpack('<I', struct.pack('<f', value))[0]
        value = struct.unpack('<f', struct.pack('<I', bits - 1))[0]
    return value


def clip_channel_count(info, base):
    kf = deref(info, base + 0x5C)
    if kf is None:
        return 0
    n = u32(info, kf)
    return n if 0 < n < 4096 else 0


def channel_names(info, base):
    kf = deref(info, base + 0x5C)
    if kf is None:
        return []
    cnt = u32(info, kf)
    if not (0 < cnt < 4096):
        return []
    names = []
    for e in range(cnt):
        hdr = u32(info, kf + 0xC + e * 0xC)
        off = hdr & 0xFFF
        if hdr & 0x4000:
            names.append(BUILTIN_BONE_NAMES.get(off, '__builtin%d__' % off))
        else:
            end = info.find(b'\0', kf + off)
            names.append(info[kf + off:end].decode('latin-1', 'replace'))
    return names


def derive_remap(info, base, pivots):
    """remap[model_bone] -> channel index (or -1)."""
    lut = {}
    for e, nm in enumerate(channel_names(info, base)):
        if nm:
            lut.setdefault(nm.lower(), e)
    return [lut.get((p.get('name') or '').lower(), -1) if p.get('name') else -1 for p in pivots]


def decode_anim(info, base, npivots, remap=None):
    """-> {'frames': N, 'tracks': [{'rot': [(x,y,z,w)]|None, 'pos': [(x,y,z)]|None} per bone]}"""
    frames = i32(info, base + 0x28)
    kf = deref(info, base + 0x5C)
    f64 = u16(info, base + 0x64)
    f66 = u16(info, base + 0x66)
    if kf is None or frames <= 0 or frames > 100000:
        return None
    nentry = u32(info, kf)
    nmax = nentry if 0 < nentry < 4096 else npivots
    tracks = []
    for pi in range(npivots):
        ei = remap[pi] if (remap is not None and pi < len(remap)) else pi
        if ei is None or ei < 0 or ei >= nmax:
            tracks.append({'rot': None, 'pos': None})
            continue
        e = kf + 4 + ei * 12
        posoff = u32(info, e) & 0xFFFFFF
        orioff = u32(info, e + 4) & 0xFFFFFF
        sflags = u32(info, e + 8)
        rot = pos = None
        if orioff:
            rot = []
            for F in range(frames):
                a = kf + 4 * (orioff + (0 if (sflags & 0x2000) else f66 * F * 2))
                w, x, y, z = (i16(info, a) / 32767.0, i16(info, a + 2) / 32767.0,
                              i16(info, a + 4) / 32767.0, i16(info, a + 6) / 32767.0)
                rot.append((x, y, z, w))
        if posoff:
            pos = []
            for F in range(frames):
                a = kf + 4 * (posoff + (0 if (sflags & 0x1000) else f64 * F * 3))
                pos.append((f32(info, a), f32(info, a + 4), f32(info, a + 8)))
        tracks.append({'rot': rot, 'pos': pos})
    return {'frames': frames, 'tracks': tracks}


def clip_name(record_name):
    return os.path.splitext(os.path.basename(record_name))[0]
