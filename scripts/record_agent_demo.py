"""Record real HTTP executions of the bounded AgentChoice example using a scripted test model."""

from __future__ import annotations

import hashlib
import json
import runpy
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from summonpot.runtime import Runtime
from summonpot.server import build_app

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "examples/07_bound_operation.py"
OUTPUT = ROOT / "website/src/data/agent-demo.json"
RECORDER_VERSION = 2


def record(format: str) -> dict[str, object]:
    if format not in {"summary", "detailed"}:
        raise ValueError(f"unsupported display format: {format!r}")

    namespace = runpy.run_path(str(SOURCE), run_name=f"agent_demo_{format}")
    summon = namespace["summon"]
    CustomerRecord = namespace["CustomerRecord"]
    seen: list[dict[str, Any]] = []
    calls: list[dict[str, Any]] = []
    actual_customer: list[Any] = []

    def scripted_model(messages, info: AgentInfo) -> ModelResponse:
        if not seen:
            tool = info.function_tools[0]
            schema = tool.parameters_json_schema
            assert tool.name == "load_customer"
            assert list(schema["properties"]) == ["format"]
            assert schema["properties"]["format"]["enum"] == ["summary", "detailed"]
            seen.append({"tool": tool.name, "schema": schema})
            return ModelResponse(parts=[ToolCallPart(tool.name, {"format": format})])

        # Read the actual application operation result from the agent's history.
        returns = [
            part
            for message in messages
            for part in getattr(message, "parts", ())
            if getattr(part, "part_kind", None) == "tool-return"
            and getattr(part, "tool_name", None) == "load_customer"
        ]
        assert len(returns) == 1, (
            f"expected exactly one load_customer return, got {len(returns)}"
        )
        customer = returns[0].content
        if isinstance(customer, str):
            customer = json.loads(customer)
        if hasattr(customer, "model_dump"):
            customer = customer.model_dump(mode="json")
        validated = CustomerRecord.model_validate(customer)
        actual_customer.append(validated.model_dump(mode="json"))
        display = (
            f"{validated.name} — {validated.status}"
            if validated.format == "summary"
            else f"{validated.name} — {validated.status} customer"
        )
        call_parts = [
            part
            for message in messages
            for part in getattr(message, "parts", ())
            if getattr(part, "part_kind", None) == "tool-call"
            and getattr(part, "tool_name", None) == "load_customer"
        ]
        assert len(call_parts) == 1, (
            f"expected exactly one load_customer call, got {len(call_parts)}"
        )
        arguments = call_parts[0].args
        if isinstance(arguments, str):
            arguments = json.loads(arguments)
        assert arguments == {"format": format}
        calls.append({"tool": "load_customer", "arguments": arguments})
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {
                        "customer_id": validated.customer_id,
                        "display": display,
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
    assert len(actual_customer) == 1
    assert len(calls) == 1
    assert len(seen) == 1
    return {
        "format": format,
        "request": {"customer_id": "customer-7"},
        "response": response.json(),
        "tool": seen[0],
        "tool_call": calls[0],
        "tool_return": actual_customer[0],
        "outcome_provenance": "display is scripted model output derived from the validated application tool return",
    }


def main() -> None:
    source_hash = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    data = {
        "kind": "scripted-test-model-recording",
        "source": "examples/07_bound_operation.py",
        "source_sha256": source_hash,
        "recorder_version": RECORDER_VERSION,
        "provenance": "Keyless FunctionModel fixture selects each legal format; tool returns are actual validated application results; final display is scripted model output derived from that result, not an LLM-generated response.",
        "recordings": [record("summary"), record("detailed")],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    print(
        f"Recorded {len(data['recordings'])} real HTTP executions to {OUTPUT.relative_to(ROOT)}"
    )


if __name__ == "__main__":
    main()
