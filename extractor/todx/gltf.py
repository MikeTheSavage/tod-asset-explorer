"""glTF 2.0 binary (.glb) writers for static props and animated characters."""
import json
import os
import struct

from .anim import frame_time_float32, FPS


# ------------------------------------------------------------------ math

def quat_mat(q):
    x, y, z, w = q
    return [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]


def mul44(A, B):
    return [[sum(A[i][k] * B[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def trs(pos, q):
    R = quat_mat(q)
    return [[R[0][0], R[0][1], R[0][2], pos[0]],
            [R[1][0], R[1][1], R[1][2], pos[1]],
            [R[2][0], R[2][1], R[2][2], pos[2]],
            [0, 0, 0, 1]]


def world_mats(pivots):
    out = [None] * len(pivots)

    def get(i, depth=0):
        if out[i] is not None:
            return out[i]
        L = trs(pivots[i]['pos'], pivots[i]['quat'])
        par = pivots[i]['parent']
        if 0 <= par < len(pivots) and par != i and depth < 512:
            out[i] = mul44(get(par, depth + 1), L)
        else:
            out[i] = L
        return out[i]
    for i in range(len(pivots)):
        get(i)
    return out


def xform(M, p):
    return (M[0][0] * p[0] + M[0][1] * p[1] + M[0][2] * p[2] + M[0][3],
            M[1][0] * p[0] + M[1][1] * p[1] + M[1][2] * p[2] + M[1][3],
            M[2][0] * p[0] + M[2][1] * p[1] + M[2][2] * p[2] + M[2][3])


def xform3(M, n):
    return (M[0][0] * n[0] + M[0][1] * n[1] + M[0][2] * n[2],
            M[1][0] * n[0] + M[1][1] * n[1] + M[1][2] * n[2],
            M[2][0] * n[0] + M[2][1] * n[1] + M[2][2] * n[2])


def inv_rigid(M):
    RT = [[M[j][i] for j in range(3)] for i in range(3)]
    t = [M[i][3] for i in range(3)]
    nt = [-(RT[i][0] * t[0] + RT[i][1] * t[1] + RT[i][2] * t[2]) for i in range(3)]
    return [RT[0] + [nt[0]], RT[1] + [nt[1]], RT[2] + [nt[2]], [0, 0, 0, 1]]


def colmajor(M):
    return [M[r][c] for c in range(4) for r in range(4)]


def conj(q):
    """The engine's bone rotation is the transpose of the usual quaternion->matrix convention,
    so every stored quaternion is conjugated before use in glTF."""
    return [-q[0], -q[1], -q[2], q[3]]


def strip_to_tris(idx):
    out = []
    for i in range(len(idx) - 2):
        a, b, c = idx[i], idx[i + 1], idx[i + 2]
        if a == b or b == c or a == c:
            continue
        out += [a, c, b] if (i & 1) else [a, b, c]
    return out


# ------------------------------------------------------------------ container

class GlbBuilder:
    def __init__(self):
        self.blob = bytearray()
        self.bufferViews = []
        self.accessors = []
        self.images = []
        self.textures = []
        self.materials = []
        self._img_by_key = {}

    def _pack(self, data):
        while len(self.blob) % 4:
            self.blob.append(0)
        o = len(self.blob)
        self.blob.extend(data)
        return o, len(data)

    def view(self, data):
        o, l = self._pack(data)
        self.bufferViews.append({'buffer': 0, 'byteOffset': o, 'byteLength': l})
        return len(self.bufferViews) - 1

    def accessor(self, data, comp, typ, count, mn=None, mx=None):
        a = {'bufferView': self.view(data), 'componentType': comp, 'count': count, 'type': typ}
        if mn is not None:
            a['min'] = mn
            a['max'] = mx
        self.accessors.append(a)
        return len(self.accessors) - 1

    def floats(self, rows, typ, bounds=False):
        n = len(rows[0]) if rows else 1
        flat = [c for r in rows for c in r]
        mn = mx = None
        if bounds and rows:
            mn = [min(r[i] for r in rows) for i in range(n)]
            mx = [max(r[i] for r in rows) for i in range(n)]
        return self.accessor(struct.pack('<%df' % len(flat), *flat), 5126, typ, len(rows), mn, mx)

    def indices(self, idx):
        return self.accessor(struct.pack('<%dI' % len(idx), *idx), 5125, 'SCALAR', len(idx))

    def material(self, png, key, alpha=False, name=None):
        """One material per distinct texture; returns the material index."""
        if key in self._img_by_key:
            return self._img_by_key[key]
        self.images.append({'bufferView': self.view(png), 'mimeType': 'image/png'})
        self.textures.append({'source': len(self.images) - 1})
        mat = {'pbrMetallicRoughness': {'baseColorTexture': {'index': len(self.textures) - 1},
                                        'metallicFactor': 0.0, 'roughnessFactor': 1.0},
               'doubleSided': True}
        if name:
            mat['name'] = name
        if alpha:
            mat['alphaMode'] = 'MASK'
            mat['alphaCutoff'] = 0.5
        self.materials.append(mat)
        self._img_by_key[key] = len(self.materials) - 1
        return self._img_by_key[key]

    def gltf(self, generator, **rest):
        g = {'asset': {'version': '2.0', 'generator': generator},
             'buffers': [{'byteLength': len(self.blob)}],
             'bufferViews': self.bufferViews, 'accessors': self.accessors}
        if self.images:
            g['images'] = self.images
            g['textures'] = self.textures
            g['materials'] = self.materials
        g.update(rest)
        return g


def write_glb(path, gltf, blob):
    j = json.dumps(gltf, separators=(',', ':')).encode('utf-8')
    j += b' ' * ((4 - len(j) % 4) % 4)
    b = bytes(blob) + b'\0' * ((4 - len(blob) % 4) % 4)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + '.part'
    with open(tmp, 'wb') as f:
        f.write(struct.pack('<III', 0x46546C67, 2, 12 + 8 + len(j) + 8 + len(b)))
        f.write(struct.pack('<II', len(j), 0x4E4F534A))
        f.write(j)
        f.write(struct.pack('<II', len(b), 0x004E4942))
        f.write(b)
    os.replace(tmp, path)


def _texture_for_mesh(model, mi, mesh):
    ti = mesh.get('texidx', -1)
    if not (0 <= ti < len(model['textures'])):
        ti = mi if mi < len(model['textures']) else 0
    return model['textures'][ti] if model['textures'] else None


# ------------------------------------------------------------------ static props

def _is_ident(M, eps=1e-5):
    return all(abs(M[i][j] - (1.0 if i == j else 0.0)) <= eps for i in range(3) for j in range(4))


def bake_rigid_pivots(model):
    """Rigid meshes are stored in their pivot's local space: move them into model space.
    Smooth-skinned meshes are already in model space and are left alone."""
    piv = [{'pos': p['pos'], 'quat': conj(p['quat']), 'parent': p['parent']} for p in model['pivots']]
    Wm = world_mats(piv)
    for m in model['meshes']:
        if m.get('skinned'):
            continue
        M = Wm[m['pivot']]
        if _is_ident(M):
            continue
        nv = []
        for (p, uv, n) in m['verts']:
            q = xform(M, p)
            nn = xform3(M, n)
            ln = (nn[0] ** 2 + nn[1] ** 2 + nn[2] ** 2) ** 0.5 or 1.0
            nv.append((q, uv, (nn[0] / ln, nn[1] / ln, nn[2] / ln)))
        m['verts'] = nv


def select_lod(meshes, lod=0):
    """Keep the highest-detail level. Every buffer tagged with that LOD is drawn by the engine,
    so nothing is de-duplicated by texture or pivot."""
    kept = [m for m in meshes if (m.get('source_flags', 0) & 31) == lod]
    return kept or meshes


def build_static(model, texindex):
    """Textured static glb. Positions/normals get Z negated: the engine is left-handed (D3D), glTF
    is right-handed. The mirror alone turns D3D clockwise-front triangles into glTF
    counter-clockwise-front ones, so the index order is kept."""
    gb = GlbBuilder()
    prims = []
    missing = set()
    for mi, m in enumerate(model['meshes']):
        if not m['verts']:
            continue
        idx = m['indices'] if m['isTriangles'] else strip_to_tris(m['indices'])
        idx = idx[:len(idx) - len(idx) % 3]
        if not idx or max(idx) >= len(m['verts']):
            continue
        pos = [(v[0][0], v[0][1], -v[0][2]) for v in m['verts']]
        nrm = [(v[2][0], v[2][1], -v[2][2]) for v in m['verts']]
        uv = [v[1] for v in m['verts']]
        prim = {'attributes': {'POSITION': gb.floats(pos, 'VEC3', bounds=True),
                               'NORMAL': gb.floats(nrm, 'VEC3'),
                               'TEXCOORD_0': gb.floats(uv, 'VEC2')},
                'indices': gb.indices(idx), 'mode': 4}
        ref = _texture_for_mesh(model, mi, m)
        if ref:
            png, alpha, key = texindex.png_for_ref(ref)
            if png:
                prim['material'] = gb.material(png, key, alpha, os.path.basename(key))
            else:
                missing.add(ref)
        prims.append(prim)
    if not prims:
        return None, None, missing
    g = gb.gltf('tod-asset-explorer', meshes=[{'primitives': prims}],
                nodes=[{'mesh': 0, 'name': os.path.basename(model['name'])}],
                scenes=[{'nodes': [0]}], scene=0)
    return g, bytes(gb.blob), missing


# ------------------------------------------------------------------ characters

def dedupe_lods(model):
    """Characters carry several LODs of each body part (same pivot + texture, fewer vertices).
    Drawing them all overlapped z-fights, so keep the densest mesh per (pivot, texture)."""
    best = {}
    for m in model['meshes']:
        k = (m.get('pivot'), m.get('texidx'))
        if k not in best or len(m['verts']) > len(best[k]['verts']):
            best[k] = m
    model['meshes'] = [m for m in model['meshes'] if m is best[(m.get('pivot'), m.get('texidx'))]]


def build_character(model, clips, texindex):
    """Skinned (or rigid-hierarchy) mesh + skeleton + animation clips in one glb.

    model['pivots'] must already carry conjugated quaternions and +0x58 parents.
    clips: [(name, decoded_anim)] with conjugated rotations.
    """
    piv = model['pivots']
    npiv = len(piv)
    Wm = world_mats(piv)
    nodes = [{'name': p['name'] or 'bone%d' % i, 'translation': p['pos'], 'rotation': p['quat']}
             for i, p in enumerate(piv)]
    for i in range(npiv):
        ch = [j for j, q in enumerate(piv) if q['parent'] == i and j != i]
        if ch:
            nodes[i]['children'] = ch
    roots = [i for i, p in enumerate(piv) if not (0 <= p['parent'] < npiv and p['parent'] != i)]
    # Several root pivots (a synthetic root, the Bip tree, GamePivot): hang the extras under the
    # first one so the skin has a single connected skeleton (some importers require it).
    if len(roots) > 1:
        nodes[roots[0]]['children'] = list(nodes[roots[0]].get('children', [])) + roots[1:]
        roots = [roots[0]]
    mesh_node = len(nodes)
    nodes.append({'mesh': 0, 'skin': 0, 'name': os.path.basename(model['name'])})

    gb = GlbBuilder()
    jcomp, jfmt = (5121, 'B') if npiv < 256 else (5123, 'H')
    prims = []
    missing = set()
    for mi, m in enumerate(model['meshes']):
        if not m['verts']:
            continue
        idx = m['indices'] if m['isTriangles'] else strip_to_tris(m['indices'])
        idx = idx[:len(idx) - len(idx) % 3]
        if not idx or max(idx) >= len(m['verts']):
            continue
        n = len(m['verts'])
        if m.get('skinned') and m['joints']:
            joints, weights = m['joints'], m['weights']
        else:
            joints, weights = [[m['pivot'], 0, 0, 0]] * n, [[1.0, 0.0, 0.0, 0.0]] * n
        flatj = [c for j in joints for c in j]
        attrs = {'POSITION': gb.floats([v[0] for v in m['verts']], 'VEC3', bounds=True),
                 'NORMAL': gb.floats([v[2] for v in m['verts']], 'VEC3'),
                 'TEXCOORD_0': gb.floats([v[1] for v in m['verts']], 'VEC2'),
                 'JOINTS_0': gb.accessor(struct.pack('<%d%s' % (len(flatj), jfmt), *flatj), jcomp, 'VEC4', n),
                 'WEIGHTS_0': gb.floats(weights, 'VEC4')}
        prim = {'attributes': attrs, 'indices': gb.indices(idx), 'mode': 4}
        ref = _texture_for_mesh(model, mi, m)
        if ref:
            png, alpha, key = texindex.png_for_ref(ref)
            if png:
                prim['material'] = gb.material(png, key, False, os.path.basename(key))
            else:
                missing.add(ref)
        prims.append(prim)
    if not prims:
        return None, None, missing

    # Smooth-skinned bipeds store vertices in model space -> IBM = inverse(bind world).
    # Rigid models (e.g. the chicken) store each part in its bone's local space -> IBM = identity.
    rigid = not any(mm.get('skinned') for mm in model['meshes'])
    ident = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
    ibm = [c for i in range(npiv) for c in (ident if rigid else colmajor(inv_rigid(Wm[i])))]
    iba = gb.accessor(struct.pack('<%df' % len(ibm), *ibm), 5126, 'MAT4', npiv)

    anims = []
    for name, a in clips:
        nf = a['frames']
        if nf <= 0:
            continue
        times = [frame_time_float32(f, FPS) for f in range(nf)]
        tin = gb.accessor(struct.pack('<%df' % nf, *times), 5126, 'SCALAR', nf, [0.0], [max(times)])
        samplers, channels = [], []
        for bi, t in enumerate(a['tracks'][:npiv]):
            for path, key, typ in (('rotation', 'rot', 'VEC4'), ('translation', 'pos', 'VEC3')):
                if t[key]:
                    samplers.append({'input': tin, 'output': gb.floats(t[key], typ), 'interpolation': 'LINEAR'})
                    channels.append({'sampler': len(samplers) - 1, 'target': {'node': bi, 'path': path}})
        if channels:
            anims.append({'name': name, 'samplers': samplers, 'channels': channels})

    extra = {'meshes': [{'primitives': prims}],
             'skins': [{'joints': list(range(npiv)), 'inverseBindMatrices': iba, 'skeleton': roots[0] if roots else 0}],
             'nodes': nodes, 'scenes': [{'nodes': roots + [mesh_node]}], 'scene': 0}
    if anims:
        extra['animations'] = anims
    return gb.gltf('tod-asset-explorer', **extra), bytes(gb.blob), missing
