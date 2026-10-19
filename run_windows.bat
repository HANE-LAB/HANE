@echo off
chcp 65001 >nul
cd /d "%~dp0"
title HANE

set "PY=python"
where py >nul 2>nul && set "PY=py -3"

if not exist ".venv\.ok" (
  echo 首次运行：创建独立环境并安装依赖，只需要一次，大约 1~3 分钟……
  %PY% -m venv .venv || goto :nopy
  ".venv\Scripts\python" -m pip install -q -U pip
  ".venv\Scripts\python" -m pip install -r requirements.txt || ".venv\Scripts\python" -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple || goto :fail
  echo ok> ".venv\.ok"
)

".venv\Scripts\python" lab.py %*
set "RUN_CODE=%ERRORLEVEL%"
echo.
pause
exit /b %RUN_CODE%

:nopy
echo.
echo 没找到 Python。请先安装 Python 3.10 或更高版本：https://www.python.org/downloads/
echo 安装时记得勾选「Add Python to PATH」，装好后再双击本文件。
pause
exit /b 1

:fail
echo.
echo 依赖安装失败。把上面的报错截图发给 Claude 就能帮你看。
pause
exit /b 1
