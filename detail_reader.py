"""Two-screen capture: overview fields, separate from stat contributions."""
import json
import re
from collections import Counter
from PIL import Image,ImageOps,ImageDraw,ImageFont
import numpy as np
from pathlib import Path
from awakening_reader import read_awakening

OVERVIEW_ROIS={'launch_angle':(.812,.625,.905,.670),'enhancement_level':(.823,.581,.892,.607)}
ADDITIONAL_ROWS=('훈련','강화','특훈','각성','세트덱','시너지','포지션 특훈')

def enhancement_text(text):
    # An icon row is not a readable numeric level. Do not infer a level from stat bonuses.
    text=re.sub(r'\s+','',text or '')
    for pattern,kind in [(r'(\d{1,2})각성','각성'),(r'(\d{1,2})강(?!화)','강화'),(r'각성[:：]?(\d{1,2})','각성'),(r'강화[:：]?(\d{1,2})','강화')]:
        m=re.search(pattern,text)
        if m:
            n=int(m[1])
            if 0<=n<=30:return {'kind':kind,'level':n,'display':str(n)+('강' if kind=='강화' else '각성'),'source':'ocr_text'}
    return {'kind':'각성' if '각성' in text else '강화' if '강화' in text else None,'level':None,'display':'','source':'unreadable_icon_or_text'}

def prepare_overview(image,directory,rois=None):
    rois={field:(rois or {}).get(field,box) for field,box in OVERVIEW_ROIS.items()}
    sheet=Image.new('RGB',(560,len(rois)*480),'white');draw=ImageDraw.Draw(sheet)
    font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',30)
    cells=[]
    for field_index,(field,box) in enumerate(rois.items()):
        rect=tuple(round(v*(image.width if i%2==0 else image.height)) for i,v in enumerate(box))
        crop=image.crop(rect)
        crop.save(directory/(field+'-roi.png'))
        gray=ImageOps.autocontrast(crop.convert('L'))
        if field in ('launch_angle','enhancement_level'):
            rgb=np.asarray(crop.convert('RGB')).astype('int16')
            ink=(rgb.min(axis=2)>165)&(rgb.max(axis=2)-rgb.min(axis=2)<75)
            # Keep the white number; discard the degree mark above its baseline.
            if field=='launch_angle':
                active=ink.sum(axis=1)>=2
                from digit_reader import runs
                bands=runs(active)
                if bands:
                    top,bottom=max(bands,key=lambda b:b[1]-b[0])
                    ink[:top]=False;ink[bottom:]=False
            binary=Image.fromarray(np.where(ink,0,255).astype('uint8'))
            variants=[crop,binary,ImageOps.invert(gray)]
        else:variants=[crop,gray,ImageOps.invert(gray)]
        for n,variant in enumerate(variants):
            row=field_index*3+n;y=row*160
            draw.text((10,y+55),'VALUE',font=font,fill='black')
            variant=ImageOps.contain(variant,(220,120),Image.Resampling.LANCZOS)
            sheet.paste(variant,(250+(220-variant.width)//2,y+20+(120-variant.height)//2));cells.append({'field':field,'variant':n,'rect':[250,y+20,470,y+140]})
    sheet.save(directory/'overview-numbers.png')
    return sheet,cells

def parse_overview_numbers(ocr,cells):
    votes={'launch_angle':[],'enhancement_level':[]}
    for cell in cells:
        if cell['field'] not in votes:continue
        x0,y0,x1,y1=cell['rect'];tokens=[]
        for line in ocr.get('lines',[]):
            for word in line['words']:
                # The common OCR helper scales the contact sheet by 2.
                x=(word['x']+word['width']/2)/2;y=(word['y']+word['height']/2)/2
                if x0<=x<x1 and y0<=y<y1:
                    suffix=r'[°º˚。．·.]*' if cell['field']=='launch_angle' else ''
                    prefix=r'\+?' if cell['field']=='enhancement_level' else ''
                    m=re.fullmatch(prefix+r'(\d{1,3})'+suffix,word['text'].strip())
                    if m:tokens.append((x,m[1]))
        text=''.join(t for _,t in sorted(tokens))
        if text:
            value=int(text)
            limit=(0,30) if cell['field']=='enhancement_level' else (0,60)
            if limit[0]<=value<=limit[1]:votes[cell['field']].append(value)
    values={}
    for field,items in votes.items():
        counts=Counter(items)
        agreed=[n for n,c in counts.items() if c>=2]
        values[field]=agreed[0] if len(agreed)==1 else None
    return values,votes

def remove_overall(record):
    """Drop the retired scan field and warnings when older results are loaded."""
    overview=record.get('overview',{})
    overview.pop('overall',None)
    for key in ('numeric_votes','font_readings'):
        overview.get(key,{}).pop('overall',None)
    record['issues']=[s for s in record.get('issues',[]) if s not in ('OVR 확인 필요','오버롤 확인 필요')]

def overview_issues(record):
    overview=record.get('overview')
    if overview is None:return [] # Keep old saved captures readable.
    issues=[]
    if not overview.get('card_name'):issues.append('카드명 확인 필요')
    if type(overview.get('launch_angle')) is not int:issues.append('발사각 확인 필요')
    if not record.get('enhance'):issues.append('강화/각성 단계 확인 필요')
    return issues

def read_overview(scanner,image,directory):
    directory.mkdir(parents=True,exist_ok=True)
    # Read names from the screen, and isolate angle and reinforcement numbers.
    identity=scanner.ocr(image,directory,'identity')
    if '타자능력치' in re.sub(r'\s+','',identity):raise ValueError('세부 표를 닫고 선수 상세 정보 화면에서 F6을 눌러 주세요.')
    name_image=image.crop((round(image.width*.185),round(image.height*.483),round(image.width*.80),round(image.height*.525)))
    localized_name=scanner.ocr(name_image,directory,'name-ocr')
    identity+='\n'+localized_name
    sheet,cells=prepare_overview(image,directory,scanner.profile.get('overview_rois'))
    scanner.ocr(sheet,directory,'overview-numeric-ocr')
    numeric=json.loads((directory/'overview-numeric-ocr.json').read_text(encoding='utf-8'))
    numbers,votes=parse_overview_numbers(numeric,cells)
    from overview_digits import read as read_digits
    font_readings={}
    for field in ('launch_angle','enhancement_level'):
        with Image.open(directory/(field+'-roi.png')) as crop:
            value,evidence=read_digits(crop,field,Path(__file__).parent/'overview_digits.npz')
        font_readings[field]=evidence
        if value is not None:numbers[field]=value
    names=scanner.db.visible_names(identity)
    enhancement=enhancement_text(identity)
    badge_level=numbers.pop('enhancement_level')
    # Only a row explicitly identified as 강화 may use a numeric 강화 badge.
    # The portrait's awakening diamond is detected separately below.
    if enhancement['kind']=='강화' and badge_level is not None:
        enhancement={'kind':'강화','level':badge_level,'display':f'{badge_level}강','source':'localized_badge_number'}
    reinforcement=enhancement.copy()
    awakening=read_awakening(image)
    if awakening['status']=='detected':
        enhancement={'kind':'각성','level':awakening['level'],'display':awakening['display'],'source':awakening['source']}
    (directory/'awakening-evidence.json').write_text(json.dumps(awakening,ensure_ascii=False,indent=2),encoding='utf-8')
    if awakening['status']=='detected':image.crop(tuple(awakening['bounds'])).save(directory/'awakening-badge.png')
    return {'card_name':names[0] if len(names)==1 else None,'raw_identity':identity,**numbers,'numeric_votes':votes,'font_readings':font_readings,'reinforcement':reinforcement,'awakening':awakening,'enhancement':enhancement,'source_image':str((directory/'detail.png').resolve())}
