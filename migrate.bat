@echo off
rem Run every script in migrations\ in order. Each script checks the current state first, so running this again is safe.
rem NLS_LANG must be AL32UTF8 so SQL*Plus reads the Thai text in the .sql files correctly.
set NLS_LANG=AMERICAN_AMERICA.AL32UTF8
if "%ORACLE_USER%"=="" set ORACLE_USER=pharmacy_demo
if "%ORACLE_PASSWORD%"=="" set ORACLE_PASSWORD=pharmacy_demo
if "%ORACLE_DSN%"=="" set ORACLE_DSN=localhost:1521/XEPDB1
for %%f in ("%~dp0migrations\*.sql") do (
    echo ---- %%~nxf
    echo exit | sqlplus -S -L %ORACLE_USER%/%ORACLE_PASSWORD%@%ORACLE_DSN% @"%%f"
)
if not "%1"=="nopause" pause
