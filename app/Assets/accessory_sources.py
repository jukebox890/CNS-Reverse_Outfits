"""Derive unambiguous shared-material links from this preparation's own inputs."""
import json


def plan(slots, prepared_materials, pending, parameters):
    by_slot={s['index']:s for s in slots}
    groups={}
    for index,_,path,spec in pending:
        if index>=len(prepared_materials) or prepared_materials[index]!=path:continue
        slot=by_slot[index]
        if slot.get('status')!='inspected':continue
        source=slot.get('material')
        if not source or source.startswith('/Game/OutfitReversalPrepared/'):continue
        signature={k:v for k,v in spec.items() if k not in ('assetName','assetPath')}
        signature['parameters']=[{k:v for k,v in p.items() if k!='MaterialIndex'}
                                  for p in parameters if p.get('MaterialIndex')==index]
        groups.setdefault(source,[]).append((index,path,json.dumps(signature,sort_keys=True)))
    links=[]
    for source,values in sorted(groups.items()):
        # A repeated material can have different CNS settings on different body
        # slots. Never guess which one a separate component should follow.
        if len({v[2] for v in values})!=1:continue
        index,path,_=min(values)
        links.append(dict(sourceMaterial=source,bodySlot=index,preparedMaterial=path))
    return links
