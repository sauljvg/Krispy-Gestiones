@echo off
setlocal
cd /d "%~dp0"
set "LOCK=%~dp0daemon.pid"
set "PY=%~dp0venv\Scripts\pythonw.exe"
set "LOGDIR=%~dp0logs"
if not exist "%LOGDIR%" mkdir "%LOGDIR%"

rem Si ya hay un daemon corriendo, no lanzar otro encima. No basta con mirar
rem el PID guardado en daemon.pid -- ese fichero puede quedar desactualizado
rem o ausente (p.ej. si se lanzo el proceso a mano una vez, o la tarea de
rem apagado de las 22:00 lo borro pero algo dejo un proceso vivo de una
rem sesion anterior) y entonces el chequeo por PID no ve nada y deja lanzar
rem un segundo daemon encima del que ya esta corriendo (visto en vivo 10/08:
rem dos daemons a la vez, doble tráfico contra los agregadores). Se busca en
rem vez de eso por linea de comandos, igual que ya hace detener_daemon.bat.
rem exit 1 = ya hay uno vivo (y de paso deja daemon.pid al dia); exit 0 = via libre.
powershell -NoProfile -Command "$p = Get-CimInstance Win32_Process -Filter \"Name='python.exe' OR Name='pythonw.exe'\" | Where-Object { $_.CommandLine -like '*daemon.py*' } | Select-Object -First 1; if ($p) { Write-Host ('Ya hay un daemon corriendo con PID ' + $p.ProcessId + '. No se lanza otro.'); $p.ProcessId | Out-File -FilePath '%LOCK%' -Encoding ascii -NoNewline; exit 1 } else { exit 0 }"
if errorlevel 1 exit /b 0
if exist "%LOCK%" del "%LOCK%" >nul 2>&1

for /f "delims=" %%T in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "STAMP=%%T"

powershell -NoProfile -WindowStyle Hidden -Command "$p = Start-Process -FilePath '%PY%' -ArgumentList 'daemon.py' -WorkingDirectory '%~dp0' -RedirectStandardOutput '%LOGDIR%\daemon_%STAMP%.log' -RedirectStandardError '%LOGDIR%\daemon_%STAMP%_err.log' -WindowStyle Hidden -PassThru; $p.Id | Out-File -FilePath '%LOCK%' -Encoding ascii -NoNewline"

echo Daemon de agregadores lanzado (log: logs\daemon_%STAMP%.log)
endlocal
