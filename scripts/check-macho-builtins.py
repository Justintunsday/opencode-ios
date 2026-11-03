"""Reject self-calling libc memory builtins in the clang-linked arm64 renderer.

Regression: renderer run 41531609826's _memset at 0x242984 restored its frame
then unconditionally branched back to its own entry. A real-device spindump
sampled that loop while setting styled text/program status. Manually compiling
Zig compiler_rt.zig must use -fno-builtin, matching Zig's runtime builder.
"""
import argparse
import struct
from pathlib import Path


def audit(path):
    data = path.read_bytes()
    magic, cpu, _, _, count, _, _, _ = struct.unpack_from('<IiiIIIII', data)
    if magic != 0xFEEDFACF or cpu != 0x100000C:
        raise ValueError('expected thin little-endian arm64 Mach-O')
    segments = []
    symtab = None
    offset = 32
    for _ in range(count):
        command, size = struct.unpack_from('<II', data, offset)
        if command == 0x19:
            address, length, file_offset, file_size = struct.unpack_from('<QQQQ', data, offset + 24)
            segments.append((address, file_offset, file_size))
        elif command == 2:
            symtab = struct.unpack_from('<IIII', data, offset + 8)
        offset += size
    if symtab is None:
        raise ValueError('LC_SYMTAB is required for the builtin audit')
    sym_offset, sym_count, str_offset, _ = symtab
    symbols = []
    for i in range(sym_count):
        index, kind, _, _, address = struct.unpack_from('<IBBHQ', data, sym_offset + i * 16)
        if address and kind & 0xE == 0xE and not kind & 0xE0:
            start = str_offset + index
            end = data.index(b'\0', start)
            symbols.append((address, data[start:end].decode('utf-8', errors='replace')))
    addresses = sorted({address for address, _ in symbols})
    checked = 0
    failures = []
    for address, name in symbols:
        if name not in {'_memset', '_memcpy', '_memmove', '_memcmp', '_bcmp'}:
            continue
        end = next((value for value in addresses if value > address), address + 1024)
        segment = next((s for s in segments if s[0] <= address < s[0] + s[2]), None)
        if segment is None:
            raise ValueError(f'{name}: symbol does not map to file bytes')
        checked += 1
        for pc in range(address, min(end, address + 16384), 4):
            file_offset = segment[1] + pc - segment[0]
            instruction = struct.unpack_from('<I', data, file_offset)[0]
            if instruction >> 26 not in {0b000101, 0b100101}:
                continue
            displacement = instruction & 0x3FFFFFF
            if displacement & 0x2000000:
                displacement -= 0x4000000
            if pc + displacement * 4 == address:
                failures.append(f'{name}: self branch/call at 0x{pc:x} -> 0x{address:x}')
        print(f'CHECKED {name} 0x{address:x}..0x{end:x}')
    if checked == 0:
        raise ValueError('no local memory builtin definitions found')
    if failures:
        raise ValueError('; '.join(failures))
    print(f'COMPILER_RT_BUILTINS_PASS checked={checked}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dylib', type=Path)
    args = parser.parse_args()
    try:
        audit(args.dylib)
    except (ValueError, struct.error) as error:
        parser.exit(1, f'COMPILER_RT_BUILTINS_FAIL: {error}\n')
