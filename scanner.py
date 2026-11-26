import contextlib
import json
import subprocess
import time
from datetime import datetime,timezone,timedelta
from pathlib import Path
from PIL import ImageChops, ImageStat
from core import CardDatabase, ORDER, validate_table
from read_table import extract
from windows_io import GameWindow

DEFAULT_PROFILE={
 'dh':[.667,.492],'info':[.344,.902],'stats':[.50,.735],
 'close_table':[.858,.054],'next':[.94,.264],
 'bounds':[.226,.105,.875,.446], 'delay':1.0,
}

class Scanner:
    def __init__(self,root,resources,db_path,profile,stop,log):
        self.root=Path(root);self.resources=Path(resources);self.db=CardDatabase(db_path)
        self.profile=profile;self.stop=stop;self.log=log;self.records=[]

    def ocr(self,image,directory,label,language='ko-KR'):
        p=directory/(label+'.png')
        w,h=image.size
        image.resize((w*2,h*2)).save(p)
        args=['C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe','-NoProfile','-File',str(self.resources/'ocr.ps1'),'-ImagePath',str(p.resolve()),'-Language',language]
        proc=subprocess.run(args,capture_output=True,timeout=45,creationflags=subprocess.CREATE_NO_WINDOW)
        if proc.returncode:raise RuntimeError(proc.stderr.decode('utf-8',errors='replace'))
        result=json.loads(proc.stdout.decode('utf-8-sig'))
        (directory/(label+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        return result['text']

    def save(self,directory,status,error=None):
        payload={'schema_version':1,'scope':'starting_batters','order':list(ORDER),'status':status,'error':error,'database':self.db.path,'profile':self.profile,'records':self.records,'limitations':['잠재력·스킬·강화 단계 자동 수집은 이 버전에 포함되지 않습니다.','강화/각성 단계와 실제 타순은 내보내기 전에 직접 입력합니다.']}
        (directory/'scan.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')

    def run(self):
        directory=self.root/datetime.now(timezone(timedelta(hours=9))).strftime('%Y%m%d-%H%M%S-%f');directory.mkdir(parents=True)
        self.last_directory=directory
        game=GameWindow(self.stop)
        self.log('3초 후 시작합니다. F8로 중지할 수 있습니다.')
        game.wait(3);game.focus()
        try:
            game.click(self.profile['dh']);selected=game.settled(self.profile['delay'])
            text=self.ocr(selected,directory,'selected-dh')
            if '상세정보' not in ''.join(text.split()):raise RuntimeError('DH 선택 후 상세 정보 버튼을 확인하지 못했습니다. 클릭 위치를 보정하세요.')
            game.click(self.profile['info']);detail=game.settled(self.profile['delay'])
            previous=None
            for index,slot in enumerate(ORDER):
                game.check();self.log(f'{index+1}/9 {slot}: 선수 정보와 기본 능력치 수집')
                card_dir=directory/f'{index+1:02}-{slot}';card_dir.mkdir()
                detail.save(card_dir/'detail.png')
                identity=self.ocr(detail,card_dir,'identity')
                if not self.db.visible_names(identity):raise RuntimeError(f'{slot}: 선수명을 읽지 못했습니다. 진행을 중단합니다.')
                fingerprint=detail.crop((int(detail.width*.2),int(detail.height*.04),int(detail.width*.8),int(detail.height*.43))).resize((100,100))
                if previous is not None and sum(ImageStat.Stat(ImageChops.difference(previous,fingerprint)).mean)/3<1.5:raise RuntimeError(f'{slot}: 이전 선수와 화면이 같습니다. 다음 선수 이동 실패 가능성으로 중단합니다.')
                previous=fingerprint
                game.click(self.profile['stats']);popup=game.settled(self.profile['delay'])
                header=self.ocr(popup.crop((0,0,popup.width,int(popup.height*.14))),card_dir,'table-header')
                if '타자능력치' not in ''.join(header.split()):raise RuntimeError(f'{slot}: 타자 능력치 창을 확인하지 못했습니다. 숫자를 읽거나 다음 화살표를 누르지 않고 중단합니다.')
                popup_path=card_dir/'table.png';popup.save(popup_path)
                bounds=[round(v*(popup.width if i%2==0 else popup.height)) for i,v in enumerate(self.profile['bounds'])]
                # Do not mix console progress into the GUI's UTF-8 report.
                with open(card_dir/'extraction.log','w',encoding='utf-8') as stream,contextlib.redirect_stdout(stream):
                    stats=extract(popup_path,card_dir/'ocr',bounds)
                game.check()
                match=self.db.match(stats['table'],identity)
                issues=validate_table(stats['table'])
                record={'slot':slot,'identity_text':identity,'stats':stats,'match':match,'issues':issues,'enhance':'','batting_order':None}
                self.records.append(record);self.save(directory,'running')
                self.log(f'{slot}: {match["message"]} / 표 확인 항목 {len(issues)}개')
                game.click(self.profile['close_table']);detail=game.settled(self.profile['delay'])
                # RF is the last card; do not click into bench cards.
                if index<len(ORDER)-1:
                    game.click(self.profile['next']);detail=game.settled(self.profile['delay'])
            self.save(directory,'captured');self.log('주전 9명 수집 완료. 검토 후 엑셀로 내보내세요.')
        except Exception as exc:
            self.save(directory,'stopped' if isinstance(exc,InterruptedError) else 'failed',str(exc))
            raise
        return directory,self.records
