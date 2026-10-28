# 运行 `ResearchAssistant.exe`

`release/ResearchAssistant.exe` 是一个**便携启动器**，不是把整个系统塞进单文件的绿色版。

它负责：

1. 启动仓库旁的便携 PostgreSQL（`127.0.0.1:55432`）与 Redis（`127.0.0.1:56379`）；
2. 启动后端 API（`127.0.0.1:8000`）与 arq worker；
3. 用系统浏览器打开 `http://127.0.0.1:8000/` —— 后端直接提供 `frontend/dist` 里构建好的前端。

它不包含 Python、Node、PostgreSQL、Redis、torch/Paddle 或 bge 模型。双击能用的前提是**整套目录仍然完整**：`backend/.venv`、`frontend/dist`、`.env`，以及 `D:\科研助手-runtime`（或 `RA_RUNTIME` 指向的运行时）。因此适合“把整个项目目录复制到另一台 Windows 机器”，不适合只拷贝一个 exe。

## 构建

```powershell
cd D:\科研助手
.\tools.ps1 exe
```

脚本会先执行 `npm run build`，再用 PyInstaller 生成：

```
release\ResearchAssistant.exe
```

首次构建需要 `backend\.venv` 中装有 PyInstaller（`pip install -e ".[dev]"` 已包含）。

## 使用

把 exe 放在仓库根目录或 `release/` 下，双击即可。命令行选项：

```powershell
release\ResearchAssistant.exe --check        # 只检查目录、端口与依赖，不启动
release\ResearchAssistant.exe --no-browser   # 启动但不打开浏览器
```

- 启动日志：`data/logs/api.log`、`data/logs/worker.log`、`data/logs/redis.log`；
- 关闭控制台窗口或按 `Ctrl+C` 会停止**本次启动的** API 与 worker；PostgreSQL/Redis 保持运行；
- 再次双击时，如果已有启动器在运行，只会打开页面，不会重复启动服务；
- API/worker 已在运行时（例如开发模式），启动器会复用 API，并补上 worker。

## 前置条件

| 项目 | 要求 |
|---|---|
| Python | `backend\.venv` 已按 README/AGENTS 安装依赖 |
| 前端 | `frontend\dist\index.html` 存在（`.\tools.ps1 exe` 会自动构建） |
| 数据库 | 便携 PostgreSQL 位于项目同级的 `*-runtime\pgsql`（启动器会自动扫描），或设置 `RA_RUNTIME` |
| Redis | 同一运行时的 `redis\redis-server.exe`，或已在 `56379` 运行 |
| 配置 | 根目录 `.env`（模型 key、数据库连接） |
| 模型 | `.runtime/models` 中已有 bge-m3 / bge-reranker（首次问答/检索会加载） |

如果目标机器没有便携运行时，可先用 `.\tools.ps1 db-up` 在本机准备好，或把 `D:\科研助手-runtime` 一起复制过去并设置：

```powershell
$env:RA_RUNTIME = "D:\path\to\科研助手-runtime"
```

## 常见问题

- **端口被占用**：`--check` 会显示 55432 / 56379 / 8000 的状态；先关闭旧的 API 或数据库进程。
- **页面空白**：确认 `frontend/dist/index.html` 存在，并重新执行 `.\tools.ps1 exe`。
- **API 起不来**：看 `data/logs/api.log`，常见原因是 `.env` 中的数据库密码或模型 key 未配置。
- **worker 退出**：看 `data/logs/worker.log`；OCR/模型缺失只会让对应功能降级，不应导致 API 崩溃。

## 自检

启动器运行后，可用打包烟测脚本确认 SPA 与六个模块页面都正常：

```powershell
cd frontend
node e2e/verify-exe.mjs http://127.0.0.1:8000
```

它会在 1440×900 与 1280×720 下打开 `/`、`/library`、`/qa`、`/discover`、`/graph`、`/writing`，检查导航壳、横向溢出、控制台错误和失败请求。

开发模式仍然使用 `.\tools.ps1 dev`（Vite `5173` + API `8000`），与启动器互不影响。
