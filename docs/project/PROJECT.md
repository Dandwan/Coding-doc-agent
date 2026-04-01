# 项目开发文档（DocAgent）

## 1. 项目概述

DocAgent 是一个面向需求澄清与开发文档生成的 Web 工具，采用项目管理模式组织会话与文档版本。用户可以创建多个项目，在每个项目中进行多轮选项式问答，最终沉淀为可执行的 Agent 开发文档。

当前文档是本仓库的项目开发文档，路径遵循默认规范：
- docs/project/PROJECT.md

## 2. 已实现功能清单

- 项目管理
  - 列出项目、创建项目、删除项目（仅移除索引）
  - 支持指定已有文件夹作为项目目录
  - 创建时不改动无关文件，仅补充 meta.json 与 managed 目录
  - 支持修改项目名称、项目文档路径、项目文件夹路径（迁移 managed 内容）

- 全局配置管理
  - 管理 projects_root、API 参数、文档路径规则
  - 管理 workflow 默认策略（积极上传开关与默认分支）
  - 配置持久化到 ~/.docagent/config.json
  - 项目索引持久化到 ~/.docagent/projects.json

- 会话管理
  - 每项目独立会话列表
  - 新建、重命名、删除会话
  - 每会话独立保存历史、问题、待解决清单、当前文档、当前版本

- 需求澄清交互
  - 新建会话后第一步由用户直接输入原始需求（自由文本）
  - 系统优先识别需求中的歧义点，再动态生成选项供用户确认
  - 问题 + 3~5 选项
  - 动态“其他/补充”输入标签
  - 跳过问题按钮
  - 至少选择或输入后才能提交
  - 已完成后仍可继续新增需求，系统重新核实并更新文档

- 文档生成与版本管理
  - 每次提交答案后自动生成版本
  - 保存命名为 YYYY-MM-DD_HHMMSS[_NN]_DEVELOPMENT.md
  - 同步维护 docs 版本目录中的 DEVELOPMENT.md 最新版
  - 同步维护项目根目录 AGENT_DEVELOPMENT.md（便于直接给开发 Agent 读取）
  - 支持历史版本查看、恢复、与最新版对比 diff

- 积极上传策略
  - 支持全局默认值配置
  - 支持项目级覆盖开关
  - 支持项目级分支配置：有分支则强调上传到该分支，无分支则不强调

- 项目开发文档容错读取
  - 缺失时不阻塞会话流程
  - 项目详情提供 project_doc_exists 标志

- API 集成
  - requests 调用 GPT 兼容 Chat Completions
  - 支持超时与重试
  - LLM 异常自动退回本地策略继续对话

## 3. 核心业务流程

1. 用户在首页创建/打开项目。
2. 进入项目工作区后创建会话。
3. 系统给出问题与选项，用户勾选并补充，或跳过。
4. 提交后系统：
   - 保存历史
   - 调用 LLM（失败则 fallback）
   - 生成/更新 Agent 开发文档
   - 生成文档版本快照
5. 用户可查看、对比、恢复历史版本。
6. 会话文件和文档版本持续落盘。

## 4. API 端点摘要

- 配置
  - GET /api/config
  - POST /api/config

- 项目
  - GET /api/projects
  - POST /api/projects
  - GET /api/projects/{id}
  - PATCH /api/projects/{id}
  - DELETE /api/projects/{id}
  - POST /api/projects/{id}/folder/open

- 会话
  - GET /api/projects/{id}/sessions
  - POST /api/projects/{id}/sessions
  - GET /api/projects/{id}/sessions/{sid}
  - PATCH /api/projects/{id}/sessions/{sid}
  - DELETE /api/projects/{id}/sessions/{sid}
  - POST /api/projects/{id}/sessions/{sid}/answer

- 文档版本
  - GET /api/projects/{id}/doc/versions
  - GET /api/projects/{id}/doc/versions/{version}
  - GET /api/projects/{id}/doc/compare?source=...&target=...
  - POST /api/projects/{id}/doc/versions/{version}/restore

## 5. 配置项说明

- 全局配置文件：~/.docagent/config.json
- 关键字段：
  - projects_root: 默认项目根目录
  - api.url/api_key/model/temperature/timeout/max_retries
  - doc_paths.project_doc
  - doc_paths.agent_doc_dir
  - workflow.proactive_push_enabled_default
  - workflow.proactive_push_branch_default

## 6. 部署与运行

- 运行环境
  - Python 3.9+
  - Windows/macOS/Linux

- 推荐启动方式
  1. conda create -n Coding-doc-agent python=3.9
  2. conda activate Coding-doc-agent
  3. pip install -r requirements.txt
  4. uvicorn backend.main:app --reload

## 7. 测试与质量状态

- 已提供 pytest 回归测试，覆盖：
  - 配置读写
  - 项目创建与已有文件保护
  - 项目开发文档存在标志
  - 目录选择接口
  - 会话回答、版本生成、版本对比与恢复
  - 积极上传默认/项目覆盖
  - 完成后新增需求重开核实

- 测试命令：
  - conda run -n Coding-doc-agent python -m pytest -q

## 8. 项目开发文档管理规范

- 项目开发文档固定路径由 doc_paths.project_doc 定义，默认 docs/project/PROJECT.md。
- 本文档由开发项目的 Agent 维护，用于记录实现现状、变更和运维信息。
- DocAgent 在业务流程中只读取项目开发文档，不会写入该文件。
- 当功能迭代时，应同步更新本文档中的：
  - 已实现功能清单
  - API 变更
  - 部署方式
  - 测试结果与待办项

## 9. 已知限制与后续优化

- 当前前端为原生 JS，后续可升级为组件化框架以增强可维护性。
- 当前 LLM 输出解析为宽松容错，后续可增加 JSON Schema 校验与修复策略。
- 当前存储为文件系统，后续可接入数据库支持更大规模项目与检索能力。
