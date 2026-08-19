@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0.."
setlocal enabledelayedexpansion

echo === OhMyMeme-Android: dev ^> main ===
echo.

where git >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到 git，请先安装 Git
    pause
    exit /b 1
)

git rev-parse --git-dir >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 当前目录不是 Git 仓库
    pause
    exit /b 1
)

:: 自动贮藏未提交更改
git stash push -m "merge-dev-auto-stash" >nul 2>&1
if %errorlevel% equ 0 (
    set HAS_STASH=1
    echo [信息] 已自动贮藏未提交的更改
) else (
    set HAS_STASH=0
)

echo [1/5] 切换到 main 分支
git checkout main
if %errorlevel% neq 0 (
    echo [错误] 切换到 main 失败
    if !HAS_STASH! equ 1 git stash pop >nul 2>&1
    pause
    exit /b 1
)

echo [2/5] 拉取远端更新
git fetch --all
if %errorlevel% neq 0 (
    echo [警告] fetch 失败，继续尝试合并
)

echo [3/5] 合并 dev 到 main
git merge dev
if %errorlevel% neq 0 (
    echo [错误] 合并冲突，请手动解决
    echo 解决后运行: git commit ^&^& git push origin main ^&^& git checkout dev
    if !HAS_STASH! equ 1 git stash pop >nul 2>&1
    pause
    exit /b 1
)

echo [4/5] 推送到远端
git push origin main
if %errorlevel% neq 0 (
    echo [警告] push 失败，请检查远程仓库权限
    if !HAS_STASH! equ 1 git stash pop >nul 2>&1
    pause
    exit /b 1
)

echo [5/5] 切回 dev 分支
git checkout dev
if %errorlevel% neq 0 (
    echo [错误] 切回 dev 失败
    if !HAS_STASH! equ 1 git stash pop >nul 2>&1
    pause
    exit /b 1
)

if !HAS_STASH! equ 1 (
    git stash pop >nul 2>&1
    if %errorlevel% neq 0 (
        echo [警告] 贮藏恢复失败，请手动运行: git stash pop
    ) else (
        echo [信息] 已恢复贮藏的更改
    )
)

echo.
echo === 完成！dev 已合并到 main 并切回 dev 分支 ===
pause
