$Root = $PSScriptRoot
$BatPath = Join-Path $Root "iniciar_daemon.bat"

$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$BatPath`"" -WorkingDirectory $Root
$triggerLogon = New-ScheduledTaskTrigger -AtLogOn
$triggerDaily = New-ScheduledTaskTrigger -Daily -At 8:55am
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName "AgregadoresScraperLogon" -Action $action -Trigger $triggerLogon -Settings $settings `
    -Description "Arranca el daemon del scraper de agregadores KK al iniciar sesion en Windows" -Force | Out-Null

Register-ScheduledTask -TaskName "AgregadoresScraperDiario" -Action $action -Trigger $triggerDaily -Settings $settings `
    -Description "Arranca el daemon del scraper de agregadores KK cada dia a las 8:55, por si el PC ya estaba encendido" -Force | Out-Null

Write-Host "Tareas programadas creadas: AgregadoresScraperLogon (al iniciar sesion) y AgregadoresScraperDiario (diario 8:55)."
