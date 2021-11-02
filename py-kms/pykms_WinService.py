# Warning: this script only for Windows 7 SP1 / Windows 2008 R2!
# -
# Download links x64:
# https://www.python.org/ftp/python/3.7.4/python-3.7.4-amd64.exe
# https://github.com/mhammond/pywin32/releases/download/b224/pywin32-224.win-amd64-py3.7.exe
# -
# Download links x32:
# https://www.python.org/ftp/python/3.7.4/python-3.7.4.exe
# https://github.com/mhammond/pywin32/releases/download/b224/pywin32-224.win32-py3.7.exe
# -
# Need install Python 3.7.4 before pywin32!
# -
# 1. Install Python 3.7.4 into C:\Windows\Python374
# 2. Install pywin32
# 3. Run cmd as Administrator and start command "cd C:\Windows\Python374\py-kms"
# 4. Install py-kms as service command: "python pykms_WinService.py --startup delayed install" 
# -
import win32serviceutil
import win32service
import win32event
import servicemanager
import socket
import subprocess

class AppServerSvc (win32serviceutil.ServiceFramework):
    _svc_name_ = "py-kms"
    _svc_display_name_ = "py-kms"
    _proc = None
    _cmd = ["C:\Windows\Python374\python.exe", "C:\Windows\Python374\py-kms\pykms_Server.py"]

    def __init__(self,args):
        win32serviceutil.ServiceFramework.__init__(self,args)
        self.hWaitStop = win32event.CreateEvent(None,0,0,None)
        socket.setdefaulttimeout(60)

    def SvcStop(self):
        self.killproc()
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.hWaitStop)

    def SvcDoRun(self):
        servicemanager.LogMsg(servicemanager.EVENTLOG_INFORMATION_TYPE,
                              servicemanager.PYS_SERVICE_STARTED,
                              (self._svc_name_,''))
        self.main()

    def main(self):
        self._proc = subprocess.Popen(self._cmd)
        self._proc.wait()

    def killproc(self):
        self._proc.kill()

if __name__ == '__main__':
    win32serviceutil.HandleCommandLine(AppServerSvc)
