@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo === OhMyMeme: dev ^-^> main ===
echo.

::: 检查 git 是否可用
where git >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到 git，请先安装 Git
    pause
    exit /b 1
)

::: 确保在 git 仓库中
git rev-parse --git-dir >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 当前目录不是 Git 仓库
    pause
    exit /b 1
)

echo [1/4] 切换到 main 分支
git checkout main
if %errorlevel% neq 0 (
    echo [错误] 切换到 main 失败，请先提交或贮藏当前工作
    pause
    exit /b 1
)

echo [2/4] 拉取远端更新
git fetch --all
if %errorlevel% neq 0 (
    echo [警告] fetch 失败，继续尝试合并...
)

echo [3/4] 将 dev 合并到 main
git merge dev
if %errorlevel% neq 0 (
    echo [错误] 合并冲突，请手动解决后提交
    pause
    exit /b 1
)

echo [4/4] 推送到远端
git push origin main
if %errorlevel% neq 0 (
    echo [警告] push 失败，请检查远程仓库权限
    pause
    exit /b 1
)

echo [5/5] 切回 dev 分支
git checkout dev
if %errorlevel% neq 0 (
    echo [错误] 切回 dev 失败
    pause
    exit /b 1
)

echo.
echo === 完成！dev 已合并到 main 并切回 dev 分支 ===
pause
