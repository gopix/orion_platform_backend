@echo off
echo Cleaning Python bytecode cache...
cd /d C:\Orion\codebase\orion_backend

REM Delete ALL __pycache__ directories under src\
for /d /r "src" %%d in (__pycache__) do (
    echo Deleting: %%d
    rmdir /s /q "%%d"
)

echo.
echo Done! Now restart the server.
echo Run:  uvicorn main:app --host 0.0.0.0 --port 8000
