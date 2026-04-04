@echo off
REM Financial Market Bias Analyzer - Task Scheduler Setup (Windows Batch)
REM This script requires Administrator privileges

cd /d "C:\Users\Utilizador\OneDrive\Área de Trabalho\Bot_Financeiro"

REM Check for admin privileges
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo.
    echo ERROR: This script requires Administrator privileges!
    echo.
    echo Please run this command as Administrator:
    echo 1. Press Windows + X
    echo 2. Click "Command Prompt (Admin)" or "Terminal (Admin)"
    echo 3. Run: setup_scheduler.bat
    echo.
    pause
    exit /b 1
)

echo =========================================
echo Financial Market Bias Analyzer
echo Windows Task Scheduler Setup
echo =========================================
echo.

REM Create the scheduled task
powershell -Command "^
$taskName = 'FinancialMarketBiasAnalyzer'; ^
$pythonExe = 'C:\Users\Utilizador\OneDrive\Área de Trabalho\Bot_Financeiro\.venv\Scripts\python.exe'; ^
$scriptPath = 'C:\Users\Utilizador\OneDrive\Área de Trabalho\Bot_Financeiro\main.py'; ^
$projectPath = 'C:\Users\Utilizador\OneDrive\Área de Trabalho\Bot_Financeiro'; ^
$action = New-ScheduledTaskAction -Execute $pythonExe -Argument $scriptPath -WorkingDirectory $projectPath; ^
$trigger = New-ScheduledTaskTrigger -Daily -At 06:00AM; ^
$principal = New-ScheduledTaskPrincipal -UserId '$env:USERDOMAIN\$env:USERNAME' -LogonType Interactive -RunLevel Highest; ^
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable; ^
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'Daily automated analysis of NY market bias at 06:00 AM EDT' -Force; ^
Write-Host 'SUCCESS: Task created!' -ForegroundColor Green; ^
Write-Host 'Daily analysis will run at 06:00 AM EDT' -ForegroundColor Cyan"

if %errorLevel% equ 0 (
    echo.
    echo =========================================
    echo CONFIGURACAO COMPLETA!
    echo =========================================
    echo.
    echo Task criada com sucesso!
    echo - Nome: FinancialMarketBiasAnalyzer
    echo - Horario: Diariamente as 06:00 AM EDT
    echo - Output: output/bias_report.json
    echo.
    echo Para gerenciar a tarefa:
    echo 1. Abra Task Scheduler (tasksched.msc)
    echo 2. Procure: FinancialMarketBiasAnalyzer
    echo 3. Right-click para Edit, Run, ou Delete
    echo.
) else (
    echo.
    echo ERROR: Failed to create task!
    echo.
)

pause
