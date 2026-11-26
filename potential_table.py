"""Read only the top nine starters and the three sheet potential columns."""
from pathlib import Path
import json,re
import numpy as np
from PIL import Image
from digit_reader import runs
from potential_letters import read_table_grade,normalize_grade
from potential_reader import GRADES,LEGACY
from core import ORDER
from ocr_coordinates import screenshot_coordinates

ROOT=Path(__file__).parent

def is_potential_table(text):return '한눈에보기' in re.sub(r'\s+','',text or '')

def header_geometry(ocr,size):
    width,height=size;words=[]
    for line in ocr.get('lines',[]):
        for word in line.get('words',[]):
            cx=(word['x']+word['width']/2)/2;cy=(word['y']+word['height']/2)/2
            words.append((word,cx,cy))
    player=next(((w,x,y) for w,x,y in words if re.sub(r'\s+','',w['text'])=='선수' and y<height*.40),None)
    if player is None:return None
    word,x,y=player;scale=max(.65,min(1.8,word['height']/2/13))
    columns={}
    for w,cx,cy in words:
        if cx<x+70*scale or abs(cy-y)>22*scale:continue
        text=re.sub(r'\s+','',w['text'])
        if text in ('풀스윙','풀스윔','불스윙','불스윔'):columns['pot1']=cx
        if text in ('클러치','글러치','클러지','글러지','클리치','글리지'):columns['pot2']=cx
        if '각성' in text or text=='각잠':columns['pot3']=cx
    return {'player_x':x,'header_y':y,'scale':scale,'columns':columns,'labels':[w['text'] for w,_,cy in words if abs(cy-y)<22*scale]}

def row_masks(image,geometry):
    rgb=np.asarray(image.convert('RGB')).astype('int16');scale=geometry['scale']
    left=max(0,round(geometry['player_x']-34*scale));right=min(image.width,round(geometry['player_x']+8*scale))
    top=max(0,round(geometry['header_y']+30*scale))
    roi=rgb[top:,left:right]
    cyan=(roi[:,:,0]<120)&(roi[:,:,1]>110)&(roi[:,:,2]>110)&(roi[:,:,1]-roi[:,:,0]>35)
    bands=[(a,b) for a,b in runs(cyan.sum(axis=1)>1) if b-a>=6*scale]
    rows=[]
    for a,b in bands[:9]:
        mask=cyan[a:b];normalized=normalize_grade(mask)
        if normalized is not None:rows.append({'mask':normalized,'center_y':top+(a+b)/2})
    return rows

TITLE_ALIASES={
    'pot1':{'풀스윙','풀스윔','불스윙','불스윔','품스윙','품스윔','풀스원','불스원','풀스월','불스월'},
    'pot2':{'클러치','글러치','클러지','글러지','클리치','글리지'},
    'pot3':{'각잠','각성잠재력'},
}


def table_edges(image,geometry,unit):
    rgb=np.asarray(image.convert('RGB')).astype('int16')
    cyan=(rgb[:,:,1]>60)&(rgb[:,:,2]>70)&(rgb[:,:,1]-rgb[:,:,0]>25)&(rgb[:,:,2]-rgb[:,:,0]>35)
    top=max(0,round(geometry['header_y']+15*unit));bottom=min(image.height,round(geometry['header_y']+45*unit))
    spans=[]
    for y in range(top,bottom):
        spans.extend((a,b,y) for a,b in runs(cyan[y]) if b-a>image.width*.55)
    if not spans:return None
    left,right,line_y=max(spans,key=lambda span:span[1]-span[0])
    return {'left':left,'right':right,'line_y':line_y,
            'data_left':2*geometry['player_x']-left}


def potential_headers(image,layout,full,enhanced=None):
    geometry=layout['geometry'];unit=float(np.median(np.diff([r['center_y'] for r in layout['rows']]))/59)
    edges=table_edges(image,geometry,unit)
    result={'columns':{},'headers':{},'skipped':[],'unit':unit,'edges':edges}
    if edges is None:return result
    sources=[('header',enhanced),('full',full)] if enhanced else [('full',full)]
    blocked=set()
    for source,ocr in sources:
        if not ocr:continue
        words=[]
        for line in ocr.get('lines',[]):
            for word in line.get('words',[]):
                x=(word['x']+word['width']/2)/2;y=(word['y']+word['height']/2)/2
                if abs(y-geometry['header_y'])<=25*unit and x>edges['data_left']-4*unit:
                    words.append((word,x,y,re.sub(r'[^가-힣]','',word['text'])))
        candidates={}
        for word,x,y,text in words:
            field=next((key for key,names in TITLE_ALIASES.items() if text in names),None)
            if text=='각성':
                lower=[t for _,xx,yy,t in words if abs(xx-x)<20*unit and 0<yy-y<22*unit]
                if any('재력' in t or '잰력' in t or '잠재' in t for t in lower):field='pot3'
            if field is None or field in result['columns'] or field in blocked:continue
            # Do not use a header/value touching either scrolling clip edge.
            if (word['x']/2<edges['data_left']+unit or (word['x']+word['width'])/2>edges['right']-unit
                    or x-26*unit<edges['data_left']+unit or x+26*unit>edges['right']-unit):
                result['skipped'].append({'field':field,'text':word['text'],'x':x,'reason':'clipped column','source':source});continue
            candidates.setdefault(field,[]).append((x,word['text']))
        for field,found in candidates.items():
            xs=[x for x,_ in found]
            if max(xs)-min(xs)>6*unit:
                blocked.add(field);result['skipped'].append({'field':field,'reason':'ambiguous title position','source':source});continue
            x=float(np.median(xs));result['columns'][field]=x
            result['headers'][field]={'x':x,'text':found[0][1],'source':source}
    return result


def read_snapshot(image,ocr,records=None,header_ocr=None):
    # Shared row verification with F7. Import here avoids a module-level cycle
    # because the shared layout reader uses header_geometry/row_masks above.
    from skill_reader import starter_layout
    ocr=screenshot_coordinates(ocr,image.size)
    combined=dict(ocr)
    combined['lines']=ocr.get('lines',[])+(header_ocr.get('lines',[]) if header_ocr else [])
    layout=starter_layout(image,combined,records=records)
    result={'by_slot':{},'columns':{},'row_slots':layout.get('row_slots',[]),'status':'unreadable',
            'ocr_coordinate_correction':ocr.get('coordinate_correction')}
    if layout['status']!='verified':return result
    headers=potential_headers(image,layout,ocr,header_ocr)
    result['header_evidence']=headers;result['columns']=headers['columns']
    result['geometry']={**layout['geometry'],'columns':headers['columns']}
    result.update(status='verified',row_slots=layout['row_slots'],identity_source=layout.get('identity_source'))
    unit=headers['unit']
    for row,slot in zip(layout['rows'],layout['row_slots']):
        fields={}
        for field,x in headers['columns'].items():
            cy=row['center_y']-12*unit
            box=[round(x-26*unit),round(cy-15*unit),round(x+26*unit),round(cy+15*unit)]
            raw,evidence=read_table_grade(image.crop(tuple(box)),ROOT/'potential_letters.npz')
            grade=LEGACY.get(raw,raw) if raw in GRADES or raw in LEGACY else '-'
            status='not_present' if raw=='-' else 'recognized' if raw in GRADES or raw in LEGACY else 'unreadable'
            fields[field]={'grade':grade,'raw_grade':raw,'status':status,'bounds':box,'evidence':evidence}
        result['by_slot'][slot]=fields
    result['summary']={field:{'recognized':sum(values[field]['status']=='recognized' for values in result['by_slot'].values()),
                              'not_present':sum(values[field]['status']=='not_present' for values in result['by_slot'].values()),
                              'unreadable':sum(values[field]['status']=='unreadable' for values in result['by_slot'].values())}
                       for field in headers['columns']}
    return result

def merge_snapshot(state,snapshot):
    if snapshot.get('status')!='verified':return
    row_slots=snapshot['row_slots']
    if state.get('row_slots') and state['row_slots']!=row_slots:
        state['row_mismatch']=True;return
    state['row_slots']=row_slots
    for slot,fields in snapshot['by_slot'].items():
        destination=state.setdefault('by_slot',{}).setdefault(slot,{})
        for field,result in fields.items():
            if field not in destination or result['grade']!='-' or result.get('status')=='not_present':destination[field]=result

def final_values(state,slot):
    if state.get('row_mismatch'):return dict.fromkeys(('pot1','pot2','pot3'),'-')
    return {field:state.get('by_slot',{}).get(slot,{}).get(field,{}).get('grade','-') for field in ('pot1','pot2','pot3')}

def read_manual_capture(scanner,image,directory,records=None):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True);image=image.convert('RGB');image.save(directory/'capture.png')
    scanner.ocr(image,directory,'table-ocr')
    full=screenshot_coordinates(json.loads((directory/'table-ocr.json').read_text(encoding='utf-8')),image.size)
    geometry=header_geometry(full,image.size)
    header=None
    if geometry:
        top=max(0,round(geometry['header_y']-26*geometry['scale']))
        bottom=min(image.height,round(geometry['header_y']+26*geometry['scale']))
        strip=image.crop((0,top,image.width,bottom));strip=strip.resize((strip.width*2,strip.height*2))
        scanner.ocr(strip,directory,'header-ocr')
        header=screenshot_coordinates(json.loads((directory/'header-ocr.json').read_text(encoding='utf-8')),strip.size)
        for line in header['lines']:
            for word in line.get('words',[]):
                word['x']/=2;word['width']/=2;word['y']=word['y']/2+top*2;word['height']/=2
    (directory/'geometry-ocr.json').write_text(json.dumps({'full':full,'header':header},ensure_ascii=False,indent=2),encoding='utf8')
    result=read_snapshot(image,full,records,header)
    result['source_image']=str((directory/'capture.png').resolve())
    (directory/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result

def apply_manual_capture(records,snapshot):
    if snapshot.get('status')!='verified' or not snapshot.get('columns'):
        if any(item.get('reason')=='clipped column' for item in snapshot.get('header_evidence',{}).get('skipped',[])):
            raise ValueError('잠재력 열이 잘려 있습니다. 제목과 등급의 +까지 모두 보이게 맞춘 뒤 F6을 눌러 주세요.')
        raise ValueError('잠재력 열과 주전 9명을 확인하지 못했습니다. 열 제목과 상위 9행이 보이게 다시 F6을 눌러 주세요.')
    count=0
    for record in records:
        fields=snapshot['by_slot'].get(record['slot'],{})
        for key,value in fields.items():
            # A later screenshot of another column cannot erase earlier values.
            if value.get('status')=='unreadable':continue
            if value['grade']=='-' and value.get('status')!='not_present' and record.get(key) not in (None,'','-'):continue
            record[key]=value['grade'];record.setdefault('potentials',{})[key]=value;count+=1
    return count
