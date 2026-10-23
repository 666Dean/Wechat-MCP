# SPDX-License-Identifier: MIT
"""Bounded PE dependency inventory; no executable loading or PATH search."""
import re,struct
from pathlib import Path

def imports(path):
    path=Path(path)
    if path.is_symlink() or not path.is_file() or not 64<=path.stat().st_size<=512*1024**2:raise ValueError('windows_pe_budget_or_type')
    data=path.read_bytes()
    try:
        u16=lambda offset:struct.unpack_from('<H',data,offset)[0]
        u32=lambda offset:struct.unpack_from('<I',data,offset)[0]
        pe=u32(0x3c);optional=pe+24
        if data[:2]!=b'MZ' or data[pe:pe+4]!=b'PE\0\0' or u16(pe+4)!=0x8664 or u16(optional)!=0x20b:raise ValueError()
        sections=u16(pe+6);optional_size=u16(pe+20)
        if not 1<=sections<=128 or optional_size<240 or u32(optional+108)<14:raise ValueError()
        table=optional+optional_size;image_base=struct.unpack_from('<Q',data,optional+24)[0]
        def mapped(rva,size=1):
            if not rva or not 0<size<=65536:raise ValueError()
            for i in range(sections):
                row=table+i*40;length,address,raw,offset=(u32(row+n) for n in (8,12,16,20))
                if address<=rva and rva-address+size<=min(length,raw):
                    value=offset+rva-address
                    if value+size>len(data):raise ValueError()
                    return value
            raise ValueError()
        names=set()
        for number,stride,name_offset in ((1,20,12),(13,32,4)):
            rva,size=(u32(optional+112+number*8+n) for n in (0,4))
            if not rva and not size:continue
            if not rva or not 0<size<=65536:raise ValueError()
            for offset in range(0,size,stride):
                row=mapped(rva+offset,stride)
                if not any(data[row:row+stride]):break
                address=u32(row+name_offset)
                if number==13 and not u32(row)&1:address-=image_base
                start=mapped(address);end=data.find(b'\0',start,min(start+261,len(data)))
                if end<0:raise ValueError()
                name=data[start:end].decode('ascii').lower()
                if not re.fullmatch(r'[a-z0-9_.-]{1,250}\.dll',name):raise ValueError()
                names.add(name)
            else:raise ValueError()
        return names
    except (ValueError,IndexError,struct.error,UnicodeError,OverflowError):raise ValueError('windows_pe_imports_invalid') from None

def inventory(root):
    import hashlib
    root=Path(root);result={};size=0
    for path in sorted(root.rglob('*')):
        if path.is_symlink() or path.is_junction():raise ValueError('windows_package_links_denied')
        if path.is_dir():continue
        relative=path.relative_to(root).as_posix()
        if (not path.is_file() or len(result)>=20000 or path.stat().st_nlink!=1 or
                any(c in relative for c in '\\:\r\n') or any(p.endswith((' ','.')) for p in path.relative_to(root).parts)):
            raise ValueError('windows_package_file_invalid')
        size+=path.stat().st_size
        if size>2*1024**3:raise ValueError('windows_package_budget')
        result[relative]=hashlib.sha256(path.read_bytes()).hexdigest()
    return result
