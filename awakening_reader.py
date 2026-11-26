"""Recognize the portrait's awakening diamond using original client sprites.

No OCR text, card identity, or stat contributions are used to guess a level.
"""
from pathlib import Path
import sys
import numpy as np
from PIL import Image

ROOT=Path(getattr(sys,'_MEIPASS',Path(__file__).parent))
ASSETS=ROOT/'resources/awakening'
PHOTO_ROI=(.285,.128,.445,.220)

def read_awakening(image,assets=ASSETS):
    bounds=tuple(round(v*(image.width if i%2==0 else image.height)) for i,v in enumerate(PHOTO_ROI))
    crop=image.convert('RGB').crop(bounds)
    # Work at a common scale so resizing the emulator doesn't change the search.
    scale=278/image.width
    crop=crop.resize((max(1,round(crop.width*scale)),max(1,round(crop.height*scale))),Image.Resampling.LANCZOS)
    pixels=np.asarray(crop,dtype=np.float32)/255
    matches=[]
    for level in range(1,10):
        path=Path(assets)/f'{level}.png'
        if not path.exists():
            return {'status':'unavailable','level':None,'display':'','source':'client-awakening-sprites','reason':'각성 배지 이미지 누락'}
        with Image.open(path) as source:sprite=source.convert('RGBA')
        best=None
        for width in range(20,31):
            height=round(width*sprite.height/sprite.width)
            if width>crop.width or height>crop.height:continue
            sample=np.asarray(sprite.resize((width,height),Image.Resampling.LANCZOS),dtype=np.float32)/255
            mask=(sample[:,:,3]>.90).astype(np.float32)
            if mask.sum()<50:continue
            patches=np.lib.stride_tricks.sliding_window_view(pixels,(height,width),axis=(0,1))
            template=np.moveaxis(sample[:,:,:3],2,0)
            error=((patches-template)**2*mask).sum(axis=(-3,-2,-1))/(mask.sum()*3)
            y,x=np.unravel_index(np.argmin(error),error.shape)
            score=float(error[y,x])
            if best is None or score<best['score']:
                best={'level':level,'score':score,'local_bounds':[int(x),int(y),int(x+width),int(y+height)]}
        if best:matches.append(best)
    matches.sort(key=lambda m:m['score'])
    if len(matches)<2:return {'status':'unavailable','level':None,'display':'','source':'client-awakening-sprites'}
    best,second=matches[:2];margin=second['score']-best['score']
    detected=best['score']<=.035 and margin>=.008
    local=best['local_bounds']
    box=[round(bounds[0]+local[0]/scale),round(bounds[1]+local[1]/scale),round(bounds[0]+local[2]/scale),round(bounds[1]+local[3]/scale)]
    return {'status':'detected' if detected else 'not_detected','level':best['level'] if detected else None,
            'display':f'{best["level"]}각성' if detected else '', 'source':'client-awakening-sprites',
            'score':best['score'],'margin':margin,'bounds':box,'candidates':matches}
