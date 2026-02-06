@echo off
setlocal

REM ==================================================
REM この bat がある場所（リポジトリ直下）へ移動
REM ==================================================
cd /d "%~dp0"

REM ==================================================
REM venv 作成（なければ）
REM ==================================================
if not exist ".venv\Scripts\python.exe" (
    echo [INFO] Creating venv...
    python -m venv .venv
)

REM ==================================================
REM venv 有効化
REM ==================================================
call ".venv\Scripts\activate.bat"

REM ==================================================
REM pip 更新
REM ==================================================
echo [INFO] Upgrading pip...
python -m pip install --upgrade pip

REM ==================================================
REM requirements インストール
REM ==================================================
if exist "src\requirements.txt" (
    echo [INFO] Installing dependencies from src/requirements.txt...
    python -m pip install -r src\requirements.txt
) else (
    echo [ERROR] src\requirements.txt not found. Abort.
    pause
    exit /b 1
)


REM ==================================================
REM インストール確認（デバッグ用）
REM ==================================================
echo [INFO] Installed packages:
python -m pip list

REM ==================================================
REM アプリ起動
REM ==================================================
echo [INFO] Starting application...
python -m src.main

pause
endlocal
