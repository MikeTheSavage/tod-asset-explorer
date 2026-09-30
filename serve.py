#!/usr/bin/env python3
"""Serve the prebuilt TOD Asset Explorer viewer. Python 3 standard library only, no Node needed.

  python serve.py                      # assets from ./assets, http://127.0.0.1:5190
  python serve.py --assets D:\\tod     # another asset folder (or set TOD_ASSETS)
  python serve.py --open               # also open the browser

Routes:
  /                 the viewer (dist/ from `npm run build`, shipped in the release zip)
  /manifest.json    generated on request from the .glb files under the asset folder
  /assets/<path>    files from the asset folder (read-only, no access outside it)
Keep this in sync with scripts/assets.mjs, which does the same for `npm run dev`.
"""
import argparse
import json
import mimetypes
import os
import re
import struct
import sys
import threading
import time
import webbrowser
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote, unquote, urlsplit

HERE = os.path.dirname(os.path.abspath(__file__))

GROUP_NAMES = {'characters': 'Characters', 'animals': 'Animals', 'vegetation': 'Vegetation',
               'weapons': 'Weapons', 'vehicles': 'Vehicles', 'props': 'Props', 'world': 'World',
               'mockups': 'Mockups', 'misc': 'Misc'}

MIME = {'.glb': 'model/gltf-binary', '.gltf': 'model/gltf+json', '.js': 'text/javascript',
        '.mjs': 'text/javascript', '.css': 'text/css', '.html': 'text/html; charset=utf-8',
        '.json': 'application/json', '.png': 'image/png', '.svg': 'image/svg+xml',
        '.dds': 'image/vnd-ms.dds', '.wasm': 'application/wasm'}


def parse_glb(path):
    try:
        with open(path, 'rb') as f:
            head = f.read(20)
            if len(head) < 20 or head[:4] != b'glTF':
                return None
            jlen = struct.unpack_from('<I', head, 12)[0]
            j = json.loads(f.read(jlen).decode('utf-8'))
    except Exception:
        return None
    anims = j.get('animations') or []
    return {'meshes': len(j.get('meshes') or []), 'materials': len(j.get('materials') or []),
            'images': len(j.get('images') or []), 'skins': len(j.get('skins') or []),
            'anims': len(anims), 'clips': [a.get('name') or 'clip_%d' % i for i, a in enumerate(anims)]}


def categorize(rel):
    parts = rel.split('/')
    n = re.sub(r'\.charanim$', '', re.sub(r'\.glb$', '', parts[-1], flags=re.I), flags=re.I)
    if n.startswith('data_'):
        n = n[5:]
    if parts[0] == 'characters':
        group = 'Characters'
    elif parts[0] == 'animated':
        group = 'Animated'
    elif parts[0] == 'models' and len(parts) > 2:
        group = GROUP_NAMES.get(parts[1], parts[1])
    else:
        group = 'Other'
    m = re.search(r'(?:^|_)(Map\d+)', n, re.I)
    if m:
        mp = m.group(1)[0].upper() + m.group(1)[1:]
    else:
        mp = group if group in ('Characters', 'Animated', 'Animals') else 'Common'
    return mp, group, n.replace('_', ' ')


def build_manifest(root):
    entries = []
    if os.path.isdir(root):
        for dp, dn, fn in os.walk(root):
            dn.sort()
            for f in sorted(fn):
                if not f.lower().endswith('.glb'):
                    continue
                full = os.path.join(dp, f)
                rel = os.path.relpath(full, root).replace(os.sep, '/')
                st = os.stat(full)
                info = parse_glb(full) or {}
                mp, group, label = categorize(rel)
                entries.append({
                    'id': rel,
                    'url': 'assets/' + quote(rel) + '?v=%d' % int(st.st_mtime * 1000),
                    'file': f, 'label': label, 'map': mp, 'group': group,
                    'source': rel.split('/')[0], 'kb': round(st.st_size / 1024),
                    'meshes': info.get('meshes', 0), 'materials': info.get('materials', 0),
                    'images': info.get('images', 0), 'skins': info.get('skins', 0),
                    'anims': info.get('anims', 0), 'clips': info.get('clips', []),
                })
    entries.sort(key=lambda e: e['label'].lower())
    return {'schemaVersion': 3, 'generatedAt': datetime.now(timezone.utc).isoformat(),
            'assetsRoot': root, 'assetsRootExists': os.path.isdir(root), 'count': len(entries),
            'animated': sum(1 for e in entries if e['anims'] > 0 or e['skins'] > 0),
            'entries': entries}


def inside(base, path):
    base = os.path.realpath(base)
    path = os.path.realpath(path)
    try:
        return os.path.commonpath([base, path]) == base and path != base
    except ValueError:
        return False


def make_handler(dist, assets):
    cache = {'at': 0.0, 'body': b''}
    lock = threading.Lock()

    class Handler(SimpleHTTPRequestHandler):
        server_version = 'tod-asset-explorer'

        def log_message(self, fmt, *args):
            if os.environ.get('TOD_SERVE_VERBOSE'):
                sys.stderr.write('%s\n' % (fmt % args))

        def _send_file(self, path, head_only=False):
            ext = os.path.splitext(path)[1].lower()
            ctype = MIME.get(ext) or mimetypes.guess_type(path)[0] or 'application/octet-stream'
            size = os.path.getsize(path)
            self.send_response(200)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(size))
            self.send_header('Cache-Control', 'no-cache' if ext == '.html' else 'public, max-age=3600')
            self.end_headers()
            if head_only:
                return
            with open(path, 'rb') as f:
                while True:
                    chunk = f.read(1 << 20)
                    if not chunk:
                        break
                    self.wfile.write(chunk)

        def _route(self, head_only=False):
            p = unquote(urlsplit(self.path).path)
            if p in ('/manifest.json',):
                with lock:
                    if time.time() - cache['at'] > 2:
                        cache['body'] = json.dumps(build_manifest(assets)).encode('utf-8')
                        cache['at'] = time.time()
                    body = cache['body']
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                if not head_only:
                    self.wfile.write(body)
                return
            if p.startswith('/assets/'):
                base, rel = assets, p[len('/assets/'):]
            else:
                base, rel = dist, p.lstrip('/') or 'index.html'
            if '\0' in rel or any(seg == '..' for seg in re.split(r'[\\/]+', rel)):
                return self.send_error(400)
            full = os.path.join(base, *[s for s in rel.split('/') if s])
            if os.path.isdir(full):
                full = os.path.join(full, 'index.html')
            if not os.path.isfile(full) or not inside(base, full):
                return self.send_error(404)
            self._send_file(full, head_only)

        def do_GET(self):
            try:
                self._route()
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_HEAD(self):
            self._route(head_only=True)

    return Handler


def main(argv=None):
    ap = argparse.ArgumentParser(description='Serve the TOD Asset Explorer viewer.')
    ap.add_argument('--assets', default=None,
                    help='asset folder (default: $TOD_ASSETS, else ./assets next to this script)')
    ap.add_argument('--dist', default=os.path.join(HERE, 'dist'), help='prebuilt viewer folder')
    ap.add_argument('--host', default='127.0.0.1', help='bind address (default 127.0.0.1)')
    ap.add_argument('--port', type=int, default=5190, help='port (default 5190; next free one is used)')
    ap.add_argument('--open', action='store_true', help='open the viewer in the default browser')
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    assets = os.path.abspath(a.assets or os.environ.get('TOD_ASSETS') or os.path.join(HERE, 'assets'))
    dist = os.path.abspath(a.dist)
    if not os.path.isfile(os.path.join(dist, 'index.html')):
        print('ERROR: no prebuilt viewer at %s' % dist)
        print('Use the release zip (it includes dist/), or build it: npm install && npm run build')
        return 2
    httpd = None
    for port in range(a.port, a.port + 20):
        try:
            httpd = ThreadingHTTPServer((a.host, port), make_handler(dist, assets))
            break
        except OSError:
            continue
    if httpd is None:
        print('ERROR: no free port in %d-%d' % (a.port, a.port + 19))
        return 2
    url = 'http://%s:%d/' % ('127.0.0.1' if a.host in ('0.0.0.0', '') else a.host, httpd.server_address[1])
    m = build_manifest(assets)
    print('TOD Asset Explorer')
    print('  viewer : %s' % dist)
    print('  assets : %s  (%d models, %d animated)%s' % (
        assets, m['count'], m['animated'], '' if m['assetsRootExists'] else '  [folder does not exist]'))
    print('  open   : %s' % url)
    print('Press Ctrl+C to stop.')
    if a.open:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
