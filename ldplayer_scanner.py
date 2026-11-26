"""LDPlayer window backend, with guarded navigation and per-card checkpoints."""
import contextlib
import csv
import json
import re
from datetime import datetime,timezone,timedelta
from pathlib import Path
from PIL import ImageChops,ImageStat
from core import ORDER,validate_table
from scanner import Scanner
from windows_io import GameWindow
from read_table import extract
from detail_reader import read_overview,ADDITIONAL_ROWS
from batting_order import read_batting_order,is_order_screen,order_header_evidence
from potential_table import is_potential_table,final_values

class LDWindow:
    def __init__(self,stop,read_only=False):
        self.base=GameWindow(stop,window_title='LDPlayer',read_only=read_only)
        _,_,w,h=self.base.rect()
        self.viewport=(0,39,w-40,h)
        if abs((w-40)/(h-39)-1080/1920)>.015:
            raise RuntimeError('LDPlayer 창이 세로 9:16 비율과 다릅니다. 사이드바를 펼친 기본 창 모드로 실행하세요.')
    def check(self):self.base.check()
    def wait(self,s):self.base.wait(s)
    def focus(self):self.base.focus()
    def capture(self,path=None):
        image=self.base.capture().crop(self.viewport)
        if path:image.save(path)
        return image
    def click(self,point):
        x,y=point;_,_,w,h=self.base.rect();l,t,r,b=self.viewport
        self.base.click(((l+x*(r-l))/w,(t+y*(b-t))/h))
    def drag(self,start,end):
        _,_,w,h=self.base.rect();l,t,r,b=self.viewport
        convert=lambda p:((l+p[0]*(r-l))/w,(t+p[1]*(b-t))/h)
        self.base.drag(convert(start),convert(end))
    def settled(self,delay=.9):
        self.wait(delay)
        previous=None
        for _ in range(12):
            image=self.capture()
            area=image.crop((0,int(image.height*.52),image.width,int(image.height*.81))).resize((100,80))
            if previous is not None and sum(ImageStat.Stat(ImageChops.difference(previous,area)).mean)/3<2:return image
            previous=area;self.wait(.2)
        raise RuntimeError('화면 전환이 안정되지 않았습니다.')

def table_row_hints(ocr,bounds):
    hints=[]
    for line in ocr.get('lines',[]):
        words=[w for w in line.get('words',[]) if 0<=w.get('x',-2)/2<bounds[0]
               and bounds[1]<=(w.get('y',-2)+w.get('height',0)/2)/2<=bounds[3]]
        if not words:continue
        text=re.sub(r'\s+','',''.join(w.get('text','') for w in sorted(words,key=lambda w:w['x'])))
        aliases={'세트액':'세트덱','세트엑':'세트덱','라커품':'라커룸','라커퓸':'라커룸'}
        label=aliases.get(text,text)
        if label.startswith('포지션'):label='포지션 특훈'
        if label=='이달의선수':label='이달의 선수'
        if not re.search(r'[가-힣A-Za-z]',label):continue
        hints.append({'label':label,'y':sum((w['y']+w['height']/2)/2 for w in words)/len(words)})
    return hints

def find_table_geometry(ocr,size):
    width,height=size;scale=width/558
    for line in ocr.get('lines',[]):
        if '타자능력치' not in re.sub(r'\s+','',line['text']):continue
        words=line['words'];top=min(w['y'] for w in words)/2;bottom=max(w['y']+w['height'] for w in words)/2
        cy=(top+bottom)/2
        last=None
        for candidate in ocr.get('lines',[]):
            for word in candidate['words']:
                if '종합' in word.get('text','') and word.get('x',width*2)/2<width*.23 and word['y']/2>cy+150*scale:
                    last=(word['y']+word['height'])/2+10*scale
        bottom=last if last is not None else cy+394*scale
        bounds=[round(width*.226),round(cy+53*scale),round(width*.875),round(bottom)]
        if bounds[3]>height:raise RuntimeError('능력치 표가 화면 밖으로 잘렸습니다.')
        return bounds,(.858,cy/height)
    return None,None

def export_csv(records,path):
    skill_columns=[name for i in range(1,4) for name in (f'스킬{i}',f'스킬{i}레벨')]
    fields=['배치','타순','카드ID','카드명','카드종류','발사각','강화각성단계','풀스윙','클러치','각잠',*skill_columns,'항목','파워','정확','선구','인내','주루','수비','확인사항']
    with open(path,'w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
        for record in records:
            card=record['match'].get('card',{});overview=record.get('overview',{})
            skill_values={};skills=record.get('skills',[])
            for i in range(3):
                skill=skills[i] if i<len(skills) and skills[i] else {}
                skill_values[f'스킬{i+1}']=skill.get('name');skill_values[f'스킬{i+1}레벨']=skill.get('lv')
            for label,stats in record['stats']['table'].items():
                writer.writerow({'배치':record['slot'],'타순':record.get('batting_order'),'카드ID':card.get('id',''),'카드명':card.get('name') or overview.get('card_name',''),'카드종류':card.get('template',''),'발사각':overview.get('launch_angle'),'강화각성단계':record.get('enhance',''),'풀스윙':record.get('pot1') or '-','클러치':record.get('pot2') or '-','각잠':record.get('pot3') or '-',**skill_values,'항목':label,**stats,'확인사항':'; '.join(s for s in record['issues'] if s not in ('OVR 확인 필요','오버롤 확인 필요'))})

class LDScanner(Scanner):
    def __init__(self,*args,count=9,on_record=None,**kwargs):
        super().__init__(*args,**kwargs);self.count=count;self.on_record=on_record or (lambda r:None)
        self.batting_order={};self.batting_order_capture={'status':'not_captured'}
        self.potentials_capture={'status':'not_captured','by_slot':{}}
    def save(self,directory,status,error=None):
        payload={'schema_version':2,'backend':'ldplayer-window','status':status,'error':error,'database':self.db.path,'order':list(ORDER),'records':self.records,'batting_order_capture':self.batting_order_capture,'potentials_capture':self.potentials_capture}
        # Store plain user-facing Korean; keep raw images separate from the summary.
        payload['limitations']=['각성 아이콘과 숫자 미인식 단계는 직접 확인해야 합니다.','발사각 미인식 값은 빈칸으로 저장합니다.']
        (directory/'scan.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
        export_csv(self.records,directory/'all_stats.csv')
    def screen_ocr(self,image,directory,label):
        text=self.ocr(image,directory,label)
        data=json.loads((directory/(label+'.json')).read_text(encoding='utf-8'))
        return text,data
    def capture_batting_order(self,game,lineup,directory):
        target=directory/'batting-order';target.mkdir(exist_ok=True)
        lineup.save(target/'lineup.png')
        self.log('타순 변경 화면에서 실제 타순 확인')
        game.click((.918,.134));image=game.settled();image.save(target/'order.png')
        text,data=self.screen_ocr(image,target,'order-ocr')
        if not is_order_screen(text):raise RuntimeError('타순 화면을 확인하지 못했습니다. 현재 화면에서 중단합니다.')
        try:
            headers=order_header_evidence(data,image.size)
            result=read_batting_order(lineup,image,target/'recognition')
            result['header_evidence']=headers
            if not headers['verified']:result.update(status='needs_review',orders={})
        finally:
            # X only: do not touch cards, 원래대로, 선수 교체, or 저장.
            game.check();game.click((.108,.897));returned=game.settled()
        returned.save(target/'returned-lineup.png')
        text,_=self.screen_ocr(returned,target,'returned-ocr')
        compact=re.sub(r'\s+','',text)
        if '타순변경' not in compact:raise RuntimeError('타순 확인 후 라인업 복귀를 확인하지 못했습니다.')
        if result['status']=='verified':
            check=read_batting_order(returned,image)
            if check['status']!='verified' or check['orders']!=result['orders']:
                result.update(status='needs_review',orders={})
        self.batting_order_capture=result;self.batting_order=result['orders']
        (target/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        self.log('타순 1~9 자동 연결 완료' if self.batting_order else '타순 카드 대조 미확정: 수집은 계속하고 실제 타순은 검토창에서 입력하세요.')
        return returned
    def run(self):
        directory=self.root/('ldplayer-'+datetime.now(timezone(timedelta(hours=9))).strftime('%Y%m%d-%H%M%S-%f'))
        directory.mkdir(parents=True);self.last_directory=directory;self.save(directory,'starting')
        try:
            game=LDWindow(self.stop);game.focus();game.wait(.5)
            image=game.capture(directory/'initial.png');text,data=self.screen_ocr(image,directory,'initial-ocr')
            if is_potential_table(text):
                game.click((.889,.094));image=game.settled();text,data=self.screen_ocr(image,directory,'initial-lineup-ocr')
            if is_order_screen(text):
                game.click((.108,.897));image=game.settled();text,data=self.screen_ocr(image,directory,'initial-lineup-ocr')
            bounds,close=find_table_geometry(data,image.size)
            if bounds:
                game.click(close);image=game.settled();text,data=self.screen_ocr(image,directory,'overview-ocr')
            compact=re.sub(r'\s+','',text)
            if '평균발사각' in compact:
                game.click((.5,.956));image=game.settled()
                text,data=self.screen_ocr(image,directory,'lineup-ocr')
            if '라인업' not in re.sub(r'\s+','',text):raise RuntimeError('타자 라인업 화면을 확인하지 못했습니다. 라인업으로 돌아가서 시작하세요.')
            if '상세정보' in re.sub(r'\s+','',text):
                # Leaving a detail page can retain an already-open card menu.
                # Dismiss it before selecting DH, otherwise the DH click toggles it off.
                game.click((.958,.747));image=game.settled()
            image=self.capture_batting_order(game,image,directory)
            # Potential screenshots are supplied by the user with F6 after scanning.
            game.click((.67,.496));image=game.settled()
            text,_=self.screen_ocr(image,directory,'selected-dh')
            if '상세정보' not in re.sub(r'\s+','',text):raise RuntimeError('DH 선택 후 상세 정보 버튼을 확인하지 못했습니다.')
            game.click((.346,.903));detail=game.settled()
            previous_card=None
            for index,slot in enumerate(ORDER[:self.count]):
                game.check();self.log(f'{index+1}/{self.count} {slot}: 상세 정보 수집')
                target=directory/f'{index+1:02}-{slot}';target.mkdir()
                detail.save(target/'detail.png')
                overview=read_overview(self,detail,target)
                identity=overview['raw_identity']
                if not self.db.visible_names(identity):self.log(f'{slot}: 선수명 미확정. 능력치와 후보를 저장하고 검토 대상으로 남깁니다.')
                game.click((.44,.709));popup=game.settled()
                text,data=self.screen_ocr(popup,target,'popup-ocr');bounds,close=find_table_geometry(data,popup.size)
                if bounds is None:raise RuntimeError(f'{slot}: 능력치 표 제목 인식 실패. 다음 선수로 진행하지 않습니다.')
                path=target/'table.png';popup.save(path)
                with open(target/'extraction.log','w',encoding='utf-8') as log,contextlib.redirect_stdout(log):stats=extract(path,target/'table-data',bounds,row_hints=table_row_hints(data,bounds),source_ocr=data)
                match=self.db.match(stats['table'],identity);card=match.get('card',{})
                if card.get('id') and card['id']==previous_card:raise RuntimeError(f'{slot}: 이전과 같은 카드입니다. 오른쪽 이동을 확인하세요.')
                previous_card=card.get('id')
                if card:overview['card_name']=card['name']
                issues=validate_table(stats['table'])
                if match['status']!='verified':issues.append(match['message'])
                if overview.get('launch_angle') is None:issues.append('발사각 확인 필요')
                stage=overview['enhancement']['display']
                if not stage:issues.append('강화/각성 단계 확인 필요')
                record={'slot':slot,'identity_text':identity,'overview':overview,'stats':stats,'additional_stats':{k:v for k,v in stats['table'].items() if k not in ('기본','종합')},'match':match,'enhance':stage,'batting_order':self.batting_order.get(slot),'potentials':self.potentials_capture.get('by_slot',{}).get(slot,{}),**final_values(self.potentials_capture,slot),'issues':issues}
                if record['batting_order'] is None:issues.append('실제 타순 확인 필요')
                self.records.append(record);self.save(directory,'running');self.on_record(record)
                self.log(f'{slot}: {card.get("name","카드 미확정")} / {match["status"]} / 확인 {len(issues)}개')
                game.check();game.click(close);detail=game.settled()
                if index<self.count-1:
                    game.click((.937,.257));detail=game.settled()
            self.save(directory,'captured');self.log('수집 완료. RF 뒤 후보로 이동하지 않습니다.')
        except Exception as exc:
            self.save(directory,'stopped' if isinstance(exc,InterruptedError) else 'failed',str(exc));raise
        return directory,self.records
