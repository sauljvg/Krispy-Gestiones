@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
set "PY=%~dp0venv\Scripts\pythonw.exe"
set "LOGDIR=%~dp0logs"
if not exist "%LOGDIR%" mkdir "%LOGDIR%"

rem Cuántas instancias en paralelo arranca esta máquina -- viene de SCRAPER_WORKERS en
rem .env (no versionado: cada máquina pone la suya). Sin la variable, 1 -- portátil de
rem trabajo (OT), comportamiento de siempre. En el ordenador personal (OP), 6-8, para
rem que sirva de refuerzo en paralelo cuando se enciende (ver README.md).
set "WORKERS=1"
if exist "%~dp0.env" (
    for /f "usebackq tokens=1,* delims==" %%A in ("%~dp0.env") do (
        if /i "%%A"=="SCRAPER_WORKERS" set "WORKERS=%%B"
    )
)

for /f "delims=" %%T in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "STAMP=%%T"

set /a "ULTIMO=%WORKERS%-1"
for /L %%i in (0,1,%ULTIMO%) do call :lanzar_worker %%i

endlocal
exit /b 0

:lanzar_worker
set "IDX=%~1"
set "LOCK=%~dp0daemon_w%IDX%.pid"

rem Si ya hay un daemon con ESTE worker-index corriendo, no lanzar otro encima. No basta
rem con mirar el PID guardado en el .pid -- ese fichero puede quedar desactualizado o
rem ausente (p.ej. si se lanzo el proceso a mano una vez, o la tarea de apagado de las
rem 22:00 lo borro pero algo dejo un proceso vivo de una sesion anterior) y entonces el
rem chequeo por PID no ve nada y deja lanzar un segundo daemon encima del que ya esta
rem corriendo (visto en vivo 10/08: dos daemons a la vez, doble tráfico contra los
rem agregadores). Se busca en vez de eso por linea de comandos, filtrando por el
rem worker-index exacto -- así no bloquea a los demás workers, solo a un duplicado del
rem mismo.
powershell -NoProfile -Command "$p = Get-CimInstance Win32_Process -Filter \"Name='python.exe' OR Name='pythonw.exe'\" | Where-Object { $_.CommandLine -like '*daemon.py*' -and $_.CommandLine -like '*--worker-index %IDX%*' } | Select-Object -First 1; if ($p) { Write-Host ('Worker %IDX%: ya hay un daemon corriendo con PID ' + $p.ProcessId + '. No se lanza otro.'); $p.ProcessId | Out-File -FilePath '%LOCK%' -Encoding ascii -NoNewline; exit 1 } else { exit 0 }"
if errorlevel 1 exit /b 0
if exist "%LOCK%" del "%LOCK%" >nul 2>&1

powershell -NoProfile -WindowStyle Hidden -Command "$p = Start-Process -FilePath '%PY%' -ArgumentList 'daemon.py','--worker-index','%IDX%','--worker-count','%WORKERS%' -WorkingDirectory '%~dp0' -RedirectStandardOutput '%LOGDIR%\daemon_w%IDX%_%STAMP%.log' -RedirectStandardError '%LOGDIR%\daemon_w%IDX%_%STAMP%_err.log' -WindowStyle Hidden -PassThru; $p.Id | Out-File -FilePath '%LOCK%' -Encoding ascii -NoNewline"

echo Worker %IDX%/%WORKERS% de agregadores lanzado (log: logs\daemon_w%IDX%_%STAMP%.log)
exit /b 0
