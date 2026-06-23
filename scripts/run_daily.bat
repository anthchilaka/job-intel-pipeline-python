@echo off
setlocal enabledelayedexpansion
REM ============================================================
REM  Job Intel Pipeline — Daily Collection
REM  Layer 1: all source scripts per user
REM  Scheduled run: 5:00 AM daily via Windows Task Scheduler
REM
REM  ARCHITECTURE: Option A — single bat, all configs
REM  To add a new user: copy a user block below and update
REM  the name and config path. One scheduled task handles all.
REM ============================================================

set SCRIPTS_DIR=%~dp0
set CONFIG_DIR=%~dp0..\config
set LOG_DIR=%~dp0..\logs

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

echo. >> "%LOG_DIR%\run_log.txt"
echo ============================================================ >> "%LOG_DIR%\run_log.txt"
echo [%date% %time%] -- Job Intel Pipeline daily run started >> "%LOG_DIR%\run_log.txt"
echo ============================================================ >> "%LOG_DIR%\run_log.txt"

REM ── DNS READINESS CHECK ──────────────────────────────────────
REM  Waits up to 3 minutes for DNS to resolve after wake-from-sleep.
REM  Scripts exit 0 even on network failure, so Task Scheduler retries
REM  never fire. This pre-check catches the gap before any script runs.
set DNS_ATTEMPTS=0
:DNSCHECK
ping -n 1 -w 2000 8.8.8.8 >nul 2>&1
if !ERRORLEVEL! EQU 0 goto DNSREADY
set /a DNS_ATTEMPTS+=1
echo [%date% %time%] -- DNS not ready (attempt !DNS_ATTEMPTS!/6), waiting 30s... >> "%LOG_DIR%\run_log.txt"
if !DNS_ATTEMPTS! GEQ 6 (
    echo [%date% %time%] -- DNS check failed after 3 minutes. Aborting run. >> "%LOG_DIR%\run_log.txt"
    echo. >> "%LOG_DIR%\run_log.txt"
    exit /b 1
)
timeout /t 30 /nobreak >nul
goto DNSCHECK
:DNSREADY
echo [%date% %time%] -- Network ready (DNS resolved after !DNS_ATTEMPTS! wait(s)) >> "%LOG_DIR%\run_log.txt"
REM ─────────────────────────────────────────────────────────────

cd /d "%SCRIPTS_DIR%"


REM ── USER 1 (primary) ────────────────────────────────────────

echo [%date% %time%] -- Running: User1 (LinkedIn A+B) >> "%LOG_DIR%\run_log.txt"
python collect_jobs.py --config "%CONFIG_DIR%\user1.json" >> "%LOG_DIR%\run_log.txt" 2>&1
set ERR=!ERRORLEVEL!
if !ERR! EQU 0 (echo [%date% %time%] -- User1 LinkedIn: OK >> "%LOG_DIR%\run_log.txt") else (echo [%date% %time%] -- User1 LinkedIn: FAILED code !ERR! >> "%LOG_DIR%\run_log.txt")

echo [%date% %time%] -- Running: User1 (JobSpy Source D) >> "%LOG_DIR%\run_log.txt"
python collect_jobspy.py --config "%CONFIG_DIR%\user1.json" >> "%LOG_DIR%\run_log.txt" 2>&1
set ERR=!ERRORLEVEL!
if !ERR! EQU 0 (echo [%date% %time%] -- User1 JobSpy: OK >> "%LOG_DIR%\run_log.txt") else (echo [%date% %time%] -- User1 JobSpy: FAILED code !ERR! >> "%LOG_DIR%\run_log.txt")

echo [%date% %time%] -- Running: User1 (WeWorkRemotely) >> "%LOG_DIR%\run_log.txt"
python collect_wwr.py --config "%CONFIG_DIR%\user1.json" >> "%LOG_DIR%\run_log.txt" 2>&1
set ERR=!ERRORLEVEL!
if !ERR! EQU 0 (echo [%date% %time%] -- User1 WWR: OK >> "%LOG_DIR%\run_log.txt") else (echo [%date% %time%] -- User1 WWR: FAILED code !ERR! >> "%LOG_DIR%\run_log.txt")

echo [%date% %time%] -- Running: User1 (WorkAtAStartup) >> "%LOG_DIR%\run_log.txt"
python collect_waas.py --config "%CONFIG_DIR%\user1.json" >> "%LOG_DIR%\run_log.txt" 2>&1
set ERR=!ERRORLEVEL!
if !ERR! EQU 0 (echo [%date% %time%] -- User1 WAAS: OK >> "%LOG_DIR%\run_log.txt") else (echo [%date% %time%] -- User1 WAAS: FAILED code !ERR! >> "%LOG_DIR%\run_log.txt")

REM Wellfound parked — DataDome CAPTCHA blocks headless Playwright (OPEN issue)
REM python collect_wellfound.py --config "%CONFIG_DIR%\user1.json" >> "%LOG_DIR%\run_log.txt" 2>&1


REM ── USER 2 (second user / mentee — illustrates the multi-tenant pattern) ──

echo [%date% %time%] -- Running: User2 (LinkedIn A+B) >> "%LOG_DIR%\run_log.txt"
python collect_jobs.py --config "%CONFIG_DIR%\mentees\user2.json" >> "%LOG_DIR%\run_log.txt" 2>&1
set ERR=!ERRORLEVEL!
if !ERR! EQU 0 (echo [%date% %time%] -- User2 LinkedIn: OK >> "%LOG_DIR%\run_log.txt") else (echo [%date% %time%] -- User2 LinkedIn: FAILED code !ERR! >> "%LOG_DIR%\run_log.txt")

echo [%date% %time%] -- Running: User2 (JobSpy Source D) >> "%LOG_DIR%\run_log.txt"
python collect_jobspy.py --config "%CONFIG_DIR%\mentees\user2.json" >> "%LOG_DIR%\run_log.txt" 2>&1
set ERR=!ERRORLEVEL!
if !ERR! EQU 0 (echo [%date% %time%] -- User2 JobSpy: OK >> "%LOG_DIR%\run_log.txt") else (echo [%date% %time%] -- User2 JobSpy: FAILED code !ERR! >> "%LOG_DIR%\run_log.txt")

echo [%date% %time%] -- Running: User2 (WeWorkRemotely) >> "%LOG_DIR%\run_log.txt"
python collect_wwr.py --config "%CONFIG_DIR%\mentees\user2.json" >> "%LOG_DIR%\run_log.txt" 2>&1
set ERR=!ERRORLEVEL!
if !ERR! EQU 0 (echo [%date% %time%] -- User2 WWR: OK >> "%LOG_DIR%\run_log.txt") else (echo [%date% %time%] -- User2 WWR: FAILED code !ERR! >> "%LOG_DIR%\run_log.txt")

echo [%date% %time%] -- Running: User2 (WorkAtAStartup) >> "%LOG_DIR%\run_log.txt"
python collect_waas.py --config "%CONFIG_DIR%\mentees\user2.json" >> "%LOG_DIR%\run_log.txt" 2>&1
set ERR=!ERRORLEVEL!
if !ERR! EQU 0 (echo [%date% %time%] -- User2 WAAS: OK >> "%LOG_DIR%\run_log.txt") else (echo [%date% %time%] -- User2 WAAS: FAILED code !ERR! >> "%LOG_DIR%\run_log.txt")


REM ── ADD NEW USERS BELOW THIS LINE ─────────────────────────────
REM  Copy the User2 block above, update name and config path.


echo [%date% %time%] -- Daily run complete >> "%LOG_DIR%\run_log.txt"
echo. >> "%LOG_DIR%\run_log.txt"
endlocal
