@echo off
setlocal enabledelayedexpansion

:: Get the current datetime formatted as YYYY-MM-DD_HH-MM-SS
for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value ^| find "="') do set datetime=%%I
set datetime=%datetime:~0,4%-%datetime:~4,2%-%datetime:~6,2%_%datetime:~8,2%-%datetime:~10,2%-%datetime:~12,2%

:: Define output file with timestamp
set output_file="C:\Users\nnu04\PycharmProjects\projects\appointmentReminder\output_%datetime%.txt"

:: Run the Python script and save output to timestamped file
"C:\Users\nnu04\.conda\envs\projects\python.exe" "C:\Users\nnu04\PycharmProjects\projects\appointmentReminder\apptReminder.py" > %output_file% 2>&1
