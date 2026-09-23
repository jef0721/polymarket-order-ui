#!/bin/zsh
cd "$(dirname "$0")"
if [[ -x .venv/bin/python ]]; then
  .venv/bin/python web_app.py --open
  if [[ $? -ne 0 ]]; then
    echo '启动失败：请检查依赖是否安装，或页面是否已在运行。'
    read '?按回车关闭'
  fi
  exit
fi
CONDA_BIN="$(command -v conda)"
if [[ ! -x "$CONDA_BIN" ]]; then
  for candidate in /opt/miniconda3/bin/conda "$HOME/miniconda3/bin/conda" "$HOME/anaconda3/bin/conda" /opt/anaconda3/bin/conda; do
    if [[ -x "$candidate" ]]; then CONDA_BIN="$candidate"; break; fi
  done
fi
if [[ ! -x "$CONDA_BIN" ]]; then
  echo '未找到 .venv 或 Conda 环境。请按 README 首次安装步骤创建环境。'
  read '?按回车关闭'
  exit 1
fi
"$CONDA_BIN" run --no-capture-output -n polymarket python web_app.py --open
if [[ $? -ne 0 ]]; then
  echo '启动失败：请检查 polymarket 环境是否安装，或页面是否已在运行。'
  read '?按回车关闭'
fi
