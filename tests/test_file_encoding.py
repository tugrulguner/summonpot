"""File I/O must not depend on the interpreter's default encoding.

`open()` with no `encoding=` uses `locale.getpreferredencoding(False)`, which is
UTF-8 on the CI runner and on most developer machines -- so a missing
`encoding="utf-8"` is invisible there and only surfaces for a user whose
default is `cp1252`, `ascii`, `cp932` or similar. That is exactly the class of
bug this suite has to catch on a UTF-8 machine.

Two complementary checks are used.

The behavioural ones run the code under test in a **child interpreter with a
forced non-UTF default encoding** (`PYTHONUTF8=0`, `LC_ALL=C`) and assert on the
bytes that land on disk. On Linux -- what CI runs -- the child's default is
`ascii`, and reading this repository's own UTF-8 files then raises. They cannot
fail on a `cp1252` host: every UTF-8 byte decodes to *some* cp1252 character and
re-encodes to the same byte, so a read-modify-write cancels out invisibly.

`test_the_package_never_relies_on_the_locale_encoding` covers that gap. It is a
static check over `src/`, so it fails identically on every platform the moment
an explicit encoding is dropped -- which is the property that keeps CI from
going green on a regression.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# Undecodable as ascii, so the behavioural tests raise rather than mojibake on
# the C locale CI runs under. A cp1252 host decodes it to nonsense instead, which
# is why the static guard below is the one that holds everywhere.
NON_ASCII = "用户 テスト — café"


def _child_env() -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        {
            "PYTHONUTF8": "0",  # opt out of UTF-8 mode
            "PYTHONCOERCECLOCALE": "0",  # do not let CPython upgrade the C locale
            "PYTHONIOENCODING": "utf-8",  # only stdio, so failures stay readable
            "LC_ALL": "C",
            "LANG": "C",
            "PYTHONPATH": str(ROOT / "src"),
        }
    )
    return env


def _run_child(script: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script)],
        env=_child_env(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(ROOT),
    )


@pytest.fixture(scope="module")
def non_utf8_default(tmp_path_factory) -> str:
    """The child's default encoding, or skip if this host cannot force one."""
    probe = tmp_path_factory.mktemp("probe") / "probe.py"
    probe.write_text(
        "import locale\nprint(locale.getpreferredencoding(False))\n",
        encoding="utf-8",
    )
    result = _run_child(probe)
    assert result.returncode == 0, result.stderr

    encoding = result.stdout.strip()
    if encoding.lower().replace("-", "").replace("_", "") in {"utf8", "cp65001"}:
        pytest.skip(f"host forces UTF-8 regardless of locale (got {encoding!r})")
    return encoding


def test_the_packaged_skill_reads_under_a_non_utf8_default(non_utf8_default, tmp_path):
    """`skill_body()` reads a file that is UTF-8 on disk, whatever the locale says."""
    script = tmp_path / "read_skill.py"
    script.write_text(
        "from summonpot.skills.content import skill_body\n"
        "body = skill_body()\n"
        "assert body.strip()\n"
        "print(len(body))\n",
        encoding="utf-8",
    )

    result = _run_child(script)

    assert result.returncode == 0, (
        f"skill_body() failed under default encoding {non_utf8_default!r}:\n"
        f"{result.stderr}"
    )


@pytest.mark.parametrize("agent", ["claude", "cursor", "windsurf", "cline"])
def test_generated_agent_files_are_utf8_whatever_the_locale(
    agent, non_utf8_default, tmp_path
):
    """The generated file must be UTF-8 on disk, not the host's ANSI codepage.

    Without an explicit encoding the writer emits the locale's bytes, so the
    same repository ends up with mojibake for one contributor and not another.
    """
    target = tmp_path / f"project-{agent}"
    target.mkdir()
    script = tmp_path / f"write_{agent}.py"
    script.write_text(
        "from pathlib import Path\n"
        "from summonpot.commands.add_skills import Agent, _WRITERS\n"
        f"_WRITERS[Agent({agent!r})](Path({str(target)!r}))\n",
        encoding="utf-8",
    )

    result = _run_child(script)
    assert result.returncode == 0, result.stderr

    written = [p for p in target.rglob("*") if p.is_file()]
    assert written, f"the {agent} writer produced no files"

    for path in written:
        raw = path.read_bytes()
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError as exc:  # pragma: no cover - the failure message
            pytest.fail(
                f"{path.name} is not valid UTF-8 under default encoding "
                f"{non_utf8_default!r}: {exc}"
            )


def test_surrounding_non_ascii_content_survives_an_upsert(non_utf8_default, tmp_path):
    """The reported shape: an existing shared file the user already wrote in.

    `_upsert_managed_block` reads the whole file and writes it back. Under a
    non-UTF default the read mangles or rejects the user's own text, so their
    content is corrupted or the command dies -- neither is acceptable for a
    file summonpot does not own.
    """
    shared = tmp_path / "AGENTS.md"
    original = f"# House rules\n\n{NON_ASCII}\n\nKeep this paragraph intact.\n"
    shared.write_bytes(original.encode("utf-8"))

    script = tmp_path / "upsert.py"
    script.write_text(
        "from pathlib import Path\n"
        "from summonpot.commands.add_skills import _upsert_managed_block\n"
        f"_upsert_managed_block(Path({str(shared)!r}), 'managed body')\n",
        encoding="utf-8",
    )

    result = _run_child(script)
    assert result.returncode == 0, (
        f"upsert failed under default encoding {non_utf8_default!r}:\n{result.stderr}"
    )

    raw = shared.read_bytes()
    text = raw.decode("utf-8")
    assert NON_ASCII in text, "the user's own text did not survive the round trip"
    assert "Keep this paragraph intact." in text
    assert "managed body" in text


def test_a_second_upsert_is_still_idempotent_under_a_non_utf8_default(
    non_utf8_default, tmp_path
):
    """A mangled read makes the marker search miss, appending a second block."""
    shared = tmp_path / "CLAUDE.md"
    shared.write_bytes(f"{NON_ASCII}\n".encode())

    script = tmp_path / "upsert_twice.py"
    script.write_text(
        "from pathlib import Path\n"
        "from summonpot.commands.add_skills import _upsert_managed_block\n"
        f"path = Path({str(shared)!r})\n"
        "_upsert_managed_block(path, 'managed body')\n"
        "_upsert_managed_block(path, 'managed body')\n",
        encoding="utf-8",
    )

    result = _run_child(script)
    assert result.returncode == 0, result.stderr

    text = shared.read_bytes().decode("utf-8")
    assert text.count("managed body") == 1, (
        "the second run appended instead of replacing"
    )
    assert NON_ASCII in text


# ---------------------------------------------------------------------------
# The guard that holds on every platform.
#
# The behavioural tests above bite where the default is `ascii` (the C locale on
# Linux, which is what CI forces). They cannot bite on a `cp1252` host: every
# byte of UTF-8 decodes to *some* cp1252 character and re-encodes to the same
# byte, so a read-modify-write silently cancels out. That makes them necessary
# but not sufficient for "CI stays green while the encodings are removed".
#
# This one is a static check, so it fails identically everywhere the moment an
# explicit encoding is dropped.
# ---------------------------------------------------------------------------

# Text I/O whose encoding defaults to the locale when it is not passed.
_ENCODING_SENSITIVE = {"read_text", "write_text", "open"}

_SOURCE_FILES = sorted((ROOT / "src").rglob("*.py"))


def _unencoded_text_io(tree: ast.AST) -> list[tuple[str, int]]:
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name not in _ENCODING_SENSITIVE:
            continue
        if any(kw.arg == "encoding" for kw in node.keywords):
            continue
        # Binary mode has no encoding to give. Builtin `open` takes the path
        # first and the mode second; `Path.open` takes the mode first.
        positional = None
        if name == "open":
            index = 1 if isinstance(func, ast.Name) else 0
            if len(node.args) > index:
                positional = node.args[index]
        mode = next((kw.value for kw in node.keywords if kw.arg == "mode"), positional)
        if isinstance(mode, ast.Constant) and "b" in str(mode.value):
            continue
        found.append((name, node.lineno))
    return found


def test_the_package_never_relies_on_the_locale_encoding():
    """Every text read and write in `src/` must name its encoding.

    This is the check that cannot pass by accident: it does not depend on the
    host's default encoding, so removing an `encoding="utf-8"` fails here even
    on a UTF-8 runner.
    """
    offenders = []
    for path in _SOURCE_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for name, lineno in _unencoded_text_io(tree):
            offenders.append(f"{path.relative_to(ROOT)}:{lineno} {name}()")

    assert not offenders, (
        "text I/O without an explicit encoding falls back to the locale:\n  "
        + "\n  ".join(offenders)
    )


def test_the_guard_detects_a_missing_encoding():
    """A guard nobody has seen fail is not a guard."""
    tree = ast.parse("from pathlib import Path\nPath('x').read_text()\n")
    assert _unencoded_text_io(tree) == [("read_text", 2)]


def test_the_guard_accepts_an_explicit_encoding_and_binary_mode():
    tree = ast.parse(
        "from pathlib import Path\n"
        "Path('x').read_text(encoding='utf-8')\n"
        "Path('x').read_bytes()\n"
        "open('x', 'rb')\n"
    )
    assert _unencoded_text_io(tree) == []
