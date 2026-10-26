"""Upgrade retained positional bindings without changing saved colour policies."""
import hashlib
import json

def pending_records(candidate,records):
    active=candidate.active_entries()
    return [r for r in records if r['id'] in active and any(v.get('supported',True) and v.get('materialBindingsVersion',0)<2
             for frame in [active[r['id']]]+active[r['id']].get('history',[]) for v in frame['prepared']['variants'])]

def repair(candidate,records,extracted,token):
    meshes={m['id']:m for m in extracted['meshes']};fixed=0
    for record in records:
        entry=candidate.state['outfits'][record['id']]
        for index,variant in [(i,v) for frame in [entry]+entry.get('history',[]) for i,v in enumerate(frame['prepared']['variants'])]:
            if not variant.get('supported',True) or variant.get('materialBindingsVersion',0)>=2:continue
            mesh=meshes.get(token([record['id'],index]))
            if not mesh or not mesh.get('slots'):raise ValueError('Could not resolve retained material bindings: '+record['id'])
            materials=variant['materials'];repairs=0;unresolved=[]
            for slot in mesh['slots']:
                i=slot['index']
                if i>=256:raise ValueError('Retained outfit exceeds material-slot bound')
                parent=slot.get('material')
                if i<len(materials) and materials[i] and materials[i]!=parent:continue
                if not parent:
                    if slot.get('status')=='empty_material_slot':continue
                    unresolved.append(i);continue
                cls=str(slot.get('materialClass',''))
                if cls.startswith('UMaterialInstance'):
                    path,asset=isolated_binding(parent,'MaterialInstanceConstant',[record['id'],index,i],token)
                    candidate.state['assets'][path]={'kind':'material','spec':asset}
                    entry['assetPaths']=sorted(set(entry['assetPaths'])|{path})
                elif cls=='UMaterial':
                    spec={'parent':parent,'parentClass':'Material','textureParameters':[],'vectorParameters':[]}
                    name='MI_RV_'+token(spec);path='/Game/OutfitReversalPrepared/Materials/'+name+'.'+name
                    candidate.state['assets'][path]={'kind':'material','spec':{**spec,'assetName':name,'assetPath':path}}
                    entry['assetPaths']=sorted(set(entry['assetPaths'])|{path})
                else:unresolved.append(i);continue
                while len(materials)<=i:materials.append('')
                materials[i]=path;repairs+=1
            variant['materialBindingsVersion']=2
            if unresolved:
                variant['partial']=True;variant['unresolvedMaterialSlots']=unresolved
                candidate._issue('retained_material_slots_unresolved',record['id'],variant=index,slots=unresolved,
                    detail='Existing unresolved slots remain partial; no material reference or UV mapping was guessed.')
            fixed+=repairs
            if repairs:candidate._issue('retained_material_slots_repaired',record['id'],variant=index,slots=repairs,
                detail='Resolved from this exact source mesh/variant; saved conversion settings are unchanged.')
    return fixed


def isolated_binding(parent,parent_class,owner,token):
    spec={'parent':parent,'parentClass':parent_class,'textureParameters':[],'vectorParameters':[]}
    name='MI_RV_'+token([spec,owner,'isolated-source-v2'])
    path='/Game/OutfitReversalPrepared/Materials/'+name+'.'+name
    return path,{**spec,'assetName':name,'assetPath':path}
