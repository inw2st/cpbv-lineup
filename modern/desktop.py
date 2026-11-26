"""Standalone React + WebView2 launcher; the Tk launcher is untouched."""
import argparse,json,logging,sys
from pathlib import Path
from service import RosterService,ROOT,VERSION,DEFAULT_SETTINGS
from catalog_store import CatalogStore


class DesktopApi:
    def __init__(self,service):self._service=service;self._window=None

    def _reply(self,call,*args):
        try:return {'ok':True,'data':call(*args)}
        except Exception as error:
            logging.getLogger('cpbv').exception('Desktop operation failed')
            return {'ok':False,'error':str(error)}

    def get_state(self,revision=-1):return self._reply(self._service.state,revision)
    def get_options(self):return self._reply(self._service.options)
    def get_assets(self):return self._reply(self._service.assets)
    def set_theme(self,theme):return self._reply(self._service.set_theme,theme)
    def sync_catalog(self):return self._reply(self._service.sync_catalog)
    def use_server_catalog(self):return self._reply(self._service.use_server_catalog)
    def set_editing(self,value):return self._reply(self._service.set_editing,value)
    def save(self):return self._reply(self._service.save)
    def start_scan(self,count=9):return self._reply(self._service.start_scan,count)
    def stop_scan(self):return self._reply(self._service.stop_scan)
    def catalog(self,slot,filters):return self._reply(self._service.catalog,slot,filters)
    def select_card(self,slot,card_id,confirmed,version):return self._reply(self._service.select_card,slot,card_id,confirmed,version)
    def update_record(self,slot,values,version):return self._reply(self._service.update_record,slot,values,version)
    def open_folder(self):return self._reply(self._service.open_folder)
    def open_evidence(self,slot,kind='stats'):return self._reply(self._service.open_evidence,slot,kind)

    def choose_result(self):
        def run():
            import webview
            result=self._window.create_file_dialog(webview.FileDialog.OPEN,directory=str(self._service._results),allow_multiple=False,file_types=('수집 결과 (*.json)',))
            return self._service.load(result[0]) if result else None
        return self._reply(run)

    def choose_database(self):
        def run():
            import webview
            result=self._window.create_file_dialog(webview.FileDialog.OPEN,directory=str(ROOT),allow_multiple=False,file_types=('카드 데이터 (*.json)',))
            return self._service.set_database(result[0]) if result else None
        return self._reply(run)

    def export_dialog(self,kind):
        def run():
            import webview
            if kind not in ('xlsx','csv','json'):raise ValueError('지원하지 않는 저장 형식입니다.')
            if kind=='xlsx':
                issues=self._service.state()['export_issues']
                if issues:raise ValueError('\n'.join(issues))
            filename={'xlsx':'라인업_사이트가져오기.xlsx','csv':'라인업_전체능력치.csv','json':'scan.json'}[kind]
            self._service._results.mkdir(parents=True,exist_ok=True)
            result=self._window.create_file_dialog(webview.FileDialog.SAVE,directory=str(self._service._results),save_filename=filename,file_types=(f'{kind.upper()} (*.{kind})',))
            if not result:return None
            path=Path(result[0] if isinstance(result,(list,tuple)) else result)
            if path.suffix.lower()!='.'+kind:path=path.with_suffix('.'+kind)
            return self._service.export(kind,path)
        return self._reply(run)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--preview',action='store_true');parser.add_argument('--load');parser.add_argument('--debug',action='store_true')
    parser.add_argument('--self-check',action='store_true');parser.add_argument('--online',action='store_true');parser.add_argument('--report')
    args=parser.parse_args();directory=Path(__file__).resolve().parent
    if args.self_check:
        from diagnostics import self_check
        result=self_check(online=args.online)
        if args.report:Path(args.report).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        elif sys.stdout:print(json.dumps(result,ensure_ascii=True))
        if not result['ok']:raise SystemExit(1)
        return
    DEFAULT_SETTINGS.parent.mkdir(parents=True,exist_ok=True)
    logging.basicConfig(filename=str(DEFAULT_SETTINGS.parent/'runtime.log'),encoding='utf-8',level=logging.INFO)
    import webview
    options={'preview':args.preview}
    if args.preview:options.update(results=directory/'validation'/'preview-results',settings=None,catalog_store=CatalogStore())
    service=RosterService(**options)
    if args.load:service.load(args.load)
    api=DesktopApi(service)
    page=directory/'web-build'/'index.html'
    if not page.exists():raise RuntimeError('화면 빌드가 없습니다. modern 폴더에서 npm run build를 먼저 실행하세요.')
    window=webview.create_window('LINEUP · 라인업 스캐너'+(' · 미리보기' if args.preview else ''),str(page),
                                 js_api=api,width=1500,height=980,min_size=(1060,740),background_color='#F6F7FB',text_select=True)
    api._window=window
    window.events.closed+=service.close
    try:webview.start(service.start_hotkeys,gui='edgechromium',debug=args.debug)
    finally:service.close()


if __name__=='__main__':
    try:main()
    except Exception as error:
        import ctypes
        logging.exception('Desktop startup failed')
        ctypes.windll.user32.MessageBoxW(0,str(error),'라인업 새 UI 실행 오류',0x10)
        raise
