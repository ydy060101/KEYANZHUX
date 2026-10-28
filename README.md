[README.md](https://github.com/user-attachments/files/34062957/README.md)
# 科研助手 Agent

> 基于大模型的科研 PDF 阅读、文档问答、工具调用 Agent 项目，AI 协同迭代开发。

## ✨ 项目简介

本项目为 AI 协同开发的科研助手 Agent，支持 PDF/文档解析、长文本上下文压缩、模型网关调度、工具链调用，面向科研文献阅读、资料检索、智能问答场景。项目全程分模块迭代开发，所有 Git 提交对应独立功能迭代与 AI 对话链路，开发过程、Bug 修复 Prompt 记录在 `prompt_log.txt`。

## 📦 环境前置（10 分钟复现）

### 基础依赖
- 系统：Windows / Linux / WSL
- 运行时：PowerShell / Bash
- 模型：支持 Claude / DeepSeek 等兼容 OpenAI 协议模型，自备 API Key 与中转网关

### 依赖安装
```powershell
# 拉取代码
git clone https://github.com/ydy060101/KEYANZHUX.git
cd KEYANZHUX

# 安装依赖
pip install -r requirements.txt
```

### 环境变量配置
复制环境模板，修改里面的密钥、中转地址、模型名称
```powershell
# Windows
copy .env.example .env

# Linux
cp .env.example .env
```

`.env` 示例：
```env
# LLM 中转网关地址
LLM_BASE_URL=
# API 密钥
LLM_API_KEY=
# 默认模型名称
LLM_MODEL=
# 文档存放目录
DOC_PATH=./docs
# 上下文最大 token 上限
MAX_CONTEXT_TOKEN=80000
```

## 🚀 启动方式

### PowerShell 一键启动
```powershell
.\工具.ps1
```

### 直接启动主程序
```powershell
python main.py
```

## 📁 目录结构

```
KEYANZHUX/
├── AGENTS.md            # Agent 角色定义、系统提示词
├── CHANGE_REQUESTS.md   # 迭代需求记录
├── DEPENDENCIES.md      # 依赖说明
├── PROGRESS.md          # 开发进度跟踪
├── QUESTIONS.md         # 问题与待确认事项
├── README.md            # 复现指南（本文件）
├── prompt_log.txt       # AI 对话 Prompt 快照
├── .env.example         # 环境变量模板
├── requirements.txt     # 依赖清单
├── main.py              # 程序入口
├── docs/                # 文档存放目录
├── logs/                # 日志输出目录
└── screenshot/          # AI 对话截图
```

## 🧩 核心功能

| 模块 | 功能说明 |
|---|---|
| 文档解析 | 支持 PDF / TXT 文档读取，长文本分段与上下文压缩 |
| 智能问答 | 基于文档内容的 RAG 问答，无依据问题自动拒答 |
| 模型网关 | 统一封装多模型调用，支持 fast / strong 分层调度 |
| 工具链 | 支持文件检索、文本处理等外部工具调用 |
| 上下文管理 | 长文本自动压缩，控制 token 上限，避免超限报错 |

## 📖 AI 协同开发说明

本项目分 3 轮核心迭代，每一轮迭代均保留完整对话记录，对应 Git 原子化提交：

1. **迭代 1：项目骨架搭建** —— 搭建 Agent 目录结构、网关配置
2. **迭代 2：文档解析模块** —— PDF 读取、文本解析，修复路径报错
3. **迭代 3：上下文压缩** —— 长文本处理，解决 token 超限异常

完整对话快照见 `prompt_log.txt`，对话截图见 `screenshot/` 目录。

## 🧪 验证方式

```powershell
# 运行主程序
python main.py

# 加载文档后提问，验证问答与工具调用
```

## 📄 交付物清单

- 完整前后端源码，可一键启动
- `README.md` 复现指南
- `.env.example` 环境变量模板
- `prompt_log.txt` AI 对话 Prompt 快照
- 技术文档 PDF（≤30 页）
- 演示视频（5-8 分钟，MP4 1080p）

## 📝 License

内部科研原型项目。
