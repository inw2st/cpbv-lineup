"""Versioned public catalog download. No player records or screenshots are sent.

Each release is validated in a staging directory, then activated by one atomic
pointer update. A failed download never replaces the last usable release.
"""
from __future__ import annotations
import hashlib,io,json,os,re,shutil,tempfile,threading,zipfile
from dataclasses import dataclass
from pathlib import Path,PurePosixPath
from urllib.parse import urljoin,urlsplit
from urllib.request import Request,urlopen
from datetime import datetime,timezone

DEFAULT_MANIFEST='https://cpbv-app-data.minwestt.workers.dev/v1/manifest.json'
DEFAULT_CACHE=Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'CPBVRosterDesktop'/'catalog'
MAX_DOWNLOAD=24*1024*1024
MAX_EXPANDED=64*1024*1024
_VERSIONS=re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9._-]{0,79}$')


def write_json(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,temporary=tempfile.mkstemp(prefix='.catalog-',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as stream:
            json.dump(data,stream,ensure_ascii=False,indent=2);stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)


@dataclass(frozen=True)
class CatalogRelease:
    version:str
    directory:Path
    manifest:dict

    @property
    def cards(self):return self.directory/'cards.json'
    @property
    def skills(self):return self.directory/'skills'
    @property
    def concepts(self):return self.directory/'impact-concepts.json'


def validate_payload(directory,manifest=None):
    directory=Path(directory)
    cards=json.loads((directory/'cards.json').read_text(encoding='utf-8-sig'))
    if not isinstance(cards,list) or not 1<=len(cards)<=100000:raise ValueError('카드 데이터 개수가 올바르지 않습니다.')
    ids=set();batters=0
    for card in cards:
        if not isinstance(card,dict) or type(card.get('id')) is not int or card['id'] in ids:raise ValueError('카드 ID가 없거나 중복됐습니다.')
        ids.add(card['id'])
        if not isinstance(card.get('name'),str) or not 1<=len(card['name'])<=100:raise ValueError('카드 이름이 올바르지 않습니다.')
        if card.get('role')=='타자':
            batters+=1
            if type(card.get('kind')) is not int or card['kind'] not in range(7):raise ValueError('카드 종류가 올바르지 않습니다.')
            stats=card.get('stats',{})
            if any(type(stats.get(k)) is not int for k in ('POWER','CONTACT','VISION','DISCIPLINE','RUNNING_SPEED','FIELDING')):raise ValueError('카드 기본 능력치가 누락됐습니다.')
    if not batters:raise ValueError('타자 카드가 없습니다.')
    skills=json.loads((directory/'skills/skills.json').read_text(encoding='utf-8'))
    if not isinstance(skills,list) or not 1<=len(skills)<=2000:raise ValueError('스킬 목록이 올바르지 않습니다.')
    ids=set();names=set();batter_skills=0
    from PIL import Image
    for skill in skills:
        if type(skill.get('id')) is not int or skill['id'] in ids:raise ValueError('스킬 ID가 없거나 중복됐습니다.')
        ids.add(skill['id'])
        name=skill.get('name');role=skill.get('role')
        if not isinstance(name,str) or not 1<=len(name)<=100 or role not in ('batter','pitcher') or (role,name) in names:raise ValueError('스킬 이름 또는 구분이 올바르지 않습니다.')
        names.add((role,name));batter_skills+=role=='batter'
        icon=skill.get('icon','')
        if not re.fullmatch(r'icons/icon_skill_\d+\.png',icon):raise ValueError('스킬 아이콘 경로가 올바르지 않습니다.')
        with Image.open(directory/'skills'/icon) as image:
            if image.width>1024 or image.height>1024:raise ValueError('스킬 아이콘이 너무 큽니다.')
            image.verify()
    if not batter_skills:raise ValueError('타자 스킬이 없습니다.')
    import numpy as np
    for name,required in [('level-font.npz',{'labels','images'}),('position-font.npz',{'labels','images'})]:
        with np.load(directory/'skills'/name,allow_pickle=False) as bank:
            if not required.issubset(bank.files):raise ValueError('판독 글꼴 자료가 누락됐습니다.')
            for key in bank.files:
                values=bank[key]
                if values.dtype.hasobject or values.size>2_000_000:raise ValueError('판독 자료 형식이 올바르지 않습니다.')
    concepts=json.loads((directory/'impact-concepts.json').read_text(encoding='utf-8'))
    if not isinstance(concepts,dict) or any(not isinstance(v,str) for v in concepts.values()):raise ValueError('임팩트 컨셉 자료가 올바르지 않습니다.')
    counts={'cards':len(cards),'batters':batters,'skills':len(skills),'batter_skills':batter_skills,'pitcher_skills':len(skills)-batter_skills}
    if manifest and any(manifest.get('counts',{}).get(key)!=value for key,value in counts.items()):raise ValueError('서버의 자료 개수와 실제 내용이 다릅니다.')
    return counts


class CatalogStore:
    def __init__(self,cache=DEFAULT_CACHE,manifest_url=DEFAULT_MANIFEST,fetcher=None):
        self.cache=Path(cache);self.manifest_url=manifest_url;self._fetcher=fetcher or self._fetch
        self._sync_lock=threading.Lock()

    def _fetch(self,url,limit):
        parsed=urlsplit(url)
        if parsed.scheme!='https' or parsed.username or parsed.password:raise ValueError('HTTPS 데이터 서버 주소가 필요합니다.')
        request=Request(url,headers={'User-Agent':'CPBVRosterDesktop/1','Accept':'application/json,application/zip','Cache-Control':'no-cache'})
        with urlopen(request,timeout=15) as response:
            final=urlsplit(response.geturl())
            if final.scheme!='https' or final.netloc!=parsed.netloc:raise ValueError('데이터 서버가 다른 주소로 이동했습니다.')
            length=response.headers.get('Content-Length')
            if length and int(length)>limit:raise ValueError('서버 데이터가 허용 크기를 초과했습니다.')
            data=response.read(limit+1)
        if len(data)>limit:raise ValueError('서버 데이터가 허용 크기를 초과했습니다.')
        return data

    def current(self,verify=False):
        try:
            pointer=json.loads((self.cache/'current.json').read_text(encoding='utf-8'))
            version=pointer['version']
            if not isinstance(version,str) or not _VERSIONS.fullmatch(version):return None
            directory=self.cache/'releases'/version
            manifest=json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
            if manifest.get('version')!=version or manifest.get('schema_version')!=1:return None
            if not (directory/'cards.json').is_file() or not (directory/'skills/skills.json').is_file():return None
            if verify:
                expected=manifest.get('files',{})
                if not expected:return None
                for name,digest in expected.items():
                    path=self._safe_path(name)
                    if hashlib.sha256((directory/path).read_bytes()).hexdigest()!=digest:return None
                validate_payload(directory,manifest)
            return CatalogRelease(version,directory,manifest)
        except (OSError,ValueError,KeyError,TypeError,zipfile.BadZipFile):return None

    @staticmethod
    def _safe_path(name):
        path=PurePosixPath(name)
        if '\\' in name or path.is_absolute() or '..' in path.parts or ':' in name or not path.parts:raise ValueError('자료에 허용하지 않는 경로가 있습니다.')
        valid=name in ('cards.json','impact-concepts.json','skills/skills.json','skills/level-font.npz','skills/position-font.npz') or re.fullmatch(r'skills/icons/icon_skill_\d+\.png',name)
        if not valid:raise ValueError('허용하지 않는 배포 파일입니다: '+name)
        return Path(*path.parts)

    def sync(self):
        if not self._sync_lock.acquire(blocking=False):raise ValueError('이미 데이터를 갱신하고 있습니다.')
        staging=None
        try:
            raw=self._fetcher(self.manifest_url,256*1024)
            manifest=json.loads(raw.decode('utf-8-sig'));version=manifest.get('version')
            if manifest.get('schema_version')!=1 or not isinstance(version,str) or not _VERSIONS.fullmatch(version):raise ValueError('지원하지 않는 데이터 버전입니다.')
            files=manifest.get('files',{})
            if not isinstance(files,dict) or not 5<=len(files)<=300:raise ValueError('배포 파일 목록이 올바르지 않습니다.')
            for name,digest in files.items():
                self._safe_path(name)
                if not isinstance(digest,str) or not re.fullmatch(r'[a-f0-9]{64}',digest):raise ValueError('배포 파일 검증 정보가 올바르지 않습니다.')
            current=self.current(verify=True)
            if current and current.version==version:
                if current.manifest.get('files')!=files:raise ValueError('같은 버전의 데이터 내용이 변경됐습니다.')
                return current,False
            bundle=manifest.get('bundle',{});relative=bundle.get('path','')
            if not isinstance(relative,str) or relative.startswith(('/','\\')) or '..' in PurePosixPath(relative).parts:raise ValueError('다운로드 경로가 올바르지 않습니다.')
            url=urljoin(self.manifest_url,relative)
            if urlsplit(url).netloc!=urlsplit(self.manifest_url).netloc or urlsplit(url).scheme!=urlsplit(self.manifest_url).scheme:raise ValueError('배포 자료는 같은 데이터 서버에서 받아야 합니다.')
            if type(bundle.get('size')) is not int or not 1<=bundle['size']<=MAX_DOWNLOAD:raise ValueError('다운로드 크기가 올바르지 않습니다.')
            payload=self._fetcher(url,MAX_DOWNLOAD)
            if len(payload)!=bundle['size'] or hashlib.sha256(payload).hexdigest()!=bundle.get('sha256'):raise ValueError('다운로드한 자료의 무결성을 확인하지 못했습니다.')
            self.cache.mkdir(parents=True,exist_ok=True)
            staging=Path(tempfile.mkdtemp(prefix='.stage-',dir=self.cache))
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                members=archive.infolist()
                if len(members)!=len(files) or sum(m.file_size for m in members)>MAX_EXPANDED:raise ValueError('압축 자료의 크기 또는 파일 개수가 올바르지 않습니다.')
                seen=set()
                for entry in members:
                    name=entry.filename;path=self._safe_path(name)
                    if name in seen or name not in files or entry.file_size>32*1024*1024 or ((entry.external_attr>>16)&0o170000)==0o120000:raise ValueError('압축 자료에 중복되거나 허용하지 않는 파일이 있습니다.')
                    seen.add(name);data=archive.read(entry)
                    if hashlib.sha256(data).hexdigest()!=files[name]:raise ValueError('배포 파일 내용이 검증 정보와 다릅니다.')
                    target=staging/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
            validate_payload(staging,manifest)
            write_json(staging/'manifest.json',manifest)
            destination=self.cache/'releases'/version;destination.parent.mkdir(parents=True,exist_ok=True)
            if destination.exists():
                # An invalid cached version is quarantined instead of being
                # overwritten while another operation might still use it.
                destination.rename(destination.with_name(version+'.invalid-'+datetime.now().strftime('%H%M%S%f')))
            staging.rename(destination);staging=None
            write_json(self.cache/'current.json',{'version':version,'checked_at':datetime.now(timezone.utc).isoformat()})
            return CatalogRelease(version,destination,manifest),True
        finally:
            if staging and staging.exists():shutil.rmtree(staging)
            self._sync_lock.release()
