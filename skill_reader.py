"""Current client icons and badge glyphs for a manually captured skills table."""
from functools import lru_cache
from difflib import SequenceMatcher
from pathlib import Path
import copy,json
import re
import numpy as np
from PIL import Image
from digit_reader import normalized
from potential_table import row_masks,header_geometry
from core import ORDER
from ocr_coordinates import screenshot_coordinates

ROOT=Path(__file__).resolve().parent
DATA=ROOT/'resources/skills'
LEVEL_THRESHOLDS=(90,120,150)


def badge_components(mask):
    remaining=set(zip(*np.where(mask)));result=[]
    while remaining:
        first=remaining.pop();stack=[first];points=[first]
        while stack:
            y,x=stack.pop()
            for dy in (-1,0,1):
                for dx in (-1,0,1):
                    point=(y+dy,x+dx)
                    if point in remaining:remaining.remove(point);stack.append(point);points.append(point)
        yy,xx=zip(*points);result.append((min(xx),min(yy),max(xx)+1,max(yy)+1,len(points)))
    return result


def enclosed_spaces(glyph):
    ink=glyph>.5;yy,xx=np.where(ink)
    if not len(yy):return []
    low,high=int(yy.min()),int(yy.max());seen=set();holes=[];height,width=ink.shape
    for y,x in zip(*np.where(~ink)):
        if (y,x) in seen:continue
        stack=[(y,x)];seen.add((y,x));points=[];edge=False
        while stack:
            y,x=stack.pop();points.append((y,x));edge|=y in (0,height-1) or x in (0,width-1)
            for dy,dx in ((0,-1),(0,1),(-1,0),(1,0)):
                point=(y+dy,x+dx);py,px=point
                if 0<=py<height and 0<=px<width and not ink[py,px] and point not in seen:
                    seen.add(point);stack.append(point)
        if not edge and len(points)>=3:
            holes.append(float((sum(p[0] for p in points)/len(points)-low)/(high-low+1)))
    return holes


class SkillCatalog:
    def __init__(self,directory=DATA):
        self.directory=Path(directory)
        self.skills=json.loads((self.directory/'skills.json').read_text(encoding='utf8'))
        self.batters=[s for s in self.skills if s['role']=='batter']
        self.batter_names=sorted({s['name'] for s in self.batters})
        self.by_id={s['id']:s for s in self.batters}


@lru_cache(maxsize=2)
def icon_bank(directory=str(DATA)):
    catalog=SkillCatalog(directory);bank=[];labels=[]
    mask=np.zeros((40,36),bool);mask[6:30,6:30]=True
    for skill in catalog.batters:
        with Image.open(catalog.directory/skill['icon']) as image:icon=image.convert('RGBA')
        # Sprite images have trimmed bounds. Keep their native aspect and pixel
        # scale, rather than stretching a short eye/bat symbol into a tall player.
        for scale in (.22,.24,.26,.28,.30):
            sprite=icon.resize((round(icon.width*scale),round(icon.height*scale)),Image.Resampling.LANCZOS)
            for dx in (-2,0,2):
                for dy in (-2,0,2):
                    canvas=Image.new('RGBA',(36,40),(29,36,40,255))
                    canvas.alpha_composite(sprite,((36-sprite.width)//2+dx,(40-sprite.height)//2+dy))
                    values=np.asarray(canvas.convert('L'),dtype=np.float32)[mask]
                    bank.append((values-values.mean())/(values.std()+1));labels.append(skill['id'])
    return catalog,np.array(bank),np.array(labels),mask


def read_icon(crop,directory=DATA):
    catalog,bank,labels,mask=icon_bank(str(directory))
    values=np.asarray(crop.convert('L').resize((36,40),Image.Resampling.LANCZOS),dtype=np.float32)[mask]
    if values.std()<10:return None,{'reason':'blank/low contrast icon'}
    values=(values-values.mean())/(values.std()+1)
    errors=np.mean((bank-values)**2,axis=1)
    ranked=sorted((float(errors[labels==key].min()),int(key)) for key in set(labels))
    best,key=ranked[0];margin=ranked[1][0]-best
    evidence={'distance':best,'margin':margin,'candidates':[
        {'id':k,'name':catalog.by_id[k]['name'],'distance':error} for error,k in ranked[:3]]}
    skill=catalog.by_id[key] if best<=.85 and margin>=.15 else None
    return skill,evidence


def level_crop(image,cx,cy,unit):
    bounds=[round(cx+8*unit),round(cy),round(cx+23*unit),round(cy+20*unit)]
    return image.crop(tuple(bounds)),bounds


def level_glyphs(crop):
    # Find the printed digit inside the shield, instead of cutting a fixed
    # 4-pixel glyph rectangle whose alignment changes between scaled rows.
    rgb=np.asarray(crop.convert('RGB').resize((15,20),Image.Resampling.LANCZOS)).astype('int16')
    green=(rgb[:,:,1]-rgb[:,:,0]>30)&(rgb[:,:,1]-rgb[:,:,2]>15)
    style='green' if green[3:16,3:12].sum()>=5 else 'white'
    passes=[]
    for threshold in LEVEL_THRESHOLDS:
        ink=(rgb.max(axis=2)>threshold)
        ink &= green if style=='green' else (rgb.max(axis=2)-rgb.min(axis=2)<70)
        parts=[p for p in badge_components(ink) if 2<=p[2]-p[0]<=9 and 5<=p[3]-p[1]<=12
               and p[4]>=7 and 3<=(p[0]+p[2])/2<=12 and 4<=(p[1]+p[3])/2<=15]
        if not parts:passes.append(None);continue
        part=min(parts,key=lambda p:((p[0]+p[2])/2-7.5)**2+((p[1]+p[3])/2-10)**2)
        x0,y0,x1,y1,_=part
        # A printed 10 has two connected components. Keep both rather than
        # silently classifying its right-hand 0 or left-hand 1 as the level.
        for other in parts:
            if other==part:continue
            a,b,c,d,_=other
            if (abs((b+d-y0-y1)/2)<=2 and min(d-b,y1-y0)>=max(d-b,y1-y0)*.75
                    and max(c,x1)-min(a,x0)<=10 and 3<=min(a,x0) and max(c,x1)<=13):
                x0,y0,x1,y1=min(a,x0),min(b,y0),max(c,x1),max(d,y1)
        # Include detached anti-aliased pieces within the digit's bounding box.
        passes.append(normalized(ink[y0:y1,x0:x1]))
    return style,passes


@lru_cache(maxsize=2)
def level_bank(directory=str(DATA)):
    with np.load(Path(directory)/'level-font.npz',allow_pickle=False) as bank:
        return {key:bank[key].copy() for key in bank.files}


def read_level(crop,directory=DATA):
    bank=level_bank(str(directory));style,glyphs=level_glyphs(crop)
    holes=[enclosed_spaces(glyph) if glyph is not None else [] for glyph in glyphs]
    impossible=set()
    # Preserve the open lower-left stroke of a 5 and the lower counter of a 6.
    # Pure silhouette matching can mistake these for a closed 6/8/9 after AA.
    if all(not h for h in holes):impossible.update((6,8,9))
    elif len(holes[-1])==1 and holes[-1][0]>.58:impossible.update((8,9))
    elif len(holes[-1])>=2:impossible.update((6,9))
    passes=[];all_scores=[]
    for threshold,glyph in zip(LEVEL_THRESHOLDS,glyphs):
        if glyph is None:return None,{'reason':'empty badge glyph'}
        errors=np.mean(abs(bank['images']-glyph),axis=(1,2));ranked=[]
        for number in range(1,11):
            actual=(bank['labels']==number)&(bank['styles']==style)
            pool=actual|((bank['labels']==number)&(bank['styles']=='font'))
            ranked.append((float(errors[pool].min())+(1 if number in impossible else 0),number))
        ranked.sort();passes.append({'threshold':threshold,'candidate':ranked[0][1],
                                     'distance':ranked[0][0],'margin':ranked[1][0]-ranked[0][0]})
        all_scores.append({number:score for score,number in ranked})
    ranked=sorted((sum(scores[number] for scores in all_scores)/len(all_scores),number) for number in range(1,11))
    best,number=ranked[0];margin=ranked[1][0]-best
    votes=sum(p['candidate']==number for p in passes)
    decision=None;value=None
    for candidate in range(1,11):
        agreeing=[p for p in passes if p['candidate']==candidate and p['distance']<=.15]
        agreeing=sorted(agreeing,key=lambda p:p['margin'],reverse=True)[:2]
        if (len(agreeing)==2 and max(p['distance'] for p in agreeing)<=.15
                and sum(p['margin'] for p in agreeing)/2>=.014):
            value=candidate;decision='two-threshold-agreement';break
    if value is None and len({p['candidate'] for p in passes})==1:
        if (min(p['distance'] for p in passes)<=.15 and max(p['distance'] for p in passes)<=.20
                and sum(p['margin'] for p in passes)/3>=.06):
            value=passes[0]['candidate'];decision='three-consistent-strongly-separated-shapes'
    if value is None:
        # Low-resolution white 5s can break into a 6/9 at an eroded threshold.
        # Accept one strong shape only if the disagreeing shapes are ambiguous.
        strong=[p for p in passes if p['distance']<=.08 and p['margin']>=.028
                and all(q['candidate']==p['candidate'] or q['margin']<.014 for q in passes)]
        if strong and len({p['candidate'] for p in strong})==1:
            value=strong[0]['candidate'];decision='strong-shape-with-ambiguous-other-passes'
    return value,{'style':style,'distance':best,'margin':margin,'votes':votes,'decision':decision,
                  'enclosed_spaces':holes,'excluded_shapes':sorted(impossible),'passes':passes}


def skills_geometry(ocr,layout):
    g=layout['geometry'];pitch=float(np.median(np.diff([r['center_y'] for r in layout['rows']])))
    unit=pitch/59
    candidates=[]
    for line in ocr.get('lines',[]):
        for word in line.get('words',[]):
            text=re.sub(r'\s+','',word.get('text',''))
            x=(word['x']+word['width']/2)/2;y=(word['y']+word['height']/2)/2
            if text in ('스킬','스길','스컬','스칼') and abs(y-g['header_y'])<20*unit and x>g['player_x']+80*unit:
                candidates.append(x)
    if not candidates:return None
    center=float(np.median(candidates))
    xs=[center-55*unit,center,center+55*unit]
    if xs[0]-18*unit<g['player_x']+85*unit or xs[-1]+22*unit>layout['image_width']:return None
    return {'columns':xs,'unit':unit,'row_pitch':pitch}


def caption_confirmation(ocr,cx,cy,unit,evidence,directory):
    if evidence.get('distance',9)>1.05 or evidence.get('margin',0)<.08:return None
    words=[]
    for line in ocr.get('lines',[]):
        for word in line.get('words',[]):
            x=(word['x']+word['width']/2)/2;y=(word['y']+word['height']/2)/2
            if abs(x-cx)<27*unit and cy+19*unit<y<cy+37*unit:words.append((x,word['text']))
    text=re.sub(r'[^가-힣A-Za-z]','',''.join(w for _,w in sorted(words)))
    if len(text)<3:return None
    catalog=icon_bank(str(directory))[0]
    ranked=sorted(((SequenceMatcher(None,text,re.sub(r'\s+','',s['name'])).ratio(),s) for s in catalog.batters),key=lambda v:v[0],reverse=True)
    score,skill=ranked[0]
    if score>=.75 and score-ranked[1][0]>=.15 and skill['id']==evidence['candidates'][0]['id']:
        evidence['caption_confirmation']={'text':text,'similarity':score};return skill
    return None


def starter_layout(image,ocr,directory=DATA,records=None):
    geometry=header_geometry(ocr,image.size)
    if geometry is None:return {'status':'unreadable','row_slots':[]}
    rows=row_masks(image,geometry)
    if len(rows)!=9:return {'status':'unreadable','row_slots':[]}
    gaps=np.diff([r['center_y'] for r in rows]);pitch=np.median(gaps)
    if np.max(abs(gaps-pitch))>pitch*.18:return {'status':'unreadable','row_slots':[]}
    # Owned card names identify the exact destination even when the small blue
    # position glyph changes shape at a different window scale.
    named_slots=[];unit=float(pitch/59)
    for row in rows:
        words=[]
        for line in ocr.get('lines',[]):
            for word in line.get('words',[]):
                x=(word['x']+word['width']/2)/2;y=(word['y']+word['height']/2)/2
                if geometry['player_x']-40*unit<x<geometry['player_x']+100*unit and row['center_y']-32*unit<y<row['center_y']-8*unit:
                    words.append(word['text'])
        title=re.sub(r'[^가-힣A-Za-z]','',''.join(words))
        matches=[]
        for record in records or []:
            card=record.get('match',{}).get('card',{})
            aliases=[card.get('player'),card.get('name'),record.get('overview',{}).get('card_name')]
            aliases=[re.sub(r'[^가-힣A-Za-z]','',re.split("['’]",s)[0]) for s in aliases if s]
            if any(len(name)>=2 and name in title for name in aliases):matches.append(record['slot'])
        named_slots.append(matches[0] if len(matches)==1 else None)
    if set(named_slots)==set(ORDER):
        return {'status':'verified','row_slots':named_slots,'geometry':geometry,'rows':rows,
                'image_width':image.width,'identity_source':'owned-card-name'}
    with np.load(Path(directory)/'position-font.npz',allow_pickle=False) as bank:
        labels=bank['labels'];images=bank['images'];slots=[]
        for row in rows:
            errors=np.mean(abs(images-row['mask']),axis=(1,2))
            ranked=sorted((float(errors[labels==label].min()),str(label)) for label in set(labels))
            if ranked[0][0]>.12 or ranked[1][0]-ranked[0][0]<.012:return {'status':'unreadable','row_slots':[]}
            slots.append(ranked[0][1])
    if set(slots)!=set(ORDER):return {'status':'unreadable','row_slots':slots}
    return {'status':'verified','row_slots':slots,'geometry':geometry,'rows':rows,'image_width':image.width,
            'identity_source':'position-badge'}


def read_skills(image,ocr,directory=DATA,records=None):
    ocr=screenshot_coordinates(ocr,image.size)
    # Normalize the row pitch before matching tiny position badges/digits, so
    # a larger LDPlayer window does not depend on the screenshot's pixel size.
    analysis_scale=1.0
    header=header_geometry(ocr,image.size)
    bands=row_masks(image,header) if header else []
    if len(bands)==9:
        pitch=float(np.median(np.diff([r['center_y'] for r in bands])))
        if 30<=pitch<=180 and abs(pitch/59-1)>.025:
            analysis_scale=59/pitch
            image=image.resize((round(image.width*analysis_scale),round(image.height*analysis_scale)),Image.Resampling.LANCZOS)
            ocr=copy.deepcopy(ocr)
            for line in ocr.get('lines',[]):
                for word in line.get('words',[]):
                    for key in ('x','y','width','height'):word[key]*=analysis_scale
    layout=starter_layout(image,ocr,directory,records)
    result={'status':'unreadable','by_slot':{},'row_slots':layout.get('row_slots',[]),
            'analysis_scale':analysis_scale,'analysis_size':list(image.size),
            'ocr_coordinate_correction':ocr.get('coordinate_correction')}
    if layout['status']!='verified':return result
    result['identity_source']=layout['identity_source']
    geometry=skills_geometry(ocr,layout)
    if geometry is None:return result
    result.update(status='verified',geometry=geometry)
    unit=geometry['unit']
    for row,slot in zip(layout['rows'],layout['row_slots']):
        cy=row['center_y']-18*unit;cells=[]
        for cx in geometry['columns']:
            bounds=[round(cx-18*unit),round(cy-20*unit),round(cx+18*unit),round(cy+20*unit)]
            skill,icon_evidence=read_icon(image.crop(tuple(bounds)),directory)
            if skill is None:skill=caption_confirmation(ocr,cx,cy,unit,icon_evidence,directory)
            badge,level_bounds=level_crop(image,cx,cy,unit)
            level,level_evidence=read_level(badge,directory)
            cells.append({'id':skill['id'] if skill else None,'name':skill['name'] if skill else None,
                          'lv':level,'icon_bounds':bounds,'level_bounds':level_bounds,
                          'icon_evidence':icon_evidence,'level_evidence':level_evidence})
        result['by_slot'][slot]=cells
    return result


def read_manual_skills(scanner,image,directory,records=None):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    image=image.convert('RGB');image.save(directory/'capture.png')
    scanner.ocr(image,directory,'table-ocr')
    ocr=json.loads((directory/'table-ocr.json').read_text(encoding='utf8'))
    ocr=screenshot_coordinates(ocr,image.size)
    (directory/'geometry-ocr.json').write_text(json.dumps(ocr,ensure_ascii=False,indent=2),encoding='utf8')
    result=read_skills(image,ocr,records=records)
    if result['analysis_scale']!=1.0:
        image.resize(tuple(result['analysis_size']),Image.Resampling.LANCZOS).save(directory/'analysis.png')
        result['analysis_image']=str((directory/'analysis.png').resolve())
    result['source_image']=str((directory/'capture.png').resolve())
    (directory/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    return result


def apply_skills(records,snapshot):
    if snapshot.get('status')!='verified' or set(snapshot.get('by_slot',{}))!=set(('DH','C','1B','2B','3B','SS','LF','CF','RF')):
        raise ValueError('스킬 열과 주전 9명을 확인하지 못했습니다. 한눈에 보기의 스킬 3칸과 상위 9행이 보이게 F7을 눌러 주세요.')
    if (len({r.get('slot') for r in records})!=len(records) or
            any(r.get('slot') not in snapshot['by_slot'] for r in records) or
            any(len(cells)!=3 for cells in snapshot['by_slot'].values())):
        raise ValueError('수집 결과의 배치 또는 스킬 3칸을 확인할 수 없습니다.')
    count=0;unresolved=0
    for record in records:
        cells=snapshot['by_slot'][record['slot']];previous=record.get('skills',[])
        skills=[];pending=[]
        for index,cell in enumerate(cells):
            old=previous[index] if index<len(previous) and previous[index] else {}
            if cell['name'] and cell['lv'] is not None:
                skills.append({'id':cell['id'],'name':cell['name'],'lv':cell['lv']});count+=1
            else:
                # An uncertain read never destroys an existing pair or combines
                # a newly read name with a different previous skill's level.
                value=dict(old) if old else {'id':cell['id'],'name':cell['name'],'lv':cell['lv']}
                skills.append(value);pending.append(index);unresolved+=1
        record['skills']=skills
        record['skill_capture']={'source_image':snapshot.get('source_image'),
                                 'cells':cells,'unresolved':pending}
        record['issues']=[issue for issue in record.get('issues',[]) if not issue.startswith('스킬 ')]
        record['issues'].extend(f'스킬 {i+1}: 이름/레벨 확인 필요' for i in pending)
    return count,unresolved


def skills_from_form(names,levels,catalog=None):
    catalog=catalog or SkillCatalog();result=[]
    for i,(name,level) in enumerate(zip(names,levels),1):
        name=name.strip();level=str(level).strip()
        if not name and not level:result.append({});continue
        if name not in catalog.batter_names:raise ValueError(f'스킬 {i}: 목록에서 정확한 스킬명을 선택하세요.')
        if not level.isdigit() or not 1<=int(level)<=99:raise ValueError(f'스킬 {i}: 표시된 레벨을 숫자로 입력하세요.')
        skill=next(s for s in catalog.batters if s['name']==name)
        result.append({'id':skill['id'],'name':name,'lv':int(level)})
    return result
