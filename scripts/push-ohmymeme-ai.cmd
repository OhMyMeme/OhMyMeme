@echo off
setlocal EnableExtensions
cd /d "%~dp0.."

set "REMOTE_NAME=fork"
set "BRANCH_NAME=Ohmymeme-AI"
set "REMOTE_URL=https://github.com/luckymolong/OhMyMeme-AI.git"

echo.
echo === OhMyMeme-AI: Push Existing Commits ===
echo This script only pushes existing commits.
echo It never runs git add or git commit.
echo.

where git >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Git was not found. Install Git for Windows first.
    goto :failed
)

git rev-parse --is-inside-work-tree >nul 2>&1
if errorlevel 1 (
    echo [ERROR] This script must be run inside the OhMyMeme repository.
    goto :failed
)

for /f "delims=" %%i in ('git branch --show-current') do set "CURRENT_BRANCH=%%i"
if /I not "%CURRENT_BRANCH%"=="%BRANCH_NAME%" (
    echo [ERROR] Current branch is "%CURRENT_BRANCH%".
    echo [ERROR] Switch to "%BRANCH_NAME%" before pushing.
    goto :failed
)

git remote get-url "%REMOTE_NAME%" >nul 2>&1
if errorlevel 1 (
    echo [INFO] Creating remote "%REMOTE_NAME%".
    git remote add "%REMOTE_NAME%" "%REMOTE_URL%"
    if errorlevel 1 goto :failed
) else (
    echo [INFO] Updating remote "%REMOTE_NAME%" to the renamed repository.
    git remote set-url "%REMOTE_NAME%" "%REMOTE_URL%"
    if errorlevel 1 goto :failed
)

echo.
echo [INFO] The following status is informational only.
echo [INFO] This script does not run git add or git commit.
git status --short

echo.
echo [INFO] Pushing existing commits to %REMOTE_NAME%/%BRANCH_NAME%...
git push --set-upstream "%REMOTE_NAME%" "%BRANCH_NAME%"
if errorlevel 1 (
    echo.
    echo [ERROR] Push failed.
    echo [HINT] Complete the GitHub sign-in prompt if one appeared.
    echo [HINT] Check that your account can write to luckymolong/OhMyMeme-AI.
    goto :failed
)

echo.
echo [SUCCESS] Push completed.
echo https://github.com/luckymolong/OhMyMeme-AI/tree/Ohmymeme-AI
pause
exit /b 0

:failed
echo.
pause
exit /b 1
