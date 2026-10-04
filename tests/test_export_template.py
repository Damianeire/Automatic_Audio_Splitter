"""Runs the node tests for the Export tunes template's pure logic."""

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_export_template_logic():
    test = Path(__file__).with_name("export_template.test.mjs")
    run = subprocess.run(["node", "--test", str(test)], capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr
