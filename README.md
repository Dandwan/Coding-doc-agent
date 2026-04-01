# DocAgent

> 项目管理式需求澄清 Agent：多会话问答、开发文档版本化、项目文档只读参考。

DocAgent 用于帮助用户在需求不完整的情况下，通过多轮选项式问答逐步收敛需求，并持续生成结构化的 Agent 开发文档。系统支持按项目管理会话历史与文档版本，适合作为后续开发 Agent 的输入源。

## 核心特性

- 项目管理
	- 创建/打开/删除项目索引
	- 支持指定已有目录作为项目根目录
	- 保护已有文件：只创建和维护 `meta.json`、`sessions/`、文档目录等受管内容

- 全局配置
	- 配置 `projects_root`、GPT 兼容 API 参数、文档路径规则
	- 持久化到 `~/.docagent/config.json`

- 会话管理
	- 每项目独立会话列表
	- 新建、重命名、删除会话
	- 每会话独立保存历史、待解决清单、当前文档

- 需求澄清交互
	- 每轮 3~5 个选项
	- 动态“其他 / 补充”输入
	- 支持“我认为这个问题不需要回答”跳过逻辑
	- 输入有效性校验（至少选择或补充）

- 文档生成与版本管理
	- 每次提交自动生成文档版本
	- 版本命名：`YYYY-MM-DD_HHMMSS[_NN]_DEVELOPMENT.md`
	- 同步维护 `DEVELOPMENT.md` 最新版
	- 支持历史版本查看、恢复、与最新版对比 diff

- 项目开发文档容错引用
	- 默认读取 `docs/project/PROJECT.md`
	- 文档缺失不阻塞业务，仅提示状态
	- DocAgent 只读该文档，不写入

## 技术栈

- 后端：FastAPI、Pydantic、requests
- 前端：HTML/CSS/JavaScript（原生）+ marked.js
- 存储：JSON + Markdown 文件
- 测试：pytest + FastAPI TestClient

## 本地运行（Conda）

1. 创建并激活环境

```bash
conda create -n Coding-doc-agent python=3.9 -y
conda activate Coding-doc-agent
```

2. 安装依赖

```bash
pip install -r requirements.txt
```

3. 启动服务

```bash
uvicorn backend.main:app --reload
```

4. 打开浏览器

访问 `http://127.0.0.1:8000`

## 测试

```bash
python -m pytest -q
```

测试覆盖：
- 配置读写
- 项目创建与已有文件保护
- 项目开发文档存在标志
- 会话回答、版本生成、版本对比与恢复

## API 概览

- 配置：`/api/config`（GET/POST）
- 项目：`/api/projects`、`/api/projects/{id}`、`/api/projects/{id}/folder/open`
- 会话：`/api/projects/{id}/sessions`、`/api/projects/{id}/sessions/{sid}`、`/answer`
- 文档版本：`/api/projects/{id}/doc/versions`、`/restore`、`/compare`

## 关键路径

- 项目开发文档：`docs/project/PROJECT.md`
- Agent 文档版本目录：`docs/agent/`（默认，可在设置中调整）
- 全局配置：`~/.docagent/config.json`
- 项目索引：`~/.docagent/projects.json`

## 目录结构

```text
backend/     FastAPI 后端
frontend/    原生前端页面与交互
docs/        项目文档与开发文档
tests/       自动化测试
```

## GitHub 仓库描述建议

建议仓库 Description 使用：

项目管理式需求澄清 Agent：多会话问答、文档版本化、项目文档只读参考、FastAPI + 原生前端一体化实现。

## 发布后补充说明

- 已提供 `DESCRIPTION.md`，可直接复制其中一句话到 GitHub 仓库 Description。
- 项目开发文档采用 `docs/project/PROJECT.md`，后续每次功能迭代请同步更新该文件。
