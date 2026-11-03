"""Small deterministic Debian ar/tar helpers; no archive extraction on the host."""
import hashlib
import io
import lzma
from pathlib import PurePosixPath
import tarfile


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def safe_name(name):
    name = name.removeprefix('./')
    if not name or name.startswith('/') or '..' in PurePosixPath(name).parts or '\\' in name:
        raise ValueError('Unsafe archive name')
    return name


def read_tar(data):
    files, links = {}, {}
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:*') as archive:
        for item in archive:
            name = safe_name(item.name)
            if item.isdir():
                continue
            if name in files or name in links:
                raise ValueError('Duplicate archive member: ' + name)
            if item.isfile():
                files[name] = (archive.extractfile(item).read(), item.mode)
            elif item.issym():
                if item.linkname.startswith('/'):
                    raise ValueError('Absolute symlink target')
                links[name] = item.linkname
            else:
                raise ValueError('Unsupported archive member type')
    return files, links


def read_deb(path):
    data = path.read_bytes()
    if data[:8] != b'!<arch>\n':
        raise ValueError('Not a Debian ar archive')
    position, members = 8, {}
    while position < len(data):
        header = data[position:position + 60]
        if len(header) != 60 or header[-2:] != b'`\n':
            raise ValueError('Malformed ar header')
        name = header[:16].decode('ascii').strip().removesuffix('/')
        size = int(header[48:58])
        if name in members or size < 0 or position + 60 + size > len(data):
            raise ValueError('Malformed ar member')
        members[name] = data[position + 60:position + 60 + size]
        position += 60 + size + size % 2
    if set(members) != {'debian-binary', 'control.tar.xz', 'data.tar.xz'} or members['debian-binary'] != b'2.0\n':
        raise ValueError('Unexpected Debian archive layout')
    control, _ = read_tar(members['control.tar.xz'])
    files, links = read_tar(members['data.tar.xz'])
    fields = {}
    for line in control['control'][0].decode('utf-8').splitlines():
        if line and not line.startswith((' ', '\t')):
            key, value = line.split(':', 1)
            fields[key] = value.strip()
    return fields, files, links


def tar_xz(files, links, epoch):
    directories = set()
    for name in (*files, *links):
        parent = PurePosixPath(safe_name(name)).parent
        while str(parent) != '.':
            directories.add(str(parent))
            parent = parent.parent
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w', format=tarfile.USTAR_FORMAT) as archive:
        for name in sorted(directories):
            item = tarfile.TarInfo(name + '/')
            item.type, item.mode, item.mtime = tarfile.DIRTYPE, 0o755, epoch
            item.uname, item.gname = 'root', 'wheel'
            archive.addfile(item)
        for name, (data, mode) in sorted(files.items()):
            item = tarfile.TarInfo(name)
            item.size, item.mode, item.mtime = len(data), mode, epoch
            item.uname, item.gname = 'root', 'wheel'
            archive.addfile(item, io.BytesIO(data))
        for name, target in sorted(links.items()):
            item = tarfile.TarInfo(name)
            item.type, item.linkname, item.mode, item.mtime = tarfile.SYMTYPE, target, 0o777, epoch
            item.uname, item.gname = 'root', 'wheel'
            archive.addfile(item)
    return lzma.compress(buffer.getvalue(), preset=6)


def build_deb(control, files, links, epoch):
    md5sums = ''.join(f'{hashlib.md5(data, usedforsecurity=False).hexdigest()}  {name}\n' for name, (data, _) in sorted(files.items())).encode()
    members = [('debian-binary', b'2.0\n'), ('control.tar.xz', tar_xz({'control':(control,0o644),'md5sums':(md5sums,0o644)}, {}, epoch)), ('data.tar.xz', tar_xz(files, links, epoch))]
    data = b'!<arch>\n'
    for name, payload in members:
        header = f'{name+"/":<16}{epoch:<12}{0:<6}{0:<6}{"100644":<8}{len(payload):<10}`\n'.encode()
        if len(header) != 60:
            raise ValueError('Invalid ar header width')
        data += header + payload + (b'\n' if len(payload) % 2 else b'')
    return data
