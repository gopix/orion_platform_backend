@echo off

echo Showing __pycache__ directories...
for /d /r . %%d in (__pycache__) do (
    if exist "%%d" echo %%d
)

echo Deleting __pycache__ directories...
for /d /r . %%d in (__pycache__) do (
    if exist "%%d" rd /s /q "%%d"
)

echo Done.
pause