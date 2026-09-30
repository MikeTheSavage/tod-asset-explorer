// Prints a summary of what the viewer will find, or writes the manifest to a file:
//   node scripts/gen-manifest.mjs [--assets <dir>] [--write <file.json>]
// The dev server and serve.py build the manifest on the fly, so this is only a diagnostic.
import fs from 'node:fs'
import { resolveAssetsRoot, buildManifest } from './assets.mjs'

const root = resolveAssetsRoot()
const m = buildManifest(root)
const i = process.argv.indexOf('--write')
if (i > 0 && process.argv[i + 1]) {
  fs.writeFileSync(process.argv[i + 1], JSON.stringify(m))
  console.log(`wrote ${process.argv[i + 1]}`)
}
console.log(`assets root: ${root}${m.assetsRootExists ? '' : ' (does not exist)'}`)
console.log(`manifest: ${m.count} models (${m.animated} animated/skinned)`)
