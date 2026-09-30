"""MODEL asset (type 3) -> pivots, meshes, skin weights and texture references.

Walk (see FORMATS.md):
  ModelAsset: +0x20 TextureReferencesList (8-byte refs, name ptr @+4), +0x30 pivot list, +0x34 count
    pivot (stride 0x7C): +0x00 pos(3f) +0x0C quat(4f) +0x1C name +0x24 SkinnedMeshBuffer list
                         +0x28 count  +0x58 parent index
      SkinnedMeshBuffer (stride 0x3C): +0x00 MeshBuffer, +0x08 texture-ref index vector,
                                      +0x38 flags (low 5 bits = LOD)
        MeshBuffer: +0x0C VertexBuffer, +0x10 IndexBuffer, +0x44 skin records, +0x48 influence counts
          VertexBuffer: +0x00 count, +0x0C byte length, +0x10 data, +0x14 stride (u16)
          IndexBuffer : +0x00 count, +0x04 primitive type (0 = strip), +0x0C u16 data
"""
import struct

from .block import u16, u32, i32, f32, deref, cstr, find_records

MODEL_TYPE = 3


def find_model_records(info):
    return find_records(info, MODEL_TYPE, '.model')


def _parse_vertex(buf, off, stride):
    p = (f32(buf, off), f32(buf, off + 4), f32(buf, off + 8))
    n = (f32(buf, off + 12), f32(buf, off + 16), f32(buf, off + 20))
    uvo = 28 if stride == 36 else 24          # a diffuse DWORD sits at +24 when stride == 36
    uv = (f32(buf, off + uvo), f32(buf, off + uvo + 4))
    return p, uv, n


def extract_model(info, base, name):
    """Returns {'name','pivots','meshes','textures'} or None.

    Each pivot: pos, quat (x,y,z,w as stored), name, parent (+0x58), nSkin.
    Each mesh: pivot, isTriangles, verts [(pos, uv, normal)], indices, skinned, joints, weights,
               texidx, source_flags (LOD in the low 5 bits).
    """
    texrefs = []
    tl = deref(info, base + 0x20)
    tc = i32(info, base + 0x24)
    if tl is not None and 0 < tc < 4096:
        for ti in range(tc):
            texrefs.append(cstr(info, deref(info, tl + ti * 8 + 0x04)))
    piv_ptr = deref(info, base + 0x30)
    piv_cnt = i32(info, base + 0x34)
    if piv_ptr is None or not (0 < piv_cnt < 4096):
        return None
    pivots, meshes = [], []
    for pi in range(piv_cnt):
        pv = piv_ptr + pi * 0x7C
        pivots.append({
            'pos': [f32(info, pv), f32(info, pv + 4), f32(info, pv + 8)],
            'quat': [f32(info, pv + 0x0C), f32(info, pv + 0x10), f32(info, pv + 0x14), f32(info, pv + 0x18)],
            'name': cstr(info, deref(info, pv + 0x1C), 48),
            # The real hierarchy is at +0x58. (+0x4C is 0 for every bone and gives a flat skeleton
            # that looks right in bind pose but falls apart under animation.)
            'parent': i32(info, pv + 0x58),
            'nSkin': 0,
        })
        sm_ptr = deref(info, pv + 0x24)
        sm_cnt = i32(info, pv + 0x28)
        if sm_ptr is None or not (0 < sm_cnt < 4096):
            continue
        pivots[pi]['nSkin'] = sm_cnt
        for si in range(sm_cnt):
            sm = sm_ptr + si * 0x3C
            mb = deref(info, sm)
            if mb is None:
                continue
            # Per-submesh texture: model TextureReferencesList[ m_TextureReferences[0] ].
            tr_b = deref(info, sm + 0x08)
            tr_c = i32(info, sm + 0x0C)
            texidx = i32(info, tr_b) if (tr_b is not None and 0 < tr_c < 4096) else -1
            vb = deref(info, mb + 0x0C)
            ib = deref(info, mb + 0x10)
            if vb is None or ib is None:
                continue
            vcount = i32(info, vb)          # +0x04 ("list size") is 0 in compiled assets
            vlen = i32(info, vb + 0x0C)
            stride = u16(info, vb + 0x14)
            vbuf = deref(info, vb + 0x10)
            icount = i32(info, ib)
            ibuf = deref(info, ib + 0x0C)
            if vbuf is None or ibuf is None or stride not in (32, 36, 40):
                continue
            if vcount <= 0 or vcount > 200000 or vlen != vcount * stride:
                continue
            skin_ptr = deref(info, mb + 0x44)
            infl_ptr = deref(info, mb + 0x48)
            # Level (.map) blocks leave runtime placeholder values (0xBAAD....) in these fields:
            # only treat the mesh as skinned when both streams really fit in the buffer.
            skinned = (skin_ptr is not None and infl_ptr is not None
                       and skin_ptr + vcount * 96 <= len(info) and infl_ptr + vcount * 2 <= len(info))
            verts, joints, weights = [], [], []
            for vi in range(vcount):
                verts.append(_parse_vertex(info, vbuf + vi * stride, stride))
                if skinned:
                    rec = skin_ptr + vi * 96
                    ninf = u16(info, infl_ptr + vi * 2)
                    ninf = max(1, min(4, ninf if 0 < ninf <= 4 else 1))
                    bi = [i32(info, rec + 0x20 + k * 4) for k in range(4)]
                    wt = [f32(info, rec + 0x40 + k * 4) for k in range(4)]
                    jj = [(bi[k] if (k < ninf and 0 <= bi[k] < piv_cnt) else 0) for k in range(4)]
                    ww = [(wt[k] if k < ninf else 0.0) for k in range(4)]
                    s = sum(ww) or 1.0
                    joints.append(jj)
                    weights.append([w / s for w in ww])
            if 0 < icount < 4000000:
                indices = list(struct.unpack_from('<%dH' % icount, info, ibuf))
            else:
                indices = []
            flags = u32(info, sm + 0x38)
            meshes.append({'pivot': pi, 'isTriangles': 1 if i32(info, ib + 0x04) else 0,
                           'verts': verts, 'indices': indices, 'skinned': skinned,
                           'joints': joints, 'weights': weights, 'texidx': texidx,
                           'source_flags': flags})
    return {'name': name, 'pivots': pivots, 'meshes': meshes, 'textures': texrefs}


def is_biped(model):
    names = {p['name'] for p in model['pivots']}
    return 'Bip' in names and 'Pelvis' in names and 'Spine' in names and len(model['pivots']) >= 20
