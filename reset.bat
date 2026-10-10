@echo off
rem Reset demo data: clears queue/chat/prescription/order/payment/receipt rows and restores stock (drug A = 20).
rem NLS_LANG must be AL32UTF8 so SQL*Plus reads the Thai text in the .sql file correctly.
set NLS_LANG=AMERICAN_AMERICA.AL32UTF8
if "%ORACLE_USER%"=="" set ORACLE_USER=pharmacy_demo
if "%ORACLE_PASSWORD%"=="" set ORACLE_PASSWORD=pharmacy_demo
if "%ORACLE_DSN%"=="" set ORACLE_DSN=localhost:1521/XEPDB1
echo exit | sqlplus -S -L %ORACLE_USER%/%ORACLE_PASSWORD%@%ORACLE_DSN% @"%~dp0sql\reset.sql"
pause
