#!/usr/bin/env python3
"""Minimal, dependency-free reader for Debian binary packages (.deb).

A .deb is an ``ar`` archive containing:

* ``debian-binary``   -- text ``2.0\\n``
* ``control.tar.*``   -- control file and maintainer scripts
* ``data.tar.*``      -- the filesystem tree, paths relative to ``/``

``scripts/validate-port.sh`` uses this module so that the validation suite can
inspect a package on any host (CI macOS runner or a development machine) without
requiring dpkg to be installed. It is intentionally strict: unsafe archive
members (absolute paths, ``..`` components, symlinks escaping the package root)
raise :class:`DebError` instead of being silently extracted.
"""
from __future__ import annotations

import hashlib
import io
import os
import shutil
import stat
import tarfile
from pathlib import Path

AR_MAGIC = b"!<arch>\n"
CHUNK = 1 << 20


class DebError(Exception):
    """Raised for malformed or unsafe .deb archives."""


class DebPackage:
    """Parsed representation of a .deb archive."""

    def __init__(self, path):
        self.path = Path(path)
        if not self.path.is_file():
            raise DebError(f"not a file: {self.path}")
        self.raw = self.path.read_bytes()
        if not self.raw.startswith(AR_MAGIC):
            raise DebError(f"{self.path}: not a Debian ar archive (missing ar magic)")
        self.members = self._parse_ar(self.raw)
        if "debian-binary" not in self.members:
            raise DebError("archive has no debian-binary member (not a .deb)")
        version = self.members["debian-binary"].decode("ascii", "replace").strip()
        if version != "2.0":
            raise DebError(f"unsupported debian-binary version {version!r}")
        self.control_member = self._find_member("control.tar")
        self.data_member = self._find_member("data.tar")

    # ------------------------------------------------------------------ ar ---
    @staticmethod
    def _parse_ar(raw):
        members = {}
        pos = len(AR_MAGIC)
        while pos < len(raw):
            # Tolerate the single padding newline that some ar writers emit.
            if raw[pos:pos + 1] == b"\n":
                pos += 1
                continue
            if raw[pos:].strip() == b"":
                break
            if pos + 60 > len(raw):
                raise DebError("truncated ar member header")
            header = raw[pos:pos + 60]
            name = header[0:16].decode("ascii", "replace").strip()
            size_field = header[48:58].decode("ascii", "replace").strip()
            try:
                size = int(size_field)
            except ValueError as exc:
                raise DebError(f"bad ar member size for {name!r}: {size_field!r}") from exc
            body_start = pos + 60
            body_end = body_start + size
            if body_end > len(raw):
                raise DebError(f"truncated ar member {name!r}")
            if name.endswith("/"):
                name = name[:-1]
            if name in members:
                raise DebError(f"duplicate ar member {name!r}")
            members[name] = raw[body_start:body_end]
            pos = body_end + (size % 2)  # ar pads members to even length
        return members

    def _find_member(self, stem):
        candidates = [
            name for name in self.members
            if name == stem or name.startswith(stem + ".")
        ]
        if not candidates:
            raise DebError(f"archive has no {stem}.* member")
        if len(candidates) > 1:
            raise DebError(f"archive has multiple {stem}.* members: {sorted(candidates)}")
        return candidates[0]

    # -------------------------------------------------------------- tar io ---
    def _open_member(self, member_name):
        data = self.members[member_name]
        suffixes = member_name.split(".")
        comp = suffixes[-1].lower() if len(suffixes) > 1 else ""
        try:
            if comp in ("gz", "gzip"):
                return tarfile.open(fileobj=io.BytesIO(data), mode="r:gz")
            if comp == "xz":
                return tarfile.open(fileobj=io.BytesIO(data), mode="r:xz")
            if comp == "zst":
                return self._open_zstd_tar(member_name, data)
            if comp == "tar":
                return tarfile.open(fileobj=io.BytesIO(data), mode="r:")
        except tarfile.TarError as exc:
            raise DebError(f"cannot read {member_name}: {exc}") from exc
        raise DebError(
            f"unsupported compression for {member_name!r} "
            "(supported: .tar, .tar.gz, .tar.xz, .tar.zst)"
        )

    @staticmethod
    def _open_zstd_tar(member_name, data):
        decompressed = None
        try:  # Python >= 3.14 standard library
            from compression import zstd  # type: ignore[import-not-found]

            decompressed = zstd.decompress(data)
        except ImportError:
            try:
                import zstandard  # type: ignore[import-not-found]

                decompressed = zstandard.ZstdDecompressor().decompress(data)
            except ImportError as exc:
                raise DebError(
                    f"{member_name}: zstd payload needs Python 3.14+ "
                    "(compression.zstd) or the optional 'zstandard' module"
                ) from exc
        return tarfile.open(fileobj=io.BytesIO(decompressed), mode="r:")

    # ------------------------------------------------------------- control ---
    def control_text(self):
        """Return the raw text of the control file."""
        with self._open_member(self.control_member) as tf:
            for member in tf.getmembers():
                name = _normalise_member_name(member.name)
                if name == "control" and member.isfile():
                    handle = tf.extractfile(member)
                    if handle is None:
                        break
                    return handle.read().decode("utf-8", "replace")
        raise DebError("control archive has no 'control' file")

    def parse_control(self):
        """Parse the control file into ``{field: value}`` (continuations kept)."""
        text = self.control_text().replace("\r\n", "\n")
        fields = {}
        current = None
        for line in text.split("\n"):
            if not line:
                continue
            if line[0] in " \t":
                if current is None:
                    raise DebError("control file starts with a continuation line")
                fields[current] += "\n" + line[1:]
                continue
            if ":" not in line:
                raise DebError(f"control file line is not a field: {line!r}")
            key, _, value = line.partition(":")
            key = key.strip()
            if key in fields:
                raise DebError(f"duplicate control field {key!r}")
            fields[key] = value.strip()
            current = key
        return fields

    def control_files(self):
        """Return ``{name: {"data": bytes, "mode": int, "sha256": str}}`` for control.tar.*."""
        result = {}
        with self._open_member(self.control_member) as tf:
            for member in tf.getmembers():
                name = _normalise_member_name(member.name)
                if name in ("", "."):
                    continue
                _reject_unsafe_path(name)
                if member.isdir():
                    continue
                if not member.isfile():
                    raise DebError(f"unsupported control archive member type for {name!r}")
                handle = tf.extractfile(member)
                if handle is None:
                    raise DebError(f"cannot read control member {name!r}")
                data = handle.read()
                result[name] = {
                    "data": data,
                    "mode": member.mode & 0o7777,
                    "size": member.size,
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
        return result

    # ---------------------------------------------------------------- data ---
    def data_entries(self):
        """Return metadata for every member of ``data.tar.*`` (files hashed)."""
        entries = []
        with self._open_member(self.data_member) as tf:
            for member in tf.getmembers():
                name = _normalise_member_name(member.name)
                if name in ("", "."):
                    continue
                _reject_unsafe_path(name)
                if member.isdir():
                    kind = "dir"
                elif member.issym():
                    kind = "symlink"
                elif member.islnk():
                    kind = "hardlink"
                elif member.isfile():
                    kind = "file"
                else:
                    kind = "other"
                entry = {
                    "path": name,
                    "type": kind,
                    "mode": member.mode & 0o7777,
                    "size": member.size,
                }
                if member.issym() or member.islnk():
                    entry["linkname"] = member.linkname
                    _reject_unsafe_link(name, member.linkname)
                if member.isfile():
                    handle = tf.extractfile(member)
                    if handle is None:
                        raise DebError(f"cannot read data member {name!r}")
                    digest = hashlib.sha256()
                    while True:
                        chunk = handle.read(CHUNK)
                        if not chunk:
                            break
                        digest.update(chunk)
                    entry["sha256"] = digest.hexdigest()
                entries.append(entry)
        return entries

    def extract_data(self, dest):
        """Extract ``data.tar.*`` into ``dest``; returns the member metadata list."""
        dest = Path(dest)
        dest.mkdir(parents=True, exist_ok=True)
        root = dest.resolve()
        entries = []
        with self._open_member(self.data_member) as tf:
            for member in tf.getmembers():
                name = _normalise_member_name(member.name)
                if name in ("", "."):
                    continue
                _reject_unsafe_path(name)
                target = dest / name
                mode = member.mode & 0o7777
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    os.chmod(target, mode or 0o755)
                elif member.isfile():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    handle = tf.extractfile(member)
                    if handle is None:
                        raise DebError(f"cannot read data member {name!r}")
                    with open(target, "wb") as out:
                        shutil.copyfileobj(handle, out, CHUNK)
                    os.chmod(target, mode or 0o644)
                elif member.issym():
                    _reject_unsafe_link(name, member.linkname)
                    if os.path.lexists(target):
                        os.unlink(target)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    os.symlink(member.linkname, target)
                elif member.islnk():
                    link_name = _normalise_member_name(member.linkname)
                    _reject_unsafe_path(link_name)
                    source = dest / link_name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if os.path.lexists(target):
                        os.unlink(target)
                    try:
                        os.link(source, target)
                    except OSError:
                        shutil.copy2(source, target)
                else:
                    raise DebError(f"unsupported archive member type for {name!r}")
                entry = {
                    "path": name,
                    "type": "dir" if member.isdir() else
                            "symlink" if member.issym() else
                            "hardlink" if member.islnk() else "file",
                    "mode": mode,
                    "size": member.size,
                }
                if member.isfile():
                    entry["sha256"] = _sha256_file(target)
                if member.issym() or member.islnk():
                    entry["linkname"] = member.linkname
                entries.append(entry)
        # Validate that no symlink/hardlink resolves outside the extraction root.
        for entry in entries:
            if entry["type"] not in ("symlink", "hardlink"):
                continue
            link = dest / entry["path"]
            resolved = (link.parent / entry["linkname"]).resolve()
            try:
                resolved.relative_to(root)
            except ValueError as exc:
                raise DebError(
                    f"archive member {entry['path']!r} links outside the package root"
                ) from exc
        return entries


def _normalise_member_name(name):
    name = name.replace("\\", "/")
    while name.startswith("./"):
        name = name[2:]
    return name.rstrip("/") if name not in ("", ".") else name


def _reject_unsafe_path(name):
    if name.startswith("/") or name.startswith("..") or "/../" in name or name == "..":
        raise DebError(f"unsafe archive path: {name!r}")
    for part in name.split("/"):
        if part in ("", ".", ".."):
            raise DebError(f"unsafe archive path component in {name!r}")


def _reject_unsafe_link(name, linkname):
    if not linkname:
        raise DebError(f"archive member {name!r} has an empty link target")
    if linkname.startswith("/"):
        raise DebError(f"archive member {name!r} has an absolute link target {linkname!r}")
    combined = os.path.normpath(os.path.join(os.path.dirname(name), linkname))
    if combined.startswith("..") or combined.startswith("/"):
        raise DebError(
            f"archive member {name!r} links outside the package root via {linkname!r}"
        )


def _sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(CHUNK)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def parse_sha256sums(text):
    """Parse a ``sha256sum``-format file into ``{path: hexdigest}``."""
    entries = {}
    for line in text.replace("\r\n", "\n").split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            raise DebError(f"malformed SHA256SUMS line: {line!r}")
        digest, name = parts
        name = name.strip()
        if name.startswith("*"):
            name = name[1:]
        name = name.lstrip("./")
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest.lower()):
            raise DebError(f"malformed SHA256SUMS digest: {line!r}")
        entries[name] = digest.lower()
    return entries


def sha256_file(path):
    """Public re-export used by the verification engine."""
    return _sha256_file(path)


def file_mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)
