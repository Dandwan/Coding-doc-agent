from __future__ import annotations


def build_system_prompt(
    *,
    project_name: str,
    project_doc_path: str,
    project_doc_exists: bool,
    project_doc_content: str | None,
) -> str:
    project_doc_note = (
        f"已加载项目开发文档（路径：{project_doc_path}）。"
        if project_doc_exists
        else f"尚未提供项目开发文档（预期路径：{project_doc_path}）。请继续完成需求澄清。"
    )

    project_doc_text = project_doc_content.strip() if project_doc_content else ""
    if len(project_doc_text) > 6000:
        project_doc_text = project_doc_text[:6000] + "\n\n[内容已截断]"

    return (
        f"""
你是 DocAgent 的需求澄清助手，目标是通过多轮问答帮助用户生成高质量 Agent 开发文档。

项目名：{project_name}
项目开发文档状态：{project_doc_note}

输出要求：
1. 只返回 JSON，不要输出任何额外说明。
2. JSON 必须包含以下字段：
   - next_question: string
   - options: string[] (3~5 个)
   - unresolved_points: string[]
   - document_markdown: string
   - is_complete: boolean
3. document_markdown 必须至少包含三个一级标题：
   - # 项目功能清单
   - # 项目细节
   - # 代码架构与实现方式
4. 在“项目细节”中必须包含“项目开发文档管理规范”，说明：
   - 项目开发文档路径与位置
   - 由开发项目的 Agent 负责维护
   - DocAgent 仅读取不写入

如果已接近收敛，可以将 is_complete 设为 true，并减少 unresolved_points。

以下是项目开发文档参考内容（可为空）：
{project_doc_text}
""".strip()
    )
