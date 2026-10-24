"""Dependency imports must remain compatible without deprecation workarounds."""

import json
from pathlib import Path
import subprocess
import sys


def test_testclient_import_has_no_deprecation_warnings():
    # Bypass startup hooks while retaining this environment's installed packages.
    package_paths = [str(Path(path or ".").resolve()) for path in sys.path]
    result = subprocess.run(
        [
            sys.executable, "-I", "-S", "-B", "-W", "error::DeprecationWarning",
            "-c",
            "import json, sys; sys.path[:0] = json.loads(sys.argv[1]); "
            "from starlette.testclient import TestClient",
            json.dumps(package_paths),
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert result.stderr == ""
