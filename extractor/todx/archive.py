"""Game-data sources: the retail/GOG `blocks.naz` archive, a plain zip, or an unpacked folder.

`.naz` is a stored (uncompressed) zip with three changes, read here the same way the game's own
loader does it:
  * the end-of-central-directory signature is 0x16ED5B50 instead of 0x06054B50;
  * every central-directory record keeps its 0x2E-byte size, but the fields the loader needs sit
    8 bytes earlier than in a normal zip (uncompressed size @+0x10, name length @+0x14,
    extra length @+0x16, comment length @+0x18, local header offset @+0x22);
  * file names are stored rotated right by 2 bits (decode = rotate each byte left by 2).
File data starts at local_header_offset + 30 + name_len + extra_len and is never compressed.
The local headers are also scrambled, but nothing needs them.
"""
import os
import struct
import zipfile

NAZ_EOCD_MAGIC = 0x16ED5B50
ZIP_EOCD_MAGIC = 0x06054B50

BLOCK_EXTS = ('.main', '.submap', '.mission', '.map', '.playerdata')


class SourceError(Exception):
    """Raised when the given path does not look like Total Overdose game data."""


def _rol2(b):
    return ((b << 2) | (b >> 6)) & 0xFF


class NazArchive:
    def __init__(self, path):
        self.path = path
        self.entries = {}          # normalised name -> (offset, size)
        with open(path, 'rb') as f:
            f.seek(0, 2)
            size = f.tell()
            if size < 22:
                raise SourceError('%s is too small to be a .naz archive' % path)
            f.seek(size - 22)
            sig, _d1, _d2, _n1, count, cd_size, cd_off, _cl = struct.unpack('<IHHHHIIH', f.read(22))
            if sig != NAZ_EOCD_MAGIC:
                raise SourceError('%s is not a Total Overdose .naz archive (bad signature 0x%08X)'
                                  % (path, sig))
            f.seek(cd_off)
            cd = f.read(cd_size)
        p = 0
        for _ in range(count):
            if p + 0x2E > len(cd):
                raise SourceError('%s: central directory is truncated' % path)
            usize, = struct.unpack_from('<I', cd, p + 0x10)
            nlen, xlen, clen = struct.unpack_from('<HHH', cd, p + 0x14)
            loff, = struct.unpack_from('<I', cd, p + 0x22)
            raw = cd[p + 0x2E:p + 0x2E + nlen]
            name = bytes(_rol2(b) for b in raw).decode('latin-1').replace('\\', '/')
            self.entries[name] = (loff + 30 + nlen + xlen, usize)
            p += 0x2E + nlen + xlen + clen

    def names(self):
        return list(self.entries)

    def read(self, name):
        off, size = self.entries[name]
        with open(self.path, 'rb') as f:
            f.seek(off)
            data = f.read(size)
        if len(data) != size:
            raise IOError('short read for %s in %s' % (name, self.path))
        return data


class ZipSource:
    """A .naz already converted to a normal zip (e.g. by a third-party converter)."""
    def __init__(self, path):
        self.path = path
        try:
            self.zf = zipfile.ZipFile(path)
        except zipfile.BadZipFile as e:
            raise SourceError('%s is not a valid zip: %s' % (path, e))
        self._map = {i.filename.replace('\\', '/'): i.filename for i in self.zf.infolist()
                     if not i.is_dir()}

    def names(self):
        return list(self._map)

    def read(self, name):
        return self.zf.read(self._map[name])


class FolderSource:
    """An unpacked copy of blocks.naz: a folder that contains `data_pc/`."""
    def __init__(self, root):
        self.path = root
        self._names = []
        for dp, _dn, fn in os.walk(os.path.join(root, 'data_pc')):
            for f in fn:
                full = os.path.join(dp, f)
                self._names.append(os.path.relpath(full, root).replace('\\', '/'))

    def names(self):
        return list(self._names)

    def read(self, name):
        with open(os.path.join(self.path, name), 'rb') as f:
            return f.read()


def open_game(path):
    """Accepts, in order of preference:
      - the game install folder (contains blocks.naz),
      - a blocks.naz / blocks.zip file directly,
      - a folder with an unpacked `data_pc/` tree (or its parent, e.g. `<x>/blocks/data_pc`).
    """
    if not path:
        raise SourceError('no game path given')
    path = os.path.abspath(os.path.expanduser(path))
    if not os.path.exists(path):
        raise SourceError('path does not exist: %s' % path)
    if os.path.isfile(path):
        low = path.lower()
        if low.endswith('.naz'):
            return NazArchive(path)
        if low.endswith('.zip'):
            return ZipSource(path)
        raise SourceError('%s is a file, but not blocks.naz / blocks.zip' % path)
    for cand in ('blocks.naz', 'Blocks.naz', 'BLOCKS.NAZ'):
        p = os.path.join(path, cand)
        if os.path.isfile(p):
            return NazArchive(p)
    for sub in ('', 'blocks'):
        root = os.path.join(path, sub) if sub else path
        if os.path.isdir(os.path.join(root, 'data_pc')):
            return FolderSource(root)
    if os.path.isfile(os.path.join(path, 'blocks.zip')):
        return ZipSource(os.path.join(path, 'blocks.zip'))
    hint = ''
    if os.path.isfile(os.path.join(path, 'TOD.exe')):
        hint = ' (TOD.exe is here but blocks.naz is missing - is the install complete?)'
    raise SourceError(
        'could not find Total Overdose game data in %s%s.\n'
        'Point --game at the folder that contains TOD.exe and blocks.naz '
        '(for GOG usually "C:\\GOG Games\\Total Overdose"), at blocks.naz itself, '
        'or at a folder containing an unpacked data_pc/ tree.' % (path, hint))


LANG_MARKERS = ('/de/', '/es/', '/fr/', '/it/', '/uk/')


def is_localized(name):
    n = '/' + name.lower()
    return any(m in n for m in LANG_MARKERS)


def list_blocks(src, exts=BLOCK_EXTS, include_localized=False):
    """Asset blocks in a stable order: .main, .submap, .map, .mission, .playerdata."""
    order = {e: i for i, e in enumerate(('.main', '.submap', '.map', '.mission', '.playerdata'))}
    out = [n for n in src.names()
           if os.path.splitext(n)[1].lower() in exts
           and (include_localized or not is_localized(n))]
    out.sort(key=lambda n: (order.get(os.path.splitext(n)[1].lower(), 9), n.lower()))
    return out


def unpack(src, dest, log=print):
    """Write every archive member to dest/<name>. Returns the number of files written."""
    n = 0
    for name in src.names():
        out = os.path.join(dest, *name.split('/'))
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, 'wb') as f:
            f.write(src.read(name))
        n += 1
        if n % 100 == 0:
            log('  unpacked %d files...' % n)
    return n
