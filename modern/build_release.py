"""Create a portable ZIP locally. No upload, credential access or GUI actions."""
import ast,hashlib,importlib.metadata,json,os,shutil,subprocess,sys,zipfile
from datetime import datetime
from pathlib import Path

MODERN=Path(__file__).resolve().parent


def version():
    tree=ast.parse((MODERN/'service.py').read_text(encoding='utf-8'))
    for item in tree.body:
        if isinstance(item,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='VERSION' for t in item.targets):return ast.literal_eval(item.value)
    raise RuntimeError('App version missing')


def run():
    tag=version();stamp=datetime.now().strftime('%Y%m%d-%H%M%S')
    build=MODERN/'build'/stamp;dist=build/'dist'
    subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm','--clean','--distpath',str(dist),'--workpath',str(build/'work'),str(MODERN/'LINEUP.spec')],cwd=MODERN,check=True)
    app=dist/'LINEUP'
    if not (app/'LINEUP.exe').is_file():raise RuntimeError('Executable was not built')
    packages=['pywebview','numpy','Pillow','pythonnet','clr_loader','bottle','cffi','pycparser','typing_extensions','proxy_tools']
    license_dir=app/'LICENSES';license_dir.mkdir()
    inventory=[]
    for name in packages:
        package=importlib.metadata.distribution(name)
        inventory.append({'name':name,'version':package.version})
        for file in package.files or []:
            if '.dist-info/' in str(file).replace('\\','/') and any(part in str(file).lower() for part in ('license','copying','notice','authors')):
                source=Path(package.locate_file(file))
                if source.is_file():
                    target=license_dir/name/source.name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
    python_license=Path(sys.base_prefix)/'LICENSE.txt'
    if python_license.exists():shutil.copy2(python_license,license_dir/'Python-LICENSE.txt')
    for name in ('react','react-dom','lucide-react'):
        package_dir=MODERN/'node_modules'/name
        metadata=json.loads((package_dir/'package.json').read_text(encoding='utf-8'))
        inventory.append({'name':name,'version':metadata['version']})
        for source in package_dir.glob('LICENSE*'):
            target=license_dir/name/source.name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
    (license_dir/'packages.json').write_text(json.dumps(inventory,ensure_ascii=False,indent=2),encoding='utf-8')
    (app/'시작하기.txt').write_text(f'''LINEUP v{tag} · Windows 64비트

1. ZIP을 전부 압축 해제한 뒤 LINEUP.exe를 실행하세요.
2. LINEUP.exe 옆의 _internal 폴더도 함께 있어야 합니다.
3. 최초 실행에는 인터넷이 필요합니다. 공통 카드·스킬 자료를 무료 데이터 서버에서 받습니다.
4. LDPlayer 타자 라인업에서 수집을 시작하세요. 잠재력은 F6, 스킬은 F7, 수집 중지는 F8입니다.
5. 다른 스캐너를 동시에 실행하면 단축키가 중복될 수 있으므로 한 프로그램만 사용하세요.
6. 사이드바의 시스템 / 라이트 / 다크 버튼으로 테마를 선택할 수 있습니다.
7. Windows 한국어 OCR과 Microsoft Edge WebView2 Runtime이 필요합니다.

Python·Node.js·카드 JSON을 따로 설치하거나 준비할 필요는 없습니다.
개인 수집 결과는 Documents/CPBV 새UI 수집, 설정과 공통 자료는 로컬 앱 데이터에 저장됩니다.
카드·스킬 다운로드에는 Cloudflare 계정이나 서비스 관리 키가 필요하지 않습니다.
개인 라인업과 캡처 이미지는 공통 데이터 서버로 전송하지 않습니다.

이 배포본은 코드 서명을 하지 않았으며, 다른 PC에서 게임 수집과 OCR의 실사용 확인이 필요합니다.
공통 자료와 앱 업데이트는 별도입니다. 카드·스킬은 앱에서 갱신하고, 프로그램은 새 ZIP으로 교체합니다.
''',encoding='utf-8-sig')
    relative_files=[p.relative_to(app).as_posix() for p in app.rglob('*') if p.is_file()]
    forbidden=('.wrangler/','node_modules/','.venv/','runtime.log','settings.json','scan.json','default.toml','legacy-integrity.json')
    if any(any(part in name for part in forbidden) for name in relative_files):raise RuntimeError('A development/private file entered the bundle')
    if any(name.endswith('/cards.json') or name=='cards.json' or '/skills/skills.json' in name for name in relative_files):raise RuntimeError('Common catalogs should be downloaded, not packaged')
    for name in ['_internal/skill_reader.py','_internal/web-build/index.html','_internal/template.xlsx']:
        if name not in relative_files:raise RuntimeError('Missing packaged resource: '+name)
    health_path=build/'bundle-self-check.json'
    subprocess.run([str(app/'LINEUP.exe'),'--self-check','--report',str(health_path)],check=True,timeout=60,creationflags=subprocess.CREATE_NO_WINDOW)
    health=json.loads(health_path.read_text(encoding='utf-8'))
    if not health.get('ok'):raise RuntimeError('Packaged diagnostics failed: '+str(health.get('errors')))
    releases=MODERN/'releases';releases.mkdir(exist_ok=True)
    destination=releases/f'LINEUP-{tag}-windows-x64.zip'
    if destination.exists():
        archived=releases/'previous-builds';archived.mkdir(exist_ok=True)
        destination.rename(archived/(destination.stem+'-'+stamp+destination.suffix))
        old_hash=destination.with_suffix('.sha256')
        if old_hash.exists():old_hash.rename(archived/(destination.stem+'-'+stamp+'.sha256'))
    with zipfile.ZipFile(destination,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for path in sorted(app.rglob('*')):
            if path.is_file():archive.write(path,Path('LINEUP')/path.relative_to(app))
    report={'version':tag,'exe':str(app/'LINEUP.exe'),'zip':str(destination),'bytes':destination.stat().st_size,
            'sha256':hashlib.sha256(destination.read_bytes()).hexdigest(),'files':len(relative_files),
            'private_file_check':True,'catalogs_downloaded_separately':True,'offline_self_check':True}
    (releases/'latest-build.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    destination.with_suffix('.sha256').write_text(report['sha256']+'  '+destination.name+'\n',encoding='ascii')
    print(json.dumps(report,ensure_ascii=True))


if __name__=='__main__':run()
