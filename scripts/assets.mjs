// Asset root + manifest for the development server (Vite). serve.py implements the same
// contract in Python for the prebuilt viewer, so keep the two in sync:
//   GET manifest.json          -> generated from whatever .glb files are under the asset root
//   GET assets/<relative path> -> the file, read from the asset root (no traversal outside it)
//
// Asset root, first match wins: --assets <dir> (or --assets=<dir>) on the command line,
// the TOD_ASSETS environment variable, then ./assets next to package.json.
import fs from 'node:fs'
import path from 'node:path'
import url from 'node:url'

const REPO = path.resolve(path.dirname(url.fileURLToPath(import.meta.url)), '..')

export function resolveAssetsRoot(argv = process.argv, env = process.env) {
  let fromArg = null
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === '--assets' && argv[i + 1]) fromArg = argv[i + 1]
    else if (argv[i].startsWith('--assets=')) fromArg = argv[i].slice('--assets='.length)
  }
  const chosen = fromArg || env.TOD_ASSETS || path.join(REPO, 'assets')
  return path.resolve(REPO, chosen)
}

function listGlb(dir, out = []) {
  let items
  try { items = fs.readdirSync(dir, { withFileTypes: true }) } catch { return out }
  for (const e of items) {
    const fp = path.join(dir, e.name)
    if (e.isDirectory()) listGlb(fp, out)
    else if (e.name.toLowerCase().endsWith('.glb')) out.push(fp)
  }
  return out
}

// Reads only the JSON chunk of a binary glTF.
function parseGlb(fp) {
  let fd
  try {
    fd = fs.openSync(fp, 'r')
    const head = Buffer.alloc(20)
    fs.readSync(fd, head, 0, 20, 0)
    if (head.toString('ascii', 0, 4) !== 'glTF') return null
    const jsonLen = head.readUInt32LE(12)
    const buf = Buffer.alloc(jsonLen)
    fs.readSync(fd, buf, 0, jsonLen, 20)
    const j = JSON.parse(buf.toString('utf8'))
    return {
      meshes: (j.meshes || []).length,
      materials: (j.materials || []).length,
      images: (j.images || []).length,
      skins: (j.skins || []).length,
      anims: (j.animations || []).length,
      clips: (j.animations || []).map((a, i) => a.name || `clip_${i}`),
    }
  } catch { return null } finally { if (fd !== undefined) fs.closeSync(fd) }
}

const GROUP_NAMES = {
  characters: 'Characters', animals: 'Animals', vegetation: 'Vegetation', weapons: 'Weapons',
  vehicles: 'Vehicles', props: 'Props', world: 'World', mockups: 'Mockups', misc: 'Misc',
}

// models/props/data_Models_Addons_Map08_Boat.glb -> { map: 'Map08', group: 'Props', label }
export function categorize(rel) {
  const parts = rel.split('/')
  const file = parts[parts.length - 1]
  let n = file.replace(/\.glb$/i, '').replace(/\.charanim$/i, '')
  if (n.startsWith('data_')) n = n.slice(5)
  let group
  if (parts[0] === 'characters') group = 'Characters'
  else if (parts[0] === 'animated') group = 'Animated'
  else if (parts[0] === 'models' && parts.length > 2) group = GROUP_NAMES[parts[1]] || parts[1]
  else group = 'Other'
  const m = n.match(/(?:^|_)(Map\d+)/i)
  const map = m ? m[1][0].toUpperCase() + m[1].slice(1) : (['Characters', 'Animated', 'Animals'].includes(group) ? group : 'Common')
  return { map, group, label: n.replace(/_/g, ' ') }
}

export function buildManifest(root) {
  const entries = []
  for (const fp of listGlb(root)) {
    const rel = path.relative(root, fp).split(path.sep).join('/')
    const stat = fs.statSync(fp)
    const info = parseGlb(fp)
    const cat = categorize(rel)
    entries.push({
      id: rel,
      url: 'assets/' + rel.split('/').map(encodeURIComponent).join('/') + `?v=${Math.round(stat.mtimeMs)}`,
      file: path.basename(fp),
      label: cat.label,
      map: cat.map,
      group: cat.group,
      source: rel.split('/')[0],
      kb: Math.round(stat.size / 1024),
      meshes: info?.meshes ?? 0,
      materials: info?.materials ?? 0,
      images: info?.images ?? 0,
      skins: info?.skins ?? 0,
      anims: info?.anims ?? 0,
      clips: info?.clips ?? [],
    })
  }
  entries.sort((a, b) => a.label.localeCompare(b.label))
  return {
    schemaVersion: 3,
    generatedAt: new Date().toISOString(),
    assetsRoot: root,
    assetsRootExists: fs.existsSync(root),
    count: entries.length,
    animated: entries.filter(e => e.anims > 0 || e.skins > 0).length,
    entries,
  }
}

const MIME = {
  '.glb': 'model/gltf-binary', '.gltf': 'model/gltf+json', '.png': 'image/png',
  '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.dds': 'image/vnd-ms.dds', '.json': 'application/json',
}

// Resolve a URL path under root; null if it escapes (lexically or via links).
export function resolveUnder(root, rel) {
  if (typeof rel !== 'string' || rel.includes('\0')) return null
  if (rel.split(/[\\/]+/).some(s => s === '..')) return null
  const full = path.resolve(root, rel)
  const inside = (base, p) => { const r = path.relative(base, p); return r && !r.startsWith('..') && !path.isAbsolute(r) }
  if (!inside(root, full) || !fs.existsSync(full)) return null
  try {
    const real = fs.realpathSync.native(full)
    return inside(fs.realpathSync.native(root), real) ? real : null
  } catch { return null }
}

export function assetMiddleware(root) {
  let cache = null
  return (req, res, next) => {
    const u = (req.url || '').split('?')[0]
    if (u === '/manifest.json') {
      // Rebuilt at most every 2 s, so a fresh extraction shows up on reload.
      if (!cache || Date.now() - cache.at > 2000) cache = { at: Date.now(), body: JSON.stringify(buildManifest(root)) }
      res.setHeader('Content-Type', 'application/json')
      res.setHeader('Cache-Control', 'no-store')
      return res.end(cache.body)
    }
    if (!u.startsWith('/assets/')) return next()
    let rel
    try { rel = decodeURIComponent(u.slice('/assets/'.length)) } catch { res.statusCode = 400; return res.end('bad url') }
    const full = resolveUnder(root, rel)
    if (!full || !fs.statSync(full).isFile()) { res.statusCode = 404; return res.end('not found') }
    const size = fs.statSync(full).size
    res.setHeader('Content-Type', MIME[path.extname(full).toLowerCase()] || 'application/octet-stream')
    res.setHeader('Content-Length', size)
    if (req.method === 'HEAD') return res.end()
    fs.createReadStream(full).on('error', e => { res.statusCode = 500; res.end(String(e)) }).pipe(res)
  }
}
