# LINEUP · 컴프야 라인업 스캐너

Windows용 LDPlayer 라인업 판독 도구입니다. Python 판독 엔진과 React/TypeScript 화면을 pywebview로 연결합니다. 현재 버전은 **1.3.0**입니다.

[Windows ZIP 다운로드](https://github.com/inw2st/cpbv-lineup/releases/tag/LINEUP)

## 기능

- 주전 타자 9명을 DH → C → 1B → 2B → 3B → SS → LF → CF → RF 순서로 수집합니다.
- 카드명과 기본 능력치 6개를 공통 카드 데이터와 대조합니다.
- 라이브 V1·V2·V3 배지를 원본 이미지와 비교하고 카드 선택 화면에서 버전을 필터링합니다.
- 훈련·강화·특훈·각성·세트덱·시너지·포지션 특훈을 분리해 저장합니다.
- 잠재력은 F6, 스킬은 F7로 사용자가 연 화면을 판독하며 F8로 중지합니다.
- 카드 선택·수정, JSON/CSV 저장, 웹 덱 관리기용 XLSX 내보내기, 라이트/다크 테마를 제공합니다.

## 소스에서 실행

Windows 64비트, Python 3.12, Node.js 22.12 이상, Windows 한국어 OCR,
Microsoft Edge WebView2 Runtime이 필요합니다. LDPlayer는 세로 1080×1920 / 480 DPI 설정을 기준으로 합니다.

저장소를 내려받은 뒤 루트 폴더의 PowerShell에서 실행하세요.

```powershell
py -3.12 -m venv modern/.venv
modern/.venv/Scripts/python.exe -m pip install -r modern/requirements.txt
npm.cmd --prefix modern ci
npm.cmd --prefix modern run build
modern/.venv/Scripts/python.exe modern/desktop.py
```

이후에는 `run.cmd`로 실행할 수 있습니다. 최초 실행 시 공통 카드·스킬 자료를 받으므로 인터넷 연결이 필요합니다. 내려받은 마지막 정상 자료는 로컬 캐시에 보관합니다. 별도 카드 JSON은 선택 사항이며 `LINEUP_CARD_DATABASE` 환경 변수나 앱 설정으로 지정할 수 있습니다.

## 실행 파일 빌드

```powershell
modern/.venv/Scripts/python.exe -m pip install -r modern/requirements-build.txt
npm.cmd --prefix modern run build
modern/.venv/Scripts/python.exe modern/build_release.py
```

`modern/releases/LINEUP-1.3.0-windows-x64.zip`과 SHA-256 파일을 만듭니다.
ZIP 전체를 압축 해제하고 `LINEUP/LINEUP.exe`를 실행합니다. `_internal` 폴더가 함께 필요합니다.
이 저장소에는 개발용 `.venv`, `node_modules`, 빌드 산출물, 개인 수집 결과를 포함하지 않습니다.
PyInstaller 빌드 시간·환경 차이 때문에 직접 빌드한 EXE가 배포 EXE와 바이트 단위로 같다고 보장하지 않습니다.

## 코드 검토 안내

| 위치 | 역할 |
| --- | --- |
| `windows_io.py` | 지정 게임 창의 캡처·마우스 입력, 프로세스 권한 수준 확인 |
| `scanner.py`, `ocr.ps1` | Windows 내장 OCR 실행 및 결과 저장 |
| `ldplayer_scanner.py` | LDPlayer 내 주전 타자 화면 이동 |
| `core.py`, `digit_reader.py` | 카드 대조·능력치 판독·XLSX 작성 |
| `modern/live_cards.py` | 라이브 배지 인식과 버전별 카드 매칭 |
| `modern/catalog_store.py` | 공통 데이터 다운로드·해시/경로/스키마 검증 |
| `modern/service.py`, `desktop.py` | 작업 상태·파일 저장·F6/F7/F8·데스크톱 API |
| `modern/src/` | React 화면과 테마 |
| `modern/LINEUP.spec`, `build_release.py` | 배포 파일 구성과 로컬 빌드 |

앱은 수집을 시작하면 대상 게임 창을 앞으로 가져오고 마우스를 이동·클릭합니다.
Windows `GetAsyncKeyState`로 F6/F7/F8 상태를 확인합니다. 일반 키 입력 기록 기능은 없습니다.
프로세스 권한 수준 확인에는 `OpenProcess`/토큰 조회를 사용하며 게임 메모리 덤프나 DLL 주입 도구는 이 앱에 포함하지 않습니다.
OCR은 PowerShell을 통해 Windows 내장 엔진을 호출합니다. 한국어 OCR이 준비돼 있어야 합니다.

공통 데이터 주소는 `https://cpbv-app-data.minwestt.workers.dev/v1/manifest.json`입니다.
카드·스킬·아이콘·판독 자료를 HTTPS GET으로 내려받습니다. 내려받은 JSON/PNG/NPZ를 판독 데이터로 사용하며 원격 Python 코드를 실행하지 않습니다.
개인 라인업·캡처를 업로드하는 API는 없습니다. 수집 결과는 `Documents/CPBV 새UI 수집`, 설정·공통 캐시는 `%LOCALAPPDATA%/CPBVRosterDesktop`에 저장합니다.

## 검증

```powershell
cd modern
.venv/Scripts/python.exe -m unittest test_live_cards test_public_security -v
node --test tests/theme.test.mjs
.venv/Scripts/python.exe desktop.py --self-check --online --report self-check.json
```

내부 진단은 게임 창이나 GUI를 조작하지 않습니다. `--online`은 임시 폴더로 공통 자료를 내려받아 검사합니다.
개인 캡처를 요구하는 회귀 테스트는 기본적으로 건너뜁니다. 직접 확인하려면 `LINEUP_TEST_CAPTURES`를 지정합니다.
V3는 실제 저장된 게임 캡처로 검증했으며 V1/V2는 원본 배지를 합성한 테스트로 검증했습니다. 모든 화면 배율·환경에서의 판독 성공을 보장하지 않습니다.

## 라이선스와 배포

직접 작성한 소스 코드는 [MIT](LICENSE)로 공개합니다. 게임 유래 자료와 의존성은 [별도 고지](THIRD_PARTY_NOTICES.md)를 확인하세요.
일반 사용을 위해 GitHub 로그인, Cloudflare 계정이나 서비스 관리 키가 필요하지 않습니다.
소스 공개는 동작 검토에 도움이 되지만 백신 오탐 방지나 코드 서명을 대신하지 않습니다.
