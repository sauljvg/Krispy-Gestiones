@echo off
setlocal
cd /d "%~dp0"

rem Mata TODOS los workers del daemon (cualquier --worker-index), tanto el proceso
rem "lanzador" del venv como el interprete real que arranca debajo (el launcher de venv
rem de Windows arranca el python.exe base como hijo con la misma linea de comandos, asi
rem que Stop-Process necesita alcanzar a los dos, no solo al PID guardado en el .pid).
powershell -NoProfile -Command ^
  "$procs = Get-CimInstance Win32_Process -Filter \"Name='python.exe' OR Name='pythonw.exe'\" | Where-Object { $_.CommandLine -like '*daemon.py*' };" ^
  "if (-not $procs) { Write-Host 'No hay ningun daemon de agregadores corriendo.'; exit 0 };" ^
  "foreach ($p in $procs) { Write-Host ('Matando PID ' + $p.ProcessId + ': ' + $p.CommandLine); Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue }"

del "%~dp0daemon_w*.pid" >nul 2>&1

echo Daemon(s) de agregadores detenidos.
endlocal
