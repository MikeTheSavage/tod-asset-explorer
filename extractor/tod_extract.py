#!/usr/bin/env python3
"""Total Overdose asset extractor: your own copy of the game -> .glb models, animations, textures.

  python extractor/tod_extract.py --game "C:\\GOG Games\\Total Overdose" --out assets

Pure Python 3 (standard library only). Reads the game's blocks.naz directly (nothing is
unpacked to disk unless you ask for it with --unpack). Failing assets are skipped and listed in
<out>/extract_report.json; the run never aborts because of a single bad asset.

Output layout:
  <out>/models/<category>/*.glb     every model, textured, static (bind pose)
  <out>/characters/*.charanim.glb   humanoids: skinned mesh + skeleton + animation clips
  <out>/animated/*.charanim.glb     other rigs with their own clips (e.g. the chicken)
  <out>/textures/**.dds|.png        every texture (use --textures none to skip)
  <out>/extract_report.json         counts, skipped assets and the reason for each
"""
import argparse
import json
import os
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from todx import __version__                                    # noqa: E402
from todx.archive import open_game, list_blocks, unpack, SourceError  # noqa: E402
from todx.block import Block                                    # noqa: E402
from todx.model import find_model_records, extract_model, is_biped  # noqa: E402
from todx.anim import (find_anim_records, decode_anim, derive_remap,  # noqa: E402
                       clip_channel_count, clip_name)
from todx.textures import TextureIndex, decode_dds, rgba_to_png   # noqa: E402
from todx import gltf as G                                      # noqa: E402

SHARED_ANIM_BLOCK = 'overdose.main'     # the humanoid clip library lives here


def categorize(model_name):
    low = model_name.lower().lstrip('/')
    if low.startswith('data/'):
        low = low[5:]
    if low.startswith('characters'):
        return 'characters'
    if low.startswith('animals'):
        return 'animals'
    if 'vegetation' in low:
        return 'vegetation'
    if 'weapon' in low:
        return 'weapons'
    if 'vehicle' in low or '/car_' in low or 'traffic' in low:
        return 'vehicles'
    if low.startswith('models/addons') or '/addons/' in low:
        return 'props'
    if low.startswith('models'):
        return 'world'
    if low.startswith('mockupmodels'):
        return 'mockups'
    return 'misc'


def out_name(model_name):
    # '/data/characters/ram/ram.model' -> 'data_characters_ram_ram.glb'
    n = model_name.lstrip('/')
    if n.lower().endswith('.model'):
        n = n[:-6]
    safe = ''.join(c if (c.isalnum() or c in '-_.') else '_' for c in n.replace('/', '_'))
    return safe + '.glb'


def stem(model_name):
    return os.path.splitext(os.path.basename(model_name))[0]


class Report:
    def __init__(self):
        self.counts = {}
        self.skipped = []
        self.missing_textures = set()

    def inc(self, k, n=1):
        self.counts[k] = self.counts.get(k, 0) + n

    def skip(self, kind, name, reason):
        self.skipped.append({'kind': kind, 'name': name, 'reason': str(reason)[:300]})
        self.inc('skipped_' + kind)


def log(*a):
    print(*a, flush=True)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description='Extract Total Overdose models, animations and textures to .glb.',
        epilog='Example: python extractor/tod_extract.py --game "C:\\GOG Games\\Total Overdose" --out assets')
    ap.add_argument('--game', required=True,
                    help='game install folder (contains blocks.naz), blocks.naz itself, '
                         'or a folder with an unpacked data_pc/ tree')
    ap.add_argument('--out', default='assets', help='output folder (default: ./assets)')
    ap.add_argument('--only', default='models,characters,textures',
                    help='comma list of: models, characters, textures (default: all)')
    ap.add_argument('--textures', choices=('dds', 'png', 'none'), default='dds',
                    help='format for the loose texture files (default dds; png is much slower)')
    ap.add_argument('--filter', default=None, help='only models whose path contains this text')
    ap.add_argument('--limit', type=int, default=0, help='stop after N models (for quick tests)')
    ap.add_argument('--skip-existing', action='store_true', help='keep .glb files that already exist')
    ap.add_argument('--list', action='store_true', help='list the asset blocks found and exit')
    ap.add_argument('--unpack', metavar='DIR', default=None,
                    help='just unpack the raw archive members into DIR and exit')
    args = ap.parse_args(argv)

    try:
        src = open_game(args.game)
    except SourceError as e:
        log('ERROR: %s' % e)
        return 2
    log('tod-asset-explorer extractor %s' % __version__)
    log('game data: %s (%s)' % (src.path, type(src).__name__))

    if args.unpack:
        n = unpack(src, args.unpack, log)
        log('unpacked %d files -> %s' % (n, args.unpack))
        return 0

    blocks = list_blocks(src)
    if not blocks:
        log('ERROR: no asset blocks (.main/.submap/.map/.mission) found in %s' % src.path)
        return 2
    if args.list:
        for b in blocks:
            log('  ' + b)
        log('%d asset blocks' % len(blocks))
        return 0

    want = {w.strip() for w in args.only.split(',') if w.strip()}
    out = os.path.abspath(args.out)
    os.makedirs(out, exist_ok=True)
    rep = Report()
    t0 = time.time()

    # ---- pass 1: index textures, models and animation records across all blocks
    log('scanning %d asset blocks...' % len(blocks))
    tex = TextureIndex(src)
    models = {}            # model name -> (block, base)
    by_block = {}          # block -> [(base, name)]
    anim_blocks = {}       # block -> [(base, name)]
    shared_block = None
    for bi, bname in enumerate(blocks):
        try:
            blk = Block(src.read(bname), bname)
        except Exception as e:
            rep.skip('block', bname, e)
            continue
        rep.inc('blocks')
        try:
            tex.add_block(bname, blk)
        except Exception as e:
            rep.skip('texture_scan', bname, e)
        try:
            for base, name in find_model_records(blk.info):
                if name in models:
                    continue
                if args.filter and args.filter.lower() not in name.lower():
                    continue
                models[name] = (bname, base)
                by_block.setdefault(bname, []).append((base, name))
            recs = find_anim_records(blk.info)
            if recs:
                anim_blocks[bname] = recs
        except Exception as e:
            rep.skip('model_scan', bname, e)
        if os.path.basename(bname).lower() == SHARED_ANIM_BLOCK:
            shared_block = bname
        if (bi + 1) % 25 == 0:
            log('  ...%d/%d blocks' % (bi + 1, len(blocks)))
    log('found %d models, %d textures, %d animation clips'
        % (len(models), len(tex.entries), sum(len(v) for v in anim_blocks.values())))
    if not models:
        log('ERROR: no models found - is this really Total Overdose data?')
        return 2

    # ---- pass 2: models (static) + discover rigs
    bipeds, rigs = [], []
    done = 0
    for bname in blocks:
        if bname not in by_block:
            continue
        try:
            blk = Block(src.read(bname), bname)
        except Exception as e:
            rep.skip('block', bname, e)
            continue
        for base, name in by_block[bname]:
            if args.limit and done >= args.limit:
                break
            done += 1
            try:
                model = extract_model(blk.info, base, name)
                if not model or not any(m['verts'] for m in model['meshes']):
                    rep.skip('model', name, 'no geometry')
                    continue
                if is_biped(model):
                    bipeds.append((bname, base, name))
                else:
                    st = stem(name).lower() + '_'
                    if any(clip_name(n).lower().startswith(st) for _, n in anim_blocks.get(bname, [])) or \
                       (shared_block and any(clip_name(n).lower().startswith(st)
                                             for _, n in anim_blocks.get(shared_block, []))):
                        rigs.append((bname, base, name))
                if 'models' not in want:
                    continue
                dest = os.path.join(out, 'models', categorize(name), out_name(name))
                if args.skip_existing and os.path.exists(dest):
                    rep.inc('models_kept')
                    continue
                G.bake_rigid_pivots(model)
                model['meshes'] = G.select_lod(model['meshes'], 0)
                g, blob, missing = G.build_static(model, tex)
                rep.missing_textures |= missing
                if not g:
                    rep.skip('model', name, 'no drawable triangles')
                    continue
                G.write_glb(dest, g, blob)
                rep.inc('models')
                if rep.counts['models'] % 100 == 0:
                    log('  ...%d models written (%.0fs)' % (rep.counts['models'], time.time() - t0))
            except Exception as e:
                rep.skip('model', name, '%s: %s' % (type(e).__name__, e))
    log('models: %d written' % rep.counts.get('models', 0))

    # ---- pass 3: characters and other animated rigs
    if 'characters' in want:
        shared = None
        if shared_block:
            try:
                shared = Block(src.read(shared_block), shared_block)
            except Exception as e:
                rep.skip('block', shared_block, e)
        else:
            log('WARNING: %s not found - humanoid characters will have no animation clips'
                % SHARED_ANIM_BLOCK)
        clip_cache = {}
        jobs = [(b, base, n, 'characters') for (b, base, n) in bipeds] + \
               [(b, base, n, 'animated') for (b, base, n) in rigs]
        blk_cache = {}
        for bname, base, name, kind in jobs:
            try:
                if bname not in blk_cache:
                    blk_cache.clear()
                    blk_cache[bname] = Block(src.read(bname), bname)
                info = blk_cache[bname].info
                model = extract_model(info, base, name)
                G.dedupe_lods(model)
                for p in model['pivots']:
                    p['quat'] = G.conj(p['quat'])
                npiv = len(model['pivots'])
                clips = []
                if kind == 'characters':
                    sources = [(shared.info, shared_block)] if shared else []
                else:
                    sources = [(info, bname)]
                    if shared and shared_block != bname:
                        sources.append((shared.info, shared_block))
                st = stem(name).lower()
                seen = set()
                for ainfo, abname in sources:
                    for abase, an in find_anim_records(ainfo):
                        cn = clip_name(an)
                        if cn in seen:
                            continue
                        if kind == 'characters':
                            ne = clip_channel_count(ainfo, abase)
                            # "compatible": clips built for a skeleton of about this size
                            if ne == 0 or abs(ne - npiv) > max(10, npiv * 0.35):
                                continue
                        elif not cn.lower().startswith(st + '_'):
                            continue
                        remap = derive_remap(ainfo, abase, model['pivots'])
                        key = (abname, abase, npiv, tuple(remap))
                        if key not in clip_cache:
                            a = decode_anim(ainfo, abase, npiv, remap=remap)
                            if a:
                                for t in a['tracks']:
                                    if t['rot']:
                                        t['rot'] = [(-x, -y, -z, w) for (x, y, z, w) in t['rot']]
                            clip_cache[key] = a
                        a = clip_cache[key]
                        if a:
                            seen.add(cn)
                            clips.append((cn, a))
                if kind == 'characters':
                    clip_cache = {k: v for k, v in clip_cache.items() if k[0] == shared_block}
                dest = os.path.join(out, kind, stem(name) + '.charanim.glb')
                if args.skip_existing and os.path.exists(dest):
                    rep.inc(kind + '_kept')
                    continue
                g, blob, missing = G.build_character(model, clips, tex)
                rep.missing_textures |= missing
                if not g:
                    rep.skip(kind, name, 'no drawable triangles')
                    continue
                G.write_glb(dest, g, blob)
                rep.inc(kind)
                rep.inc(kind + '_clips', len(clips))
                log('  %-12s %-40s %3d clips' % (kind, stem(name), len(clips)))
            except Exception as e:
                rep.skip(kind, name, '%s: %s' % (type(e).__name__, e))
        log('characters: %d, other animated rigs: %d'
            % (rep.counts.get('characters', 0), rep.counts.get('animated', 0)))

    # ---- pass 4: loose textures
    if 'textures' in want and args.textures != 'none':
        keys = sorted(tex.entries, key=lambda k: (tex.entries[k][0], k))
        log('writing %d textures as .%s ...' % (len(keys), args.textures))
        for i, k in enumerate(keys):
            dest = os.path.join(out, 'textures', *(k + '.' + args.textures).split('/'))
            if args.skip_existing and os.path.exists(dest):
                continue
            try:
                data = tex.dds(k)
                if args.textures == 'png':
                    w, h, rgba = decode_dds(data)
                    data = rgba_to_png(w, h, rgba)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with open(dest, 'wb') as f:
                    f.write(data)
                rep.inc('textures')
            except Exception as e:
                rep.skip('texture', k, '%s: %s' % (type(e).__name__, e))
            if (i + 1) % 500 == 0:
                log('  ...%d/%d textures' % (i + 1, len(keys)))

    secs = time.time() - t0
    report = {
        'tool': 'tod-asset-explorer extractor', 'version': __version__,
        'source_kind': type(src).__name__, 'seconds': round(secs, 1),
        'counts': rep.counts,
        'unresolved_texture_references': sorted(rep.missing_textures),
        'skipped': rep.skipped,
    }
    with open(os.path.join(out, 'extract_report.json'), 'w') as f:
        json.dump(report, f, indent=1)
    log('')
    log('done in %.0fs -> %s' % (secs, out))
    for k in sorted(rep.counts):
        log('  %-24s %d' % (k, rep.counts[k]))
    if rep.skipped:
        log('  %d assets skipped (details in extract_report.json)' % len(rep.skipped))
    if rep.missing_textures:
        log('  %d texture references could not be resolved (models still exported, untextured)'
            % len(rep.missing_textures))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log('interrupted')
        sys.exit(130)
    except Exception:
        traceback.print_exc()
        sys.exit(1)
