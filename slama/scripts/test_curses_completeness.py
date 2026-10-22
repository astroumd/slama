"""Tests for scripts/curses_completeness.py (synthetic C sources, no SMA code)."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

_spec = importlib.util.spec_from_file_location(
    "curses_completeness", Path(__file__).with_name("curses_completeness.py"))
cc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cc)


def _c_tree(tmp_path, c_text, header_text):
    src = tmp_path / "src"
    inc = tmp_path / "include"
    src.mkdir()
    inc.mkdir()
    (inc / "servo.h").write_text(header_text)
    c = src / "page.c"
    c.write_text(c_text)
    return c


def test_literals_and_used_header_macro(tmp_path):
    c = _c_tree(tmp_path,
                '#include "servo.h"\nrm_read(a, "RM_A_F", &x);\nRV rv[] = SERVO_VARS;\n',
                '#define SERVO_VARS { \\\n  {&p, "RM_B_L"}, \\\n  {&q, "RM_C_B"}}\n'
                '#define OTHER_VARS { {&r, "RM_D_F"} }\n')
    names = cc.read_names(c)
    assert names == {"RM_A_F": "", "RM_B_L": "servo.h:SERVO_VARS", "RM_C_B": "servo.h:SERVO_VARS"}


def test_unused_macro_and_missing_header_ignored(tmp_path):
    c = _c_tree(tmp_path, '#include "servo.h"\n#include "absent.h"\n"DSM_X_L"\n',
                '#define SERVO_VARS { {&p, "RM_B_L"} }\n')
    assert cc.read_names(c) == {"DSM_X_L": ""}


def test_coverage_through_computed_points(tmp_path):
    display = tmp_path / "d.json"
    display.write_text(json.dumps({"layout": [
        {"rows": [{"points": "monitorsystem:antenna:{ant}:flag"}]},
        {"cells": [{"point": "RM:acc1:RM_SHOWN_F"}]},
    ]}))
    nodes = [
        SimpleNamespace(output="monitorsystem:antenna:3:flag",
                        inputs={"a": "monitorsystem:antenna:3:mid"}),
        SimpleNamespace(output="monitorsystem:antenna:3:mid",
                        inputs=["RM:acc3:RM_DEEP_B"]),
        SimpleNamespace(output="monitorsystem:antenna:3:unshown",
                        inputs=["RM:acc3:RM_HIDDEN_B"]),
    ]
    covered = cc.covered_names(cc.display_points(display), cc.compute_inputs(nodes))
    result = cc.coverage({"RM_SHOWN_F": "", "RM_DEEP_B": "", "RM_HIDDEN_B": ""}, covered)
    assert result == {"RM_SHOWN_F": True, "RM_DEEP_B": True, "RM_HIDDEN_B": False}
