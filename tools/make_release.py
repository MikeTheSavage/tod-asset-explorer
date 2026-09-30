#!/usr/bin/env python3
"""Build dist-release/tod-asset-explorer-<version>.zip and check it is clean.

Run `npm run build` first (or `npm run release`, which does both). The zip holds the prebuilt
viewer (dist/), the extractor, serve.py, the run scripts and the docs. The script refuses to
finish if the zip contains game content (.glb/.dds/.naz/...) or machine-specific strings.
"""
import json
import os
import re
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INCLUDE_FILES = ['README.md', 'LICENSE', 'FORMATS.md', 'requirements.txt', 'serve.py', 'run.bat', 'run.sh']
INCLUDE_DIRS = ['dist', 'extractor']
FORBIDDEN_EXT = {'.glb', '.gltf', '.dds', '.naz', '.zip', '.main', '.submap', '.mission', '.map',
                 '.playerdata', '.texture_pc', '.bin', '.pyc'}
# Strings that must never ship (checked case-insensitively). Split so this file does not match itself.
FORBIDDEN_TEXT = ['C:' + '\\Users', 'C:' + '\\\\Users', 'C:/' + 'Users', 'My ' + 'Drive', 'TOD' + 'UE',
                  'TOD ' + 'HD', '@' + 'gmail', 'Sha' + 'dow\\', 'Sha' + 'dow/', 'collin' + 'gton',
                  '.cl' + 'aude', 'Un' + 'real', 'UE' + '5']


def version():
    with open(os.path.join(ROOT, 'package.json'), encoding='utf-8') as f:
        return json.load(f)['version']


def files():
    for f in INCLUDE_FILES:
        yield f
    for d in INCLUDE_DIRS:
        for dp, dn, fn in os.walk(os.path.join(ROOT, d)):
            dn[:] = [x for x in dn if x != '__pycache__']
            for f in fn:
                yield os.path.relpath(os.path.join(dp, f), ROOT).replace(os.sep, '/')


def main():
    if not os.path.isfile(os.path.join(ROOT, 'dist', 'index.html')):
        print('dist/ is missing - run `npm run build` first')
        return 1
    ver = version()
    out_dir = os.path.join(ROOT, 'dist-release')
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, 'tod-asset-explorer-%s.zip' % ver)
    prefix = 'tod-asset-explorer-%s/' % ver
    problems = []
    names = list(files())
    pattern = re.compile('|'.join(re.escape(s) for s in FORBIDDEN_TEXT), re.I)
    for rel in names:
        if os.path.splitext(rel)[1].lower() in FORBIDDEN_EXT:
            problems.append('forbidden file type: ' + rel)
        with open(os.path.join(ROOT, rel), 'rb') as f:
            text = f.read().decode('utf-8', 'ignore')
        for m in pattern.finditer(text):
            problems.append('%s: contains %r' % (rel, m.group(0)))
    if problems:
        print('REFUSING to build the release:')
        for p in problems:
            print('  ' + p)
        return 1
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        for rel in names:
            info = zipfile.ZipInfo.from_file(os.path.join(ROOT, rel), prefix + rel)
            if rel in ('run.sh', 'serve.py', 'extractor/tod_extract.py'):
                info.external_attr = 0o100755 << 16
            else:
                info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            with open(os.path.join(ROOT, rel), 'rb') as f:
                z.writestr(info, f.read())
    print('wrote %s (%d files, %.1f KB)' % (out, len(names), os.path.getsize(out) / 1024))
    return 0


if __name__ == '__main__':
    sys.exit(main())
