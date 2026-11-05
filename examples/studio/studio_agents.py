"""An installable app can expose the same factory from its Python package."""

from qitos.config.builder import ConfiguredAgent


class ResearchAgent(ConfiguredAgent):
    def task_policy_prompt(self, state):
        return f"Research this task and distinguish evidence from inference: {state.task}"


def make_agent(*, config, model, tool_registry, protocol, parser):
    return ResearchAgent(
        name=config.name, llm=model, tool_registry=tool_registry,
        protocol=protocol.id, parser=parser, tool_use_policy=config.tool_use_policy,
        native_tool_calls_required=bool(config.tool_options.get("native_tool_calls_required", False)),
        config_digest=config.digest(),
    )
