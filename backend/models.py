from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field, model_validator


class APISettings(BaseModel):
    url: str
    api_key: str = ""
    model: str
    temperature: float = 0.7
    timeout: int = 60
    max_retries: int = 2


class DocPathSettings(BaseModel):
    project_doc: str = "docs/project/PROJECT.md"
    agent_doc_dir: str = "docs/agent"


class WorkflowSettings(BaseModel):
    proactive_push_enabled_default: bool = False
    proactive_push_branch_default: str = ""


class PromptPlaceholderSettings(BaseModel):
    project_document: str = "</projectDocument>"
    user_input: str = "</userInput>"
    question_and_input: str = "</questionAndInput>"


class PromptMarkerSettings(BaseModel):
    question_open: str = "<question>"
    question_close: str = "</question>"
    option_open: str = "<option>"
    option_close: str = "</option>"


class PromptSettings(BaseModel):
    clarify_prompt_template: str
    options_prompt_template: str
    final_doc_prompt_template: str
    placeholders: PromptPlaceholderSettings
    markers: PromptMarkerSettings


class AppConfig(BaseModel):
    projects_root: str
    api: APISettings
    doc_paths: DocPathSettings
    workflow: WorkflowSettings
    prompt_settings: PromptSettings


class AppConfigUpdate(BaseModel):
    projects_root: Optional[str] = None
    api: Optional[dict[str, Any]] = None
    doc_paths: Optional[dict[str, Any]] = None
    workflow: Optional[dict[str, Any]] = None
    prompt_settings: Optional[dict[str, Any]] = None


class ProjectCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    folder: Optional[str] = None


class ProjectUpdateRequest(BaseModel):
    name: Optional[str] = None
    folder: Optional[str] = None
    project_doc_path: Optional[str] = None
    proactive_push_use_global: Optional[bool] = None
    proactive_push_enabled: Optional[bool] = None
    proactive_push_branch: Optional[str] = None


class ProjectSummary(BaseModel):
    id: str
    name: str
    folder: str
    created_at: str
    updated_at: str


class SessionSummary(BaseModel):
    id: str
    name: str
    created_at: str
    updated_at: str
    is_complete: bool = False


class ProjectDetail(ProjectSummary):
    last_opened_at: str
    project_doc_path: str
    project_doc_exists: bool
    root_agent_doc_path: str
    proactive_push_enabled: bool
    proactive_push_branch: str
    proactive_push_use_global: bool
    proactive_push_enabled_override: Optional[bool] = None
    proactive_push_branch_override: Optional[str] = None
    sessions: list[SessionSummary]


class SessionCreateRequest(BaseModel):
    name: Optional[str] = None


class SessionRenameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class OptionQuestion(BaseModel):
    question: str
    options: list[str]


class SessionDetail(BaseModel):
    id: str
    name: str
    created_at: str
    updated_at: str
    history: list[dict[str, Any]]
    unresolved_points: list[str]
    current_question: OptionQuestion
    current_document: str
    is_complete: bool
    current_version: Optional[str] = None
    ai_thinks_clear: bool = False


class AnswerRequest(BaseModel):
    selected_options: list[str] = Field(default_factory=list)
    text_input: str = ""
    skip_question: bool = False

    @model_validator(mode="after")
    def check_has_input(self) -> "AnswerRequest":
        has_options = len(self.selected_options) > 0
        has_text = bool(self.text_input.strip())
        if not self.skip_question and not has_options and not has_text:
            raise ValueError("必须至少选择一个选项或填写补充内容")
        return self


class AnswerResponse(BaseModel):
    session: SessionDetail


class VersionInfo(BaseModel):
    file_name: str
    updated_at: str
    size: int


class RestoreVersionRequest(BaseModel):
    session_id: Optional[str] = None
