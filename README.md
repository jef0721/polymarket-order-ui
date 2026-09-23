# Polymarket 本地下单台

## 首次安装

不需要 Anaconda。先安装 Python 3.12，然后在终端进入项目文件夹。

macOS / Linux：

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python web_app.py --open
```

Windows PowerShell：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe web_app.py --open
```

如果已经安装 Miniconda，也可以使用：

```bash
conda create -n polymarket python=3.12 pip -y
conda activate polymarket
python -m pip install -r requirements.txt
python web_app.py --open
```

如果已存在环境，跳过创建步骤。Mac 首次安装完成后可双击“启动下单页面.command”；它会优先使用项目内的 `.venv`，否则使用名为 `polymarket` 的 Conda 环境。

## 配置自己的账户

在 http://127.0.0.1:8765 点击右上角“新建用户”，填写你有权使用的签名私钥和对应的 Polymarket 账户钱包地址，再保存。每次更换需要同时输入两项。保存先做本地格式检查；页面随后检查当前网络、账户认证和买入余额／授权，不提交订单。

“清除当前配置”会删除本机 `.env` 中的签名私钥和钱包地址，并使已有预览失效。状态区的“具备基础条件”并不保证某笔订单成功；余额、持仓、市场状态及平台限制仍可能导致拒单。当前网络受限时不会尝试账户认证。

地区检查按 [Polymarket 官方 API 地区规则](https://docs.polymarket.com/api-reference/geoblock)解释。部分地区（包括日本）的网页端受限，但 API 下单不受该项限制；页面会分别提示。其他受限地区仍会在提交订单前被拦截。

私钥以明文保存在这台电脑的 `.env` 中，程序将文件权限设为仅当前用户可读写。页面不回显私钥，不使用浏览器本地存储保存私钥。不要分享 `.env`、配置临时文件或整个已配置的项目文件夹。

## 下单

粘贴赛事或具体子市场链接，点击“读取市场”，从列表中选择具体子市场及其结果。也可以直接填写市场 slug。然后选择买入或卖出，填写价格与份数，点击“预览订单”。核对账户、市场和金额后，点击“确认并下单”，再在弹窗中提交真实订单。

支持二选一市场（包括 YES / NO、队伍胜负和 Over / Under）的 GTC 限价买入和卖出。卖出需要持有对应结果的足够份额；卖出价格是每份最低接受价，预览收入为扣费前下限。未成交部分持续挂单；撤单和持仓管理请到同一账户的 Polymarket 网页操作。预览有效期为 2 分钟。超时不等于失败，请先核对挂单和成交记录，避免重复下单。

交易需要足够余额、必要授权和平台允许的交易资格。服务只监听本机地址，不要把它开放到公网。配置是本机共用的，不是多用户托管账户系统。

## 公开仓库注意

本仓库不包含任何私钥或个人账户地址。首次使用请在本机网页中新建用户配置。请勿将 `.env`、本机备份、日志或真实凭证上传至 GitHub。使用 GitHub 网页手动上传时，也要逐项核对文件列表。
