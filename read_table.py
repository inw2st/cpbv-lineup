"""Read a calibrated batter-stat table screenshot; never infer missing cells as zero."""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from PIL import Image, ImageOps, ImageDraw, ImageFont
import numpy as np

ROOT = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
STATS = ['파워', '정확', '선구', '인내', '주루', '수비']
ROWS = ['기본', '훈련', '강화', '특훈', '각성', '세트덱', '시너지', '포지션 특훈', '라커룸', '종합']

def extract(image_path, output, bounds,row_hints=None,source_ocr=None):
    bank=ROOT/'digits.npz'
    if not bank.exists():return _legacy_extract(image_path,output,bounds)
    from digit_reader import read
    from core import validate_table
    output=Path(output)
    result=read(image_path,output,bounds,bank,row_hints=row_hints)
    missing=[(row,stat) for row,values in result['table'].items() for stat,value in values.items() if value is None]
    result['fallback_cells']=[]
    if missing:
        evidence=json.loads((output/'glyph-evidence.json').read_text(encoding='utf-8'))
        votes={}
        if source_ocr:
            for key,items in _positioned_ocr_values(source_ocr,evidence,scale=2).items():
                if len(set(items))==1:votes[key]=[items[0]]
        recovered=_confirmed_ocr_values(votes,evidence)
        for key,value in recovered.items():
            row,stat=key
            if result['table'][row][stat] is None:
                result['table'][row][stat]=value
                result['fallback_cells'].append({'row':row,'stat':stat,'value':value,'source':'full-screen Windows OCR agrees with visible font candidate; no card DB'})
        missing=[key for key in missing if result['table'][key[0]][key[1]] is None]
    if missing:
        recovered=_table_fallback(image_path,output,bounds,result,missing)
        for (row,stat),value in recovered.items():
            result['table'][row][stat]=value
            result['fallback_cells'].append({'row':row,'stat':stat,'value':value,'source':'Windows OCR of actual numeric table bounds; no card DB'})
        missing=[key for key in missing if result['table'][key[0]][key[1]] is None]
    if missing:
        recovered=_dynamic_fallback(image_path,output,result,missing)
        for (row,stat),value in recovered.items():
            result['table'][row][stat]=value
            result['fallback_cells'].append({'row':row,'stat':stat,'value':value,'source':'Windows OCR at detected cell bounds; no card DB'})
    result['needs_review']=validate_table(result['table'])
    result['complete']=not result['needs_review']
    (output/'stats.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result

def _positioned_ocr_values(ocr,evidence,scale=1,offset=(0,0)):
    values={}
    for line in ocr.get('lines',[]):
        for word in line.get('words',[]):
            if not re.fullmatch(r'-?\d{1,3}',word.get('text','').strip()):continue
            x=offset[0]+(word['x']+word['width']/2)/scale
            y=offset[1]+(word['y']+word['height']/2)/scale
            for e in evidence:
                left,top,right,bottom=e['passes'][0]['bounds']
                if left<=x<=right and top-2<=y<=bottom+2:
                    signs=[p['negative'] for p in e['passes']]
                    if len(set(signs))!=1:continue
                    observed=int(word['text'])
                    # OCR can omit a small minus; the two visible sign masks
                    # must agree. Never infer a sign from the row's name.
                    if observed<0 and not signs[0]:continue
                    value=abs(observed)*(-1 if signs[0] else 1)
                    values.setdefault((e['row'],e['stat']),[]).append(value)
                    break
    return values

def _confirmed_ocr_values(values,evidence):
    by_key={(e['row'],e['stat']):e for e in evidence};confirmed={}
    for key,items in values.items():
        if not items or len(set(items))!=1:continue
        value=items[0]
        # Confirm an uncertain font candidate, or require two OCR observations.
        if value in by_key[key]['votes'] or len(items)>=2:confirmed[key]=value
    return confirmed

def _table_fallback(image_path,output,bounds,result,missing):
    evidence=json.loads((output/'glyph-evidence.json').read_text(encoding='utf-8'))
    gray=Image.open(image_path).convert('L').crop(bounds)
    votes={}
    for index,variant in enumerate([gray,ImageOps.invert(gray.point(lambda p:255 if p>155 else 0))]):
        path=output/f'actual-table-{index}.png'
        variant.resize((variant.width*4,variant.height*4),Image.Resampling.NEAREST).save(path)
        try:
            proc=subprocess.run(['C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe','-NoProfile','-File',str(ROOT/'ocr.ps1'),'-ImagePath',str(path.resolve()),'-Language','ko-KR'],capture_output=True,timeout=45,creationflags=subprocess.CREATE_NO_WINDOW)
            if proc.returncode:continue
            raw=json.loads(proc.stdout.decode('utf-8-sig'))
        except (subprocess.TimeoutExpired,ValueError):continue
        (output/f'actual-table-{index}.json').write_text(json.dumps(raw,ensure_ascii=False,indent=2),encoding='utf-8')
        found=_positioned_ocr_values(raw,evidence,scale=4,offset=bounds[:2])
        for key,items in found.items():
            if key in missing and len(set(items))==1:votes.setdefault(key,[]).append(items[0])
    return _confirmed_ocr_values(votes,evidence)

def _dynamic_fallback(image_path,output,result,missing):
    """Read uncertain cells at their actual positions, regardless of extra rows."""
    evidence=json.loads((output/'glyph-evidence.json').read_text(encoding='utf-8'))
    by_cell={(e['row'],e['stat']):e for e in evidence}
    items=[(key,by_cell[key]) for key in missing if key in by_cell]
    rgb=np.asarray(Image.open(image_path).convert('RGB'))
    gray=np.maximum(np.asarray(Image.fromarray(rgb).convert('L')),rgb[:,:,0])
    recovered={}
    for page in range(0,len(items),16):
        batch=items[page:page+16];canvas=Image.new('RGB',(650,len(batch)*100),'white')
        draw=ImageDraw.Draw(canvas);font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',24)
        for index,(key,e) in enumerate(batch):
            left,top,right,bottom=e['passes'][0]['bounds']
            cell=Image.fromarray(gray[top:bottom,left:right]).point(lambda p:0 if p>160 else 255)
            cell=cell.resize((100,70),Image.Resampling.NEAREST)
            draw.text((10,index*100+25),'value',font=font,fill='black')
            for n in range(3):canvas.paste(cell,(140+n*165,index*100+10))
        path=output/f'dynamic-fallback-{page//16}.png';canvas.save(path)
        try:
            proc=subprocess.run(['C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe','-NoProfile','-File',str(ROOT/'ocr.ps1'),'-ImagePath',str(path.resolve()),'-Language','ko-KR'],capture_output=True,timeout=45,creationflags=subprocess.CREATE_NO_WINDOW)
            if proc.returncode:continue
            raw=json.loads(proc.stdout.decode('utf-8-sig'))
        except (subprocess.TimeoutExpired,ValueError):continue
        (output/f'dynamic-fallback-{page//16}.json').write_text(json.dumps(raw,ensure_ascii=False,indent=2),encoding='utf-8')
        votes={}
        for line in raw.get('lines',[]):
            for word in line.get('words',[]):
                if word['x']<130 or not re.fullmatch(r'-?\d{1,3}',word['text']):continue
                index=int((word['y']+word['height']/2)//100)
                if 0<=index<len(batch):votes.setdefault(index,[]).append(abs(int(word['text'])))
        for index,values in votes.items():
            if len(values)<2 or len(set(values))!=1:continue
            key,e=batch[index]
            signs=[p['negative'] for p in e['passes']]
            if signs[0]!=signs[1]:continue
            recovered[key]=values[0]*(-1 if signs[0] else 1)
    return recovered

def _legacy_extract(image_path, output, bounds):
    # Bounds surround the table's numeric area, not the whole application window.
    image = Image.open(image_path).convert('L')
    x0, y0, x1, y1 = bounds
    if not (0 <= x0 < x1 <= image.width and 0 <= y0 < y1 <= image.height):
        raise ValueError('Table bounds are outside the image')
    output.mkdir(parents=True, exist_ok=True)
    canvas = Image.new('RGB', (1500, 1800), 'white')
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 28)
    # Row positions are calibrated for the supplied ten-row table layout.
    ys = [155,188,221,254,288,321,354,387,420,460]
    xs = [155,219,282,346,410,474]
    ref = (130,136,492,477)
    for r in range(10):
        for c in range(6):
            i = r * 6 + c
            px, py = (i // 20) * 500, (i % 20) * 90
            x = x0 + (xs[c]-ref[0]) / (ref[2]-ref[0]) * (x1-x0)
            y = y0 + (ys[r]-ref[1]) / (ref[3]-ref[1]) * (y1-y0)
            dx,dy = 22*(x1-x0)/(ref[2]-ref[0]),13*(y1-y0)/(ref[3]-ref[1])
            crop=image.crop((round(x-dx),round(y-dy),round(x+dx),round(y+dy)))
            crop=ImageOps.invert(crop.point(lambda p:255 if p>145 else 0)).resize((132,78))
            draw.text((px+8,py+24), f'Row {r:02} col {c} value', font=font,fill='black')
            canvas.paste(crop,(px+330,py+4))
    contact=output/'ocr-cells.png'
    canvas.save(contact)
    raw={'lines':[]}
    for page in range(3):
        page_path=output/f'ocr-page-{page}.png'
        canvas.crop((page*500,0,(page+1)*500,1800)).save(page_path)
        proc=subprocess.run(['C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe','-NoProfile','-File',str(ROOT/'ocr.ps1'),'-ImagePath',str(page_path.resolve()),'-Language','ko-KR'],capture_output=True,timeout=45,creationflags=subprocess.CREATE_NO_WINDOW)
        if proc.returncode:
            raise RuntimeError(proc.stderr.decode('utf-8',errors='replace'))
        page_result=json.loads(proc.stdout.decode('utf-8-sig'))
        for line in page_result['lines']:
            for word in line['words']: word['x']+=page*500
            raw['lines'].append(line)
    (output/'ocr-raw.json').write_text(json.dumps(raw,ensure_ascii=False,indent=2),encoding='utf-8')
    cells={}
    for line in raw['lines']:
        for word in line['words']:
            cx,cy=word['x']+word['width']/2,word['y']+word['height']/2
            block=int(cx//500)
            if not 330 <= cx-block*500 <= 470: continue
            if not re.fullmatch(r'\d{1,3}',word['text']): continue
            i=block*20+int(cy//90)
            if 0<=i<60: cells.setdefault(i,[]).append(int(word['text']))
    # Independent full-table pass recovers multi-digit tokens omitted in isolated layouts.
    full_path=output/'ocr-table.png'
    full=ImageOps.invert(image.crop(bounds).point(lambda p:255 if p>140 else 0))
    full.resize((full.width*4,full.height*4)).save(full_path)
    proc=subprocess.run(['C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe','-NoProfile','-File',str(ROOT/'ocr.ps1'),'-ImagePath',str(full_path.resolve()),'-Language','ko-KR'],capture_output=True,timeout=45,creationflags=subprocess.CREATE_NO_WINDOW)
    if proc.returncode==0:
        full_result=json.loads(proc.stdout.decode('utf-8-sig'))
        (output/'ocr-table-raw.json').write_text(json.dumps(full_result,ensure_ascii=False,indent=2),encoding='utf-8')
        for line in full_result['lines']:
            for word in line['words']:
                if not re.fullmatch(r'\d{1,3}',word['text']): continue
                nx=ref[0]+(word['x']+word['width']/2)/4/(x1-x0)*(ref[2]-ref[0])
                ny=ref[1]+(word['y']+word['height']/2)/4/(y1-y0)*(ref[3]-ref[1])
                c=min(range(6),key=lambda c:abs(xs[c]-nx))
                r=min(range(10),key=lambda r:abs(ys[r]-ny))
                if abs(xs[c]-nx)<15 and abs(ys[r]-ny)<13:
                    vals=cells.setdefault(r*6+c,[])
                    if not vals: vals.append(int(word['text']))
                    elif vals[0]!=int(word['text']): vals.append(int(word['text']))
    # Missing single-character cells can be compared against OCR-read glyphs from this image.
    def glyph(i):
        px,py=(i//20)*500,(i%20)*90
        a=ImageOps.invert(canvas.crop((px+330,py+4,px+462,py+82)).convert('L'))
        box=a.getbbox()
        return np.asarray(a.crop(box).resize((24,48)),dtype=float)/255 if box else None
    known=[(i,v[0],glyph(i)) for i,v in cells.items() if len(v)==1 and v[0] in (0,1)]
    for i in range(60):
        if cells.get(i): continue
        g=glyph(i)
        if g is None: continue
        scores=sorted((float(np.mean(np.abs(g-k))),v) for _,v,k in known if k is not None)
        if scores and scores[0][0]<0.035:
            cells[i]=[scores[0][1]]
    for i in range(60):
        if cells.get(i): continue
        px,py=(i//20)*500,(i%20)*90
        cell=canvas.crop((px+330,py+4,px+462,py+82))
        isolated=Image.new('RGB',(600,120),'white')
        for n in range(3): isolated.paste(cell,(20+n*180,20))
        cell_path=output/f'retry-{i}.png'
        isolated.save(cell_path)
        proc=subprocess.run(['C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe','-NoProfile','-File',str(ROOT/'ocr.ps1'),'-ImagePath',str(cell_path.resolve()),'-Language','ko-KR'],capture_output=True,timeout=45,creationflags=subprocess.CREATE_NO_WINDOW)
        if proc.returncode: continue
        retry=json.loads(proc.stdout.decode('utf-8-sig'))
        votes=[int(w['text']) for l in retry['lines'] for w in l['words'] if re.fullmatch(r'\d{1,3}',w['text'])]
        if len(votes)>=2 and len(set(votes))==1: cells[i]=[votes[0]]
    table={row:{stat:(cells[r*6+c][0] if len(cells.get(r*6+c,[]))==1 else None) for c,stat in enumerate(STATS)} for r,row in enumerate(ROWS)}
    problems=[]
    for r,row in enumerate(ROWS):
        for c,stat in enumerate(STATS):
            if table[row][stat] is None: problems.append(f'{row}/{stat}: 인식 확인 필요')
    for stat in STATS:
        values=[table[row][stat] for row in ROWS]
        if all(v is not None for v in values) and sum(values[:-1])!=values[-1]:
            problems.append(f'{stat}: 보정 합계와 종합 값 불일치')
    result={'source_image':str(Path(image_path).resolve()),'kind':'batter','bounds':bounds,'table':table,'needs_review':problems,'complete':not problems}
    (output/'stats.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return result

if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('image',type=Path)
    ap.add_argument('--output',type=Path,default=ROOT/'output')
    ap.add_argument('--bounds',type=int,nargs=4,required=True,metavar=('LEFT','TOP','RIGHT','BOTTOM'))
    a=ap.parse_args()
    extract(a.image,a.output,a.bounds)
