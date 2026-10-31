"""The model-composed customer view must describe data, not its format token."""

import runpy
from pathlib import Path


def test_customer_example_goal_names_the_actual_record_fields():
    ns = runpy.run_path(
        str(Path(__file__).parents[1] / "examples/07_bound_operation.py")
    )
    goal = ns["summon"].endpoints[0].description.lower()
    assert "returned record" in goal and "name" in goal and "status" in goal
    description = ns["CustomerView"].model_fields["display"].description
    assert description is not None and "format" in description and "name" in description
