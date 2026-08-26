@echo off
REM GEX Dashboard - fetch data every minute during US market hours (Mon-Fri 9:30-16:00 ET) and push
set PY=C:\Users\Moham\AppData\Local\Python\pythoncore-3.14-64\python.exe
set REPO=C:\Users\Moham\gex-dashboard

for /f %%i in ('powershell -NoProfile -Command "(Get-TimeZone).Id; (Get-Date).ToUniversalTime().ToString('ddd'); [int](Get-Date).ToUniversalTime().ToString('HH')"') do set /A N+=1

powershell -NoProfile -Command ^
 "$now=[DateTime]::UtcNow.AddHours(-4);^
  $et=Get-Date $now -Format 'ddd';^
  $h=[int]$now.ToString('HH');$m=[int]$now.ToString('mm');^
  if(($et -ne 'Sat' -and $et -ne 'Sun') -and (($h -gt 13 -and $h -lt 20) -or ($h -eq 13 -and $m -ge 30))){exit 0}else{exit 1}"
if errorlevel 1 exit /b 0

cd /d %REPO%
"%PY%" scripts\fetch_gex.py >nul 2>&1
git add docs/data/gex_data.json
git diff --cached --quiet || (git commit -m "data: auto %date% %time%" -q && git push origin main -q)
