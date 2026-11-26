"""UI-independent controller. Existing scanner files are imported, never edited.

Loaded results are copied into a separate workspace before any edits or captures.
All bridge calls share one lock; OCR workers operate on private record snapshots.
"""
from __future__ import annotations
import base64,copy,hashlib,io,json,os,re,sys,tempfile,threading
from datetime import datetime
from pathlib import Path

ROOT=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent.parent))
sys.path.insert(0,str(ROOT))
from core import ORDER,STAT_KEYS,PICKER_KINDS,KIND_LABELS,validate_table,fill_template,fa_status,export_issues
from live_cards import CardDatabase,LDScanner,card_version,version_value,export_csv
from scanner import Scanner,DEFAULT_PROFILE
from manual_potentials import capture_current_game,process_capture as process_potentials
from manual_skills import process_capture as process_skills
from potential_reader import GRADES
from skill_reader import SkillCatalog,skills_from_form
from detail_reader import remove_overall
from result_status import potential_confirmed,skills_confirmed,review_count
from catalog_store import CatalogStore,DEFAULT_MANIFEST
from runtime_skills import RuntimeSkills

VERSION='1.3.0'
UPDATED=Path(os.environ.get('LINEUP_CARD_DATABASE',str(ROOT/'cards.json')))
DEFAULT_DB=UPDATED if UPDATED.exists() else ROOT/'cards.json'
DEFAULT_RESULTS=Path.home()/'Documents'/'CPBV 새UI 수집'
DEFAULT_SETTINGS=Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'CPBVRosterDesktop'/'settings.json'


def atomic_json(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix='.cpbv-',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as stream:
            json.dump(data,stream,ensure_ascii=False,indent=2);stream.flush();os.fsync(stream.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)


def number(value,label):
    if value is None or str(value).strip()=='':return None
    if type(value) is bool or not re.fullmatch(r'-?\d+',str(value).strip()):raise ValueError(label+': 정수를 입력하세요.')
    return int(value)


class RosterService:
    def __init__(self,results=DEFAULT_RESULTS,settings=DEFAULT_SETTINGS,preview=False,catalog_store=None):
        self._lock=threading.RLock();self._closed=threading.Event();self._stop=threading.Event()
        self._results=Path(results);self._settings=Path(settings) if settings else None
        self._preview=preview;self._busy=None;self._editing=False;self._revision=1;self._records_version=0
        self._records=[];self._payload={};self._current=None;self._original=None;self._logs=[]
        self._status='라인업 수집을 시작하거나 저장된 결과를 열어 주세요.';self._last_export=None
        self._assets_cache={};self._asset_revision=0;self._worker=None
        self._catalog_store=catalog_store or CatalogStore()
        self._catalog_release=None;self._runtime_skills=None;self._pending_release=None
        self._catalog_syncing=False;self._catalog_error=None;self._catalog_checked=None
        self._manual_database=False
        self._preferences={};self._theme='system'
        self._db_path=DEFAULT_DB
        if self._settings and self._settings.exists():
            try:
                preferences=json.loads(self._settings.read_text(encoding='utf-8'))
                if isinstance(preferences,dict):self._preferences=preferences
                if self._preferences.get('theme') in ('system','light','dark'):self._theme=self._preferences['theme']
                if self._preferences.get('database'):
                    candidate=Path(self._preferences['database'])
                    if candidate.is_file():self._db_path=candidate;self._manual_database=True
            except (ValueError,KeyError,TypeError,OSError):pass
        release=self._catalog_store.current(verify=True) if not preview or catalog_store is not None else None
        if not release and not preview and (not self._db_path.exists() or not (ROOT/'resources/skills/skills.json').exists()):
            release,_=self._catalog_store.sync()
        if release and not self._manual_database:self._db_path=release.cards
        try:
            self._db=CardDatabase(self._db_path)
            if not self._db.cards:raise ValueError('타자 카드가 없는 데이터입니다.')
        except (ValueError,TypeError,AttributeError,OSError):
            self._db_path=DEFAULT_DB;self._db=CardDatabase(self._db_path)
        if release:
            self._runtime_skills=RuntimeSkills(release.skills,ROOT);self._skills=self._runtime_skills.catalog
            self._db.impact_concepts.update(json.loads(release.concepts.read_text(encoding='utf-8')))
            self._catalog_release=release
        else:self._skills=SkillCatalog()

    def _log(self,message,level='info'):
        with self._lock:
            self._logs.append({'id':self._revision,'time':datetime.now().strftime('%H:%M:%S'),'message':str(message),'level':level})
            self._logs=self._logs[-200:];self._status=str(message);self._revision+=1

    def _idle(self):
        if self._busy:raise ValueError('진행 중인 작업이 끝난 뒤 다시 시도해 주세요.')

    def _record(self,slot):
        return next((r for r in self._records if r['slot']==slot),None)

    def _require_record(self,slot):
        record=self._record(slot)
        if record is None:raise ValueError('해당 선수를 현재 결과에서 찾을 수 없습니다.')
        return record

    def _publish(self,records,assets=False):
        self._records=records;self._revision+=1;self._records_version+=1
        if assets:self._asset_revision+=1;self._assets_cache.clear()

    def _normalized(self,records):
        records=copy.deepcopy(records)
        for r in records:
            remove_overall(r);r['is_fa']=fa_status(r)=='FA'
            r['additional_stats']={k:v for k,v in r['stats']['table'].items() if k not in ('기본','종합')}
        return records

    def _persist(self,records,extra=None):
        if not self._current:raise ValueError('수집 결과를 먼저 열어 주세요.')
        records=self._normalized(records);payload=copy.deepcopy(self._payload)
        payload['records']=records;payload['interface']='react-desktop';payload['interface_version']=VERSION
        if extra:
            for key,value in extra.items():payload.setdefault(key,[]).append(value)
        atomic_json(self._current,payload)
        self._payload=payload
        try:export_csv(records,self._current.parent/'all_stats.csv')
        except OSError as error:self._log('JSON은 저장됐지만 CSV를 저장하지 못했습니다: '+str(error),'warning')
        self._publish(records)

    def _issues(self,r):
        issues=[s for s in r.get('issues',[]) if s not in ('OVR 확인 필요','오버롤 확인 필요')]
        if r.get('match',{}).get('status') not in ('verified','manual_selected'):issues.append('카드 연결을 확인하세요.')
        observed=version_value(r.get('overview',{}).get('live_version_evidence',{}).get('version'))
        if observed and card_version(r.get('match',{}).get('card',{}))!=observed:
            issues.append(f'미페 배지 V{observed}와 선택 카드가 다릅니다. 직접 선택한 버전을 확인하세요.')
        if not r.get('enhance'):issues.append('강화·각성 단계를 확인하세요.')
        if r.get('batting_order') not in range(1,10):issues.append('실제 타순을 입력하세요.')
        for key,label in (('pot1','풀스윙'),('pot2','클러치'),('pot3','각성 잠재력')):
            if not potential_confirmed(r,key):issues.append(label+' 미수집')
        if skills_confirmed(r)<3:issues.append('스킬 이름·레벨을 확인하세요.')
        return list(dict.fromkeys(issues))

    def _view(self,r):
        selected=r.get('match',{}).get('card',{});card=self._db.by_id.get(selected.get('id'))
        if card:card=self._db.entry(card,r['stats']['table'].get('기본',{}))
        else:card=selected
        return {'slot':r['slot'],'name':selected.get('name') or r.get('overview',{}).get('card_name') or '선수 미확인',
                'card':card,'enhance':r.get('enhance',''),'batting_order':r.get('batting_order'),
                'observed_live_version':r.get('overview',{}).get('live_version_evidence',{}).get('version'),
                'live_version_status':r.get('overview',{}).get('live_version_evidence',{}).get('status','not_captured'),
                'launch_angle':r.get('overview',{}).get('launch_angle'),'fa':fa_status(r)=='FA',
                'pot1':r.get('pot1') or '-','pot2':r.get('pot2') or '-','pot3':r.get('pot3') or '-',
                'potentials_confirmed':{k:potential_confirmed(r,k) for k in ('pot1','pot2','pot3')},
                'skills':r.get('skills',[]),'skills_confirmed':skills_confirmed(r),
                'match_status':r.get('match',{}).get('status'),'match_message':r.get('match',{}).get('message',''),
                'issues':self._issues(r),'review_count':review_count(r),'stats':r['stats']['table'],
                'hand':r.get('hand',r.get('overview',{}).get('hand')) or '',
                'white_zone':r.get('white_zone') or '', 'cold_zone':r.get('cold_zone') or ''}

    def state(self,revision=-1):
        with self._lock:
            if revision==self._revision:return {'unchanged':True}
            records=[self._view(r) for r in self._records]
            return {'revision':self._revision,'records_version':self._records_version,'asset_revision':self._asset_revision,
                    'version':VERSION,'theme':self._theme,'preview':self._preview,'busy':self._busy,'editing':self._editing,
                    'records':records,'status':self._status,'logs':copy.deepcopy(self._logs),
                    'current':str(self._current) if self._current else None,'original':str(self._original) if self._original else None,
                    'database':str(self._db_path),'database_count':len(self._db.cards),'last_export':self._last_export,
                    'catalog':self._catalog_state(),
                    'metrics':{'players':len(records),'potentials':sum(potential_confirmed(r,k) for r in self._records for k in ('pot1','pot2','pot3')),
                               'skills':sum(skills_confirmed(r) for r in self._records),'review':sum(review_count(r)>0 for r in self._records)},
                    'export_issues':export_issues(self._records)}

    def options(self):
        concepts={c['impact_concept']:c['impact_category'] for c in self._db.catalog(kind=1)}
        return {'skills':self._skills.batter_names,'grades':list(GRADES),'awake_grades':list(GRADES[:7]),
                'stats':list(STAT_KEYS),'kinds':PICKER_KINDS,'concepts':dict(sorted(concepts.items()))}

    def load(self,path):
        with self._lock:
            self._idle();source=Path(path).resolve()
            payload=json.loads(source.read_text(encoding='utf-8-sig'));records=payload.get('records')
            if not isinstance(records,list) or not records:raise ValueError('선수 records가 있는 수집 결과 JSON을 선택하세요.')
            slots=[r.get('slot') for r in records]
            if len(slots)!=len(set(slots)) or any(s not in ORDER for s in slots):raise ValueError('선수 배치가 중복되거나 지원하지 않는 결과입니다.')
            if any(not isinstance(r.get('stats',{}).get('table',{}).get('기본'),dict) for r in records):raise ValueError('선수의 기본 능력치 표가 없습니다.')
            # Never edit the source, including when it was created by the legacy app.
            directory=self._results/('import-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
            directory.mkdir(parents=True);target=directory/'scan.json'
            records=self._normalized(records);payload['records']=records;payload['original_source']=str(source)
            atomic_json(target,payload)
            self._current=target;self._original=source;self._payload=payload;self._last_export=None
            self._publish(records,assets=True);self._log(f'선수 {len(records)}명을 열었습니다. 원본은 보존하고 복사본에 저장합니다.')
        return self.state()

    def catalog(self,slot,filters=None):
        filters=filters or {}
        with self._lock:
            r=self._require_record(slot);base=r['stats']['table'].get('기본',{})
            items=self._db.catalog(str(filters.get('name') or ''),stars=filters.get('stars'),kind=filters.get('kind'),
                                   impact_category=filters.get('concept'),base=base,live_version=filters.get('live_version'))
            years=sorted({c['season'] for c in items if type(c.get('season')) is int and 1900<=c['season']<=2100},reverse=True)
            no_year=any(c.get('season') not in years for c in items)
            season=filters.get('season')
            if season=='none':items=[c for c in items if c.get('season') not in years]
            elif season is not None:items=[c for c in items if c.get('season')==int(season)]
            offset=max(0,int(filters.get('offset') or 0));limit=100
            return {'items':items[offset:offset+limit],'total':len(items),'years':years,'no_year':no_year,'offset':offset,'limit':limit}

    def select_card(self,slot,card_id,confirmed=False,version=None):
        with self._lock:
            self._idle();self._check_version(version);r=copy.deepcopy(self._require_record(slot))
            match=self._db.choose_id(r['stats']['table'],card_id,confirm_mismatch=bool(confirmed))
            observed=version_value(r.get('overview',{}).get('live_version_evidence',{}).get('version'))
            chosen=card_version(match['card'])
            if observed and (chosen!=observed) and not confirmed:
                raise ValueError(f'화면의 라이브 V{observed}와 선택 카드가 다릅니다. 차이를 확인해 주세요.')
            if observed and chosen!=observed:
                match['status']='manual_selected';match['live_version_override']=True
            r['match']=match;r['manual_card_name']=match['card'].get('player') or match['card']['name']
            r.setdefault('overview',{})['card_name']=match['card']['name'];r['manual_reviewed']=True
            r['issues']=validate_table(r['stats']['table'])
            if match['status']=='manual_selected':r['issues'].append('기본값 불일치/누락 상태에서 사용자가 카드 직접 선택')
            if r['overview'].get('launch_angle') is None:r['issues'].append('발사각 확인 필요')
            if not r.get('enhance'):r['issues'].append('강화/각성 단계 확인 필요')
            records=[r if old['slot']==slot else old for old in self._records]
            self._persist(records);self._log(r['match']['card']['name']+' 카드를 연결했습니다.')
        return self.state()

    def _check_version(self,version):
        if version is not None and int(version)!=self._records_version:raise ValueError('수집 결과가 갱신됐습니다. 수정 창을 다시 열어 주세요.')

    def update_record(self,slot,values,version=None):
        with self._lock:
            self._idle();self._check_version(version);r=copy.deepcopy(self._require_record(slot))
            o=r.setdefault('overview',{});o['launch_angle']=number(values.get('launch_angle'),'발사각')
            r['enhance']=str(values.get('enhance') or '').strip()
            if r['enhance'] and not re.fullmatch(r'\d+(강|각성)',r['enhance']):raise ValueError('강화·각성 단계는 10강 또는 3각성처럼 입력하세요.')
            r['batting_order']=number(values.get('batting_order'),'타순')
            if r['batting_order'] is not None and not 1<=r['batting_order']<=9:raise ValueError('타순은 1~9를 입력하세요.')
            r['fa_override']=bool(values.get('fa'))
            for key in ('pot1','pot2','pot3'):
                value=values.get(key) or '-';allowed=GRADES[:7] if key=='pot3' else GRADES
                if value!='-' and value not in allowed:raise ValueError('목록에 있는 잠재력 등급을 선택하세요.')
                r[key]=value
                # A deliberate '-' is a confirmed absence; UI metrics must not
                # keep marking a manually reviewed missing potential unreadable.
                r.setdefault('potentials',{})[key]={'status':'not_present' if value=='-' else 'recognized','value':value,'source':'manual'}
            skills=values.get('skills',[])
            if len(skills)!=3:raise ValueError('스킬은 3칸으로 입력하세요.')
            r['skills']=skills_from_form([s.get('name','') for s in skills],[s.get('lv','') for s in skills],self._skills)
            if 'skill_capture' in r:r['skill_capture']['unresolved']=[];r['skill_capture']['manual_reviewed']=True
            provided=values.get('stats',{})
            if set(provided)!=set(r['stats']['table']):raise ValueError('능력치 표의 행이 달라졌습니다. 수정 창을 다시 열어 주세요.')
            for label,stats in r['stats']['table'].items():
                if set(provided[label])!=set(stats):raise ValueError('능력치 표의 열이 다릅니다.')
                for stat in stats:stats[stat]=number(provided[label][stat],label+'/'+stat)
            for key in ('hand','white_zone','cold_zone'):
                if key in values:
                    value=str(values[key] or '').strip()
                    previous=r.get(key,o.get(key) if key=='hand' else None)
                    if value!=str(previous or '').strip():r[key]=value or None
            previous=r.get('match',{})
            if previous.get('manual_selection'):
                if previous.get('selection_source')=='catalog':
                    r['match']=self._db.choose_id(r['stats']['table'],previous['card']['id'],confirm_mismatch=previous['status']=='manual_selected')
                else:r['match']=self._db.choose(r['stats']['table'],r.get('identity_text',''),previous['card']['id'],confirm_mismatch=previous['status']=='manual_selected',search_name=r.get('manual_card_name'))
            else:r['match']=self._db.match(r['stats']['table'],r.get('identity_text',''),
                 live_version=o.get('live_version_evidence',{}).get('version'))
            observed=version_value(o.get('live_version_evidence',{}).get('version'))
            if previous.get('live_version_override') and observed and card_version(r['match'].get('card',{}))!=observed:
                r['match']['status']='manual_selected';r['match']['live_version_override']=True
            r['issues']=validate_table(r['stats']['table'])
            if o['launch_angle'] is None:r['issues'].append('발사각 확인 필요')
            if not r['enhance']:r['issues'].append('강화/각성 단계 확인 필요')
            r['manual_reviewed']=True
            self._persist([r if old['slot']==slot else old for old in self._records]);self._log(slot+' 선수 정보를 저장했습니다.')
        return self.state()

    def set_editing(self,value):
        with self._lock:
            self._editing=bool(value)
            if not self._editing:self._apply_pending_catalog()
        return True

    def set_database(self,path):
        candidate=Path(path).resolve();db=CardDatabase(candidate)
        if not db.cards:raise ValueError('타자 카드가 들어 있는 카드 JSON을 선택하세요.')
        with self._lock:
            self._idle()
            preferences={**self._preferences,'database':str(candidate),'data_mode':'manual'}
            if self._settings:atomic_json(self._settings,preferences)
            self._preferences=preferences
            self._db=db;self._db_path=candidate;self._manual_database=True;self._revision+=1
            self._log(f'카드 데이터 {len(db.cards):,}장을 연결했습니다.')
        return self.state()

    def save(self):
        with self._lock:self._idle();self._persist(self._records);self._log('수집 결과 JSON과 전체 항목 CSV를 저장했습니다.')
        return self.state()

    def export(self,kind,path):
        with self._lock:
            self._idle()
            if not self._records:raise ValueError('내보낼 선수가 없습니다.')
            path=Path(path).resolve()
            if path.parent==ROOT:raise ValueError('기존 프로그램 폴더 밖에 결과를 저장하세요.')
            if path in (self._original,self._db_path.resolve()):raise ValueError('원본 결과나 카드 데이터와 다른 이름으로 저장하세요.')
            if kind=='xlsx':fill_template(ROOT/'template.xlsx',path,self._records)
            elif kind=='csv':export_csv(self._records,path)
            elif kind=='json':atomic_json(path,{**self._payload,'records':self._normalized(self._records)})
            else:raise ValueError('지원하지 않는 저장 형식입니다.')
            self._last_export=str(path);self._log(path.name+' 저장 완료')
        return self.state()

    def start_scan(self,count=9):
        with self._lock:
            self._idle()
            if self._preview:raise ValueError('미리보기에서는 게임 수집을 실행하지 않습니다.')
            if self._editing:raise ValueError('수정 창을 닫은 뒤 수집을 시작하세요.')
            if count not in (1,9):raise ValueError('주전 9명 또는 DH 1명을 선택하세요.')
            self._busy='scan';self._stop.clear();self._results.mkdir(parents=True,exist_ok=True)
            self._original=None;self._current=None;self._payload={};self._publish([],assets=True)
            db_path=self._db_path
            self._log('LDPlayer 라인업에서 수집을 시작합니다. F8로 중지할 수 있습니다.')
        def work():
            scanner=None
            try:
                scanner=LDScanner(self._results,ROOT,db_path,copy.deepcopy(DEFAULT_PROFILE),self._stop,self._log,count=count)
                def on_record(_):
                    with self._lock:
                        self._current=scanner.last_directory/'scan.json'
                        self._publish(copy.deepcopy(scanner.records),assets=True)
                scanner.on_record=on_record
                directory,records=scanner.run()
                with self._lock:self._current=directory/'scan.json';self._publish(copy.deepcopy(records),assets=True)
            except Exception as error:
                with self._lock:
                    if scanner and getattr(scanner,'last_directory',None):
                        self._current=scanner.last_directory/'scan.json';self._publish(copy.deepcopy(scanner.records),assets=True)
                self._log(('수집 중지: ' if isinstance(error,InterruptedError) else '수집을 완료하지 못했습니다: ')+str(error),'warning')
            finally:
                with self._lock:
                    if self._current and self._current.exists():self._payload=json.loads(self._current.read_text(encoding='utf-8'))
                    self._busy=None;self._revision+=1;self._apply_pending_catalog()
        self._worker=threading.Thread(target=work,daemon=True);self._worker.start()
        return self.state()

    def stop_scan(self):
        self._stop.set();self._log('중지를 요청했습니다. 현재 OCR 처리가 끝나면 멈춥니다.')
        return self.state()

    def capture(self,kind):
        with self._lock:
            self._idle()
            if self._preview:raise ValueError('미리보기에서는 게임을 캡처하지 않습니다.')
            if self._editing:raise ValueError('열린 수정 창을 닫은 뒤 게임에서 단축키를 눌러 주세요.')
            if not self._records or not self._current:raise ValueError('연결할 수집 결과를 먼저 열어 주세요.')
            if kind not in ('potentials','skills'):raise ValueError('지원하지 않는 캡처입니다.')
            # Capture synchronously while the game is foreground, before OCR.
            image=capture_current_game()
            self._busy=kind;records=copy.deepcopy(self._records);db_path=self._db_path
            runtime_skills=self._runtime_skills
            directory=self._current.parent/('potential-manual' if kind=='potentials' else 'skill-manual')/datetime.now().strftime('%Y%m%d-%H%M%S-%f')
            directory.mkdir(parents=True,exist_ok=True);self._revision+=1
            self._log(('F6 잠재력' if kind=='potentials' else 'F7 스킬')+'을 읽고 있습니다. 게임 화면은 움직이지 않습니다.')
        def work():
            try:
                scanner=Scanner(directory,ROOT,db_path,copy.deepcopy(DEFAULT_PROFILE),threading.Event(),lambda _:None)
                if kind=='potentials':
                    snapshot,count=process_potentials(scanner,image,records,directory)
                    counts=snapshot.get('summary',{})
                    summary=' · '.join(f'{dict(pot1="풀스윙",pot2="클러치",pot3="각잠")[key]} {v["recognized"]+v["not_present"]}/9' for key,v in counts.items())
                    message=f'잠재력 {count}칸 반영 · {summary}'
                else:
                    processor=runtime_skills.process_capture if runtime_skills else process_skills
                    snapshot,count,pending=processor(scanner,image,records,directory)
                    message=f'스킬 {count}개 반영 · 확인 필요 {pending}칸'
                with self._lock:
                    self._persist(records,{'manual_potential_captures' if kind=='potentials' else 'manual_skill_captures':snapshot})
                    self._log(message)
            except Exception as error:self._log(str(error),'error')
            finally:
                with self._lock:self._busy=None;self._revision+=1;self._apply_pending_catalog()
        self._worker=threading.Thread(target=work,daemon=True);self._worker.start()
        return self.state()

    def start_hotkeys(self):
        if self._preview:return
        threading.Thread(target=lambda:self.sync_catalog(automatic=True),daemon=True).start()
        from windows_io import U
        def poll():
            down={key:False for key in (0x75,0x76,0x77)}
            while not self._closed.wait(.08):
                for key,kind in ((0x75,'potentials'),(0x76,'skills'),(0x77,'stop')):
                    pressed=bool(U.GetAsyncKeyState(key)&0x8000)
                    if pressed and not down[key]:
                        try:
                            if kind=='stop':
                                if self._busy=='scan':self.stop_scan()
                            elif not self._busy:self.capture(kind)
                        except Exception as error:self._log(str(error),'warning')
                    down[key]=pressed
        threading.Thread(target=poll,daemon=True).start()

    def _catalog_state(self):
        release=self._catalog_release
        return {'source':'manual' if self._manual_database else 'server' if release else 'bundled',
                'version':release.version if release else None,'url':self._catalog_store.manifest_url,
                'counts':release.manifest['counts'] if release else None,
                'published_at':release.manifest.get('published_at') if release else None,
                'checked_at':self._catalog_checked,'syncing':self._catalog_syncing,
                'pending':self._pending_release is not None,'error':self._catalog_error}

    def _activate_catalog(self,release):
        runtime=RuntimeSkills(release.skills,ROOT)
        db=self._db if self._manual_database else CardDatabase(release.cards)
        db.impact_concepts.update(json.loads(release.concepts.read_text(encoding='utf-8')))
        self._db=db
        if not self._manual_database:self._db_path=release.cards
        self._skills=runtime.catalog;self._runtime_skills=runtime;self._catalog_release=release
        self._pending_release=None;self._asset_revision+=1;self._assets_cache.clear();self._revision+=1

    def _apply_pending_catalog(self):
        if self._pending_release and not self._busy and not self._editing:
            self._activate_catalog(self._pending_release)
            self._log('공통 카드·스킬 데이터 업데이트를 적용했습니다.')

    def sync_catalog(self,automatic=False):
        with self._lock:
            if self._catalog_syncing:
                if automatic:return self.state()
                raise ValueError('이미 공통 데이터를 확인하고 있습니다.')
            self._catalog_syncing=True;self._catalog_error=None;self._revision+=1
        try:
            release,changed=self._catalog_store.sync()
            with self._lock:
                self._catalog_checked=datetime.now().isoformat()
                if self._busy or self._editing:
                    if not self._catalog_release or self._catalog_release.version!=release.version:self._pending_release=release
                elif not self._catalog_release or self._catalog_release.version!=release.version:self._activate_catalog(release)
                self._log('공통 카드·스킬 데이터를 내려받았습니다.' if changed else '공통 카드·스킬 데이터가 최신입니다.')
        except Exception as error:
            with self._lock:
                self._catalog_error=str(error)
                self._log('공통 데이터 서버에 연결하지 못해 현재 자료를 유지합니다. '+str(error),'warning')
            if not automatic:raise
        finally:
            with self._lock:self._catalog_syncing=False;self._revision+=1
        return self.state()

    def use_server_catalog(self):
        release=self._catalog_store.current(verify=True)
        if not release:raise ValueError('먼저 공통 데이터를 다운로드해 주세요.')
        with self._lock:
            self._idle();self._manual_database=False
            preferences={**self._preferences,'data_mode':'server'};preferences.pop('database',None)
            if self._settings:atomic_json(self._settings,preferences)
            self._preferences=preferences
            self._activate_catalog(release);self._log('서버의 공통 카드 데이터를 사용합니다.')
        return self.state()

    def set_theme(self,theme):
        if theme not in ('system','light','dark'):raise ValueError('시스템·라이트·다크 중에서 선택하세요.')
        with self._lock:
            preferences={**self._preferences,'theme':theme}
            if self._settings:atomic_json(self._settings,preferences)
            self._preferences=preferences;self._theme=theme;self._revision+=1
        return self.state()

    def assets(self):
        from PIL import Image
        def data_uri(path,portrait=False):
            path=Path(path)
            if not path.is_file():return None
            key=(str(path),path.stat().st_mtime_ns,portrait)
            if key in self._assets_cache:return self._assets_cache[key]
            with Image.open(path) as original:
                image=original.convert('RGBA')
                if portrait:
                    w,h=image.size;image=image.crop((int(w*.29),int(h*.064),int(w*.71),int(h*.405)))
                    image.thumbnail((168,250))
                else:image.thumbnail((48,48))
                stream=io.BytesIO();image.save(stream,format='PNG')
            value='data:image/png;base64,'+base64.b64encode(stream.getvalue()).decode('ascii')
            self._assets_cache[key]=value;return value
        with self._lock:
            portraits={}
            for r in self._records:
                source=r.get('overview',{}).get('source_image')
                if source:
                    uri=data_uri(source,True)
                    if uri:portraits[r['slot']]=uri
            icons={s['name']:data_uri(self._skills.directory/s['icon']) for s in self._skills.batters}
            return {'revision':self._asset_revision,'portraits':portraits,'skills':icons}

    def open_folder(self):
        path=self._current.parent if self._current else self._results
        path.mkdir(parents=True,exist_ok=True);os.startfile(path);return True

    def open_evidence(self,slot,kind='stats'):
        with self._lock:
            r=self._require_record(slot)
            path=r.get('overview' if kind=='overview' else 'stats',{}).get('source_image')
            if not path or not Path(path).is_file():raise ValueError('원본 이미지 경로를 찾을 수 없습니다.')
            os.startfile(Path(path));return True

    def close(self):
        self._closed.set();self._stop.set()


def legacy_integrity():
    baseline=json.loads((Path(__file__).parent/'legacy-integrity.json').read_text(encoding='utf-8-sig'))
    return [entry['name'] for entry in baseline if not (ROOT/entry['name']).is_file() or
            hashlib.sha256((ROOT/entry['name']).read_bytes()).hexdigest().upper()!=entry['sha256']]
