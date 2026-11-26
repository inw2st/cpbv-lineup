"""Map the same nine visible cards from field positions to batting-order cells."""
import json
import re
from pathlib import Path
import numpy as np
from PIL import Image,ImageFilter
from core import ORDER

REFERENCE=(556,989)
FIELD_BOXES={
    'CF':(242,161,322,279),'LF':(91,205,174,322),'RF':(385,205,468,322),
    'SS':(177,295,259,412),'2B':(299,295,382,412),
    '3B':(54,345,137,462),'1B':(421,345,504,462),
    'C':(240,430,322,547),'DH':(332,430,414,547),
}
ORDER_BOXES=[(x,y,x+80,y+116) for y,n in [(118,5),(280,4)] for x in [51+95*i for i in range(n)]]

def is_order_screen(text):
    text=re.sub(r'\s+','',text or '')
    return ('상위타선' in text or '하위타선' in text) and ('선수비교' in text or '원래대로' in text)

def crop_card(image,box):
    w,h=REFERENCE
    bounds=tuple(round(v*(image.width/w if i%2==0 else image.height/h)) for i,v in enumerate(box))
    crop=image.convert('RGB').crop(bounds)
    # Discard the outer animated card border; retain portrait, badge and name.
    return crop.crop((3,5,crop.width-3,crop.height-3)).resize((52,76),Image.Resampling.BILINEAR)

def order_header_evidence(ocr,size):
    """Check visible 1번..9번 headers against cells; never use candidate cards."""
    width,height=size;found=[]
    for line in ocr.get('lines',[]):
        for word in line.get('words',[]):
            match=re.fullmatch(r'([1-9])번',word.get('text','').strip())
            if not match:continue
            x=(word['x']+word['width']/2)/2*REFERENCE[0]/width
            y=(word['y']+word['height']/2)/2*REFERENCE[1]/height
            candidates=[i for i,box in enumerate(ORDER_BOXES) if abs(x-(box[0]+box[2])/2)<35 and abs(y-(box[1]-14))<15]
            if len(candidates)==1:found.append({'cell':candidates[0]+1,'label':int(match[1])})
    return {'verified':len(found)>=4 and all(e['cell']==e['label'] for e in found),'headers':found}

def read_batting_order(lineup,order_screen,output=None):
    field=[crop_card(lineup,FIELD_BOXES[slot]) for slot in ORDER]
    cards=[crop_card(order_screen,box) for box in ORDER_BOXES]
    raw_a=np.stack([np.asarray(image,dtype=np.float32)/255 for image in field])
    raw_b=np.stack([np.asarray(image,dtype=np.float32)/255 for image in cards])
    raw_scores=np.mean(np.abs(raw_b[:,None]-raw_a[None,:]),axis=(2,3,4))
    # Fine pixels differ with card shimmer and thumbnail resizing. Two smoothing
    # scales must independently agree on the artwork. Raw errors are retained
    # as diagnostic evidence, since individual sparkle pixels are unstable.
    a=np.stack([np.asarray(image.filter(ImageFilter.GaussianBlur(2)).resize((20,28)),dtype=np.float32)/255 for image in field])
    b=np.stack([np.asarray(image.filter(ImageFilter.GaussianBlur(2)).resize((20,28)),dtype=np.float32)/255 for image in cards])
    scores=np.mean(np.abs(b[:,None]-a[None,:]),axis=(2,3,4))
    stable_a=np.stack([np.asarray(image.filter(ImageFilter.GaussianBlur(3)).resize((20,28)),dtype=np.float32)/255 for image in field])
    stable_b=np.stack([np.asarray(image.filter(ImageFilter.GaussianBlur(3)).resize((20,28)),dtype=np.float32)/255 for image in cards])
    stable_scores=np.mean(np.abs(stable_b[:,None]-stable_a[None,:]),axis=(2,3,4))
    picked=scores.argmin(axis=1).tolist();ranked=np.sort(scores,axis=1)
    entries=[{'order':i+1,'slot':ORDER[index],'score':float(scores[i,index]),'margin':float(ranked[i,1]-ranked[i,0])} for i,index in enumerate(picked)]
    complete=(len(set(picked))==9 and picked==stable_scores.argmin(axis=1).tolist()
              and all(e['score']<.12 and e['margin']>.012 for e in entries))
    result={'status':'verified' if complete else 'needs_review',
            'orders':{e['slot']:e['order'] for e in entries} if complete else {},
            'entries':entries,'slots':list(ORDER),'score_matrix':scores.tolist(),'stable_score_matrix':stable_scores.tolist(),'raw_score_matrix':raw_scores.tolist(),
            'source':'same-card image comparison between lineup and batting-order screen'}
    if output:
        output=Path(output);output.mkdir(parents=True,exist_ok=True)
        for slot,image in zip(ORDER,field):image.save(output/f'field-{slot}.png')
        for i,image in enumerate(cards,1):image.save(output/f'order-{i}.png')
        (output/'batting-order.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result
