"""Conservative game-font reader. No card database is consulted by this module."""
import json
from pathlib import Path
import numpy as np
from PIL import Image,ImageOps

STATS=['파워','정확','선구','인내','주루','수비']
ROWS=['기본','훈련','강화','특훈','각성','세트덱','시너지','포지션 특훈','라커룸','종합']

def runs(flags):
    result=[];start=None
    for i,on in enumerate(list(flags)+[False]):
        if on and start is None:start=i
        if not on and start is not None:result.append((start,i));start=None
    return result

def normalized(mask):
    yy,xx=np.where(mask)
    if len(xx)<3:return None
    image=Image.fromarray(mask[yy.min():yy.max()+1,xx.min():xx.max()+1].astype('uint8')*255)
    ratio=min(18/image.width,30/image.height)
    image=image.resize((max(1,round(image.width*ratio)),max(1,round(image.height*ratio))),Image.Resampling.NEAREST)
    canvas=Image.new('L',(22,34),0);canvas.paste(image,((22-image.width)//2,(34-image.height)//2))
    return np.asarray(canvas,dtype=np.float32)/255

def locate(image,bounds,threshold=150):
    rgb=np.asarray(image.convert('RGB')).astype('int16')
    gray=np.asarray(image.convert('L')).copy()
    red=(rgb[:,:,0]>130)&(rgb[:,:,0]>rgb[:,:,1]*1.5)&(rgb[:,:,0]>rgb[:,:,2]*1.5)
    gray[red]=rgb[:,:,0][red]
    x0,y0,x1,y1=map(int,bounds)
    if not (0<=x0<x1<=image.width and 0<=y0<y1<=image.height):raise ValueError('숫자 표 범위가 이미지 밖입니다.')
    area=gray[y0:y1,x0:x1]
    # Row centres come from visible glyphs, not a fixed vertical offset.
    bands=runs((area>threshold).sum(axis=1)>=4)
    bands=[(a,b) for a,b in bands if b-a>=4]
    if len(bands)<2:raise ValueError('능력치 숫자 행을 찾지 못했습니다. 숫자 영역을 보정하세요.')
    centres=[x0+(x-130)/362*(x1-x0) for x in [155,219,282,346,410,474]]
    cells=[]
    for r,(a,b) in enumerate(bands):
        a=max(0,a-2);b=min(area.shape[0],b+2)
        for c,cx in enumerate(centres):
            half=(x1-x0)/6*.38
            left=max(x0,round(cx-half));right=min(x1,round(cx+half))
            mask=gray[y0+a:y0+b,left:right]>threshold
            components=runs(mask.sum(axis=0)>0)
            negative=False
            if components:
                u,v=components[0];yy,xx=np.where(mask[:,u:v])
                if len(xx) and v-u>=3 and (v-u)/(yy.max()-yy.min()+1)>=1.5:
                    negative=True;components=components[1:]
            glyphs=[normalized(mask[:,u:v]) for u,v in components]
            cells.append({'row':r,'col':c,'bounds':[left,y0+a,right,y0+b], 'glyphs':glyphs,'negative':negative})
    return cells

def train(sources,target,require_all=True):
    """Labels must be independently read from screenshots, not predicted from cards.json."""
    images=[];labels=[];provenance=[]
    for source in sources:
        image=Image.open(source['path'])
        for threshold in (170,200):
            for cell in locate(image,source['bounds'],threshold):
                r,c=cell['row'],cell['col'];text=str(abs(source['values'][r][c]))
                if (source['values'][r][c]<0)!=cell['negative']:raise ValueError('부호 분리 실패')
                if len(text)!=len(cell['glyphs']):raise ValueError(f'글자 분리 실패: {source["path"]} {r}/{c} {text}')
                for digit,glyph in zip(text,cell['glyphs']):
                    if glyph is None:raise ValueError('빈 글자')
                    labels.append(int(digit));images.append(glyph)
        provenance.append({'path':str(source['path']),'bounds':source['bounds'],'label_source':'visual transcription of screenshot; no card database'})
    if require_all and set(labels)!=set(range(10)):raise ValueError('0~9의 모든 글자 예제가 필요합니다.')
    np.savez_compressed(target,images=np.stack(images),labels=np.array(labels,dtype=np.int8))
    Path(target).with_suffix('.json').write_text(json.dumps({'sources':provenance,'templates':len(labels)},ensure_ascii=False,indent=2),encoding='utf-8')

def row_labels(cells,hints=None):
    count=len(cells)//6
    if not hints and count==len(ROWS):return list(ROWS)
    labels=[None]*count
    centres=[(cells[i*6]['bounds'][1]+cells[i*6]['bounds'][3])/2 for i in range(count)]
    tolerance=min(b-a for a,b in zip(centres,centres[1:]))*.45
    for hint in hints or []:
        index=min(range(count),key=lambda i:abs(centres[i]-hint['y']))
        if abs(centres[index]-hint['y'])<=tolerance and labels[index] is None and hint['label'] not in labels:
            labels[index]=hint['label']
    # Fill a missing standard label only when its neighbouring anchors and
    # the number of intervening rows agree. Additional rows never shift stats.
    for left in range(count):
        if labels[left] not in ROWS:continue
        right=next((i for i in range(left+1,count) if labels[i] is not None),None)
        if right is None or labels[right] not in ROWS:continue
        expected=ROWS[ROWS.index(labels[left])+1:ROWS.index(labels[right])]
        if len(expected)==right-left-1:
            labels[left+1:right]=expected
    return [label or f'미확인 행 {i+1}' for i,label in enumerate(labels)]

def read(image_path,output,bounds,bank_path,row_hints=None):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    image=Image.open(image_path)
    bank=np.load(bank_path,allow_pickle=False);templates=bank['images'];labels=bank['labels']
    # Two thresholds must agree; do not fabricate a value when glyph classification is uncertain.
    passes=[locate(image,bounds,t) for t in (170,200)]
    if len(passes[0])!=len(passes[1]):raise ValueError('두 인식 단계의 행 수가 다릅니다.')
    labels_for_rows=row_labels(passes[0],row_hints)
    table={row:{stat:None for stat in STATS} for row in labels_for_rows};evidence=[]
    for index in range(len(passes[0])):
        votes=[];details=[]
        for cells in passes:
            cell=cells[index];text='';confident=True;digit_scores=[]
            if not 1<=len(cell['glyphs'])<=3:confident=False
            for glyph in cell['glyphs']:
                if glyph is None:confident=False;break
                distances=np.mean(np.abs(templates-glyph),axis=(1,2))
                scores=sorted((float(distances[labels==d].min()),d) for d in range(10))
                best,digit=scores[0];margin=scores[1][0]-best
                if best>.095 or margin<.018:confident=False
                text+=str(digit);digit_scores.append({'digit':digit,'distance':best,'margin':margin})
            votes.append(int(text)*(-1 if cell['negative'] else 1) if confident and text else None)
            details.append({'bounds':cell['bounds'],'negative':cell['negative'],'glyph_count':len(cell['glyphs']),'digits':digit_scores})
        r,c=divmod(index,6)
        if votes[0] is not None and votes[0]==votes[1]:table[labels_for_rows[r]][STATS[c]]=votes[0]
        agreement=False
        # A slightly eroded threshold can reduce the runner-up margin without
        # changing its best digit. Require both shapes to name the same digit,
        # a strong pass for each digit, and a strong average separation.
        a,b=details
        if (table[labels_for_rows[r]][STATS[c]] is None and a['negative']==b['negative']
                and 1<=a['glyph_count']==b['glyph_count']<=3
                and len(a['digits'])==len(b['digits'])==a['glyph_count']):
            agreement=all(x['digit']==y['digit'] and max(x['distance'],y['distance'])<=.095
                          and max(x['margin'],y['margin'])>=.018
                          and (x['margin']+y['margin'])/2>=.014
                          for x,y in zip(a['digits'],b['digits']))
            if agreement:table[labels_for_rows[r]][STATS[c]]=int(''.join(str(d['digit']) for d in a['digits']))*(-1 if a['negative'] else 1)
        evidence.append({'row':labels_for_rows[r],'stat':STATS[c],'votes':votes,'threshold_agreement':agreement,'passes':details})
    problems=[]
    for row in labels_for_rows:
        for stat in STATS:
            if table[row][stat] is None:problems.append(f'{row}/{stat}: 글꼴 인식 확인 필요')
    for stat in STATS:
        values=[table[row][stat] for row in labels_for_rows]
        if '종합' in table and all(v is not None for v in values) and sum(v[stat] for row,v in table.items() if row!='종합')!=table['종합'][stat]:problems.append(f'{stat}: 보정 합계와 종합 값 불일치')
    for row in ['기본','종합']:
        if row not in table:
            table[row]=dict.fromkeys(STATS);problems.append(f'{row}: 행 이름 확인 필요')
    result={'source_image':str(Path(image_path).resolve()),'kind':'batter','bounds':bounds,'engine':'game-font-v1','row_hints':row_hints or [],'table':table,'needs_review':problems,'complete':not problems}
    (output/'stats.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    (output/'glyph-evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    return result
