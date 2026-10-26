"""Strict Stellar Blade package-store profile for our one-export generated assets.

The shipped game and prior working containers use 32-byte Initial store entries,
not 16-byte PreInitial entries. Normalize single-export dependency bundles and
populate byte sizes/load order before publishing. No original game assets change.
"""
from pathlib import Path
import shutil
import struct

PROFILE = 'stellarblade-initial-single-export-v1'

def u32(data, offset):
    return struct.unpack_from('<I', data, offset)[0]

def take_vector(data, offset, unit=1):
    count=u32(data,offset);start=offset+4;end=start+count*unit
    if count>1000000 or end>len(data):raise ValueError('Invalid package-store vector bounds')
    return data[start:end],end,count

def read_store(data):
    if len(data)<36:raise ValueError('Truncated package store')
    container,count=struct.unpack_from('<QI',data)
    names,pos,_=take_vector(data,12)
    hashes,pos,_=take_vector(data,pos)
    ids,pos,n=take_vector(data,pos,8)
    if n!=count or not 1<=n<=100000:raise ValueError('Package-store count mismatch')
    buffer,pos,_=take_vector(data,pos)
    if len(buffer)<n*32:raise ValueError('Package-store entries do not use the Stellar Blade layout')
    rows={}
    for i in range(n):
        pid=struct.unpack_from('<Q',ids,8*i)[0];off=i*32
        size,exports,bundles,order,pad,num,delta=struct.unpack_from('<Qii4I',buffer,off)
        start=off+24+delta;end=start+num*8
        if exports!=1 or bundles not in (1,2) or pad or num>100000 or (num and (start<n*32 or end>len(buffer))):
            raise ValueError('Generated package-store entry has an unsupported layout')
        imports=list(struct.unpack_from('<'+'Q'*num,buffer,start)) if num else []
        if pid in rows:raise ValueError('Duplicate package ID')
        rows[pid]=dict(size=size,exports=exports,bundles=bundles,order=order,imports=imports)
    # Generated assets have no localized packages. Keep genuine redirects intact;
    # remove only the writer's redundant id -> id redirects.
    if u32(data,pos)!=0:raise ValueError('Generated package store contains localization data')
    redirects,pos,nredir=take_vector(data,pos+4,16)
    for i in range(nredir):
        source,target=struct.unpack_from('<QQ',redirects,i*16)
        if source!=target:raise ValueError('Unexpected generated package redirect')
    # Native containers pad this chunk to a 64 KiB block; accept only zeros.
    if any(data[pos:]) or len(data)-pos>=65536:raise ValueError('Unexpected package-store trailing data')
    return container,names,hashes,rows

def normalize_package(data,row,generated_ids):
    if len(data)<64:raise ValueError('Truncated generated package')
    imp,exp,bundle,graph,graph_size=struct.unpack_from('<5i',data,40)
    count=row['bundles']
    if not 64<=imp<=exp<bundle<graph or graph+graph_size>len(data):raise ValueError('Invalid generated summary offsets')
    if graph-bundle!=count*8+16:raise ValueError('Only one-export generated assets can be normalized')
    headers=[struct.unpack_from('<II',data,bundle+i*8) for i in range(count)]
    if headers not in ([(0,2)],[(0,1),(1,1)]):raise ValueError('Unexpected generated bundle sequence')
    entries=data[bundle+count*8:graph]
    if entries!=struct.pack('<4I',0,0,0,1):raise ValueError('Unexpected export commands')
    pos=graph;n=u32(data,pos);pos+=4;records=[]
    if n>100000:raise ValueError('Invalid dependency graph size')
    for _ in range(n):
        pid=struct.unpack_from('<Q',data,pos)[0];pos+=8
        arcs,pos,num=take_vector(data,pos,8);seen=set();new=[]
        for i in range(num):
            source,target=struct.unpack_from('<ii',arcs,i*8)
            if target not in range(count) or source < -1:raise ValueError('Invalid dependency bundle reference')
            if pid in generated_ids and source>=0:
                if source>1:raise ValueError('Invalid generated source bundle')
                source=0
            arc=(source,0)
            if arc not in seen:seen.add(arc);new.append(arc)
        records.append(struct.pack('<QI',pid,len(new))+b''.join(struct.pack('<ii',*arc) for arc in new))
    if pos!=graph+graph_size:raise ValueError('Dependency graph does not match summary')
    new_graph=struct.pack('<I',n)+b''.join(records)
    new_bundle=struct.pack('<II',0,2)+entries
    result=bytearray(data[:bundle]+new_bundle+new_graph+data[pos:])
    struct.pack_into('<ii',result,52,bundle+len(new_bundle),len(new_graph))
    # Export payload and all colour/UV data remain byte-for-byte unchanged.
    if result[bundle+len(new_bundle)+len(new_graph):]!=data[pos:]:raise ValueError('Generated export payload changed')
    return bytes(result)

def write_store(container,names,hashes,rows):
    keys=sorted(rows);orders={};visiting=set()
    def visit(pid):
        if pid in orders:return
        if pid in visiting:raise ValueError('Generated package dependency cycle')
        visiting.add(pid)
        for dep in sorted(rows[pid]['imports']):
            if dep in rows:visit(dep)
        visiting.remove(pid);orders[pid]=len(orders)
    for pid in keys:visit(pid)
    entries=bytearray(len(keys)*32)
    for i,pid in enumerate(keys):
        row=rows[pid];imports=row['imports'];off=i*32
        delta=len(entries)-off-24 if imports else 0
        struct.pack_into('<Qii4I',entries,off,row['size'],1,1,orders[pid],0,len(imports),delta)
        entries.extend(b''.join(struct.pack('<Q',x) for x in imports))
    def vec(value):return struct.pack('<I',len(value))+value
    return (struct.pack('<QI',container,len(keys))+vec(names)+vec(hashes)+struct.pack('<I',len(keys))
            +b''.join(struct.pack('<Q',pid) for pid in keys)+vec(entries)+struct.pack('<II',0,0))

def normalize_container(executable,toc,stage,run):
    toc=Path(toc);stage=Path(stage);raw=stage/'profile-raw'
    run(executable,['unpack-raw',str(toc),str(raw)],stage)
    chunks=raw/'chunks';header_files=[p for p in chunks.iterdir() if p.name.endswith('0a')]
    if len(header_files)!=1:raise ValueError('Expected exactly one package-store header')
    header_file=header_files[0];container,names,hashes,rows=read_store(header_file.read_bytes())
    ids=set(rows);packages={}
    for path in chunks.iterdir():
        if path.name.endswith('02'):
            pid=int.from_bytes(bytes.fromhex(path.name[:16]),'little');packages[pid]=path
    if set(packages)!=ids:raise ValueError('Package-store and generated chunks differ')
    for pid,path in packages.items():
        data=normalize_package(path.read_bytes(),rows[pid],ids);path.write_bytes(data)
        rows[pid]['size']=len(data);rows[pid]['bundles']=1
    store=write_store(container,names,hashes,rows)
    header_file.write_bytes(store+bytes((-len(store))%65536))
    # Re-read the normalized format using the same strict bounds checks.
    _,_,_,checked=read_store(header_file.read_bytes())
    if any(row['bundles']!=1 or row['size']!=packages[pid].stat().st_size for pid,row in checked.items()):
        raise ValueError('Generated package-store profile verification failed')
    fixed=stage/'profile-fixed';fixed.mkdir()
    target=fixed/toc.name
    run(executable,['pack-raw',str(raw),str(target)],stage)
    for suffix in ('.utoc','.ucas'):target.with_suffix(suffix).replace(toc.with_suffix(suffix))
    shutil.rmtree(raw);shutil.rmtree(fixed)
    return dict(profile=PROFILE,packageStoreLayout='Initial',storeEntryBytes=32,
                oneExportBundlePerPackage=True,packageSizesValidated=True,
                dependencyLoadOrderValidated=True,packagesChecked=len(rows))
