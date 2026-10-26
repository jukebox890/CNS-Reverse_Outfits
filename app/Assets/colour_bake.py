"""Offline artistic colour-wheel complement for sRGB PNG textures.

No Unreal objects, outfit profiles, game files or runtime shaders are involved.
The PNG alpha channel is copied byte-for-byte. Large images use bounded NumPy
tiles instead of allocating full-size float RGB/HLS intermediates.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

import numpy as np
from PIL import Image, ImageFilter

TRANSFORM_VERSION = "artistic-ryb-hls-v11-skin-evidence-before-hardware"

SKIN_HEURISTIC_WARNING = (
    "Skin-colour protection uses a conservative sRGB colour heuristic, not a skin mask. "
    "It can also retain similarly coloured peach/tan/brown fabric, and cannot identify "
    "every stylised, tinted, shadowed or unusual skin colour. Material-level skin "
    "exclusions remain the first line of protection."
)


def transform_settings(invert_lightness=False, *, protect_skin=True,
                       retain_red=False, retain_gold=False, mode="reverse", skin_strength=50,
                       red_strength=50, gold_strength=50, red_blue_swap=False):
    """Canonical settings for cache keys, asset names and preparation manifests."""
    if mode not in ("reverse", "white"):
        raise ValueError("mode must be 'reverse' or 'white'")
    for name, strength in (("skin_strength", skin_strength), ("red_strength", red_strength),
                           ("gold_strength", gold_strength)):
        if isinstance(strength, bool) or not isinstance(strength, int) or not 0 <= strength <= 100:
            raise ValueError(name + " must be an integer from 0 to 100")
    return {"skinStrength": skin_strength if protect_skin else 0, "transform": TRANSFORM_VERSION, "invertLightness": bool(invert_lightness),
            "protectSkin": bool(protect_skin), "retainRed": bool(retain_red),
            "retainGold": bool(retain_gold), "mode": mode,
            "redStrength": red_strength if retain_red else 0,
            "goldStrength": gold_strength if retain_gold else 0,
            "redBlueSwap": bool(red_blue_swap) if mode == "reverse" else False}


def _colour_data(rgb):
    r, g, b = np.moveaxis(rgb, -1, 0)
    high, low = rgb.max(axis=-1), rgb.min(axis=-1)
    delta, light = high-low, (high+low)*.5
    coloured = delta > 0
    safe_delta = np.where(coloured, delta, 1)
    saturation = np.zeros_like(light)
    denominator = np.where(light <= .5, high+low, 2-high-low)
    np.divide(delta, denominator, out=saturation, where=coloured)
    # Same priority as colorsys: red wins a tied maximum, then green.
    hue = np.where(high == r, (g-b)/safe_delta,
                   np.where(high == g, 2+(b-r)/safe_delta, 4+(r-g)/safe_delta))
    hue = (hue / 6) % 1
    hsv_saturation = np.zeros_like(light)
    np.divide(delta, high, out=hsv_saturation, where=high > 0)
    return hue, light, saturation, hsv_saturation


def _protection_masks(rgb, hue, hsv_saturation, *, protect_skin, retain_red, retain_gold,
                      skin_strength=50, red_strength=50, gold_strength=50):
    """Colour-only masks; these never inspect or infer a texture's UV layout.

    Skin requires a warm/rosy hue, plausible chroma and the common Cb/Cr skin
    range. Hue wraps at red: compression can put natural rosy skin just below
    360 degrees, with blue a few byte values above green. Treating red as a
    one-sided boundary made those pixels become green speckles after reversal.
    Absolute Cb/Cr limits reject strong red and most saturated yellow/gold. Low
    saturation neutrals are intentionally never treated as skin, so black/white
    fabric still converts. Identical skin and textile pixels are indistinguishable.
    """
    r, g, b = np.moveaxis(rgb, -1, 0)
    cb = 128+255*(-.168736*r-.331264*g+.5*b)
    cr = 128+255*(.5*r-.418688*g-.081312*b)
    # Nested thresholds: 50 exactly matches the established standard filter.
    # Lower values narrow every condition; higher values broaden them together.
    # This is sensitivity, not a percentage of pixels to preserve.
    t = (skin_strength-50)/50.0
    if t > 0: t = t*(1+1.5*t)
    warm_or_rosy = (hue <= .115+.055*t) | (hue >= .965-(.04 if skin_strength>50 else .025)*t)
    natural_skin = (warm_or_rosy &
                    (hsv_saturation >= max(.005,.06-.04*t)) & (hsv_saturation <= min(.98,.68+.20*t)) &
                    (r+.04*t >= g) & (r+.04*t >= b) & (g+.04+.04*t >= b) & (r > .055-.04*t) &
                    (cb >= 77-12*t) & (cb <= 128+12*t) & (cr >= 133-10*t) & (cr <= 174+14*t))
    if skin_strength == 0:
        natural_skin = np.zeros(hue.shape, dtype=bool)
    # Sensitivity expands a nested colour family, rather than selecting a
    # percentage of pixels. At 50 these are the exact 0.3.3 retain masks.
    # Higher settings include nearby hue/compression shades, dimmer shadows and
    # less-saturated highlights. A positive chroma threshold always excludes
    # actual neutrals, including black and white. Skin protection is independent.
    red_t = (red_strength-50)/50.0
    gold_t = (gold_strength-50)/50.0
    red = (((hue <= (25+20*red_t)/360) | (hue >= (340-20*red_t)/360)) &
           (hsv_saturation >= .20-.16*red_t) & (rgb.max(axis=-1) >= .04-.03*red_t))
    gold = ((hue >= (25-15*gold_t)/360) & (hue <= (70+15*gold_t)/360) &
            (hsv_saturation >= .12-.10*gold_t) & (rgb.max(axis=-1) >= .04-.03*gold_t))
    empty = np.zeros(hue.shape, dtype=bool)
    return {"skin": natural_skin if protect_skin else empty,
            "red": red if retain_red and red_strength > 0 else empty,
            "gold": gold if retain_gold and gold_strength > 0 else empty}


def _transform_srgb(rgb, settings, skin_context=None):
    hue, light, saturation, hsv_saturation = _colour_data(rgb)
    masks = _protection_masks(rgb, hue, hsv_saturation,
                             protect_skin=settings["protectSkin"], skin_strength=settings.get("skinStrength",50),
                             retain_red=settings["retainRed"], retain_gold=settings["retainGold"],
                             red_strength=settings.get("redStrength",50), gold_strength=settings.get("goldStrength",50))
    if skin_context is not None:
        masks['skin'] &= np.asarray(skin_context,dtype=bool)
    if settings["mode"] == "white":
        # Retain the ordering of perceptual texture shading and a faint colour
        # trace. This maps black through white to 199..250/255 instead of washing
        # every source pixel to identical white. No alpha or technical map edits.
        luminance = rgb @ np.array([.2126, .7152, .0722])
        out = (.78+.20*luminance)[..., None]+.012*(rgb-luminance[..., None])
    else:
        # Reflect the continuous RGB hue circle around its green axis for the
        # optional red/blue palette: red <-> blue, yellow <-> cyan, green and
        # magenta remain fixed. This is an alternative to artistic complements,
        # not a channel-value swap, and leaves HSL shading/saturation intact.
        hue = (2/3-hue) % 1 if settings.get("redBlueSwap",False) else _artist_to_rgb((_rgb_to_artist(hue)+.5) % 1)
        if settings["invertLightness"]:
            light = 1-light
        m2 = np.where(light <= .5, light*(1+saturation), light+saturation-light*saturation)
        m1 = 2*light-m2

        def channel(offset):
            h = (hue+offset) % 1
            return np.select([h < 1/6, h < .5, h < 2/3],
                             [m1+(m2-m1)*h*6, m2, m1+(m2-m1)*(2/3-h)*6], default=m1)

        out = np.stack([channel(1/3), channel(0), channel(-1/3)], axis=-1)
    protected = masks["skin"] | masks["red"] | masks["gold"]
    return np.where(protected[..., None], rgb, out), masks


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rgb_to_artist(h):
    return np.select(
        [h < 1/12, h < 1/6, h < 1/3, h < 2/3, h < .75],
        [h*2, 1/6+(h-1/12)*2, 1/3+(h-1/6), .5+(h-1/3)*.5,
         2/3+(h-2/3)*2], default=5/6+(h-.75)*2/3)


def _artist_to_rgb(h):
    return np.select(
        [h < 1/6, h < 1/3, h < .5, h < 2/3, h < 5/6],
        [h*.5, 1/12+(h-1/6)*.5, 1/6+(h-1/3), 1/3+(h-.5)*2,
         2/3+(h-2/3)*.5], default=.75+(h-5/6)*1.5)


def reverse_rgba(pixels, invert_lightness=False, *, protect_skin=True,
                 retain_red=False, retain_gold=False, mode="reverse", skin_strength=50,
                 red_strength=50, gold_strength=50, red_blue_swap=False):
    """Return uint8 RGBA pixels with unchanged alpha.

    PNG values already represent sRGB. HSL is therefore calculated directly
    here; no linear/gamma conversion should be applied a second time. With
    protect_skin=False and no retain options, reverse mode matches the original
    colour_reference.reverse_srgb. The positional lightness default is retained
    for API compatibility; the prelaunch UI selects inversion by default.
    """
    settings = transform_settings(invert_lightness, protect_skin=protect_skin,
                                  retain_red=retain_red, retain_gold=retain_gold, mode=mode, skin_strength=skin_strength,
                                  red_strength=red_strength, gold_strength=gold_strength, red_blue_swap=red_blue_swap)
    return _rgba_with_counts(pixels, settings)[0]


def _rgba_with_counts(pixels, settings, skin_context=None):
    data = np.asarray(pixels)
    if data.dtype != np.uint8 or data.ndim < 1 or data.shape[-1] != 4:
        raise ValueError("Expected uint8 RGBA pixels")
    rgb = data[..., :3].astype(np.float64) / 255.0
    out, masks = _transform_srgb(rgb, settings, skin_context)
    result = np.empty_like(data)
    result[..., :3] = np.floor(np.clip(out, 0, 1)*255+.5+1e-9).astype(np.uint8)
    result[..., 3] = data[..., 3]
    # Counts exclude fully transparent pixels, whose RGB is not visible.
    visible = data[..., 3] > 0
    counts = {name: int(np.count_nonzero(mask & visible)) for name, mask in masks.items()}
    counts["any"] = int(np.count_nonzero((masks["skin"] | masks["red"] | masks["gold"]) & visible))
    return result, counts


def reverse_linear_rgba(values, invert_lightness=False, *, protect_skin=True,
                        retain_red=False, retain_gold=False, mode="reverse", skin_strength=50,
                        red_strength=50, gold_strength=50, red_blue_swap=False):
    """Transform linear RGBA material vectors using the same colour policy.

    Accepts one RGBA vector or an array of vectors; returns float64 values. A
    common HDR amplitude above one is retained, as is alpha exactly. Negative
    RGB/non-finite data is rejected for callers to skip/report instead of baking
    an invalid material. Skin heuristics use display sRGB of the normalised RGB.
    """
    data = np.asarray(values, dtype=np.float64)
    if data.ndim < 1 or data.shape[-1] != 4:
        raise ValueError("Expected linear RGBA values")
    if not np.isfinite(data).all() or np.any(data[..., :3] < 0):
        raise ValueError("Linear RGBA values must be finite, with non-negative RGB")
    settings = transform_settings(invert_lightness, protect_skin=protect_skin,
                                  retain_red=retain_red, retain_gold=retain_gold, mode=mode, skin_strength=skin_strength,
                                  red_strength=red_strength, gold_strength=gold_strength, red_blue_swap=red_blue_swap)
    rgb = data[..., :3]
    peak = np.maximum(1, rgb.max(axis=-1))[..., None]
    normalised = rgb/peak
    srgb = np.where(normalised <= .0031308, 12.92*normalised,
                    1.055*normalised**(1/2.4)-.055)
    changed, masks = _transform_srgb(srgb, settings)
    changed = np.clip(changed, 0, 1)
    linear = np.where(changed <= .04045, changed/12.92, ((changed+.055)/1.055)**2.4)
    result = np.array(data, copy=True)
    result[..., :3] = linear*peak
    # Retained vectors are byte/float exact, without roundtrip transfer drift.
    protected = masks["skin"] | masks["red"] | masks["gold"]
    result[..., :3] = np.where(protected[..., None], rgb, result[..., :3])
    return result


def texture_skin_context(image, strength=50):
    """Keep broad skin regions; reject detached, thin warm cloth-shadow islands.

    Analyse a bounded thumbnail once, never individual tiles. Aggressive settings
    gradually relax this spatial test; 100 keeps the broad colour-only filter.
    This is an aid for mixed atlases, not proof that a pixel is skin.
    """
    if strength>=100 or min(image.size)<16:return None
    thumb=image.convert('RGBA');thumb.thumbnail((256,256),Image.Resampling.NEAREST)
    data=np.asarray(thumb);rgb=data[...,:3].astype(np.float64)/255
    hue,_,_,sat=_colour_data(rgb)
    candidate=_protection_masks(rgb,hue,sat,protect_skin=True,retain_red=False,retain_gold=False,skin_strength=strength)['skin'] & (data[...,3]>0)
    strict=candidate & (sat <= .54+.16*max(0,strength-50)/50)
    seeds=np.asarray(Image.fromarray(strict.astype('uint8')*255).filter(ImageFilter.MinFilter(3)))>0
    h,w=candidate.shape;seen=np.zeros((h,w),bool);keep=np.zeros_like(seen)
    minimum=max(5,int(candidate.size*.0002*(1-max(0,strength-50)/60)))
    for y,x in zip(*np.nonzero(seeds)):
        if seen[y,x]:continue
        stack=[(int(y),int(x))];seen[y,x]=True;component=[];seed_count=0
        while stack:
            cy,cx=stack.pop();component.append((cy,cx));seed_count+=int(seeds[cy,cx])
            for ny,nx in ((cy-1,cx),(cy+1,cx),(cy,cx-1),(cy,cx+1)):
                if 0<=ny<h and 0<=nx<w and candidate[ny,nx] and not seen[ny,nx]:
                    seen[ny,nx]=True;stack.append((ny,nx))
        if seed_count>=minimum:
            yy,xx=zip(*component);keep[yy,xx]=True
    # One thumbnail pixel of room retains boundary skin without turning this
    # into a blanket material/UV mask. Full-resolution colour tests still apply.
    return Image.fromarray(keep.astype('uint8')*255).filter(ImageFilter.MaxFilter(3)).resize(image.size,Image.Resampling.NEAREST)


def bake_png(source, destination, invert_lightness=False, cache_dir=None, tile_size=512,
             *, protect_skin=True, retain_red=False, retain_gold=False, mode="reverse", skin_strength=50,
             red_strength=50, gold_strength=50, red_blue_swap=False):
    """Bake one PNG, optionally reusing a content-addressed cached PNG.

    Only the requested destination/cache paths are written. Input is never
    overwritten. Returns JSON-compatible metadata for preparation manifests.
    """
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination:
        raise ValueError("Destination must differ from the original texture")
    if not source.is_file():
        raise FileNotFoundError(source)
    if not isinstance(tile_size, int) or not 16 <= tile_size <= 2048:
        raise ValueError("tile_size must be an integer between 16 and 2048")
    settings = transform_settings(invert_lightness, protect_skin=protect_skin,
                                  retain_red=retain_red, retain_gold=retain_gold, mode=mode, skin_strength=skin_strength,
                                  red_strength=red_strength, gold_strength=gold_strength, red_blue_swap=red_blue_swap)
    source_hash = sha256_file(source)
    cache_key = hashlib.sha256(json.dumps({"source": source_hash, **settings},
                                         sort_keys=True, separators=(",", ":")).encode("ascii")).hexdigest()
    cache_root = Path(cache_dir).resolve() if cache_dir else None
    cached = cache_root / (cache_key+".png") if cache_root else None
    count_cache = cache_root / (cache_key+".counts.json") if cache_root else None
    destination.parent.mkdir(parents=True, exist_ok=True)
    hit = False
    protected_counts = {"skin": 0, "red": 0, "gold": 0, "any": 0}
    with Image.open(source) as original:
        if original.format != "PNG":
            raise ValueError("Source must be a PNG")
        size = original.size
        context=texture_skin_context(original,skin_strength) if protect_skin and skin_strength>0 else None
        if cached and cached.is_file():
            with Image.open(cached) as existing:
                hit = existing.format == "PNG" and existing.mode == "RGBA" and existing.size == size
        if hit:
            if cached != destination:
                shutil.copyfile(cached, destination)
            # A caller must know whether a global material tint could change
            # protected skin pixels. Counts must not depend on cache state.
            try:
                saved=json.loads(count_cache.read_text(encoding='utf-8'))
                values=saved['protectedPixels']
                if saved.get('cacheKey')!=cache_key or any(not isinstance(values[k],int) or values[k]<0 for k in protected_counts):
                    raise ValueError('Invalid protection counts')
                protected_counts={k:values[k] for k in protected_counts}
            except (OSError,ValueError,KeyError,TypeError):
                rgba=original.convert('RGBA')
                for y in range(0,size[1],tile_size):
                    for x in range(0,size[0],tile_size):
                        box=(x,y,min(x+tile_size,size[0]),min(y+tile_size,size[1]))
                        _,counts=_rgba_with_counts(np.asarray(rgba.crop(box)),settings,None if context is None else np.asarray(context.crop(box))>0)
                        for name,count in counts.items():protected_counts[name]+=count
        else:
            rgba = original.convert("RGBA")
            result = Image.new("RGBA", size)
            for y in range(0, size[1], tile_size):
                for x in range(0, size[0], tile_size):
                    box = (x, y, min(x+tile_size, size[0]), min(y+tile_size, size[1]))
                    changed, counts = _rgba_with_counts(np.asarray(rgba.crop(box)), settings,None if context is None else np.asarray(context.crop(box))>0)
                    result.paste(Image.fromarray(changed), box[:2])
                    for name, count in counts.items():
                        protected_counts[name] += count
            target = cached or destination
            target.parent.mkdir(parents=True, exist_ok=True)
            fd, temp_name = tempfile.mkstemp(prefix="bake-", suffix=".png", dir=target.parent)
            os.close(fd)
            try:
                result.save(temp_name, format="PNG", compress_level=6)
                os.replace(temp_name, target)
            finally:
                if os.path.exists(temp_name):
                    os.unlink(temp_name)
            if target != destination:
                shutil.copyfile(target, destination)
        if count_cache:
            fd,count_name=tempfile.mkstemp(prefix='counts-',suffix='.json',dir=count_cache.parent)
            os.close(fd)
            try:
                Path(count_name).write_text(json.dumps({'cacheKey':cache_key,'protectedPixels':protected_counts},sort_keys=True)+'\n',encoding='utf-8')
                os.replace(count_name,count_cache)
            finally:
                if os.path.exists(count_name):os.unlink(count_name)
    return {"sourcePng": str(source), "outputPng": str(destination),
            "sourceSha256": source_hash, "outputSha256": sha256_file(destination),
            "width": size[0], "height": size[1], "alphaPreserved": True,
            **settings, "protectedPixels": protected_counts,
            "limitations": [SKIN_HEURISTIC_WARNING] if protect_skin else [],
            "cacheKey": cache_key, "cacheHit": hit, "tileSize": tile_size}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source")
    parser.add_argument("destination")
    parser.add_argument("--disable-lightness-inversion", dest="invert_lightness", action="store_false", default=True)
    parser.add_argument("--invert-lightness", dest="invert_lightness", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--allow-skin-colour-changes", dest="protect_skin", action="store_false", default=True)
    parser.add_argument("--skin-strength", type=int, choices=range(101), default=50, metavar="0..100")
    parser.add_argument("--retain-red", action="store_true")
    parser.add_argument("--retain-gold", action="store_true")
    parser.add_argument("--red-strength", type=int, choices=range(101), default=50, metavar="0..100")
    parser.add_argument("--gold-strength", type=int, choices=range(101), default=50, metavar="0..100")
    parser.add_argument("--red-blue-swap", action="store_true", help="Reflect hues so red and blue exchange; reverse mode only")
    parser.add_argument("--mode", choices=("reverse", "white"), default="reverse")
    parser.add_argument("--cache-dir")
    parser.add_argument("--tile-size", type=int, default=512)
    args = parser.parse_args()
    print(json.dumps(bake_png(args.source, args.destination, args.invert_lightness,
                              args.cache_dir, args.tile_size, protect_skin=args.protect_skin,
                              retain_red=args.retain_red, retain_gold=args.retain_gold, mode=args.mode, skin_strength=args.skin_strength,
                              red_strength=args.red_strength, gold_strength=args.gold_strength, red_blue_swap=args.red_blue_swap), indent=2))


if __name__ == "__main__":
    main()
