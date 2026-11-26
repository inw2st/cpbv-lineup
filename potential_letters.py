"""Small alphabet reader for the game's coloured potential grade tiles."""
from pathlib import Path
import numpy as np
from PIL import Image
from digit_reader import normalized,runs

def split(crop,threshold):
    peak=np.asarray(crop.convert('RGB')).max(axis=2)
    mask=peak>threshold
    return [normalized(mask[:,a:b]) for a,b in runs(mask.sum(axis=0)>0) if b-a>=2]

def read_grade(crop,bank_path):
    if not Path(bank_path).exists():return None,{'reason':'grade font bank missing'}
    bank=np.load(bank_path,allow_pickle=False);templates=bank['images'];labels=bank['labels']
    votes=[];passes=[]
    for threshold in (140,165):
        glyph=normalize_grade(np.asarray(crop.convert('RGB')).max(axis=2)>threshold)
        if glyph is None:votes.append(None);passes.append({'threshold':threshold,'candidate':''});continue
        distance=np.mean(np.abs(templates-glyph),axis=(1,2))
        ranked=sorted((float(distance[labels==label].min()),str(label)) for label in sorted(set(labels)))
        best,text=ranked[0];margin=ranked[1][0]-best
        votes.append(text if best<.12 and margin>.012 else None)
        passes.append({'threshold':threshold,'candidate':text,'distance':best,'margin':margin})
    return (votes[0] if votes[0] is not None and votes[0]==votes[1] else None),{'votes':votes,'passes':passes}


def grade_colour(crop):
    rgb=np.asarray(crop.convert('RGB')).astype('int16');r,g,b=np.moveaxis(rgb,-1,0)
    vivid=(rgb.max(axis=2)>110)&(rgb.max(axis=2)-rgb.min(axis=2)>70)
    masks={
        'C':vivid&(g>r*1.25)&(b>r*1.25)&(b>=g*.85),
        'B':vivid&(g>r*1.25)&(g>b*1.25),
        'A':vivid&(r>g*1.5)&(r>=b*.9),
        'D':vivid&(b>r*1.05)&(r>g*1.3),
        'S':vivid&(r>100)&(g>70)&(b<np.minimum(r,g)*.5)&(g>=r*.70),
        'SR':vivid&(r>100)&(g>70)&(b<np.minimum(r,g)*.5)&(g<r*.70),
    }
    counts=sorted(((int(mask.sum()),name) for name,mask in masks.items()),reverse=True)
    count,name=counts[0]
    if count>=5 and count>=int(vivid.sum())*.65:return name
    return None


def read_table_grade(crop,bank_path):
    """Read a coloured table grade, keeping absence distinct from uncertainty."""
    rgb=np.asarray(crop.convert('RGB'));peak=rgb.max(axis=2);mask=peak>110
    yy,xx=np.where(mask)
    if not len(xx):return None,{'state':'unreadable','reason':'empty grade cell'}
    width=int(xx.max()-xx.min()+1);height=int(yy.max()-yy.min()+1)
    if height<=3 and width>=5 and width>=height*3:
        return '-',{'state':'not_present','reason':'visible horizontal dash'}
    family=grade_colour(crop)
    if family is None:
        raw,evidence=read_grade(crop,bank_path)
        return raw,{'state':'recognized' if raw is not None else 'unreadable','colour':None,**evidence}
    allowed={'C':('C','C+'),'B':('B','B+'),'A':('A','A+'),
             'D':('D','D+'),'S':('S','S+','SS','SS+'),'SR':('SR','SR+')}[family]
    with np.load(bank_path,allow_pickle=False) as bank:
        labels=bank['labels'];templates=bank['images']
        use=np.isin(labels,allowed);labels=labels[use];templates=templates[use]
    passes=[]
    for threshold in (120,145,170):
        glyph=normalize_grade(peak>threshold)
        if glyph is None:continue
        distance=np.mean(abs(templates-glyph),axis=(1,2))
        ranked=sorted((float(distance[labels==label].min()),str(label)) for label in set(labels))
        best,text=ranked[0];margin=ranked[1][0]-best if len(ranked)>1 else 1-best
        passes.append({'threshold':threshold,'candidate':text,'distance':best,'margin':margin})
    for candidate in allowed:
        agreeing=[p for p in passes if p['candidate']==candidate and p['distance']<=.13]
        if len(agreeing)>=2 and sum(p['margin'] for p in agreeing)/len(agreeing)>=.012:
            return candidate,{'state':'recognized','colour':family,'passes':passes}
    return None,{'state':'unreadable','colour':family,'passes':passes}

def normalize_grade(mask):
    yy,xx=np.where(mask)
    if len(xx)<5:return None
    image=Image.fromarray(mask[yy.min():yy.max()+1,xx.min():xx.max()+1].astype('uint8')*255)
    ratio=min(44/image.width,28/image.height)
    image=image.resize((max(1,round(image.width*ratio)),max(1,round(image.height*ratio))),Image.Resampling.NEAREST)
    canvas=Image.new('L',(48,32));canvas.paste(image,((48-image.width)//2,(32-image.height)//2))
    return np.asarray(canvas,dtype=np.float32)/255
