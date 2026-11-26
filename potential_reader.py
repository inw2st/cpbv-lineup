"""Read only the three batter potential grades accepted by sheet import."""
from collections import Counter
import json
from pathlib import Path
import re
import numpy as np
from PIL import Image,ImageDraw,ImageFont,ImageOps
from digit_reader import runs

GRADES=('C','C+','B','B+','A','A+','S','S+','SS','SS+','SR','SR+')
LEGACY={'E':'C','D':'C','D+':'C'}
FIELDS={'pot1':'풀스윙','pot2':'클러치','pot3':'각성 잠재력'}

def potential_geometry(image):
    rgb=np.asarray(image.convert('RGB'))
    x0,x1=round(image.width*.10),round(image.width*.90)
    y0,y1=round(image.height*.45),round(image.height*.66)
    white=(rgb[y0:y1,x0:x1].min(axis=2)>210)
    bands=runs(white.sum(axis=1)>(x1-x0)*.35)
    bands=[(a,b) for a,b in bands if b-a>image.height*.065]
    if not bands:return None
    a,b=max(bands,key=lambda v:v[1]-v[0]);top,bottom=y0+a,y0+b
    spans=runs(rgb[top+3].min(axis=1)>210)
    spans=[v for v in spans if v[1]-v[0]>image.width*.60]
    if not spans:return None
    x0,x1=max(spans,key=lambda v:v[1]-v[0]);panel_width=x1-x0
    left_center=round(x0+panel_width*.436)
    dark=rgb[top:bottom,left_center-16:left_center+17].max(axis=2)<160
    rows=runs(dark.mean(axis=1)>.30)
    rows=[v for v in rows if v[1]-v[0]>10]
    if len(rows)!=3:return None
    boxes={}
    for field,cx,row in [('pot1',.436,0),('pot2',.436,1),('pot3',.946,2)]:
        center=round(x0+panel_width*cx);ra,rb=rows[row]
        local_left=max(0,center-25);local_right=min(image.width,center+26)
        tile=rgb[top+ra:top+rb,local_left:local_right]
        dark_columns=runs((tile.max(axis=2)<160).mean(axis=0)>.25)
        dark_columns=[v for v in dark_columns if v[1]-v[0]>=10]
        if dark_columns:
            ca,cb=max(dark_columns,key=lambda v:v[1]-v[0])
            boxes[field]=[local_left+ca+1,top+ra+1,local_left+cb-1,top+rb-1]
        else:boxes[field]=[center-15,top+ra+1,center+15,top+rb-1]
    return {'panel':[x0,top,x1,bottom],'boxes':boxes}

def prepare_potentials(image,directory):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    geometry=potential_geometry(image)
    if geometry is None:return None,[],None
    sheet=Image.new('RGB',(700,1080),'white');draw=ImageDraw.Draw(sheet)
    font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',24);cells=[]
    for field_index,(field,box) in enumerate(geometry['boxes'].items()):
        crop=image.convert('RGB').crop(tuple(box));crop.save(directory/f'{field}-grade.png')
        rgb=np.asarray(crop)
        present=float((rgb.max(axis=2)<160).mean())>.25
        if not present:
            cells.append({'field':field,'present':False});continue
        # Neutral tile background is dark; red/green/gold/grey lettering is
        # recovered using the brightest RGB channel, not greyscale luminance.
        peak=Image.fromarray(rgb.max(axis=2))
        variants=[crop,ImageOps.invert(peak.point(lambda p:255 if p>145 else 0)),ImageOps.invert(peak.point(lambda p:255 if p>180 else 0))]
        for variant_index,variant in enumerate(variants):
            y=(field_index*3+variant_index)*120
            draw.text((8,y+35),'grade',font=font,fill='black')
            variant=variant.resize((112,76),Image.Resampling.NEAREST)
            for copy_index in range(3):
                x=180+copy_index*165;sheet.paste(variant,(x,y+16))
                cells.append({'field':field,'present':True,'variant':variant_index,'copy':copy_index,'rect':[x,y+16,x+112,y+92]})
    return sheet,cells,geometry

def parse_potentials(ocr,cells):
    fields={field:{'label':label,'grade':'-','raw_grade':None,'status':'unreadable','votes':[]} for field,label in FIELDS.items()}
    for field in FIELDS:
        if any(c['field']==field and not c['present'] for c in cells):
            fields[field].update(grade='',status='not_present')
    for cell in cells:
        if not cell['present']:continue
        left,top,right,bottom=cell['rect'];tokens=[]
        for line in ocr.get('lines',[]):
            for word in line.get('words',[]):
                x=(word['x']+word['width']/2)/2;y=(word['y']+word['height']/2)/2
                if left<=x<right and top<=y<bottom:
                    tokens.append((x,word.get('text','')))
        raw=re.sub(r'\s+','',''.join(text for _,text in sorted(tokens))).upper().replace('＋','+')
        if raw in GRADES or raw in LEGACY:fields[cell['field']]['votes'].append(raw)
    for field,result in fields.items():
        counts=Counter(result['votes']);ranked=counts.most_common()
        if ranked and ranked[0][1]>=2 and (len(ranked)==1 or ranked[0][1]>ranked[1][1]):
            raw=ranked[0][0];result.update(raw_grade=raw,grade=LEGACY.get(raw,raw),status='recognized')
    return {'values':{field:r['grade'] for field,r in fields.items()},'fields':fields,'source':'localized potential grade OCR; no skill scan'}

def read_potentials(scanner,image,directory):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    image.save(directory/'potential.png')
    sheet,cells,geometry=prepare_potentials(image,directory)
    if sheet is None:
        result=parse_potentials({'lines':[]},[]);result['page_verified']=False
    else:
        from potential_letters import read_grade
        result=parse_potentials({'lines':[]},cells);result['page_verified']=True
        for field,box in geometry['boxes'].items():
            if result['fields'][field]['status']=='not_present':continue
            raw,evidence=read_grade(image.crop(tuple(box)),Path(__file__).parent/'potential_letters.npz')
            result['fields'][field]['font_evidence']=evidence
            if raw in GRADES or raw in LEGACY:
                grade=LEGACY.get(raw,raw)
                result['fields'][field].update(raw_grade=raw,grade=grade,status='recognized')
                result['values'][field]=grade
        result['source']='visible potential grade glyphs; no skill scan'
    result['geometry']=geometry
    (directory/'potentials.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result
