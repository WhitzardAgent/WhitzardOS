"""Deterministic TypeScript tool-chain check; no model-quality claim.

Run after installing QitOS and building qitos-studio-coding-node:local:
    python examples/projects/studio_coding/demo/offline_typescript_check.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

from qitos.config import (
    AgentConfig, BudgetConfig, EnvironmentConfig, ModelConfig, RuntimeConfig,
    SessionConfig, TrajectoryConfig, build_agent_composition,
)
from qitos.studio.registry import AgentSpec
from qitos.studio.service import StudioService

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
IMAGE = os.environ.get("QITOS_STUDIO_TYPESCRIPT_IMAGE", "qitos-studio-coding-node:local")


class ScriptedModel:
    model = "offline-typescript"
    qitos_protocol = "json_decision_multi_v1"
    context_window = 65536
    max_tokens = 1024

    def __init__(self):
        self.stage = 0

    def call_raw(self, messages, **options):
        _ = messages, options
        actions = [
            ("read_file", {"path": "src/format.ts"}),
            ("run_command", {"command": "npm test", "timeout": 25}),
            ("edit_file", {"path": "src/format.ts",
                           "old_text": "toLowerCase()", "replacement": "toUpperCase()"}),
            ("run_command", {"command": "npm test", "timeout": 25}),
            ("edit_file", {"path": "src/summary.ts",
                           "old_text": 'return names.map(formatName).join(", ");',
                           "replacement": 'return names.map(formatName).join(", ");\n}\n\n'
                           'export function countNames(names: string[]): number {\n  return 0;'}),
            ("write_file", {"path": "test/count.test.ts", "content":
                            "import assert from 'node:assert/strict';\n"
                            "import test from 'node:test';\n"
                            "import { countNames } from '../src/summary.ts';\n"
                            "test('counts names', () => { assert.equal(countNames(['Ada', 'Lin']), 2); });\n"}),
            ("run_command", {"command": "npm test", "timeout": 25}),
            ("edit_file", {"path": "src/summary.ts",
                           "old_text": "return 0;", "replacement": "return names.length;"}),
            ("run_command", {"command": "npm test", "timeout": 25}),
        ]
        stage = self.stage
        self.stage += 1
        if stage >= len(actions):
            summary = "Final Answer: Fixed formatting, added countNames, and ran npm test."
            return {"choices": [{"message": {"content": summary}}]}
        name, args = actions[stage]
        return {"choices": [{"message": {"content": None, "tool_calls": [{
            "id": f"ts-{stage}", "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)},
        }]}}]}


def main() -> None:
    from qitos_studio_coding import make_agent

    with tempfile.TemporaryDirectory(prefix="qitos-studio-ts-") as raw:
        temp = Path(raw)
        source = temp / "source"
        shutil.copytree(ROOT / "demo/typescript", source)
        config_file = temp / "agent.yaml"
        config_file.write_text("schema: qitos.agent", encoding="utf-8")
        config = AgentConfig(
            name="studio-ts-check", protocol="json_decision_multi_v1", parser="auto",
            model=ModelConfig(provider="openai-compatible", model="offline-typescript"),
            tool_preset="none", tool_options={"native_tool_calls_required": True},
            budgets=BudgetConfig(max_steps=14, max_requests=14, max_runtime_seconds=180),
            runtime=RuntimeConfig(
                environment=EnvironmentConfig(workspace=str(source), image=IMAGE,
                                              cpus=.5, memory_mb=512, pids_limit=64),
                session=SessionConfig(mode="durable", store="sqlite", path=str(temp / "sessions.sqlite3")),
                trajectory=TrajectoryConfig(enabled=True, output=str(temp / "trajectory.journal")),
            ),
        )
        spec = AgentSpec("typescript", "TypeScript", "", config_file,
                         factory_ref="qitos_studio_coding:make_agent",
                         adapter_ref="qitos_studio_coding:StudioCodingAdapter")

        def builder(_spec, loaded, _):
            return build_agent_composition(
                loaded, model_override=ScriptedModel(), agent_factory=make_agent,
            )

        with StudioService({"typescript": spec}, state_path=temp / "studio.sqlite3",
                           credential_path=temp / "credentials.yaml", config_loader=lambda _: config,
                           composition_builder=builder) as service:
            launch = service.start(
                "typescript", "Fix formatting, add countNames, verify failures and repairs",
            )
            service.wait_for_idle()
            detail = service.get_session(launch["id"])
            assert detail["status"] == "completed", detail
            after = 0
            codes = []
            while True:
                page = service.events(launch["id"], after=after, limit=100)
                for fact in page["records"]:
                    if fact["kind"] != "tool_slot":
                        continue
                    for item in fact["payload"].get("payload", {}).get("action_results", []):
                        if item.get("tool_name") == "run_command":
                            codes.append(json.loads(item["model_output"]).get("returncode"))
                if not page["has_more"] or not page["records"]:
                    break
                after = page["next_after"]
            assert codes == [1, 0, 1, 0], codes
            print(json.dumps({"status": detail["status"], "command_returncodes": codes,
                              "run_id": detail["run_id"]}))


if __name__ == "__main__":
    main()
