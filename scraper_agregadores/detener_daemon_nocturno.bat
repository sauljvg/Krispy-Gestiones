@echo off
setlocal
set "ROOT=%~dp0"
set "LOCK=%ROOT%daemon.pid"

rem Version "silenciosa" de detener_daemon.bat para la tarea programada de las
rem 22:00 -- solo mata el proceso, NO toca las tareas programadas (a
rem diferencia de detener_daemon.bat, que las borra a proposito para una
rem parada manual definitiva). Si esto borrara las tareas, la de las 8:55am
rem tambien desaparaceria y el ciclo diario se romperia tras la primera noche.

if exist "%LOCK%" (
    set /p PID=<"%LOCK%"
    taskkill /PID %PID% /T /F >nul 2>&1
    del "%LOCK%" >nul 2>&1
)

powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe' OR Name='pythonw.exe'\" | Where-Object { $_.CommandLine -like '*daemon.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"

endlocal
