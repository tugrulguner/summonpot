"""The Google extra must not admit the known-vulnerable ASN.1 decoder."""

import tomllib
from pathlib import Path


def test_google_extra_requires_pyasn1_decoder_fixes():
    project = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())
    assert "pyasn1>=0.6.5" in project["project"]["optional-dependencies"]["google"]
