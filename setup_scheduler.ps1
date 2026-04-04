# ============================================================================
# Financial Market Bias Analyzer - Windows Task Scheduler Setup
# Execute this script as ADMINISTRATOR to create automated daily analysis
# ============================================================================

# Check if running as Administrator
if (-not ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole] "Administrator")) {
    Write-Host "ERROR: This script must be run as Administrator!" -ForegroundColor Red
    Write-Host "Right-click on PowerShell and select 'Run as administrator', then run this script again." -ForegroundColor Yellow
    pause
    exit
}

$projectPath = "C:\Users\Utilizador\OneDrive\Área de Trabalho\Bot_Financeiro"
$pythonExe = "$projectPath\.venv\Scripts\python.exe"
$scriptPath = "$projectPath\main.py"
$logPath = "$projectPath\output\logs\scheduler.log"

# Verify files exist
if (-not (Test-Path $pythonExe)) {
    Write-Host "ERROR: Python executable not found at $pythonExe" -ForegroundColor Red
    exit
}

if (-not (Test-Path $scriptPath)) {
    Write-Host "ERROR: Script not found at $scriptPath" -ForegroundColor Red
    exit
}

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "Financial Market Bias Analyzer" -ForegroundColor Cyan
Write-Host "Windows Task Scheduler Setup" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan

# Task name and description
$taskName = "FinancialMarketBiasAnalyzer"
$taskDescription = "Daily automated analysis of NY market bias at 06:00 AM EDT"

# Check if task already exists
$existingTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue

if ($existingTask) {
    Write-Host "`nTask '$taskName' already exists!" -ForegroundColor Yellow
    $response = Read-Host "Do you want to replace it? (Y/N)"
    
    if ($response -eq "Y" -or $response -eq "y") {
        Write-Host "Removing existing task..." -ForegroundColor Cyan
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
        Write-Host "Existing task removed." -ForegroundColor Green
    } else {
        Write-Host "Cancelled." -ForegroundColor Yellow
        exit
    }
}

# Create action (runs Python script with venv)
$action = New-ScheduledTaskAction `
    -Execute $pythonExe `
    -Argument $scriptPath `
    -WorkingDirectory $projectPath

# Create trigger (Daily at 06:00 AM)
$trigger = New-ScheduledTaskTrigger `
    -Daily `
    -At 06:00AM

# Create principal (run with highest privileges)
$principal = New-ScheduledTaskPrincipal `
    -UserID "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Highest

# Create settings
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable

# Register the task
Write-Host "`nCreating scheduled task..." -ForegroundColor Cyan

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description $taskDescription `
    -Force | Out-Null

Write-Host "SUCESSO - Task created!" -ForegroundColor Green

Write-Host "`n=========================================" -ForegroundColor Green
Write-Host "Task automation configured!" -ForegroundColor Green
Write-Host "=========================================" -ForegroundColor Green

Write-Host "`nAnalysis will run daily at 06:00 AM EDT" -ForegroundColor Cyan
Write-Host "Results: output/bias_report.json" -ForegroundColor Cyan

Write-Host "`nTo manage the task:" -ForegroundColor Yellow
Write-Host "  1. Open Task Scheduler (tasksched.msc)" -ForegroundColor White
Write-Host "  2. Find: FinancialMarketBiasAnalyzer" -ForegroundColor White
Write-Host "  3. Right-click to Run, Edit, or Delete" -ForegroundColor White

pause
