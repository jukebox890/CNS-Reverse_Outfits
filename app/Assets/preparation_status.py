"""Small saved-policy summaries. Scans never decode images to build these."""
import json
from pathlib import Path

def policy_text(options,variant):
    mode='White' if variant.get('mode',options.get('mode'))=='white' else 'Reverse'
    if not options:return mode+' · Settings unknown'
    skin=str(options.get('skinStrength',50)) if options.get('protectSkin',True) else 'off'
    red=str(options.get('redStrength',50)) if options.get('retainRed',False) else 'off'
    gold=str(options.get('goldStrength',50)) if options.get('retainGold',False) else 'off'
    parts=[mode,'Skin '+skin,'Red '+red,'Gold '+gold]
    if mode=='Reverse':parts+=['Lightness '+('on' if options.get('invertLightness',False) else 'off'),
                               'Red/blue '+('on' if options.get('redBlueSwap',False) else 'off')]
    return ' · '.join(parts)

def installed_outfits(pak_root):
    try:
        packages=Path(pak_root)/'~mods/OutfitReversalPrepared'
        if not any(t.with_suffix('.pak').is_file() and t.with_suffix('.ucas').is_file() for t in packages.glob('*.utoc')):return {}
        path=Path(pak_root).parents[1]/'Binaries/Win64/ue4ss/Mods/DekCNS/Scripts/OutfitReversal/Prepared.json'
        return json.loads(path.read_text(encoding='utf-8-sig')).get('outfits',{})
    except (OSError,ValueError,TypeError):return {}

def describe(entry,installed):
    from prepared_library import prepared_value
    versions=entry.get('history',[])+[entry]
    lines=[];summaries=[];partial=False
    for number,frame in enumerate(versions,1):
        options=frame.get('variantOptions',[])
        for i,variant in enumerate(frame['prepared']['variants']):
            if not variant.get('supported',True):continue
            text=policy_text(options[i] if i<len(options) else frame.get('options',{}),variant)
            summaries.append(text);partial|=bool(variant.get('partial'))
            label=('Colour version '+str(number)+' / ' if len(versions)>1 else '')+'Variant '+str(i+1)
            lines.append(label+': '+text+(' · Source texture/tint reset' if variant.get('maximumSkinResetParameters') else '')+(' · Partial' if variant.get('partial') else ''))
    status='Installed' if installed==prepared_value(entry) else 'Prepared (not installed)'
    unique=list(dict.fromkeys(summaries))
    summary=(unique[0] if len(unique)==1 else 'Mixed settings ('+str(len(unique))+')') if unique else 'Settings unknown'
    if len(versions)>1:
        summary=str(len(versions))+' colour versions '+('installed' if status=='Installed' else 'prepared (not installed)')
        if partial:summary+=' · Partial'
        return {'installed':status=='Installed','preparationSummary':summary,
                'preparationDetails':status+'\n'+'\n'.join(lines)}
    if partial:summary+=' · Partial'
    return {'installed':status=='Installed','preparationSummary':status+' · '+summary,
            'preparationDetails':status+'\n'+'\n'.join(lines)}
