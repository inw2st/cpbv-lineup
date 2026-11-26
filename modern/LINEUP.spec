# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import sys

modern=Path(SPECPATH)
engine=modern.parent
data_names=['ocr.ps1','template.xlsx','digits.npz','overview_digits.npz','potential_letters.npz','impact-concepts.json','skill_reader.py']
datas=[(str(engine/name),'.') for name in data_names]
datas.extend([(str(engine/'resources/awakening'/f'{level}.png'),'resources/awakening') for level in range(1,10)])
datas.append((str(modern/'web-build'),'web-build'))
datas.append((str(modern/'resources/live-badges'),'resources/live-badges'))
# This Python runtime ships an SSL trust-policy data file beside ssl.py.
# Preserve it in the frozen app; HTTPS verification must stay enabled.
ssl_policy=Path(sys.base_prefix)/'Lib/codex-rejected-cas.pem'
if ssl_policy.exists():datas.append((str(ssl_policy),'.'))

a=Analysis(
    [str(modern/'desktop.py')],
    pathex=[str(modern),str(engine)],binaries=[],datas=datas,
    hiddenimports=['webview.platforms.edgechromium','webview.platforms.winforms','runtime_skills','diagnostics'],
    hookspath=[],hooksconfig={},runtime_hooks=[],
    excludes=['tkinter','PyQt5','PyQt6','PySide2','PySide6','gi','cefpython3'],
    noarchive=False,optimize=1,
)
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='LINEUP',debug=False,
        bootloader_ignore_signals=False,strip=False,upx=False,console=False,
        disable_windowed_traceback=False,argv_emulation=False,target_arch=None,
        codesign_identity=None,entitlements_file=None)
coll=COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='LINEUP')
