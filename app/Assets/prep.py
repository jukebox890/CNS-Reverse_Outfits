"""Prelaunch CNS colour preparation. Source game/config files stay read-only."""
from __future__ import annotations
import argparse
import copy
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import uuid
from PIL import Image

HERE = Path(__file__).resolve().parent
MATERIAL_SLOT_LIMIT = 256
from colour_bake import bake_png, reverse_linear_rgba, transform_settings, SKIN_HEURISTIC_WARNING
from cns_compat import integrate_installed
from reader_setup import ensure_reader
from prepared_library import PreparedLibrary
import material_bindings
import preparation_status
import skin_safety
import skin_reset
import accessory_sources
import dependency_check
from chunk_inventory import scan_containers, duplicate_container_groups, duplicate_chunk_label_groups, choose_chunk as choose_available_chunk

def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def read_cns_json(path):
    """CNS's bundled Lua decoder accepts trailing array/object commas.

    Match that tolerance in source configs without modifying them or relaxing
    validation of generated manifests. Commas inside quoted paths stay intact.
    """
    text=Path(path).read_text(encoding='utf-8-sig')
    out=[];quoted=False;escaped=False;previous=''
    for i,char in enumerate(text):
        if quoted:
            out.append(char)
            if escaped:escaped=False
            elif char=='\\':escaped=True
            elif char=='"':quoted=False;previous='"'
            continue
        if char=='"':quoted=True
        if char==',' and previous not in ('','[','{',',',':'):
            j=i+1
            while j<len(text) and text[j].isspace():j+=1
            if j<len(text) and text[j] in ']}':continue
        out.append(char)
        if not char.isspace():previous=char
    return json.loads(''.join(out))

def write_json(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')

def token(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:20]

def scan(settings):
    paks = Path(settings['pakRoot']).resolve()
    records, issues = [], []
    for file in sorted(paks.rglob('*.dekcns.json')):
        if any(p.lower() in ('backup','backups','.git','sources') for p in file.relative_to(paks).parts):
            continue
        # Source catalogue identity, never a mesh-path/name guess. Custom CNS
        # files referencing BS assets remain eligible.
        relative=[p.casefold() for p in file.relative_to(paks).parts]
        if (not settings.get('includeStandardOutfits',False)
            and file.name.casefold()=='dekcns-defaultoutfitseve.dekcns.json'
            and 'customnanosuitsystem' in relative and 'cosmetics' in relative):
            continue
        try:
            data = read_cns_json(file)
            if not isinstance(data, list): raise ValueError('CNS root must be an array')
            for index, row in enumerate(data):
                if not isinstance(row, dict): continue
                if row.get('FitMeshType','Body') not in ('','Body') or row.get('CharacterID','EVE').upper() != 'EVE': continue
                fit_id = row.get('UniqueFitID')
                if not isinstance(fit_id, str) or not fit_id: continue
                advanced = row.get('OutfitDatas')
                variants = copy.deepcopy(advanced) if advanced else [dict(Mesh=m,Materials=[],Parameters=[]) for m in row.get('OutfitPaths',[])]
                if not variants or any(not isinstance(v,dict) or not v.get('Mesh') for v in variants):
                    issues.append({'source':str(file),'id':fit_id,'reason':'Incomplete variant definitions'}); continue
                records.append({'id':fit_id,'name':row.get('DisplayName',fit_id),'source':str(file),'row':index,
                                'variants':variants,'userConfigs':row.get('UserConfigs',{}),'original':row})
        except Exception as error:
            issues.append({'source':str(file),'reason':str(error)[:300]})
    counts = {}
    for record in records: counts[record['id']] = counts.get(record['id'],0)+1
    for record in records: record['duplicate'] = counts[record['id']] > 1
    return records, issues

def safe_output(settings, output):
    output = Path(output).resolve()
    paks = Path(settings['pakRoot']).resolve()
    game = paks.parents[2]
    if output == game or output.is_relative_to(game): raise ValueError('Choose an output folder outside the game installation')
    output.mkdir(parents=True, exist_ok=True)
    return output

def run_process(args, log):
    print('Running '+Path(args[0]).name, flush=True)
    with Path(log).open('w',encoding='utf-8') as file:
        # Forward only sparse progress events; preserve the complete diagnostic
        # log without pushing texture/UE messages through the GUI for every line.
        with subprocess.Popen([str(a) for a in args],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                              text=True,encoding='utf-8',errors='replace',bufsize=1,
                              creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)) as process:
            for line in process.stdout:
                file.write(line)
                if line.startswith('[PROGRESS] '):print(line.rstrip('\r\n'),flush=True)
            code=process.wait()
    if code: raise RuntimeError('Step failed; see '+str(log))

def progress(phase, step, total, message, **fields):
    print('[PROGRESS] '+json.dumps(dict(phase=phase,step=step,total=total,message=message,**fields),
                                  ensure_ascii=True),flush=True)

def prepare_extraction(settings, records, output, bindings_only=False):
    meshes=[]
    for outfit_index,record in enumerate(records,1):
        for index, variant in enumerate(record['variants']):
            materials=variant.get('Materials',[])
            if not isinstance(materials,list) or any(not isinstance(m,str) for m in materials):
                raise ValueError('Materials must be a positional array of paths: '+record['id'])
            meshes.append({'id':token([record['id'],index]),'mesh':variant['Mesh'],
                'materialOverrides':[{'index':i,'material':m} for i,m in enumerate(materials) if m],
                'parameters':variant.get('Parameters',[]),'userConfigs':record.get('userConfigs',{}),
                'outfitIndex':outfit_index,'outfitTotal':len(records),'outfitName':record.get('name',record['id']),
                'variantIndex':index+1,'variantTotal':len(record['variants'])})
    job={key:settings[key] for key in ('pakRoot','mappings','libraries')}
    if settings.get('nativeRoot'): job['nativeRoot']=settings['nativeRoot']
    job.update(outputRoot=str(output/'extracted'),meshes=meshes,bindingsOnly=bindings_only)
    write_json(output/'extract-job.json',job)
    run_process([settings.get('powershell','pwsh.exe'),'-NoProfile','-File',HERE/'Extractor.ps1','-Job',output/'extract-job.json'],output/'extraction.log')
    return read_json(output/'extracted/extraction-manifest.json')

def rgba_values(value):
    if isinstance(value,dict):raw=[value.get(k,1 if k=='A' else 0) for k in 'RGBA']
    elif isinstance(value,(list,tuple)) and len(value) in (3,4):raw=list(value)+([1] if len(value)==3 else [])
    else:return None
    try:return [float(v) for v in raw]
    except (ValueError,TypeError):return None

def reverse_vector(value, invert=False, **options):
    # A vector can use HDR intensity; preserve its common intensity multiplier.
    rgba=rgba_values(value)
    if rgba is None:return None
    if not all(math.isfinite(v) for v in rgba) or min(rgba[:3])<0: return None
    try:return reverse_linear_rgba(rgba,invert,**options).tolist()
    except ValueError:return None

def is_colour_vector(name):
    lower=name.lower()
    return ('color' in lower or 'colour' in lower or 'tint' in lower) and not any(
        word in lower for word in ('normal','mask','uv','channel','aotint','ao tint','skin','hair','eye'))

def is_primary_colour_texture(name):
    compact=re.sub('[^a-z]','',name.lower())
    return compact in {base+suffix for base in ('basecolor','basecolour','albedo','diffuse')
                       for suffix in ('','texture','map')}

def effective_parameters(parameters):
    # Cooked FName aliases cannot author two competing texture values. Keep
    # the most specific source override, retaining its original spelling.
    selected={};rank={'master_default':0,'material_override':1,'cns_variant':2}
    for parameter in parameters:
        key=(parameter['parameter'].casefold(),parameter['association'],parameter['layer'])
        previous=selected.get(key)
        if previous is None or rank.get(parameter.get('origin'),1)>=rank.get(previous.get('origin'),1):
            selected[key]=parameter
    return selected.values()

def make_cook_job(settings, records, extracted, output, chunk, invert=True, *, protect_skin=True, retain_red=False, retain_gold=False, mode='reverse', skin_strength=50, red_strength=50, gold_strength=50, red_blue_swap=False, report_progress=False):
    options=dict(protect_skin=protect_skin,retain_red=retain_red,retain_gold=retain_gold,mode=mode,skin_strength=skin_strength,
                 red_strength=red_strength,gold_strength=gold_strength,red_blue_swap=red_blue_swap)
    policy=transform_settings(invert,**options)
    textures, images, materials, prepared, issues = {}, {}, {}, {}, list(extracted.get('issues',[]))
    reference_evidence=[]
    # Extraction inputs are immutable for this job. Reuse hashes and reference
    # inspections across variants/slots rather than decoding identical 4K PNGs.
    source_hashes={};reference_traits={}
    meshes={m['id']:m for m in extracted['meshes']}
    for outfit_index,record in enumerate(records,1):
        if report_progress:
            progress('bake',2,5,'Converting colours with Python',outfitIndex=outfit_index,
                     outfitTotal=len(records),outfitName=record.get('name',record['id']))
        prepared_variants=[];supported_variants=[]
        for variant_index, original in enumerate(record['variants']):
            mesh=meshes.get(token([record['id'],variant_index]))
            if not mesh or mesh.get('status')=='failed':
                raise ValueError('Mesh extraction failed: '+record['id'])
            current=list(original.get('Materials',[])); replacements=[]; colour_slots=0
            pending=[]; direct=[];valid_inputs=0
            # A known skin BaseColor remains skin when another material uses an
            # anonymous name. Exact source/PNG matches are stronger evidence
            # than guessing from the clothing material's name or an RGB range.
            skin_sources=set();skin_hashes=set()
            skin_reference_paths=[]
            for ref in mesh.get('skinReferences',[]):
                if not ref.get('referenceOnly') or ref.get('bindingConfidence',ref.get('confidence')) not in ('high','medium'):continue
                reference=output/'extracted'/str(ref.get('png',''))
                informative=False
                if ref.get('png') and reference.is_file():
                    if reference not in reference_traits:
                        with Image.open(reference) as image:
                            rgba=image.convert('RGBA');extrema=rgba.getextrema()
                            reference_traits[reference]=min(image.size)>=16 and extrema[3][1]>0 and any(a!=b for a,b in extrema[:3])
                    informative=reference_traits[reference]
                    if informative:
                        skin_reference_paths.append(reference)
                        if reference not in source_hashes:source_hashes[reference]=hashlib.sha256(reference.read_bytes()).hexdigest()
                        skin_hashes.add(source_hashes[reference])
                        if ref.get('source'):skin_sources.add(ref['source'])
                reference_evidence.append({'id':record['id'],'variant':variant_index,**ref,'assetExemptionEligible':informative})
            hardware_label=lambda path:bool(re.search(r'(?:^|[_\W])(?:metal\d*|metallic|steel|chrome)(?:$|[_\W])',str(path).rsplit('/',1)[-1].split('.')[0].lower()))
            hardware_sources={p.get('source') for s in mesh.get('slots',[]) if hardware_label(s.get('material',''))
                              for p in effective_parameters(s.get('textures',[])) if is_primary_colour_texture(p['parameter'])
                              and p.get('source') and not re.search(r'skin|body|flesh|mixed',str(p['source']).rsplit('/',1)[-1],re.I)}
            maximum_safety=protect_skin and skin_strength==100
            maximum_skin_slots={s['index'] for s in mesh.get('slots',[]) if s.get('status')=='protected_skin_or_cosmetic'} if maximum_safety else set()
            palette=skin_safety.reference_palette(skin_reference_paths) if maximum_safety else None
            maximum_checks={}
            maximum_resets=[]
            for slot in mesh.get('slots',[]):
                if slot.get('status') != 'inspected': continue
                index=slot['index']
                if not slot.get('material'): continue
                uses_known_skin=False
                for parameter in effective_parameters(slot.get('textures',[])):
                    if parameter.get('kind')!='colour' or not parameter.get('png') or not is_primary_colour_texture(parameter['parameter']):continue
                    path=output/'extracted'/parameter['png']
                    if path not in source_hashes:source_hashes[path]=hashlib.sha256(path.read_bytes()).hexdigest()
                    if parameter.get('source') in skin_sources or source_hashes[path] in skin_hashes:
                        uses_known_skin=True;break
                if uses_known_skin:
                    if maximum_safety:maximum_skin_slots.add(index)
                    valid_inputs+=1
                    issues.append({'code':'skin_reference_material_preserved','id':record['id'],'variant':variant_index,'slot':index,
                        'detail':'The primary colour asset exactly matches a dedicated skin reference; this material and its tints remain unchanged.'})
                    continue
                tx, vec=[],[]
                # Strong, generic surface evidence only. Mixed body/cloth and
                # lace atlases still use adaptive pixel-level skin protection.
                leaf=slot['material'].rsplit('/',1)[-1].split('.')[0].lower()
                primary_sources=[p.get('source') for p in effective_parameters(slot.get('textures',[])) if is_primary_colour_texture(p['parameter']) and p.get('kind')=='colour']
                hardware=bool(skin_sources) and (hardware_label(slot['material']) or bool(primary_sources) and all(s in hardware_sources for s in primary_sources))
                if maximum_safety:
                    evidence=None
                    for parameter in effective_parameters(slot.get('textures',[])):
                        if parameter.get('kind')!='colour' or not parameter.get('png') or not is_primary_colour_texture(parameter['parameter']):continue
                        source=output/'extracted'/parameter['png']
                        if source not in maximum_checks:maximum_checks[source]=skin_safety.broad_skin_evidence(source,palette)
                        candidate=maximum_checks[source]
                        # A material called Metal can contain the entire body
                        # in a custom atlas. Names alone must not disable skin
                        # protection at maximum safety. Require much broader,
                        # reference-matched flesh evidence on hardware so warm
                        # gold trim does not preserve a whole metal material.
                        if candidate and (not hardware or
                            candidate['referenceMatched'] and candidate['broadSkinCoverage'] >= .15):
                            evidence=candidate;break
                    if evidence:
                        maximum_skin_slots.add(index);valid_inputs+=1
                        issues.append({'code':'maximum_skin_material_preserved','id':record['id'],'variant':variant_index,'slot':index,
                            **evidence,'detail':'Maximum skin safety preserves this whole source material, including any clothing sharing it.'})
                        continue
                protected_skin_pixels=0
                protected_retained_pixels=0
                for parameter in effective_parameters(slot.get('textures',[])):
                    if parameter.get('kind')!='colour' or not parameter.get('png'): continue
                    # Do not activate every optional pattern declared by a master.
                    # Preserve inherited master defaults; only transform actual
                    # instance/CNS overrides or the primary base-colour input.
                    if parameter.get('origin')=='master_default' and not is_primary_colour_texture(parameter['parameter']):
                        continue
                    if parameter['association']!=2 or parameter['layer']!=-1:
                        issues.append({'code':'layered_material_requires_preparation','id':record['id'],'slot':index,'parameter':parameter['parameter']});continue
                    source=output/'extracted'/parameter['png']
                    if source not in source_hashes:source_hashes[source]=hashlib.sha256(source.read_bytes()).hexdigest()
                    texture_options=dict(options)
                    texture_leaf=str(parameter.get('source','')).rsplit('/',1)[-1].lower()
                    if hardware and not re.search(r'skin|body|flesh|mixed',texture_leaf):
                        texture_options['protect_skin']=False
                        issues.append({'code':'hardware_skin_false_positive_avoided','id':record['id'],'variant':variant_index,'slot':index,'parameter':parameter['parameter']})
                    key=token([source_hashes[source],policy,texture_options['protect_skin']])
                    asset='T_RV_'+key
                    asset_path='/Game/OutfitReversalPrepared/Textures/'+asset+'.'+asset
                    if key not in images:
                        target=output/'recoloured'/(asset+'.png')
                        images[key]=bake_png(source,target,invert_lightness=invert,cache_dir=output/'cache',**texture_options)
                        textures[key]={'sourcePng':str(target),'assetName':asset,'assetPath':asset_path}
                    tx.append({'name':parameter['parameter'],'association':2,'index':-1,'value':asset_path})
                    protected_skin_pixels+=images[key]['protectedPixels']['skin']
                    protected_retained_pixels+=images[key]['protectedPixels']['red']+images[key]['protectedPixels']['gold']
                    valid_inputs+=1
                    replacements.append({'MaterialIndex':index,'Association':'Global','LayerIndex':-1,'ParamName':parameter['parameter'],'ParamType':'Texture'})
                for parameter in effective_parameters(slot.get('vectors',[])):
                    if parameter['association']!=2 or parameter['layer']!=-1 or not is_colour_vector(parameter['parameter']): continue
                    if parameter.get('origin')=='master_default': continue
                    source_value=rgba_values(parameter['value'])
                    if source_value is None:continue
                    if not all(math.isfinite(v) for v in source_value) or min(source_value[:3])<0:
                        issues.append({'code':'invalid_colour_vector_preserved','id':record['id'],'variant':variant_index,
                            'slot':index,'parameter':parameter['parameter']})
                        continue
                    compact=re.sub('[^a-z]','',parameter['parameter'].lower())
                    if maximum_safety and 'emissive' in compact and max(source_value[:3])<=1e-9:
                        issues.append({'code':'disabled_emissive_preserved','id':record['id'],'variant':variant_index,
                            'slot':index,'parameter':parameter['parameter'],
                            'detail':'Maximum skin safety does not activate a previously black/off emissive input.'})
                        continue
                    primary_multiplier=('tint' in compact or compact in ('basecolor','basecolour','color','colour','diffusecolor','diffusecolour'))
                    if protect_skin and protected_skin_pixels and (primary_multiplier or skin_strength>50):
                        issues.append({'code':'skin_safe_tint_preserved','id':record['id'],'variant':variant_index,
                            'slot':index,'parameter':parameter['parameter'],
                            'detail':'A whole-material colour multiplier could recolour protected flesh in the same texture; its original value is retained.'})
                        continue
                    if protected_retained_pixels and primary_multiplier:
                        issues.append({'code':'retained_colour_tint_preserved','id':record['id'],'variant':variant_index,
                            'slot':index,'parameter':parameter['parameter'],
                            'detail':'Retained red/gold pixels share this texture; retain the original whole-material multiplier so it cannot recolour those pixels after baking.'})
                        continue
                    # A coloured texture and its primary RGB multiplier are a
                    # compound input. Independently inverting both can turn a
                    # newly lightened atlas almost black a second time. Keep
                    # recognised base multipliers on texture-led reversals;
                    # in white mode a fully unprotected cloth input can use a
                    # neutral multiplier, preserving its original alpha.
                    known_base_multiplier=compact in ('basetint','basecolortint','basecolourtint',
                        'basecolor','basecolour','diffusecolor','diffusecolour','diffusetint',
                        'diffusecolortint','diffusecolourtint')
                    has_primary_texture=any(is_primary_colour_texture(p['name']) for p in tx)
                    if known_base_multiplier and has_primary_texture:
                        if mode=='white' and not protected_skin_pixels and not protected_retained_pixels and max(source_value[:3])<=1:
                            value=[1.,1.,1.,source_value[3]]
                            if max(abs(a-b) for a,b in zip(value,source_value))>=1e-7:
                                vec.append({'name':parameter['parameter'],'association':2,'index':-1,'value':value})
                                replacements.append({'MaterialIndex':index,'Association':'Global','LayerIndex':-1,'ParamName':parameter['parameter'],'ParamType':'Vector'})
                            issues.append({'code':'white_primary_tint_neutralized','id':record['id'],'variant':variant_index,
                                'slot':index,'parameter':parameter['parameter']})
                        else:
                            issues.append({'code':'primary_texture_tint_preserved','id':record['id'],'variant':variant_index,
                                'slot':index,'parameter':parameter['parameter'],
                                'detail':'Keep the original primary multiplier instead of independently inverting both texture and tint. Existing CNS colour controls remain available.'})
                        continue
                    # A neutral white multiplier must stay neutral after its
                    # texture is inverted, otherwise white cloth becomes black.
                    if tx and 'tint' in parameter['parameter'].lower() and all(abs(v-1)<1e-6 for v in source_value[:3]):
                        continue
                    vector_options=dict(options)
                    if hardware:vector_options['protect_skin']=False
                    value=reverse_vector(source_value,invert,**vector_options)
                    if value is None: continue
                    valid_inputs+=1
                    source=source_value
                    if max(abs(a-b) for a,b in zip(value,source))<1e-7:continue
                    vec.append({'name':parameter['parameter'],'association':2,'index':-1,'value':value})
                    replacements.append({'MaterialIndex':index,'Association':'Global','LayerIndex':-1,'ParamName':parameter['parameter'],'ParamType':'Vector'})
                if not tx and not vec: continue
                spec={'parent':slot['material'],'parentClass':'Material' if slot.get('materialClass')=='UMaterial' else 'MaterialInstanceConstant','textureParameters':tx,'vectorParameters':vec}
                key=token(spec);name='MI_RV_'+key;path='/Game/OutfitReversalPrepared/Materials/'+name+'.'+name
                pending.append((index,key,path,{**spec,'assetName':name,'assetPath':path}))
                for kind,values in (('Texture',tx),('Vector',vec)):
                    for parameter in values:
                        direct.append({'MaterialIndex':index,'Association':'Global','LayerIndex':-1,
                            'ParamName':parameter['name'],'ParamType':kind,'Value':parameter['value']})
            key_of=lambda p:(p.get('MaterialIndex',0),p.get('Association','Global'),p.get('LayerIndex',-1),p.get('ParamName'),p.get('ParamType'))
            changed={key_of(p) for p in replacements}
            remaining=[p for p in original.get('Parameters',[]) if key_of(p) not in changed]
            additions=[];incomplete=set()
            if direct and len(direct)+len(remaining)<=10 and len(current)<=MATERIAL_SLOT_LIMIT:
                # CNS texture parameters retain the existing dynamic material,
                # all its non-colour state, and can address slots above nine.
                additions=direct;colour_slots=len(pending)
                strategy='existing_material_parameters'
            else:
                strategy='positional_child_materials'
                allowed=set()
                for index,key,path,spec in pending:
                    if index>=MATERIAL_SLOT_LIMIT:
                        incomplete.add(index)
                        issues.append({'code':'material_slot_safety_bound','id':record['id'],'slot':index,
                            'detail':'This layout exceeds the preparer\'s 256-slot safety bound.'})
                        continue
                    materials[key]=spec;allowed.add(index)
                    while len(current)<=index:current.append('')
                    current[index]=path;colour_slots+=1
                # Only FString material paths are resized by the checked helper.
                # Parameter structs keep the inspected ten-entry bound. Unique
                # export-text wrappers in the helper preserve holes/duplicates
                # through CNS's RemoveEmptyStrings/Array_AddUnique filtering.
                replacements=[p for p in replacements if p['MaterialIndex'] in allowed]
            issues.append({'code':'application_strategy','id':record['id'],'variant':variant_index,
                           'strategy':strategy,'colourSlots':colour_slots,'parameterUpdates':len(additions)})
            selected_keys={key_of(p) for p in replacements}
            kept_parameters=[p for p in original.get('Parameters',[]) if key_of(p) not in selected_keys]
            supported=(colour_slots>0 or (valid_inputs>0 and not pending)) and len(current)<=MATERIAL_SLOT_LIMIT and len(kept_parameters)+len(additions)<=10
            if len(kept_parameters)+len(additions)>10:
                issues.append({'code':'source_parameter_capacity','id':record['id'],'variant':variant_index,
                    'detail':'Existing parameter structs exceed the inspected ten-entry handoff; the previous successful result is kept.'})
            if not supported:
                issues.append({'code':'no_supported_colour_materials','id':record['id'],'variant':variant_index})
            else:
                # CNS's advanced branch skips its default-MID reset as soon as
                # any material path is present. Empty protected/unchanged slots
                # therefore keep a PREVIOUS outfit's override. Restore each
                # slot from its own effective source binding instead of holes.
                restored=0
                for slot in mesh.get('slots',[]):
                    index=slot['index']
                    if index>=MATERIAL_SLOT_LIMIT:
                        incomplete.add(index);continue
                    parent=slot.get('material')
                    if index<len(current) and current[index] and current[index]!=parent:continue
                    if not parent:
                        if slot.get('status')!='empty_material_slot':incomplete.add(index)
                        continue
                    if str(slot.get('materialClass','')).startswith('UMaterialInstance'):
                        if index in maximum_skin_slots:
                            reset_tx,reset_vec,reset_params=skin_reset.source_parameters(slot,[r for r in mesh.get('skinReferences',[]) if r.get('source') in skin_sources],effective_parameters,rgba_values,is_primary_colour_texture)
                            path,asset=skin_reset.material(parent,'MaterialInstanceConstant',[record['id'],variant_index,index],reset_tx,reset_vec,token)
                            materials[asset['assetName']]=asset;maximum_resets.extend(reset_params)
                            issues.append({'code':'maximum_skin_source_defaults_restored','id':record['id'],'variant':variant_index,'slot':index,
                                'textures':len(reset_tx),'vectors':len(reset_vec),'detail':'Explicit source colour defaults are restored without converting them.'})
                        else:
                            path,asset=material_bindings.isolated_binding(parent,'MaterialInstanceConstant',[record['id'],variant_index,index],token)
                            materials[asset['assetName']]=asset
                    elif slot.get('materialClass')=='UMaterial':
                        # The BP accepts MaterialInstance objects only. A
                        # passthrough child represents a verified plain parent,
                        # without colour/UV changes.
                        spec={'parent':parent,'parentClass':'Material','textureParameters':[],'vectorParameters':[]}
                        key=token(spec);name='MI_RV_'+key
                        path='/Game/OutfitReversalPrepared/Materials/'+name+'.'+name
                        materials[key]={**spec,'assetName':name,'assetPath':path}
                    else:
                        incomplete.add(index)
                        issues.append({'code':'source_material_restore_unverified','id':record['id'],'variant':variant_index,
                            'slot':index,'detail':'Original material class was not resolved; no guessed replacement was generated.'})
                        continue
                    while len(current)<=index:current.append('')
                    current[index]=path;restored+=1
                issues.append({'code':'original_material_slots_restored','id':record['id'],'variant':variant_index,
                    'slots':restored,'detail':'Each unchanged/protected slot explicitly restores its own original material instead of inheriting a previous outfit override.'})
                # Use CNS's existing parameter handoff to clear stale MID values
                # too. The checked ten-entry limit and author parameters remain.
                known_keys={key_of(p) for p in additions}
                kept=[p for p in original.get('Parameters',[]) if key_of(p) not in {key_of(r) for r in replacements}]
                for parameter in sorted(maximum_resets,key=lambda p:(p['ParamType']!='Texture',p['MaterialIndex'],p['ParamName'].casefold())):
                    if key_of(parameter) in known_keys:continue
                    existing=next((p for p in kept if key_of(p)==key_of(parameter)),None)
                    if len(kept)+len(additions)-(1 if existing else 0)>=10:continue
                    if existing:kept.remove(existing)
                    additions.append(parameter);known_keys.add(key_of(parameter))
                    replacements.append({key:value for key,value in parameter.items() if key!='Value'})
            supported_variants.append(supported)
            prepared_variants.append({'mesh':original['Mesh'],'materials':current,'parameters':additions,'materialBindingsVersion':2,
                                      'accessorySources':accessory_sources.plan(mesh.get('slots',[]),current,pending,additions) if supported else [],
                                      'maximumSkinPreservedSlots':sorted(maximum_skin_slots),
                                      'maximumSkinResetParameters':maximum_resets,
                                      'replacedParameters':replacements,'supported':supported,'mode':mode,'partial':bool(incomplete)})
        if any(supported_variants):
            prepared[record['id']]={'originalCount':len(record['variants']),'variants':prepared_variants}
        else:
            issues.append({'code':'outfit_not_marked_prepared','id':record['id'],
                'detail':'No variant has supported colour inputs; any previous successful preparation is retained.'})
        if any(record.get('userConfigs',{}).get(key) for key in ('VectorControls','TextureOptions')):
            issues.append({'code':'existing_colour_controls_preserved','id':record['id'],
                           'detail':'Existing controls can override prepared material defaults; runtime control values are not baked.'})
    write_json(output/'bake-validation.json',list(images.values()))
    write_json(output/'Prepared.json',{'schemaVersion':1,'reverseLightness':invert,'colourPolicy':policy,'outfits':prepared})
    write_json(output/'preparation-report.json',{'complete':False,'outfits':len(records),'uniqueTextures':len(textures),
        'preparedMaterials':len(materials),'colourPolicy':policy,'issues':issues,'skinReferenceAssets':reference_evidence,
        'limitations':extracted.get('limitations',[])+([SKIN_HEURISTIC_WARNING] if protect_skin else [])})
    job={'outputRoot':str(output/'cooked'),'pakRoot':settings['pakRoot'],
         'chunkId':chunk,'textures':list(textures.values()),'materials':list(materials.values())}
    write_json(output/'cook-job.json',job)
    return job

def choose_chunk(settings):
    return choose_available_chunk(settings['pakRoot'])

def write_inventory(settings,candidate,records,issues,output):
    ready=candidate.prepared_manifest()['outfits'];entries=candidate.active_entries()
    installed=preparation_status.installed_outfits(settings['pakRoot'])
    rows=[]
    for r in records:
        item={key:r[key] for key in ('id','name','source','duplicate')}
        item.update(prepared=r['id'] in ready,preparedModes=sorted({v.get('mode','reverse') for v in ready.get(r['id'],{}).get('variants',[]) if v.get('supported',True)}),
                    partial=any(v.get('partial',False) for v in ready.get(r['id'],{}).get('variants',[])))
        if r['id'] in entries:item.update(preparation_status.describe(entries[r['id']],installed.get(r['id'])))
        else:item.update(installed=False,preparationSummary='Not prepared',preparationDetails='No saved preparation for this outfit.')
        rows.append(item)
    write_json(output/'inventory.json',{'outfits':rows,'issues':issues+candidate.issues,'dependencies':settings.get('_dependencies',{})})

def stage(settings, output):
    output=safe_output(settings,output)
    if (output/'Prepared.json').stat().st_size>16*1024*1024:
        raise ValueError('Saved colour versions exceed the CNS metadata size limit. Replace or uninstall some earlier versions before preparing again.')
    result=read_json(output/'cooked/prepared-cook-manifest.json')
    profile=result.get('validation',{}).get('profile')
    if profile!='stellarblade-initial-single-export-v1':raise ValueError('Prepared output has an obsolete container format. Prepare outfits again before installing.')
    payload=output/'_InstallPayload'
    scripts=payload/'SB/Binaries/Win64/ue4ss/Mods/DekCNS/Scripts'
    module=scripts/'OutfitReversal';module.mkdir(parents=True,exist_ok=True)
    for name in ('Init.lua','MetadataBridge.lua','AccessoryLink.lua'):
        shutil.copy2(HERE/'CNSRuntime'/name,module/name)
    shutil.copy2(output/'Prepared.json',module/'Prepared.json')
    live=Path(settings['pakRoot']).parents[1]/'Binaries/Win64/ue4ss/Mods/DekCNS/Scripts/main.lua'
    source=live.read_bytes()
    (scripts/'main.lua').write_bytes(integrate_installed(source))
    paks=payload/'SB/Content/Paks/~mods/OutfitReversalPrepared';paks.mkdir(parents=True,exist_ok=True)
    for filename in result['packageFiles']:
        item=Path(filename if isinstance(filename,str) else filename['path'])
        shutil.copy2(item,paks/item.name)
    files=[{'relativePath':p.relative_to(payload).as_posix(),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
           for p in sorted((payload/'SB').rglob('*')) if p.is_file()]
    write_json(payload/'InstallManifest.json',{'schemaVersion':1,'containerProfile':profile,'sourceCnsMainSha256':hashlib.sha256(source).hexdigest(),'files':files})
    sys.path.insert(0,str(HERE/'installer'))
    from export_installer import export_installer
    delivery=output/'Install'
    export_installer(payload,delivery)
    return delivery


def publish(settings, output, run, candidate):
    """Promote a complete build, retaining the previous install for recovery."""
    output=safe_output(settings,output);run=Path(run).resolve()
    if not run.is_relative_to(output/'Runs'):raise ValueError('Build must be inside the output Runs directory')
    source=run/'Install';destination=output/'Install';backup=None
    if destination.exists():
        backups=output/'Backups';backups.mkdir(exist_ok=True)
        backup=backups/('Install-'+uuid.uuid4().hex[:12])
        destination.rename(backup)
    try:
        source.rename(destination)
        candidate.commit()
    except Exception:
        if destination.exists():destination.rename(source)
        if backup is not None and backup.exists():backup.rename(destination)
        raise
    # These are convenience diagnostics; the library index and Install are
    # authoritative. All stored PNG inputs already belong to Library/blobs.
    for name in ('Prepared.json','cook-job.json','preparation-report.json','bake-validation.json','cook.log'):
        if (run/name).is_file():shutil.copy2(run/name,output/name)
    (output/'cooked').mkdir(exist_ok=True)
    shutil.copy2(run/'cooked/prepared-cook-manifest.json',output/'cooked/prepared-cook-manifest.json')
    return destination

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--settings',default=str(HERE/'Settings.json'))
    parser.add_argument('--output',required=True)
    parser.add_argument('--scan',action='store_true')
    parser.add_argument('--uninstall',action='store_true',help='Remove selected generated choices from the library and installed game')
    parser.add_argument('--keep-previous',action='store_true',help='Keep earlier colour versions of the selected outfits')
    parser.add_argument('--outfit',action='append',default=[])
    parser.add_argument('--all',action='store_true')
    parser.set_defaults(invert_lightness=True)
    parser.add_argument('--invert-lightness',dest='invert_lightness',action='store_true')
    parser.add_argument('--disable-lightness-inversion',dest='invert_lightness',action='store_false')
    parser.add_argument('--skin-strength',type=int,choices=range(101),default=50,metavar='0..100')
    parser.add_argument('--red-strength',type=int,choices=range(101),default=50,metavar='0..100')
    parser.add_argument('--gold-strength',type=int,choices=range(101),default=50,metavar='0..100')
    parser.add_argument('--red-blue-swap',action='store_true')
    parser.add_argument('--no-protect-skin',action='store_true')
    parser.add_argument('--retain-red',action='store_true')
    parser.add_argument('--retain-gold',action='store_true')
    parser.add_argument('--mode',choices=('reverse','white'),default='reverse')
    args=parser.parse_args()
    settings_path=Path(args.settings).resolve();settings=read_json(settings_path)
    for key in ('pakRoot','mappings','libraries','nativeRoot','python','powershell','readerArchive'):
        if settings.get(key) and not Path(settings[key]).is_absolute():
            settings[key]=str((settings_path.parent/settings[key]).resolve())
    settings['readOnlyDdcRoots']=[str((settings_path.parent/p).resolve()) if not Path(p).is_absolute() else p
                                  for p in settings.get('readOnlyDdcRoots',[])]
    output=safe_output(settings,args.output)
    from uninstall_selected import operation_lock
    import atexit
    guard=operation_lock(output);guard.__enter__();atexit.register(guard.__exit__,None,None,None)
    if args.scan:progress('scan',1,1,'Scanning custom CNS outfits')
    records,issues=scan(settings)
    containers=scan_containers(settings['pakRoot'])
    settings['_dependencies']=dependency_check.check(settings['pakRoot'],containers)
    for dependency in settings['_dependencies']['items']:
        print('DEPENDENCY '+dependency['name']+': '+dependency['message']+(' '+dependency['url'] if dependency['state']!='ok' else ''),flush=True)
    conflicts=duplicate_container_groups(containers)
    label_conflicts=duplicate_chunk_label_groups(containers)
    write_json(output/'container-inventory.json',{'containers':containers,'duplicateGroups':conflicts,
        'duplicateChunkLabels':label_conflicts,'readOnly':True,'existingPackagesModified':False})
    print('Checked '+str(len(containers))+' installed IoStore headers; '+str(len(conflicts))+' duplicate container-ID groups; '+str(len(label_conflicts))+' repeated filename chunk labels.',flush=True)
    for conflict in conflicts:
        issues.append({'code':'existing_container_id_overlap',**conflict})
        print('Existing container-ID overlap: '+'; '.join(conflict['paths'])+'. Existing packages were not changed.',flush=True)
    for conflict in label_conflicts:
        kind='duplicate internal IDs' if len(conflict['containerIds'])==1 else 'distinct internal IDs; not duplicate containers'
        print('Filename chunk label '+str(conflict['chunk'])+' is reused ('+kind+').',flush=True)
    candidate=PreparedLibrary(output/'Library').begin(records=records)
    candidate.import_legacy(output)
    for snapshot in sorted((HERE/'Migration').glob('*')):
        if snapshot.is_dir():candidate.import_legacy(snapshot)
    write_inventory(settings,candidate,records,issues,output)
    if args.scan:
        print(json.dumps({'outfits':len(records),'scanIssues':len(issues),'inventory':str(output/'inventory.json')}));return
    if args.uninstall:
        from uninstall_selected import uninstall
        if args.all:raise ValueError('Uninstall requires explicit selected outfit IDs.')
        print(json.dumps(uninstall(settings,output,candidate,args.outfit,records,issues,write_inventory)),flush=True)
        return
    selected=[r for r in records if not r['duplicate'] and (args.all or r['id'] in args.outfit)]
    if not selected:raise ValueError('Select at least one nonduplicate outfit with --outfit or --all')
    missing=set(args.outfit)-{r['id'] for r in selected}
    if missing:raise ValueError('Missing or duplicate outfit IDs: '+', '.join(sorted(missing)))
    run=output/'Runs'/uuid.uuid4().hex[:12];run.mkdir(parents=True)
    options=dict(protect_skin=not args.no_protect_skin,retain_red=args.retain_red,retain_gold=args.retain_gold,mode=args.mode,skin_strength=args.skin_strength,
                 red_strength=args.red_strength,gold_strength=args.gold_strength,red_blue_swap=args.red_blue_swap)
    try:
        if not Path(settings.get('mappings','')).is_file():
            settings['mappings']=str(HERE/'Mappings/StellarBlade_1.1.0.usmap')
        if not Path(settings['mappings']).is_file():raise ValueError('Bundled mapping is missing. Extract the entire ZIP, or choose a matching .usmap in Settings.')
        live=Path(settings['pakRoot']).parents[1]/'Binaries/Win64/ue4ss/Mods/DekCNS/Scripts/main.lua'
        integrate_installed(live.read_bytes())
        progress('extract',1,5,'Setting up and inspecting outfit assets')
        ensure_reader(settings,output)
        extracted=prepare_extraction(settings,selected,run)
        job=make_cook_job(settings,selected,extracted,run,choose_chunk(settings),args.invert_lightness,report_progress=True,**options)
        imported=candidate.import_specs(read_json(run/'Prepared.json'),job,records=selected,
            provenance='preparer-0.4.10',options=transform_settings(args.invert_lightness,**options),source_root=run,keep_previous=args.keep_previous)
        repair_records=material_bindings.pending_records(candidate,records)
        if repair_records:
            progress('cook',3,5,'Checking retained outfit material bindings')
            bindings=prepare_extraction(settings,repair_records,run/'binding-repair',bindings_only=True)
            repaired=material_bindings.repair(candidate,repair_records,bindings,token)
            print('Repaired '+str(repaired)+' retained material slots; saved colour settings preserved.',flush=True)
        write_json(run/'Prepared.json',candidate.prepared_manifest())
        aggregate=candidate.cook_job(job)
        write_json(run/'cook-job.json',aggregate)
        report=read_json(run/'preparation-report.json')
        report.update(preparedOutfits=len(candidate.prepared_manifest()['outfits']),updatedOutfits=imported,
            retainedOutfits=[key for key in candidate.prepared_manifest()['outfits'] if key not in imported],
            issues=report['issues']+candidate.issues)
        write_json(run/'preparation-report.json',report)
        progress('cook',3,5,'Building textures and materials')
        if not aggregate.get('textures') and not aggregate.get('materials'):
            if not candidate.prepared_manifest()['outfits']:
                raise ValueError('No supported colour inputs were found. Previous successful output is unchanged.')
            write_json(run/'cooked/prepared-cook-manifest.json',{'packageFiles':[],'textures':[],'materials':[],
                'validation':{'identityOnly':True,'inGameVisualTested':False}})
            (run/'cook.log').write_text('All recognised colours were retained by the selected policy; no generated assets required.\n')
        else:
            run_process([sys.executable,HERE/'engine_free_backend.py',run/'cook-job.json'],run/'cook.log')
        progress('verify',4,5,'Checking the generated package manifest')
        cooked=read_json(run/'cooked/prepared-cook-manifest.json')
        if cooked.get('packageFiles'):
            # Cooking already validates the exact asset set/container. Keep this
            # quick so progress reporting does not add another game-file mount.
            files=[Path(p if isinstance(p,str) else p['path']) for p in cooked['packageFiles']]
            if (len(files)!=3 or {p.suffix.casefold() for p in files}!={'.pak','.ucas','.utoc'}
                or len({p.stem for p in files})!=1 or any(not p.is_file() or p.stat().st_size==0 for p in files)):
                raise ValueError('Generated package triplet is incomplete; previous output retained.')
        progress('stage',5,5,'Building installer output and saving the preparation library')
        stage(settings,run)
        destination=publish(settings,output,run,candidate)
        write_inventory(settings,candidate,records,issues,output)
    except Exception:
        if (run/'cook.log').is_file():shutil.copy2(run/'cook.log',output/'cook.log')
        raise
    print(json.dumps({'success':True,'installFolder':str(destination),'preparedOutfits':len(candidate.prepared_manifest()['outfits']),
                     'updatedOutfits':imported,'gameFilesModified':False}),flush=True)

if __name__=='__main__':
    try:main()
    except Exception as error:
        print('ERROR: '+str(error),file=sys.stderr,flush=True);raise SystemExit(1)
