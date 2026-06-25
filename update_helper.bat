@echo off
setlocal enabledelayedexpansion

rem Always log updater output so failures aren't silent when running hidden.
for /f %%T in ('powershell -NoProfile -InputFormat None -Command "(Get-Date).ToString(\"yyyyMMddHHmmss\")"') do set "RUNSTAMP=%%T"
set "LOG_FILE=%TEMP%\BlindRSS_update_!RUNSTAMP!_!RANDOM!.log"
set "SENTINEL=__BLINDRSS_UPDATE_DONE__"

set "UPDATE_MODE=archive"
if /I "%~1"=="--installer" (
    set "UPDATE_MODE=installer"
    set "PID=%~2"
    set "INSTALL_DIR=%~3"
    set "INSTALLER_PATH=%~4"
    set "EXE_NAME=BlindRSS.exe"
    set "TEMP_ROOT=%~5"
    set "SHOW_LOG=%~6"
) else (
    set "PID=%~1"
    set "INSTALL_DIR=%~2"
    set "STAGING_DIR=%~3"
    set "EXE_NAME=%~4"
    set "TEMP_ROOT=%~5"
    set "SHOW_LOG=%~6"
)
set "BACKUP_DIR="

call :main >> "%LOG_FILE%" 2>&1
set "RC=%ERRORLEVEL%"

if %RC% equ 0 (
    rem Success - always delete log file
    del /f /q "%LOG_FILE%" >nul 2>nul
) else (
    rem Failure - write sentinel so any running log window will close
    echo %SENTINEL%>>"%LOG_FILE%"
)
exit /b %RC%

:main
echo [BlindRSS Update] Log: "%LOG_FILE%"

if "%PID%"=="" goto :usage
if "%INSTALL_DIR%"=="" goto :usage
if "%EXE_NAME%"=="" goto :usage
if /I "%UPDATE_MODE%"=="installer" (
    if "%INSTALLER_PATH%"=="" goto :usage
) else (
    if "%STAGING_DIR%"=="" goto :usage
)

rem Ensure we are not running from within the install directory
if not defined BLINDRSS_UPDATE_HELPER_RELOCATED (
    set "SCRIPT_PATH=%~f0"
    powershell -NoProfile -InputFormat None -Command "$sp=[string]$env:SCRIPT_PATH; $inst=[string]$env:INSTALL_DIR; if ($sp -and $inst -and $sp.ToLower().StartsWith($inst.ToLower())) { exit 0 } else { exit 1 }" >nul 2>nul
    if not errorlevel 1 (
        set "BLINDRSS_UPDATE_HELPER_RELOCATED=1"
        for /f %%T in ('powershell -NoProfile -InputFormat None -Command "(Get-Date).ToString(\"yyyyMMddHHmmss\")"') do set "HSTAMP=%%T"
        set "TMP_HELPER=%TEMP%\BlindRSS_update_helper_!HSTAMP!_!RANDOM!.bat"
        copy /Y "%~f0" "!TMP_HELPER!" >nul 2>nul
        if /I "%UPDATE_MODE%"=="installer" (
            start "" /b cmd /d /c call "!TMP_HELPER!" --installer "%PID%" "%INSTALL_DIR%" "%INSTALLER_PATH%" "%TEMP_ROOT%" "%SHOW_LOG%"
        ) else (
            start "" /b cmd /d /c call "!TMP_HELPER!" "%PID%" "%INSTALL_DIR%" "%STAGING_DIR%" "%EXE_NAME%" "%TEMP_ROOT%" "%SHOW_LOG%"
        )
        exit /b 0
    )
)

rem Never keep the working directory inside the install folder
if exist "%TEMP%" (
    pushd "%TEMP%" >nul 2>nul
) else if exist "%SystemRoot%" (
    pushd "%SystemRoot%" >nul 2>nul
)

if /I "%UPDATE_MODE%"=="installer" goto :run_installer_update

if not exist "%STAGING_DIR%" (
    echo [BlindRSS Update] Staging folder not found: "%STAGING_DIR%"
    exit /b 1
)

call :ensure_app_stopped
if errorlevel 1 goto :rollback

call :verify_install_unlocked
if errorlevel 1 goto :rollback

rem OneDrive Fix: Don't move the root folder. Move CONTENTS.
rem We back up the current contents to a backup folder, then move new contents in.
rem Robocopy is more robust for this than 'move'.

for /f %%T in ('powershell -NoProfile -InputFormat None -Command "(Get-Date).ToString(\"yyyyMMddHHmmss\")"') do set STAMP=%%T
set "BACKUP_DIR=%INSTALL_DIR%_backup_%STAMP%"

echo [BlindRSS Update] Backing up current install to "%BACKUP_DIR%"...
if not exist "%BACKUP_DIR%" mkdir "%BACKUP_DIR%"
rem /MOVE moves files and dirs, effectively emptying source. /E for recursive. /NFL /NDL to reduce noise.
rem We exclude user data (rss.db, config.json) from the MOVE so they stay in place, 
rem preventing potential data loss if restore fails, and reducing IO.
rem Wait, if we leave them there, robocopy moving new files in won't touch them unless they exist in new files (they shouldn't).
rem BUT if we want to "clean install", we should move everything except user data.
rem Let's move everything. We will copy user data back if needed, or if we excluded them, they are just there.
rem To be safe and identical to previous logic: Move EVERYTHING out, then move EVERYTHING in, then Restore user data.
rem Logic:
rem 1. Robocopy /MOVE * from INSTALL to BACKUP.
rem 2. Robocopy /MOVE * from STAGING to INSTALL.
rem 3. Copy user data from BACKUP to INSTALL (if missing).

rem Robocopy exit codes: 0=No Change, 1=Copy Successful, >1=Warning/Error.
rem We accept <= 3 usually (1=copy, 2=extra, 3=both). 
rem However, for /MOVE, we want to ensure it worked.

rem A freshly-exited app can leave a runtime DLL (e.g. _internal\VCRUNTIME140.dll)
rem briefly locked by Defender/Search-indexing, so robocopy /MOVE copies it but
rem cannot delete the source ("Access is denied"). robocopy /R retries copies, not
rem the /MOVE source-delete, so retry the whole move a few times with a short settle
rem before treating leftover files as a hard failure.
set "BACKUP_ATTEMPTS=0"
:backup_move_attempt
set /a BACKUP_ATTEMPTS+=1
robocopy "%INSTALL_DIR%" "%BACKUP_DIR%" /E /MOVE /R:10 /W:3 /NFL /NDL /XD .git .venv __pycache__
set RC=%ERRORLEVEL%
if %RC% gtr 8 (
    echo [X] Backup failed with robocopy code %RC%.
    goto :rollback
)
call :verify_install_drained
if not errorlevel 1 goto :backup_drained
if %BACKUP_ATTEMPTS% geq 5 (
    echo [X] Backup did not fully move the current install after %BACKUP_ATTEMPTS% attempts.
    goto :rollback
)
echo [BlindRSS Update] Install folder not fully drained; waiting for locks to clear, then retrying move (attempt %BACKUP_ATTEMPTS%)...
powershell -NoProfile -InputFormat None -Command "Start-Sleep -Seconds 2" >nul 2>nul
goto :backup_move_attempt
:backup_drained

echo [BlindRSS Update] Applying update...
robocopy "%STAGING_DIR%" "%INSTALL_DIR%" /E /MOVE /R:10 /W:3 /NFL /NDL
set RC=%ERRORLEVEL%
if %RC% gtr 8 (
    echo [X] Update application failed with robocopy code %RC%.
    goto :rollback
)

echo [BlindRSS Update] Restoring user data...
call :restore_user_data "%BACKUP_DIR%" "%INSTALL_DIR%"

echo [BlindRSS Update] Launching app...
start "" /b "%INSTALL_DIR%\%EXE_NAME%"
call :cleanup_success "%BACKUP_DIR%" "%STAGING_DIR%" "%TEMP_ROOT%"
exit /b 0

:run_installer_update
if not exist "%INSTALLER_PATH%" (
    echo [BlindRSS Update] Installer not found: "%INSTALLER_PATH%"
    exit /b 1
)

call :ensure_app_stopped
if errorlevel 1 goto :installer_failure

call :verify_install_unlocked
if errorlevel 1 goto :installer_failure

echo [BlindRSS Update] Running signed per-user installer...
start "" /wait "%INSTALLER_PATH%" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS /DIR="%INSTALL_DIR%"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
    echo [X] Installer failed with exit code %RC%.
    goto :installer_failure
)
if not exist "%INSTALL_DIR%\.windows-installed" (
    echo [X] Installer completed without the installed-build marker.
    goto :installer_failure
)

echo [BlindRSS Update] Launching app...
start "" /b "%INSTALL_DIR%\%EXE_NAME%"
if not "%TEMP_ROOT%"=="" call :schedule_temp_cleanup "%TEMP_ROOT%"
exit /b 0

:installer_failure
if not "%SHOW_LOG%"=="" if /I not "%SHOW_LOG%"=="0" (
    call :start_log_window "%LOG_FILE%" "%SENTINEL%"
)
if exist "%INSTALL_DIR%\%EXE_NAME%" start "" /b "%INSTALL_DIR%\%EXE_NAME%"
powershell -NoProfile -InputFormat None -Command "param([string]$log) try { Add-Type -AssemblyName PresentationFramework | Out-Null; $msg = 'BlindRSS installer update failed.' + \"`n`n\" + 'Log file:' + \"`n\" + $log; [System.Windows.MessageBox]::Show($msg, 'BlindRSS Update', 'OK', 'Error') | Out-Null } catch { }" "%LOG_FILE%" >nul 2>nul
exit /b 1

:rollback
echo [BlindRSS Update] Update failed. Restoring backup...
if not "%SHOW_LOG%"=="" if /I not "%SHOW_LOG%"=="0" (
    call :start_log_window "%LOG_FILE%" "%SENTINEL%"
)
if not "%BACKUP_DIR%"=="" if exist "%BACKUP_DIR%" (
    robocopy "%BACKUP_DIR%" "%INSTALL_DIR%" /E /MOVE /R:10 /W:3 /NFL /NDL
)
start "" /b "%INSTALL_DIR%\%EXE_NAME%"
powershell -NoProfile -InputFormat None -Command "param([string]$log) try { Add-Type -AssemblyName PresentationFramework | Out-Null; $msg = 'BlindRSS update failed.' + \"`n`n\" + 'Log file:' + \"`n\" + $log; [System.Windows.MessageBox]::Show($msg, 'BlindRSS Update', 'OK', 'Error') | Out-Null } catch { }" "%LOG_FILE%" >nul 2>nul
exit /b 1

:ensure_app_stopped
echo [BlindRSS Update] Waiting for process %PID% and install-owned app instances to exit...
powershell -NoProfile -InputFormat None -Command "$ErrorActionPreference='SilentlyContinue'; $exe=[IO.Path]::GetFileNameWithoutExtension([string]$env:EXE_NAME); $install=([IO.Path]::GetFullPath([string]$env:INSTALL_DIR)).TrimEnd('\') + '\'; function Get-BlindRssProc { $items=@(); if ($exe) { $items += @(Get-Process -Name $exe -ErrorAction SilentlyContinue) }; $target=0; if ([int]::TryParse([string]$env:PID, [ref]$target)) { $p=Get-Process -Id $target -ErrorAction SilentlyContinue; if ($p) { $items += $p } }; $items | Sort-Object Id -Unique | Where-Object { try { $p=[IO.Path]::GetFullPath([string]$_.Path); $p.StartsWith($install, [StringComparison]::OrdinalIgnoreCase) } catch { $false } } }; function Wait-Gone([int]$seconds) { $deadline=(Get-Date).AddSeconds($seconds); while ((Get-Date) -lt $deadline) { $procs=@(Get-BlindRssProc); if ($procs.Count -eq 0) { return $true }; Start-Sleep -Milliseconds 500 }; return (@(Get-BlindRssProc).Count -eq 0) }; if (-not (Wait-Gone 20)) { $procs=@(Get-BlindRssProc); if ($procs.Count -gt 0) { Write-Host ('[BlindRSS Update] Asking remaining app instance(s) to close: ' + (($procs | ForEach-Object Id) -join ', ')); foreach ($p in $procs) { try { $null=$p.CloseMainWindow() } catch { } } } }; if (-not (Wait-Gone 10)) { $procs=@(Get-BlindRssProc); if ($procs.Count -gt 0) { Write-Host ('[BlindRSS Update] Forcing remaining app instance(s) to exit: ' + (($procs | ForEach-Object Id) -join ', ')); foreach ($p in $procs) { try { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue } catch { } } } }; if (-not (Wait-Gone 10)) { $procs=@(Get-BlindRssProc); Write-Host ('[X] BlindRSS is still running from the install folder: ' + (($procs | ForEach-Object Id) -join ', ')); exit 1 }; Start-Sleep -Milliseconds 1500; exit 0"
exit /b %ERRORLEVEL%

:verify_install_unlocked
echo [BlindRSS Update] Verifying install files are unlocked...
powershell -NoProfile -InputFormat None -Command "$ErrorActionPreference='SilentlyContinue'; $install=[string]$env:INSTALL_DIR; $exe=[string]$env:EXE_NAME; $paths=@((Join-Path $install $exe),(Join-Path $install '_internal\VCRUNTIME140.dll'),(Join-Path $install '_internal\python314.dll'),(Join-Path $install '_internal\python313.dll'),(Join-Path $install '_internal\python312.dll'),(Join-Path $install '_internal\python311.dll')); $locked=@(); foreach ($path in $paths) { if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { continue }; $ok=$false; for ($i=0; $i -lt 8 -and -not $ok; $i++) { try { $fs=[IO.File]::Open($path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::None); $fs.Close(); $ok=$true } catch { Start-Sleep -Milliseconds 500 } }; if (-not $ok) { $locked += $path } }; if ($locked.Count -gt 0) { Write-Host '[X] Install files are still locked:'; $locked | ForEach-Object { Write-Host ('    ' + $_) }; exit 1 }; exit 0"
exit /b %ERRORLEVEL%

:verify_install_drained
powershell -NoProfile -InputFormat None -Command "$ErrorActionPreference='SilentlyContinue'; $install=([IO.Path]::GetFullPath([string]$env:INSTALL_DIR)).TrimEnd('\') + '\'; $excluded=@('.git','.venv','__pycache__'); $remaining=@(Get-ChildItem -LiteralPath $install -File -Recurse -Force | Where-Object { $rel=$_.FullName.Substring($install.Length).TrimStart('\'); $parts=$rel -split '\\'; -not @($parts | Where-Object { $excluded -contains $_ }) } | Select-Object -First 10); if ($remaining.Count -gt 0) { Write-Host '[X] Files remained in the install folder after backup:'; $remaining | ForEach-Object { Write-Host ('    ' + $_.FullName) }; exit 1 }; exit 0"
exit /b %ERRORLEVEL%

:restore_user_data
setlocal
set "OLD_DIR=%~1"
set "NEW_DIR=%~2"

if "%OLD_DIR%"=="" goto :restore_done
if "%NEW_DIR%"=="" goto :restore_done
if not exist "%OLD_DIR%" goto :restore_done
if not exist "%NEW_DIR%" goto :restore_done

rem Copy back config and database if they were moved to backup
if exist "%OLD_DIR%\config.json" (
    copy /Y "%OLD_DIR%\config.json" "%NEW_DIR%\config.json" >nul 2>nul
)

for %%F in (rss.db rss.db-wal rss.db-shm rss.db-journal) do (
    if exist "%OLD_DIR%\%%F" (
        copy /Y "%OLD_DIR%\%%F" "%NEW_DIR%\%%F" >nul 2>nul
    )
)

if exist "%OLD_DIR%\.windows-installed" (
    copy /Y "%OLD_DIR%\.windows-installed" "%NEW_DIR%\.windows-installed" >nul 2>nul
)

rem Restore podcasts folder if exists
if exist "%OLD_DIR%\podcasts" (
    if not exist "%NEW_DIR%\podcasts" (
        robocopy "%OLD_DIR%\podcasts" "%NEW_DIR%\podcasts" /E /MOVE /R:3 /W:1 /NFL /NDL >nul 2>nul
    )
)

rem Restore sounds folder if exists (preserves user customizations)
if exist "%OLD_DIR%\sounds" (
    if not exist "%NEW_DIR%\sounds" (
        robocopy "%OLD_DIR%\sounds" "%NEW_DIR%\sounds" /E /MOVE /R:3 /W:1 /NFL /NDL >nul 2>nul
    )
)

:restore_done
endlocal
exit /b 0

:cleanup_success
setlocal
set "BACKUP_DIR=%~1"
set "STAGING_DIR=%~2"
set "TEMP_ROOT=%~3"
set "KEEP_BACKUP=0"

call :should_keep_backup "%BACKUP_DIR%" "%INSTALL_DIR%"

if "%KEEP_BACKUP%"=="1" (
    echo [BlindRSS Update] Keeping backup for safety: "%BACKUP_DIR%"
) else (
    call :safe_rmdir "%BACKUP_DIR%" "backup" "%INSTALL_DIR%_backup_"
)

call :safe_rmdir "%STAGING_DIR%" "staging" "BlindRSS_update_"

if "%TEMP_ROOT%"=="" (
    call :derive_temp_root "%STAGING_DIR%"
)

if not "%TEMP_ROOT%"=="" (
    call :schedule_temp_cleanup "%TEMP_ROOT%"
)

endlocal
exit /b 0

:should_keep_backup
setlocal
set "BACKUP_DIR=%~1"
set "INSTALL_DIR=%~2"
set "KEEP=0"

if not exist "%BACKUP_DIR%" goto :keep_done
if not exist "%INSTALL_DIR%" goto :keep_done

if exist "%BACKUP_DIR%\config.json" if not exist "%INSTALL_DIR%\config.json" set "KEEP=1"

for %%F in (rss.db rss.db-wal rss.db-shm rss.db-journal) do (
    if exist "%BACKUP_DIR%\%%F" if not exist "%INSTALL_DIR%\%%F" set "KEEP=1"
)

if exist "%BACKUP_DIR%\.windows-installed" if not exist "%INSTALL_DIR%\.windows-installed" set "KEEP=1"

if exist "%BACKUP_DIR%\podcasts" if not exist "%INSTALL_DIR%\podcasts" set "KEEP=1"

if exist "%BACKUP_DIR%\sounds" if not exist "%INSTALL_DIR%\sounds" set "KEEP=1"

:keep_done
endlocal & set "KEEP_BACKUP=%KEEP%"
exit /b 0

:derive_temp_root
setlocal
set "STAGING_DIR=%~1"
if "%STAGING_DIR%"=="" goto :derive_done

for %%I in ("%STAGING_DIR%") do (
    set "STAGING_DIR=%%~fI"
    set "STAGING_NAME=%%~nxI"
    set "STAGING_PARENT=%%~dpI"
)

if /I "%STAGING_NAME%"=="extract" (
    endlocal & set "TEMP_ROOT=%STAGING_PARENT%" & exit /b 0
)

for %%I in ("%STAGING_PARENT%.") do (
    set "STAGING_PARENT=%%~fI"
    set "PARENT_NAME=%%~nxI"
    set "PARENT_PARENT=%%~dpI"
)

if /I "%PARENT_NAME%"=="extract" (
    endlocal & set "TEMP_ROOT=%PARENT_PARENT%" & exit /b 0
)

:derive_done
endlocal & set "TEMP_ROOT="
exit /b 0

:schedule_temp_cleanup
setlocal
set "TEMP_ROOT=%~1"
if "%TEMP_ROOT%"=="" goto :schedule_done

start "" /b powershell -NoProfile -WindowStyle Hidden -Command "param([string]$path,[string]$install) Start-Sleep -Seconds 2; try { if (-not $path) { return }; $full=[IO.Path]::GetFullPath($path); $inst=[IO.Path]::GetFullPath($install); if ($full -ieq $inst) { return }; if ($full -notmatch 'BlindRSS_update_') { return }; if (Test-Path -LiteralPath $full -PathType Container) { Remove-Item -LiteralPath $full -Recurse -Force -ErrorAction SilentlyContinue }; $parent = Split-Path -Parent $full; if ((Split-Path -Leaf $parent) -ieq '_BlindRSS_update_tmp') { if (-not (Get-ChildItem -LiteralPath $parent -Force | Select-Object -First 1)) { Remove-Item -LiteralPath $parent -Recurse -Force -ErrorAction SilentlyContinue } } } catch { }" "%TEMP_ROOT%" "%INSTALL_DIR%" >nul 2>nul

:schedule_done
endlocal
exit /b 0

:start_log_window
setlocal
set "LOG_FILE=%~1"
set "SENTINEL=%~2"
if "%LOG_FILE%"=="" goto :start_done

start "" cmd /c powershell -NoProfile -Command "param([string]$log,[string]$sent) Write-Host 'BlindRSS update in progress...'; if (Test-Path -LiteralPath $log) { Get-Content -LiteralPath $log -Wait | ForEach-Object { $_; if ($_ -eq $sent) { break } } } else { Write-Host 'Update log not found.'; Start-Sleep -Seconds 3 }" "%LOG_FILE%" "%SENTINEL%"

:start_done
endlocal
exit /b 0

:safe_rmdir
setlocal
set "TARGET=%~1"
set "LABEL=%~2"
set "REQUIRED_SUBSTR=%~3"
if "%TARGET%"=="" goto :safe_done

for %%I in ("%TARGET%") do set "TARGET=%%~fI"
if not exist "%TARGET%" goto :safe_done
if /I "%TARGET%"=="%INSTALL_DIR%" goto :safe_done
if /I "%TARGET%"=="%SystemRoot%" goto :safe_done
if /I "%TARGET%"=="%SystemDrive%\" goto :safe_done

if not "%REQUIRED_SUBSTR%"=="" (
    echo(%TARGET%| find /I "%REQUIRED_SUBSTR%" >nul
    if errorlevel 1 goto :safe_done
)

rmdir /s /q "%TARGET%" >nul 2>nul
echo [BlindRSS Update] Cleaned %LABEL% "%TARGET%"

:safe_done
endlocal
exit /b 0

:usage
echo Usage: update_helper.bat ^<pid^> ^<install_dir^> ^<staging_dir^> ^<exe_name^> [temp_root]
echo    or: update_helper.bat --installer ^<pid^> ^<install_dir^> ^<installer.exe^> [temp_root]
exit /b 1
