# MiniMall V1.0 测试工程说明

MiniMall 是一个用于“软件测试实战”的本地 Web 商城被测系统。项目包含 Web 前端、REST API 后端、MySQL 数据库，以及配套的 Python 接口自动化、数据库校验和 Playwright UI 自动化测试。

本文档面向测试岗位求职展示，重点说明如何安装、配置、运行测试，以及如何查看报告和排查常见问题。

## 测试范围

当前 Python 自动化测试覆盖以下模块：

- 登录：正确登录、错误密码、空密码、手机号格式错误、Token 复用。
- 商品：UI 商品搜索，包括存在商品和无结果场景。
- 购物车：接口添加商品、UI 加入购物车、数量变化和小计校验。
- 订单：接口创建订单并动态查询，UI 创建订单并取消订单。
- 支付：接口支付失败、支付成功、重复支付；UI 支付状态流转。
- 数据库校验：通过接口创建订单后，用参数化 SQL 查询 MySQL，对比接口数据和数据库数据。

当前 pytest 可收集到 16 条测试，其中 API/数据库测试 9 条，UI 测试 7 条。

## 目录结构

```text
MiniMall/
├─ backend/                  后端 REST API
├─ frontend/                 Web 前端页面
├─ database/                 数据库初始化 SQL
├─ python_api_tests/         API 自动化与数据库校验测试
│  ├─ config.py              Python 测试公共配置
│  ├─ conftest.py            登录 Token、数据库连接 fixture
│  └─ test_*.py              API/DB 测试用例
├─ ui_tests/                 Playwright UI 自动化测试
│  ├─ test_ui_*.py           UI 测试用例
│  └─ screenshots/           失败截图目录，已加入 .gitignore
├─ scripts/                  启动、停止、初始化和测试脚本
│  ├─ start.ps1              启动 MiniMall
│  ├─ stop.ps1               停止 MiniMall
│  └─ run_python_tests.ps1   一键运行 Python 自动化测试
├─ reports/                  全量 HTML 测试报告目录，已加入 .gitignore
├─ pytest.ini                pytest 公共配置与标记
├─ requirements.txt          Python 测试依赖
└─ .env.example              本地环境变量示例，不包含真实敏感信息
```

## 环境安装

建议在 PowerShell 中执行：

```powershell
python -m pip install -r requirements.txt
python -m playwright install chromium
```

如果 Python、Node.js 或 MySQL 环境缺失，请先按项目已有启动脚本处理。MiniMall 本身可以通过项目内的 PowerShell 脚本启动。

## 启动 MiniMall

启动：

```powershell
.\scripts\start.ps1
```

停止：

```powershell
.\scripts\stop.ps1
```

浏览器访问：

```text
http://localhost:3000
```

## 配置 .env

复制示例文件：

```powershell
Copy-Item .env.example .env
```

然后在 `.env` 中填写本机配置。注意：

- 不要提交真实手机号、密码、数据库密码或 Token。
- `MINIMALL_BASE_URL` 默认可以使用 `http://localhost:3000`。
- 数据库测试需要配置 `DB_HOST`、`DB_PORT`、`DB_NAME`、`DB_USER`、`DB_PASSWORD`。如果数据库密码为空，也要保留 `DB_PASSWORD=` 这一行，表示这是有意配置为空。

## 运行测试

### API 测试

```powershell
.\scripts\run_python_tests.ps1 -Mode api
```

### UI 测试

默认无头运行：

```powershell
.\scripts\run_python_tests.ps1 -Mode ui
```

调试 UI 时可以直接使用 headed 模式：

```powershell
python -m pytest ui_tests -vv --headed
```

### 数据库校验测试

```powershell
.\scripts\run_python_tests.ps1 -Mode db
```

### 全量测试并生成 HTML 报告

```powershell
.\scripts\run_python_tests.ps1 -Mode all
```

HTML 报告位置：

```text
reports/minimall_test_report.html
```

打开报告：

```powershell
Start-Process .\reports\minimall_test_report.html
```

## pytest 标记

已注册的标记：

- `api`：接口自动化测试。
- `ui`：UI 自动化测试。
- `db`：数据库校验测试。

也可以直接使用 pytest 标记运行：

```powershell
python -m pytest python_api_tests -m "api and not db" -v
python -m pytest python_api_tests -m db -v
python -m pytest ui_tests -m ui -v
```

## 已覆盖的核心业务链路

- 登录成功和失败校验。
- 登录 Token 通过 fixture 复用。
- 查询购物车只读接口验证登录态。
- 添加购物车后数量增加。
- 创建订单后使用动态 `orderId` 查询订单详情。
- 接口订单与数据库订单字段一致性校验。
- 支付失败后订单仍为待支付。
- 支付成功后订单变为已支付。
- 重复支付被拒绝或按钮隐藏。
- UI 登录、商品搜索、购物车、创建订单、取消订单和支付状态流转。

## 测试数据清理策略

- 购物车测试会在 `try/finally` 中尽量恢复测试前的购物车状态。
- PENDING 订单测试会通过真实取消订单接口清理。
- 数据库校验测试只允许执行 `SELECT`，不使用 SQL 修改数据。
- PAID 订单不能通过业务接口取消，因此支付成功类测试会保留已支付测试订单，这是业务限制，不使用 SQL 强制删除或修改。
- 失败时 UI 测试会保存截图到 `ui_tests/screenshots`，该目录已加入 `.gitignore`。

## 常见错误及排查方法

### 1. Locator 匹配多个元素

现象：Playwright 报错显示一个定位器匹配到了多个元素，例如多个商品名称相同。

处理：不要用商品名作为唯一标识。MiniMall 页面中商品名称可能重复，购物车和订单相关操作优先使用 `productId`、`orderId`、`orderNo` 或按钮 `onclick` 中的唯一参数定位。

### 2. `first` 与 `first()` 的区别

Playwright Python 中 `locator.first` 和 `locator.last` 是属性，不是函数。

正确：

```python
expect(cards.first).to_be_visible()
```

错误：

```python
expect(cards.first()).to_be_visible()
```

### 3. `try/finally` 缩进错误

现象：

```text
SyntaxError: expected 'except' or 'finally' block
```

处理：新增业务步骤时要确认代码仍在原来的 `try` 块内，清理逻辑仍放在 `finally` 中，避免测试失败后无法恢复购物车或订单状态。

### 4. 动态 `orderId` / `orderNo` 定位

订单测试不能使用历史订单号，也不能选择页面第一张或最后一张订单。创建订单后要从真实接口响应或订单详情中提取动态 `orderId` / `orderNo`，再定位本次订单。

如果页面弹窗订单号、创建接口订单号和订单列表展示值不一致，应以后端订单详情或订单列表中的真实持久化数据为准。

### 5. dialog 重复处理或捕获不到

现象：

- `Dialog.accept: No dialog is showing`
- 弹窗消息列表为空

处理：每个弹窗只由一个地方处理。推荐使用同步辅助方法：

```python
def _click_and_accept_dialog(page, locator):
    with page.expect_event("dialog") as dialog_info:
        locator.click()
    dialog = dialog_info.value
    message = dialog.message
    dialog.accept()
    return message
```

不要同时使用全局 `page.on("dialog", ...)` 和局部 `expect_event("dialog")` 处理同一个弹窗。

### 6. Codex 环境 `WinError 5` 无法启动浏览器

在当前受限 Codex 环境中，headed 或 headless Playwright 可能因为 Windows 命名管道权限报：

```text
PermissionError: [WinError 5] 拒绝访问
```

这是运行环境权限问题，不代表测试代码断言失败。此时应在本机 PowerShell 中运行：

```powershell
python -m pytest ui_tests -vv --headed
```

### 7. MiniMall 服务未启动

脚本运行前会检查 `MINIMALL_BASE_URL` 是否可访问。如果服务未启动，会提示：

```text
MiniMall 服务不可访问：http://localhost:3000
请先启动系统，例如运行：.\scripts\start.ps1
```

### 8. 数据库环境变量缺失

数据库测试和全量测试需要 DB 环境变量。如果缺失，脚本会提示缺少哪些变量，不会猜测数据库密码。
