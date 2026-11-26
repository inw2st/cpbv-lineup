"""Headless bundle verification. Never opens a window or accesses the game."""
from pathlib import Path
import json,sys,tempfile
import numpy as np


def self_check(online=False):
    from service import ROOT,VERSION
    from catalog_store import CatalogStore
    from runtime_skills import RuntimeSkills
    result={'ok':False,'version':VERSION,'frozen':bool(getattr(sys,'frozen',False)),'checks':{},'errors':[]}
    required=['ocr.ps1','template.xlsx','digits.npz','overview_digits.npz','potential_letters.npz','impact-concepts.json','skill_reader.py']
    for name in required:
        exists=(ROOT/name).is_file();result['checks'][name]=exists
        if not exists:result['errors'].append('Missing resource: '+name)
    frontend=Path(__file__).resolve().parent/'web-build/index.html'
    result['checks']['frontend']=frontend.is_file()
    if not frontend.is_file():result['errors'].append('Missing frontend')
    for name in ('digits.npz','overview_digits.npz','potential_letters.npz'):
        try:
            with np.load(ROOT/name,allow_pickle=False) as bank:
                for key in bank.files:assert not bank[key].dtype.hasobject
        except Exception as error:result['errors'].append(name+': '+str(error))
    result['checks']['awakening_sprites']=all((ROOT/'resources/awakening'/f'{i}.png').is_file() for i in range(1,10))
    if not result['checks']['awakening_sprites']:result['errors'].append('Missing awakening sprites')
    from live_cards import match_live_badge
    result['checks']['live_badge_templates']=all(
        (Path(__file__).resolve().parent/'resources/live-badges'/f'{group}-{version}.png').is_file()
        for group in ('live','year') for version in (1,2,3))
    if not result['checks']['live_badge_templates']:result['errors'].append('Missing live version badges')
    else:
        try:
            from PIL import Image
            versions=[]
            for version in (1,2,3):
                image=Image.new('RGB',(556,989),'black')
                with Image.open(Path(__file__).resolve().parent/'resources/live-badges'/f'live-{version}.png') as source:
                    sprite=source.resize((97,30),Image.Resampling.LANCZOS)
                    image.paste(sprite,(286,338),sprite)
                versions.append(match_live_badge(image)['version'])
            result['checks']['live_badge_reader']=versions==[1,2,3]
            if versions!=[1,2,3]:result['errors'].append('Live badge reader did not recognize bundled sprites')
        except Exception as error:result['errors'].append('Live badge reader: '+str(error))
    try:
        import ssl
        context=ssl.create_default_context()
        result['checks']['https_verification']=context.check_hostname and context.verify_mode==ssl.CERT_REQUIRED
        if not result['checks']['https_verification']:result['errors'].append('HTTPS verification is disabled')
    except Exception as error:result['errors'].append('SSL initialization: '+str(error))
    try:
        import webview
        result['checks']['webview_package']=True
        if getattr(sys,'frozen',False):
            dlls=list(Path(webview.__file__).resolve().parent.rglob('*.dll'))
            result['checks']['webview_native_libraries']=bool(dlls)
            if not dlls:result['errors'].append('Missing WebView native libraries')
    except Exception as error:result['errors'].append('WebView import: '+str(error))
    if online:
        try:
            with tempfile.TemporaryDirectory() as directory:
                release,_=CatalogStore(directory).sync()
                runtime=RuntimeSkills(release.skills,ROOT)
                result['checks']['online_catalog']=release.manifest['counts']
                result['checks']['runtime_skill_reader']=len(runtime.catalog.batter_names)==70
                result['checks']['skill_reader_source_present']=(ROOT/'skill_reader.py').is_file()
        except Exception as error:
            import traceback
            result['errors'].append('Online catalog: '+str(error))
            result['online_error_traceback']=traceback.format_exc()
    result['ok']=not result['errors']
    return result
