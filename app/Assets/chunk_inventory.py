"""Read-only IoStore identity inventory and deterministic chunk selection.

A displayed chunk number/filename is not the 64-bit ID used by IoStore.
UE 4.26 derives that ID from CityHash64(lower-case UTF-16 container name).
The generated container name is ``pakchunk<number>-WindowsNoEditor``. Check both its
predicted identity and numeric filename reservations before cooking, and still
verify the actual generated header immediately before publication/installation.
Only UToc headers are read during normal scanning; UCAS payloads are never read.
"""
from __future__ import annotations

from collections import defaultdict
import hashlib
from pathlib import Path
import re
import struct

MAGIC = b'-==--==--==--==-'
INVALID_CONTAINER_ID = 'ffffffffffffffff'
_CHUNK_NAME = re.compile(r'(?:pakchunk|OutfitReversalPrepared_)(\d+)(?:\D|$)', re.I)
_MASK64 = (1 << 64)-1
_K1 = 0xb492b66fbe98f273
_K2 = 0x9ae16a3b2f90404f


def _chunk_number(chunk):
    if isinstance(chunk, bool) or not isinstance(chunk, int) or not 1 <= chunk < 2**31:
        raise ValueError('chunk must be a positive signed 32-bit integer')
    return chunk


def _u64(value):
    return value & _MASK64


def _rotate(value, shift):
    value = _u64(value)
    return _u64((value >> shift) | (value << (64-shift)))


def _mix16(first, second, multiplier=0x9ddfea08eb382d69):
    first = _u64((_u64(first) ^ _u64(second))*multiplier)
    first ^= first >> 47
    second = _u64((_u64(second) ^ first)*multiplier)
    second ^= second >> 47
    return _u64(second*multiplier)


def _bswap(value):
    return int.from_bytes(_u64(value).to_bytes(8,'little'),'big')


def container_name_for_chunk(chunk):
    return 'pakchunk'+str(_chunk_number(chunk))+'-WindowsNoEditor'


def container_id_for_chunk(chunk):
    """UE 4.26 generated container ID, returned as 16 lower-case hex digits.

    The name's UTF-16 representation is always 50..68 bytes. Avoid shipping an
    additional binary dependency or running an unknown chunk-changing utility.
    """
    data = container_name_for_chunk(chunk).lower().encode('utf-16-le')
    size = len(data)
    fetch = lambda offset: struct.unpack_from('<Q',data,offset)[0]
    multiplier = _u64(_K2+size*2)
    if size <= 32:
        first = _u64(fetch(0)*_K1)
        second = fetch(8)
        third = _u64(fetch(size-8)*multiplier)
        fourth = _u64(fetch(size-16)*_K2)
        result = _mix16(_rotate(first+second,43)+_rotate(third,30)+fourth,
                        first+_rotate(second+_K2,18)+third,multiplier)
    elif size <= 64:
        first = _u64(fetch(0)*_K2)
        second, third, fourth = fetch(8),fetch(size-24),fetch(size-32)
        fifth = _u64(fetch(16)*_K2)
        sixth = _u64(fetch(24)*9)
        seventh = fetch(size-8)
        eighth = _u64(fetch(size-16)*multiplier)
        part_u = _u64(_rotate(first+seventh,43)+(_rotate(second,30)+third)*9)
        part_v = _u64((_u64(first+seventh) ^ fourth)+sixth+1)
        part_w = _u64(_bswap((part_u+part_v)*multiplier)+eighth)
        part_x = _u64(_rotate(fifth+sixth,42)+third)
        part_y = _u64((_bswap((part_v+part_w)*multiplier)+seventh)*multiplier)
        part_z = _u64(fifth+sixth+third)
        first = _u64(_bswap((part_x+part_z)*multiplier+part_y)+second)
        mixed = _u64((part_z+first)*multiplier+fourth+eighth)
        result = _u64((mixed ^ (mixed >> 47))*multiplier+part_x)
    else:
        # A signed 32-bit chunk label can produce at most 68 bytes; support
        # that whole valid range with the standard long-input loop.
        def weak32(offset, seed_a, seed_b):
            word_a,word_b,word_c,word_d = (fetch(offset+i) for i in (0,8,16,24))
            seed_a = _u64(seed_a+word_a)
            seed_b = _rotate(seed_b+seed_a+word_d,21)
            saved = seed_a
            seed_a = _u64(seed_a+word_b+word_c)
            seed_b = _u64(seed_b+_rotate(seed_a,44))
            return _u64(seed_a+word_d),_u64(seed_b+saved)

        part_x = fetch(size-40)
        part_y = _u64(fetch(size-16)+fetch(size-56))
        part_z = _mix16(fetch(size-48)+size,fetch(size-24))
        state_v = weak32(size-64,size,part_z)
        state_w = weak32(size-32,part_y+_K1,part_x)
        part_x = _u64(part_x*_K1+fetch(0))
        remaining = (size-1) & ~63
        offset = 0
        while remaining:
            part_x = _u64(_rotate(part_x+part_y+state_v[0]+fetch(offset+8),37)*_K1)
            part_y = _u64(_rotate(part_y+state_v[1]+fetch(offset+48),42)*_K1)
            part_x ^= state_w[1]
            part_y = _u64(part_y+state_v[0]+fetch(offset+40))
            part_z = _u64(_rotate(part_z+state_w[0],33)*_K1)
            state_v = weak32(offset,state_v[1]*_K1,part_x+state_w[0])
            state_w = weak32(offset+32,part_z+state_w[1],part_y+fetch(offset+16))
            part_x,part_z = part_z,part_x
            offset += 64
            remaining -= 64
        result = _mix16(_mix16(state_v[0],state_w[0])+_u64((part_y^(part_y>>47))*_K1)+part_z,
                        _mix16(state_v[1],state_w[1])+part_x)
    return '%016x'%result


def read_utoc_header(path):
    """Return sparse identity metadata without opening any companion payload."""
    path = Path(path)
    with path.open('rb') as handle:
        header = handle.read(64)
    if len(header) != 64 or header[:16] != MAGIC:
        raise ValueError('Invalid UToc header: '+str(path))
    version = header[16]
    header_size = struct.unpack_from('<I',header,20)[0]
    if version == 0 or header_size < 64 or header_size > path.stat().st_size:
        raise ValueError('Invalid UToc header size/version: '+str(path))
    return {'path':str(path),'containerId':'%016x'%struct.unpack_from('<Q',header,56)[0],
            'version':version,'headerSize':header_size,
            'filenameChunks':[int(match.group(1)) for match in _CHUNK_NAME.finditer(path.name)]}


def scan_containers(pak_root):
    """Inventory installed containers; unrelated unreadable files are warnings.

    Retain their paths and numeric filename reservations with a null identity.
    read_utoc_header stays strict for generated/incoming package validation.
    """
    if not pak_root:
        return []
    root = Path(pak_root)
    if not root.is_dir():
        raise ValueError('pakRoot is not a directory: '+str(root))
    rows = []
    for path in sorted(root.rglob('*')):
        if path.suffix.casefold() != '.utoc':
            continue
        try:
            if path.is_dir():
                continue
            row = read_utoc_header(path)
        except (OSError, ValueError) as error:
            row = {'path':str(path),'containerId':None,'headerReadable':False,
                   'filenameChunks':[int(match.group(1)) for match in _CHUNK_NAME.finditer(path.name)],
                   'headerError':'unreadable_header' if isinstance(error,OSError) else 'invalid_or_unsupported_header'}
        rows.append(row)
    return rows


def chunk_is_available(chunk, rows):
    expected = container_id_for_chunk(chunk)
    return not any(row['containerId'] == expected or chunk in row.get('filenameChunks',[]) for row in rows)


def choose_chunk(pak_root=None, *, rows=None, start=61947, stop=65535):
    """Choose an unused numeric label AND unused real container identity."""
    _chunk_number(start)
    if isinstance(stop,bool) or not isinstance(stop,int) or not start < stop <= 2**31:
        raise ValueError('stop must exceed start and be at most 2**31')
    rows = scan_containers(pak_root) if rows is None else rows
    occupied_ids = {row['containerId'] for row in rows}
    occupied_numbers = {number for row in rows for number in row.get('filenameChunks',[])}
    for number in range(start,stop):
        if number not in occupied_numbers and container_id_for_chunk(number) not in occupied_ids:
            return number
    raise ValueError('No unused chunk number/container identity found in the chosen range')


def duplicate_container_groups(rows, *, compare_toc_bytes=False):
    """Describe duplicate IDs without assuming duplicated TOCs imply equal UCAS.

    Optional hashing reads only repeated TOCs. It distinguishes an identical
    TOC copy from separately cooked metadata sharing an identity. No package is
    removed, and an apparent backup folder is not silently excluded from scan.
    """
    groups = defaultdict(list)
    for row in rows:
        if row.get('containerId') not in (None, INVALID_CONTAINER_ID):
            groups[row['containerId']].append(row)
    duplicates = []
    for identity, matches in sorted(groups.items()):
        if len(matches) < 2:
            continue
        item = {'containerId':identity,'paths':[row['path'] for row in matches], 'kind':'duplicate_container_id'}
        if compare_toc_bytes:
            hashes = []
            for row in matches:
                digest = hashlib.sha256()
                with Path(row['path']).open('rb') as handle:
                    for data in iter(lambda:handle.read(1024*1024),b''):
                        digest.update(data)
                hashes.append(digest.hexdigest())
            item['tocSha256'] = hashes
            item['kind'] = 'identical_utoc_duplicates' if len(set(hashes)) == 1 else 'distinct_utoc_collision'
        duplicates.append(item)
    return duplicates


def duplicate_chunk_label_groups(rows):
    """Report repeated visible numeric labels separately from real identities."""
    groups=defaultdict(list)
    for row in rows:
        for number in set(row.get('filenameChunks',[])):
            groups[number].append(row)
    return [{'chunk':number,'paths':[r['path'] for r in values],
             'containerIds':sorted({r['containerId'] for r in values if r.get('containerId') is not None}),
             'unreadableHeaders':[r['path'] for r in values if r.get('containerId') is None]}
            for number,values in sorted(groups.items()) if len(values)>1]


# CityHash's short-input arithmetic above is adapted under its MIT license:
# Copyright (c) 2011 Google, Inc.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
