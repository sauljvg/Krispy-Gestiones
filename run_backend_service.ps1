$ProjectRoot = $PSScriptRoot
Set-Location (Join-Path $ProjectRoot "backend")
$LogFile = Join-Path $ProjectRoot "backend_service.log"
& python main.py *>> $LogFile
