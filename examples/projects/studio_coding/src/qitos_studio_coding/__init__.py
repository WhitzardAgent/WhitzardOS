"""Standalone reference coding Agent for QitOS Studio."""

from __future__ import annotations

from qitos.config.builder import ConfiguredAgent
from qitos.kit.toolset.env_coding import (
    edit_file, grep_file, list_files, read_file, run_command, run_test, write_file,
)
from qitos.studio.adapter import StudioTurn


class CodingAgent(ConfiguredAgent):
    """The application decides its coding policy; Studio renders public facts."""

    def __init__(self, *, editing: bool = True, **kwargs):
        super().__init__(**kwargs)
        self.editing = editing

    def base_persona_prompt(self, state):
        if not self.editing:
            return (
                "You are a read-only project reviewer in the configured Env. "
                "Read AGENTS.md and relevant files, search code, run focused tests, "
                "and report findings with evidence. You have no editing tools."
            )
        return (
            "You are a coding agent working only in the configured Env workspace. "
            "Read AGENTS.md and project instructions before editing. Search and inspect "
            "the relevant code, make the smallest coherent change, run focused tests, "
            "repair failures, and summarize changed files, actual verification and "
            "unverified risks. Tool and model actions must use the QitOS runtime. "
            "Never claim a test ran unless a tool result confirms it."
        )

    def task_policy_prompt(self, state):
        if not self.editing:
            return "Inspect and verify; do not claim any file was changed."
        return (
            "Prefer grep_file/list_files/read_file to discover context. Use edit_file "
            "or write_file for changes, then run_test or run_command to verify. "
            "Do not modify tests solely to hide a failure. Respect the configured "
            "tool permissions, workspace and budget."
        )


def make_agent(*, config, model, tool_registry, protocol, parser):
    editing = config.tool_options.get("editing", True)
    if not isinstance(editing, bool):
        raise ValueError("editing_option_invalid")
    available = (read_file, list_files, grep_file, run_test)
    if editing:
        available += (write_file, edit_file, run_command)
    for tool in available:
        tool_registry.register(tool)
    return CodingAgent(
        name=config.name, llm=model, tool_registry=tool_registry,
        protocol=protocol.id, parser=parser, tool_use_policy=config.tool_use_policy,
        native_tool_calls_required=bool(config.tool_options.get("native_tool_calls_required", False)),
        config_digest=config.digest(),
        editing=editing,
    )


class StudioCodingAdapter:
    def capabilities(self):
        # Views describe the resource shapes this application intends to provide.
        # Studio still requires actual persisted, authorized facts before rendering.
        return {"continuation": True, "views": ["files", "diff"]}

    def continuation_task(self, turns: list[StudioTurn], message: str) -> str:
        # A terminal runtime Session stays terminal. A linked new Session gets
        # explicit prior context; no hidden state or second execution loop.
        history = "\n".join(f"Turn {index + 1}: {turn.task[:1200]}" for index, turn in enumerate(turns[-4:]))
        return (
            "Continue work in the same configured workspace. Inspect current files "
            "and tests; prior output may be stale.\n"
            f"Previous requests:\n{history}\nNew user request:\n{message}"
        )


class StudioReviewAdapter(StudioCodingAdapter):
    def capabilities(self):
        return {"continuation": True, "views": ["files"]}
