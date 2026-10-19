#!/bin/bash
# macOS / Linux：双击（Mac）或在终端里运行 bash run_mac.command
cd "$(dirname "$0")" || exit 1

PY=python3
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "没找到 python3。请先安装 Python 3.10 或更高版本：https://www.python.org/downloads/"
  read -r -n1 -p "按任意键关闭"; exit 1
fi

if [ ! -f .venv/.ok ]; then
  echo "首次运行：创建独立环境并安装依赖，只需要一次，大约 1~3 分钟……"
  "$PY" -m venv .venv || { echo "创建环境失败"; read -r -n1; exit 1; }
  .venv/bin/python -m pip install -q -U pip
  if ! .venv/bin/python -m pip install -r requirements.txt; then
    .venv/bin/python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple || {
      echo "依赖安装失败。把上面的报错截图发给 Claude 就能帮你看。"; read -r -n1; exit 1; }
  fi
  echo ok > .venv/.ok
fi

.venv/bin/python lab.py "$@"
RUN_CODE=$?
echo
read -r -n1 -p "按任意键关闭"
exit "$RUN_CODE"
