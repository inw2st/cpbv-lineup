"""Read visible overview digits; independent of card DB and stat totals."""
from pathlib import Path
import numpy as np
from PIL import Image
from digit_reader import normalized,runs

def components(mask):
    seen=np.zeros(mask.shape,dtype=bool);out=[]
    for y,x in zip(*np.where(mask)):
        if seen[y,x]:continue
        stack=[(y,x)];seen[y,x]=True;points=[]
        while stack:
            cy,cx=stack.pop();points.append((cy,cx))
            for dy,dx in [(0,-1),(0,1),(-1,0),(1,0)]:
                ny,nx=cy+dy,cx+dx
                if 0<=ny<mask.shape[0] and 0<=nx<mask.shape[1] and mask[ny,nx] and not seen[ny,nx]:
                    seen[ny,nx]=True;stack.append((ny,nx))
        yy,xx=zip(*points)
        out.append((min(xx),min(yy),max(xx)+1,max(yy)+1,len(points)))
    return out

def masks(crop,field,threshold=165):
    rgb=np.asarray(crop.convert('RGB')).astype('int16')
    ink=(rgb.min(axis=2)>threshold)&(rgb.max(axis=2)-rgb.min(axis=2)<75)
    return ink

def glyphs(crop,field,threshold=165):
    ink=masks(crop,field,threshold)
    parts=components(ink)
    if field=='enhancement_level':
        # Exclude the reflective shield rim above/below the printed badge number.
        ink[:round(crop.height*.19)]=False
        ink[round(crop.height*.86):]=False
        parts=components(ink)
    parts=[p for p in parts if p[4]>=3 and p[3]-p[1]>=3]
    if not parts:return []
    tallest=max(p[3]-p[1] for p in parts)
    parts=[p for p in parts if p[3]-p[1]>=tallest*.70]
    if not parts:return []
    keep=np.zeros(ink.shape,dtype=bool)
    for x0,y0,x1,y1,_ in parts:keep[y0:y1,x0:x1]|=ink[y0:y1,x0:x1]
    # Projection rejoins disconnected anti-aliased pieces of the same digit.
    spans=runs(keep.sum(axis=0)>0)
    if field=='enhancement_level' and len(spans)>2:
        spans=spans[-2:] # the '+' is not part of the level number
    return [normalized(keep[:,left:right]) for left,right in spans]

def read(crop,field,bank_path):
    if not Path(bank_path).exists():return None,{'source':'overview-font','reason':'font bank unavailable'}
    bank=np.load(bank_path,allow_pickle=False)
    templates=bank['images'];labels=bank['labels'];fields=bank['fields']
    votes=[];evidence=[]
    for threshold in ((190,210) if field=='enhancement_level' else (155,180)):
        found=glyphs(crop,field,threshold);text='';scores=[];confident=1<=len(found)<=3
        for glyph in found:
            if glyph is None:confident=False;break
            distances=np.mean(np.abs(templates-glyph),axis=(1,2))
            # Prefer templates captured from the same UI field, retaining other
            # visible examples for digits not yet observed in that field.
            ranked=[]
            for digit in range(10):
                same=(labels==digit)&(fields==field)
                pool=same if same.any() else labels==digit
                ranked.append((float(distances[pool].min()),digit))
            ranked.sort();distance,digit=ranked[0];margin=ranked[1][0]-distance
            if distance>.13 or margin<.014:confident=False
            text+=str(digit);scores.append({'digit':digit,'distance':distance,'margin':margin})
        vote=int(text) if confident and text else None
        votes.append(vote);evidence.append({'threshold':threshold,'scores':scores,'value':vote})
    value=votes[0] if votes[0] is not None and votes[0]==votes[1] else None
    limits=(0,30) if field=='enhancement_level' else (0,60)
    if value is not None and not limits[0]<=value<=limits[1]:value=None
    return value,{'source':'overview-font','passes':evidence}
