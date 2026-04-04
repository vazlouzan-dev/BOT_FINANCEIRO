# Financial Market Bias Analyzer - Windows Task Scheduler Setup
# Run this script as Administrator in PowerShell:
#   Right-click PowerShell -> "Run as Administrator"
#   Then: .\setup_task.ps1

$taskName   = "FinancialMarketBiasAnalyzer"
$pythonExe  = "C:\Users\Utilizador\OneDrive\Área de Trabalho\Bot_Financeiro\.venv\Scripts\python.exe"
$scriptPath = "C:\Users\Utilizador\OneDrive\Área de Trabalho\Bot_Financeiro\main.py"
$workingDir = "C:\Users\Utilizador\OneDrive\Área de Trabalho\Bot_Financeiro"

# Run at 14:00 local time (Portugal), ~30 min before NY open (14:30 UTC / 09:30 ET)
# Adjust the hour if your timezone differs from UTC+0/UTC+1
$triggerTime = "14:00"

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Financial Market Bias Analyzer"        -ForegroundColor Cyan
Write-Host "  Task Scheduler Setup"                  -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check admin privileges
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]"Administrator")
if (-not $isAdmin) {
    Write-Host "ERROR: Run this script as Administrator." -ForegroundColor Red
    exit 1
}

$action    = New-ScheduledTaskAction -Execute $pythonExe -Argument $scriptPath -WorkingDirectory $workingDir
$trigger   = New-ScheduledTaskTrigger -Daily -At $triggerTime
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Highest
$settings  = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

Register-ScheduledTask `
    -TaskName   $taskName `
    -Action     $action `
    -Trigger    $trigger `
    -Principal  $principal `
    -Settings   $settings `
    -Description "Daily NY market bias analysis — runs at $triggerTime (local time) before NY open" `
    -Force | Out-Null

Write-Host "SUCCESS: Task '$taskName' created!" -ForegroundColor Green
Write-Host ""
Write-Host "Schedule : Daily at $triggerTime (local time)"  -ForegroundColor White
Write-Host "Output   : $workingDir\output\bias_report.json" -ForegroundColor White
Write-Host ""
Write-Host "To manage the task:"                                     -ForegroundColor Yellow
Write-Host "  - Open Task Scheduler (tasksched.msc)"                -ForegroundColor White
Write-Host "  - Find: $taskName"                                     -ForegroundColor White
Write-Host "  - Right-click -> Run (to test), Edit, or Delete"      -ForegroundColor White
Write-Host ""
Write-Host "To run manually now:"                                    -ForegroundColor Yellow
Write-Host "  python main.py"                                        -ForegroundColor White
Write-Host ""
