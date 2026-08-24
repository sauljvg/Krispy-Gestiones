@echo off
setlocal
set "ROOT=%~dp0"
set "LOCK=%ROOT%daemon.pid"

echo Deteniendo daemon de agregadores...

if exist "%LOCK%" (
    set /p PID=<"%LOCK%"
    taskkill /PID %PID% /T /F >nul 2>&1
    del "%LOCK%" >nul 2>&1
    echo Proceso %PID% detenido.
) else (
    echo No se encontro daemon.pid -- buscando por linea de comandos...
)

rem Por si el lock no existia o estaba desactualizado: mata cualquier
rem python/pythonw que tenga daemon.py en su linea de comandos.
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe' OR Name='pythonw.exe'\" | Where-Object { $_.CommandLine -like '*daemon.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"

echo Quitando la tarea programada de Windows...
schtasks /Delete /TN "AgregadoresScraperLogon" /F >nul 2>&1
schtasks /Delete /TN "AgregadoresScraperDiario" /F >nul 2>&1

echo.
echo Listo: el daemon esta parado y ya no volvera a arrancar solo.
echo Para reactivarlo, vuelve a pedirmelo o ejecuta setup_tarea_programada.ps1
endlocal
pause
