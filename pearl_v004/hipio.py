"""
Read and write Houdini .hiplc / .hipnc scene files record by record, without Houdini.

A .hip* file is a cpio-style archive.  Commercial .hip files use the standard odc header ("070707" +
octal fields).  Limited-commercial / apprentice files use a 34-byte header of their own:

    magic 'HouLC' (or 'HouNC') + 0x1A
    '10336'                          constant
    '%05x' % (namesize ^ 0xbad)      namesize includes the trailing NUL
    '%09x' % mtime                   unix seconds
    '%09x' % (size ^ name_hash(name)) body size, masked by a hash of the record name
    name, NUL, body

name_hash(name) = SYSwang_inthash(h) with h = h * 37 + byte over the name (UT_String::hash).
Decoded from untitled_water_realism_v001.hiplc and cross-checked on a public .hipnc; the reader below
walks the file purely from the decoded sizes (no magic scanning), so nested cpio data inside a body
(embedded HDA sections, which also carry 'HouLC' headers) is left intact.

The last record is the archive trailer ('LIMITED_COMMERCIAL_FILE!!!' / 'NON_COMMERCIAL_FILE!!!',
size 0).  Record order is preserved on write; `Record.body` is the only thing a caller changes, plus
new records inserted next to related ones.
"""
import re

M = 0xffffffff
MAGICS = (b'HouLC', b'HouNC')
TRAILERS = (b'LIMITED_COMMERCIAL_FILE!!!', b'NON_COMMERCIAL_FILE!!!')


def wang_inthash(k):
    k = (k + (~(k << 16) & M)) & M
    k ^= k >> 5
    k = (k + (k << 3)) & M
    k ^= k >> 13
    k = (k + (~(k << 9) & M)) & M
    k ^= k >> 17
    return k


def name_hash(name):
    h = 0
    for c in name:
        h = (h * 37 + c) & M
    return wang_inthash(h)


class Record(object):
    __slots__ = ('name', 'mtime', 'body', 'magic')

    def __init__(self, name, mtime, body, magic=b'HouLC'):
        self.name, self.mtime, self.body, self.magic = name, mtime, body, magic

    @property
    def text(self):
        return self.body.decode('utf-8')

    def set_text(self, s):
        self.body = s.encode('utf-8')

    def header(self):
        ns = len(self.name) + 1
        return (self.magic + b'\x1a' +
                ('10336%05x%09x%09x' % (ns ^ 0xbad, self.mtime, len(self.body) ^ name_hash(self.name))).encode('ascii') +
                self.name + b'\0')

    def __repr__(self):
        return 'Record(%r, %d bytes)' % (self.name.decode('latin1'), len(self.body))


def read(path_or_bytes):
    data = path_or_bytes if isinstance(path_or_bytes, (bytes, bytearray)) else open(path_or_bytes, 'rb').read()
    pos, n, recs = 0, len(data), []
    while pos < n:
        magic = data[pos:pos + 5]
        if magic not in MAGICS or data[pos + 5:pos + 6] != b'\x1a':
            raise ValueError('bad record magic at offset %d: %r' % (pos, data[pos:pos + 8]))
        hx = data[pos + 6:pos + 34].decode('ascii')
        if hx[:5] != '10336':
            raise ValueError('unexpected header prefix %r at offset %d' % (hx[:5], pos))
        nul = data.index(b'\0', pos + 34)
        name = data[pos + 34:nul]
        ns = int(hx[5:10], 16) ^ 0xbad
        if ns != len(name) + 1:
            raise ValueError('namesize mismatch for %r at offset %d (%d vs %d)' % (name, pos, ns, len(name) + 1))
        mtime = int(hx[10:19], 16)
        size = int(hx[19:28], 16) ^ name_hash(name)
        bs = nul + 1
        if bs + size > n:
            raise ValueError('record %r at offset %d claims %d bytes past EOF' % (name, pos, size))
        recs.append(Record(name, mtime, data[bs:bs + size], magic))
        pos = bs + size
        if name in TRAILERS and size == 0 and pos == n:
            break
    if not recs or recs[-1].name not in TRAILERS:
        raise ValueError('file does not end with an archive trailer record')
    return recs


def write(recs, path=None):
    out = bytearray()
    for r in recs:
        out += r.header()
        out += r.body
    if path is not None:
        open(path, 'wb').write(out)
    return bytes(out)


class Hip(object):
    """Convenience wrapper: records by name, text edits, inserting node records."""

    def __init__(self, path):
        self.path = path
        self.recs = read(path)
        self.index = {r.name: r for r in self.recs}

    def get(self, name):
        if isinstance(name, str):
            name = name.encode('utf-8')
        return self.index.get(name)

    def text(self, name):
        r = self.get(name)
        if r is None:
            raise KeyError(name)
        return r.text

    def set_text(self, name, s):
        r = self.get(name)
        if r is None:
            raise KeyError(name)
        r.set_text(s)

    def names(self, pattern=None):
        names = [r.name.decode('utf-8', 'replace') for r in self.recs]
        if pattern:
            rx = re.compile(pattern)
            names = [n for n in names if rx.search(n)]
        return names

    def insert_after(self, after_name, record):
        """Insert a new record right after the record called `after_name` (or after the last record of a node)."""
        if isinstance(after_name, str):
            after_name = after_name.encode('utf-8')
        if record.name in self.index:
            raise ValueError('record %r already exists' % record.name)
        for i, r in enumerate(self.recs):
            if r.name == after_name:
                self.recs.insert(i + 1, record)
                self.index[record.name] = record
                return
        raise KeyError(after_name)

    def node_records(self, node_path):
        """All records of one node: '<node_path>.<suffix>' (not its children)."""
        prefix = node_path.encode('utf-8') + b'.'
        return [r for r in self.recs if r.name.startswith(prefix) and b'/' not in r.name[len(prefix):]]

    def save(self, path):
        return write(self.recs, path)
