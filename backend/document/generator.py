from __future__ import annotations

from typing import Any


def generate_initial_document(project_name: str) -> str:
    return f"""# 项目功能清单

- 待补充：请通过左侧问题逐步澄清目标用户、功能范围、交付标准。

# 项目细节

## 用户交互细节
- 待补充

## 业务流程细节
- 待补充

## 非功能需求细节
- 待补充

## 依赖与环境
- Python 3.9+

## 项目开发文档管理规范
- 项目开发文档路径遵循全局配置 `doc_paths.project_doc`（默认 `docs/project/PROJECT.md`）。
- 开发项目的 Agent 负责维护项目开发文档，DocAgent 仅读取该文档作为上下文。
- 项目开发文档建议记录实现清单、部署说明、配置项说明、测试结果与待办事项。

# 代码架构与实现方式

## 技术栈选型
- 待补充

## 目录结构
- 待补充

## 核心模块设计
- 待补充

## 数据模型
- 待补充

## 接口定义
- 待补充

---

> 当前项目：{project_name}
"""


def generate_document_from_context(
    *,
    project_name: str,
    project_doc_path: str,
    project_doc_exists: bool,
    history: list[dict[str, Any]],
    unresolved_points: list[str],
    previous_document: str,
) -> str:
    answers = _collect_answer_lines(history)
    function_items = _derive_function_items(answers)

    unresolved_lines = "\n".join(f"- {item}" for item in unresolved_points) if unresolved_points else "- 已收敛"
    answer_lines = "\n".join(f"- {line}" for line in answers[-8:]) if answers else "- 暂无"
    project_doc_state = "已提供" if project_doc_exists else "尚未提供"

    document = f"""# 项目功能清单

{function_items}

# 项目细节

## 用户交互细节
- 采用多轮问答澄清需求，问题由系统动态生成。
- 每轮提供 3-5 个选项，并支持“其他/补充”自由输入。

## 业务流程细节
- 会话内维护问题、回答、待解决问题清单与当前文档。
- 每次提交答案后，系统更新文档并生成版本快照。
- 当前待解决问题：
{unresolved_lines}

## 非功能需求细节
- 需要容错处理：API失败或项目文档缺失时仍可继续。
- 要求响应可追踪：保存会话历史和文档版本。

## 依赖与环境
- Python 3.9+
- FastAPI + requests + 原生前端

## 项目开发文档管理规范
- 项目开发文档固定位置：`{project_doc_path}`。
- 当前项目开发文档状态：{project_doc_state}。
- 项目开发文档由开发项目的 Agent 维护，DocAgent 仅做读取。
- 开发项目的 Agent 更新功能后，应同步回写项目开发文档。

# 代码架构与实现方式

## 技术栈选型
- 后端：FastAPI
- 前端：HTML/CSS/JS + Fetch API + marked.js
- 存储：JSON + Markdown 文件

## 目录结构
- backend：业务逻辑与 API
- frontend：页面与交互
- tests：测试与回归验证

## 核心模块设计
- 项目管理模块：负责项目创建、打开、迁移与元数据维护。
- 会话管理模块：负责会话生命周期与持久化。
- 对话模块：负责提示词构建、LLM调用与结果解析。
- 文档模块：负责项目文档加载、开发文档生成与版本管理。

## 数据模型
- 项目：id/name/folder/时间戳/项目文档路径
- 会话：历史对话、当前问题、待解决问题、当前文档

## 接口定义
- 采用 REST 风格 API，覆盖配置、项目、会话、回答、文档版本。

---

## 最近澄清摘要

{answer_lines}
"""

    return ensure_required_sections(document, previous_document=previous_document)


def ensure_required_sections(content: str, previous_document: str = "") -> str:
    required_headers = ["# 项目功能清单", "# 项目细节", "# 代码架构与实现方式"]
    if all(header in content for header in required_headers):
        return content

    if previous_document and all(header in previous_document for header in required_headers):
        return previous_document

    return generate_initial_document("未命名项目")


def _collect_answer_lines(history: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for turn in history:
        question = str(turn.get("question", "")).strip()
        answer = str(turn.get("answer", "")).strip()
        if not question and not answer:
            continue
        lines.append(f"{question} -> {answer}")
    return lines


def _derive_function_items(answer_lines: list[str]) -> str:
    if not answer_lines:
        return "- 待澄清：目标用户、核心场景、输入输出。"

    items = [f"- 需求线索：{line}" for line in answer_lines[-5:]]
    return "\n".join(items)
