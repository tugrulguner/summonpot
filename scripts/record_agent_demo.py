"""Record real HTTP executions of the bounded AgentChoice example using a scripted test model."""

from __future__ import annotations

import hashlib
import json
import runpy
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from summonpot.runtime import Runtime
from summonpot.server import build_app

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "examples/07_bound_operation.py"
OUTPUT = ROOT / "website/src/data/agent-demo.json"


def record(format: str) -> dict[str, object]:
    summon = runpy.run_path(str(SOURCE), run_name=f"agent_demo_{format}")["summon"]
    seen: list[dict[str, object]] = []

    def scripted_model(messages, info: AgentInfo) -> ModelResponse:
        if not seen:
            tool = info.function_tools[0]
            schema = tool.parameters_json_schema
            assert tool.name == "load_customer"
            assert list(schema["properties"]) == ["format"]
            assert schema["properties"]["format"]["enum"] == ["summary", "detailed"]
            seen.append({"tool": tool.name, "schema": schema})
            return ModelResponse(parts=[ToolCallPart(tool.name, {"format": format})])
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {
                        "customer_id": "customer-7",
                        "display": "Ada — active"
                        if format == "summary"
                        else "Ada Lovelace — active customer",
                    },
                )
            ]
        )

    summon._runtime = Runtime(model=FunctionModel(scripted_model))
    response = TestClient(build_app(summon)).post(
        "/customers/view", json={"customer_id": "customer-7"}
    )
    response.raise_for_status()
    assert response.json()["customer_id"] == "customer-7"
    assert seen
    return {
        "format": format,
        "request": {"customer_id": "customer-7"},
        "response": response.json(),
        "tool": seen[0],
    }


def main() -> None:
    data = {
        "kind": "scripted-test-model-recording",
        "source": "examples/07_bound_operation.py",
        "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        "provenance": "Keyless FunctionModel test fixture selects each legal format; not an LLM-generated choice.",
        "recordings": [record("summary"), record("detailed")],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    print(
        f"Recorded {len(data['recordings'])} real HTTP executions to {OUTPUT.relative_to(ROOT)}"
    )


if __name__ == "__main__":
    main()
