"""Windows-only application adapter. Used by the distributed scanner itself."""
import ctypes
from ctypes import wintypes as W
import time
from PIL import ImageGrab, ImageChops, ImageStat

U=ctypes.WinDLL('user32',use_last_error=True)
try: U.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
except (AttributeError,OSError): pass
U.GetForegroundWindow.restype=W.HWND
U.IsWindow.argtypes=[W.HWND];U.IsWindow.restype=W.BOOL
U.GetClientRect.argtypes=[W.HWND,ctypes.POINTER(W.RECT)]
U.ClientToScreen.argtypes=[W.HWND,ctypes.POINTER(W.POINT)]
U.SetForegroundWindow.argtypes=[W.HWND]
U.GetWindowTextW.argtypes=[W.HWND,W.LPWSTR,ctypes.c_int]
U.GetWindowTextLengthW.argtypes=[W.HWND]
U.IsWindowVisible.argtypes=[W.HWND]
U.SetCursorPos.argtypes=[ctypes.c_int,ctypes.c_int]
U.GetAsyncKeyState.argtypes=[ctypes.c_int];U.GetAsyncKeyState.restype=ctypes.c_short

class MouseInput(ctypes.Structure):
    _fields_=[('dx',W.LONG),('dy',W.LONG),('mouseData',W.DWORD),('dwFlags',W.DWORD),('time',W.DWORD),('dwExtraInfo',ctypes.c_size_t)]
class InputUnion(ctypes.Union):
    _fields_=[('mi',MouseInput),('padding',ctypes.c_byte*32)]
class Input(ctypes.Structure):
    _anonymous_=('data',)
    _fields_=[('type',W.DWORD),('data',InputUnion)]
U.SendInput.argtypes=[W.UINT,ctypes.POINTER(Input),ctypes.c_int];U.SendInput.restype=W.UINT

def elevated(pid):
    k=ctypes.WinDLL('kernel32',use_last_error=True);a=ctypes.WinDLL('advapi32',use_last_error=True)
    k.OpenProcess.argtypes=[W.DWORD,W.BOOL,W.DWORD];k.OpenProcess.restype=W.HANDLE
    k.CloseHandle.argtypes=[W.HANDLE]
    a.OpenProcessToken.argtypes=[W.HANDLE,W.DWORD,ctypes.POINTER(W.HANDLE)]
    a.GetTokenInformation.argtypes=[W.HANDLE,ctypes.c_int,W.LPVOID,W.DWORD,ctypes.POINTER(W.DWORD)]
    process=k.OpenProcess(0x1000,False,pid)
    if not process:return None
    token=W.HANDLE()
    try:
        if not a.OpenProcessToken(process,8,ctypes.byref(token)):return None
        value=W.DWORD();length=W.DWORD()
        return bool(value.value) if a.GetTokenInformation(token,20,ctypes.byref(value),4,ctypes.byref(length)) else None
    finally:
        if token:k.CloseHandle(token)
        k.CloseHandle(process)

def error_text(code):
    return ctypes.FormatError(code).strip() if code else '추가 오류 코드가 제공되지 않았습니다.'

class GameWindow:
    def __init__(self,stop,read_only=False,window_title='컴프야V26'):
        self.stop=stop
        found=[]
        callback=ctypes.WINFUNCTYPE(W.BOOL,W.HWND,W.LPARAM)
        def visit(hwnd,_):
            n=U.GetWindowTextLengthW(hwnd);buf=ctypes.create_unicode_buffer(n+1);U.GetWindowTextW(hwnd,buf,n+1)
            if U.IsWindowVisible(hwnd) and buf.value==window_title:found.append(hwnd)
            return True
        U.EnumWindows.argtypes=[callback,W.LPARAM]
        U.EnumWindows(callback(visit),0)
        if len(found)!=1:raise RuntimeError(f'게임 창을 하나만 열어 주세요. 발견: {len(found)}개')
        self.hwnd=found[0]
        pid=W.DWORD()
        U.GetWindowThreadProcessId.argtypes=[W.HWND,ctypes.POINTER(W.DWORD)]
        U.GetWindowThreadProcessId(self.hwnd,ctypes.byref(pid))
        import os
        if not read_only and elevated(pid.value) is True and elevated(os.getpid()) is False:
            raise RuntimeError('게임이 관리자 권한으로 실행 중입니다. 스캐너를 닫고 실행 파일을 우클릭 → 관리자 권한으로 실행하세요. Windows 권한 차이로 자동 클릭이 차단됩니다.')
        self.initial_size=self.rect()[2:]

    def check(self):
        if self.stop.is_set() or U.GetAsyncKeyState(0x77)&0x8000: # F8
            self.stop.set();raise InterruptedError('사용자가 중지했습니다.')
        if not U.IsWindow(self.hwnd):raise RuntimeError('게임 창이 닫혔습니다.')

    def rect(self):
        r=W.RECT();p=W.POINT(0,0)
        if not U.GetClientRect(self.hwnd,ctypes.byref(r)) or not U.ClientToScreen(self.hwnd,ctypes.byref(p)):raise RuntimeError('게임 창 좌표를 읽지 못했습니다.')
        w,h=r.right-r.left,r.bottom-r.top
        if w<250 or h<400:raise RuntimeError('게임 창이 최소화되었거나 너무 작습니다.')
        return p.x,p.y,w,h

    def focus(self):
        U.SetForegroundWindow(self.hwnd);time.sleep(.25)
        if U.GetForegroundWindow()!=self.hwnd:raise RuntimeError('게임을 앞으로 가져오지 못했습니다. 게임 창을 직접 클릭한 뒤 다시 시작하세요.')

    def capture(self,path=None):
        self.check()
        if U.GetForegroundWindow()!=self.hwnd:raise RuntimeError('게임에서 포커스가 벗어났습니다. 수집을 중단합니다.')
        x,y,w,h=self.rect()
        if (w,h)!=self.initial_size:raise RuntimeError('수집 중 창 크기가 변경되었습니다. 다시 시작하세요.')
        im=ImageGrab.grab((x,y,x+w,y+h),all_screens=True)
        if path:im.save(path)
        return im

    def wait(self,seconds):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:self.check();time.sleep(.05)

    def click(self,point):
        self.check()
        if U.GetForegroundWindow()!=self.hwnd:raise RuntimeError('게임 포커스가 없어 클릭을 중단했습니다.')
        x,y,w,h=self.rect();nx,ny=point
        if not (0<nx<1 and 0<ny<1):raise ValueError('클릭 위치는 창 내부여야 합니다.')
        ctypes.set_last_error(0)
        if not U.SetCursorPos(x+round(nx*w),y+round(ny*h)):
            code=ctypes.get_last_error()
            raise RuntimeError(f'커서 이동 API가 실패했습니다. Win32={code}. {error_text(code)} 원인은 미확정입니다. 수동 이동 + F6 수집 모드로 숫자 수집을 시험할 수 있습니다.')
        down=Input(type=0);down.mi.dwFlags=0x0002
        up=Input(type=0);up.mi.dwFlags=0x0004
        ctypes.set_last_error(0)
        sent=U.SendInput(1,ctypes.byref(down),ctypes.sizeof(Input))
        code=ctypes.get_last_error()
        if sent!=1:
            import os
            pid=W.DWORD();U.GetWindowThreadProcessId(self.hwnd,ctypes.byref(pid))
            detail=(f'SendInput mouse-down 반환={sent}, Win32={code} ({error_text(code)}), '
                    f'INPUT 크기={ctypes.sizeof(Input)}, 프로세스={ctypes.sizeof(ctypes.c_void_p)*8}bit, '
                    f'스캐너 관리자={elevated(os.getpid())}, 게임 관리자={elevated(pid.value)}')
            raise RuntimeError('마우스 입력 전달 실패. 원인은 아직 확정되지 않았습니다. '+detail)
        try:self.wait(.12)
        finally:
            ctypes.set_last_error(0)
            released=U.SendInput(1,ctypes.byref(up),ctypes.sizeof(Input))
            if released!=1:
                code=ctypes.get_last_error()
                raise RuntimeError(f'마우스 버튼 해제 전달 실패: SendInput={released}, Win32={code} ({ctypes.FormatError(code).strip()}). 실제 마우스 왼쪽 버튼을 한 번 눌렀다 떼어 주세요.')

    def drag(self,start,end,duration=.55):
        self.check()
        if U.GetForegroundWindow()!=self.hwnd:raise RuntimeError('게임 포커스가 없어 가로 이동을 중단했습니다.')
        x,y,w,h=self.rect()
        def move(point):
            nx,ny=point
            if not (0<nx<1 and 0<ny<1):raise ValueError('이동 위치는 창 내부여야 합니다.')
            if not U.SetCursorPos(x+round(nx*w),y+round(ny*h)):raise RuntimeError('가로 이동 중 커서 이동 실패')
        move(start)
        down=Input(type=0);down.mi.dwFlags=0x0002
        up=Input(type=0);up.mi.dwFlags=0x0004
        if U.SendInput(1,ctypes.byref(down),ctypes.sizeof(Input))!=1:raise RuntimeError('가로 이동 시작 입력 실패')
        try:
            self.wait(.15)
            for i in range(1,25):
                self.check()
                if U.GetForegroundWindow()!=self.hwnd:raise RuntimeError('가로 이동 중 게임 포커스가 벗어났습니다.')
                ratio=i/24
                move((start[0]+(end[0]-start[0])*ratio,start[1]+(end[1]-start[1])*ratio))
                self.wait(duration/24)
        finally:
            if U.SendInput(1,ctypes.byref(up),ctypes.sizeof(Input))!=1:raise RuntimeError('가로 이동 종료 입력 실패')

    def settled(self,delay):
        self.wait(delay)
        prev=self.capture().resize((100,180))
        for _ in range(10):
            self.wait(.2);current=self.capture().resize((100,180))
            if sum(ImageStat.Stat(ImageChops.difference(prev,current)).mean)/3<1.8:return self.capture()
            prev=current
        raise RuntimeError('화면 전환이 안정되지 않았습니다. 수집을 중단합니다.')
