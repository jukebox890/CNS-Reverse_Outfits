"""Maximum-safety material evidence; uses colours, never substitutes skin UV maps."""
import numpy as np
from PIL import Image, ImageFilter
from colour_bake import _colour_data, _protection_masks


def _candidates(data):
    rgb=data[...,:3].astype(np.float64)/255
    hue,_,_,sat=_colour_data(rgb)
    mask=_protection_masks(rgb,hue,sat,protect_skin=True,retain_red=False,
        retain_gold=False,skin_strength=50)['skin']
    return mask & (sat<.55) & (data[...,3]>0)


def reference_palette(paths):
    """Small 3D colour lookup from verified skin assets; no spatial/UV reuse."""
    palette=np.zeros((32,32,32),dtype=bool);found=False
    for path in paths:
        with Image.open(path) as original:
            image=original.convert('RGBA');image.thumbnail((256,256),Image.Resampling.NEAREST)
            data=np.asarray(image);mask=_candidates(data)
            if np.count_nonzero(mask)<max(32,mask.size*.02):continue
            found=True
            for r,g,b in np.unique(data[...,:3][mask]//8,axis=0):
                palette[max(0,int(r)-1):min(32,int(r)+2),max(0,int(g)-1):min(32,int(g)+2),max(0,int(b)-1):min(32,int(b)+2)]=True
    return palette if found else None


def broad_skin_evidence(path,palette):
    with Image.open(path) as original:
        if min(original.size)<16:return None
        image=original.convert('RGBA');image.thumbnail((256,256),Image.Resampling.NEAREST)
        data=np.asarray(image);mask=_candidates(data)
        if palette is not None:
            q=data[...,:3]//8;mask &=palette[q[...,0],q[...,1],q[...,2]]
        # Erosion rejects narrow warm ornament and seams. This is conservative
        # material protection at 100, not a claim of semantic segmentation.
        broad=np.asarray(Image.fromarray(mask.astype('uint8')*255).filter(ImageFilter.MinFilter(5)))>0
        visible=max(1,np.count_nonzero(data[...,3]>0))
        coverage=float(np.count_nonzero(broad)/visible)
        threshold=.02 if palette is not None else .08
        if coverage<threshold:return None
        return dict(broadSkinCoverage=round(coverage,5),referenceMatched=palette is not None,
                    policy='preserve-original-material-at-100')
