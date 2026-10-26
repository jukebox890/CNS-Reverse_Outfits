"""Restore each protected slot's own source colour inputs; no UV substitutions."""
import math
import re


def source_parameters(slot,references,effective_parameters,rgba_values,is_primary):
    textures=[];vectors=[];parameters=[]
    inputs=list(slot.get('textures',[]))
    for ref in references:
        if ref.get('slot')==slot['index'] and ref.get('source'):
            inputs.append(dict(parameter=ref['parameter'],association=ref['association'],layer=ref['layer'],
                source=ref['source'],kind='colour',origin=ref.get('origin','material_override')))
    for item in sorted(effective_parameters(inputs),key=lambda p:p['parameter'].casefold()):
        if item.get('association')!=2 or item.get('layer')!=-1 or not is_primary(item['parameter']):continue
        source=item.get('source')
        if not isinstance(source,str) or not source.startswith('/Game/') or '..' in source:continue
        textures.append(dict(name=item['parameter'],association=2,index=-1,value=source,sourceReference=True))
        parameters.append(dict(MaterialIndex=slot['index'],Association='Global',LayerIndex=-1,
            ParamName=item['parameter'],ParamType='Texture',Value=source))
    inputs=list(slot.get('vectors',[]))+list(slot.get('restoreVectors',[]))
    for item in sorted(effective_parameters(inputs),key=lambda p:p['parameter'].casefold()):
        if item.get('association')!=2 or item.get('layer')!=-1:continue
        if item.get('origin')=='master_default':continue
        compact=re.sub('[^a-z]','',item['parameter'].lower())
        if any(word in compact for word in ('mask','normal','channel','uv','eye','hair','emissive','fuzz','grime','scratch','hdri','flake','gem','coat','strap')):continue
        if 'tint' not in compact and compact not in ('color','colour','basecolor','basecolour','skincolor','skincolour','skincolourratio'):continue
        value=rgba_values(item['value'])
        if value is None or not all(math.isfinite(v) for v in value):continue
        vectors.append(dict(name=item['parameter'],association=2,index=-1,value=value))
        parameters.append(dict(MaterialIndex=slot['index'],Association='Global',LayerIndex=-1,
            ParamName=item['parameter'],ParamType='Vector',Value=value))
    return textures,vectors,parameters


def material(parent,parent_class,owner,textures,vectors,token):
    spec=dict(parent=parent,parentClass=parent_class,textureParameters=textures,vectorParameters=vectors)
    name='MI_RV_'+token([spec,owner,'explicit-source-reset-v1'])
    path='/Game/OutfitReversalPrepared/Materials/'+name+'.'+name
    return path,{**spec,'assetName':name,'assetPath':path}
