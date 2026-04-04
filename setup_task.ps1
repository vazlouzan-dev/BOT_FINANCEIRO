# Execute this entire command block in PowerShell (Run as Administrator)
# Copy and paste everything from here to the end into PowerShell

$taskName = 'FinancialMarketBiasAnalyzer'
$pythonExe = 'C:\Users\Utilizador\OneDrive\Área de Trabalho\Bot_Financeiro\.venv\Scripts\python.exe'
$scriptPath = 'C:\Users\Utilizador\OneDrive\Área de Trabalho\Bot_Financeiro\main.py'
$projectPath = 'C:\Users\Utilizador\OneDrive\Área de Trabalho\Bot_Financeiro'

# Create scheduling components
$action = New-ScheduledTaskAction -Execute $pythonExe -Argument $scriptPath -WorkingDirectory $projectPath
$trigger = New-ScheduledTaskTrigger -Daily -At 06:00AM
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

# Register the task
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description "Daily automated analysis of NY market bias at 06:00 AM EDT" -Force

Write-Host "`n========================================" -ForegroundColor Green
Write-Host "SUCCESS: Task Created!" -ForegroundColor Green  
Write-Host "========================================`n" -ForegroundColor Green
Write-Host "Agendamento: Diariamente as 06:00 AM EDT" -ForegroundColor Cyan
Write-Host "Resultado: output/bias_report.json`n" -ForegroundColor Cyan
Write-Host "Para gerenciar:" -ForegroundColor Yellow
Write-Host "1. Abra Task Scheduler (tasksched.msc)" -ForegroundColor White
Write-Host "2. Procure: FinancialMarketBiasAnalyzer" -ForegroundColor White
Write-Host "3. Right-click para Edit, Run, ou Delete`n" -ForegroundColor White
