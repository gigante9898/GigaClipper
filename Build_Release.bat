@echo off
REM Force working directory to script location (fixes Admin run from System32)
cd /d "%~dp0"
echo Working Directory: %cd%
echo.
echo [1/3] Building Python Backend (Standalone .exe)...
pyinstaller LocalMedalEngine.spec --noconfirm --clean

echo.
echo [2/3] Building Frontend (React/Vite)...
cd ElectronMedal
call npm run build

echo.
echo [3/3] Packaging Electron App (Installer) ...
set GH_TOKEN=ghp_z1upWi5Cel5IgusX3oxP4PcefM1u01X04Ua
call npm exec electron-builder -- --win --publish always

echo.
echo ========================================================
echo BUILD COMPLETE!
echo You can find the installer in: ElectronMedal/release/
echo Transfer that .exe to your friend's PC.
echo ========================================================
pause
