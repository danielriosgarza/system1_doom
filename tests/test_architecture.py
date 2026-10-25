"""The one rule, checked structurally and at run time: d1-ultra decides, code renders, bounds and presses keys.

- The removed modules (`modules.py`, `arbiter.py`, `exploration.py`) are gone and nothing imports them.
- Keys are pressed in one place, the controller, and only from System 1's pick: `execute_action` takes
  the menu entry of `result.pick.action`, and `execute_idle` runs only when there is no pick.
- Only `system1.py` turns an answer into a pick (it alone builds a `Pick` and draws random numbers).
- At run time every executed action is the central instance's answer: its top under exploit, and a
  missed central executes no action at all.
"""

import ast
from pathlib import Path

from system1_doom.controller import ControllerConfig, DoomDecisionController
from system1_doom.vizdoom_env import ViZDoomBridge
from tests.fake_d1 import FakeD1, choice, default_policy, menu_of

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "system1_doom"
REMOVED = ("modules", "arbiter", "exploration")


def _trees(*folders: Path):
    for folder in folders:
        for path in sorted(folder.rglob("*.py")):
            yield path, ast.parse(path.read_text(encoding="utf-8"))


def _imported(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            yield module
            yield from (f"{module}.{alias.name}" for alias in node.names)


def test_the_removed_modules_are_gone_and_nothing_imports_them():
    for name in REMOVED:
        assert not (SRC / f"{name}.py").exists(), name
    for path, tree in _trees(SRC, ROOT / "tests"):
        for module in _imported(tree):
            for name in REMOVED:
                assert module != f"system1_doom.{name}" and not module.startswith(f"system1_doom.{name}."), (path.name, module)


def _calls(tree: ast.AST, attribute: str):
    return [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == attribute]


def test_keys_are_pressed_only_by_the_controller_and_only_from_the_pick():
    pressing = {}
    for path, tree in _trees(SRC):
        for attribute in ("execute_action", "execute_idle"):
            if _calls(tree, attribute):
                pressing.setdefault(path.name, set()).add(attribute)
    assert pressing == {"controller.py": {"execute_action", "execute_idle"}}

    tree = ast.parse((SRC / "controller.py").read_text(encoding="utf-8"))
    (press,) = _calls(tree, "execute_action")
    assert [ast.unparse(a) for a in press.args] == ["executed"]
    assignments = [
        n for n in ast.walk(tree)
        if isinstance(n, (ast.Assign, ast.AnnAssign)) and "executed" in [ast.unparse(t) for t in (n.targets if isinstance(n, ast.Assign) else [n.target])]
    ]
    (assignment,) = assignments
    assert ast.unparse(assignment.value) == "menu_by_id[result.pick.action] if result.pick.action is not None else None"
    (idle,) = _calls(tree, "execute_idle")
    assert [ast.unparse(a) for a in idle.args] == ["bounds.decision_frames"]
    # The idle runs in the else branch of `if executed is not None`: only when there is no pick.
    branch = next(n for n in ast.walk(tree) if isinstance(n, ast.If) and ast.unparse(n.test) == "executed is not None" and press in ast.walk(n))
    assert any(idle in ast.walk(stmt) for stmt in branch.orelse)


def test_only_system1_turns_an_answer_into_a_pick():
    for path, tree in _trees(SRC):
        builds_pick = any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "Pick" for n in ast.walk(tree))
        imports_random = "random" in set(_imported(tree))
        if path.name == "system1.py":
            assert builds_pick and imports_random
        else:
            assert not builds_pick and not imports_random, path.name


def test_every_executed_action_is_the_centrals_answer_and_a_miss_executes_nothing(tmp_path):
    # The central answers the last action of the menu, which no sense recommends; misses at calls 2 and 5.
    def last_action(name, payload):
        if name == "central":
            menu = menu_of(payload)
            return {"choose": choice(menu, menu[-1], p=0.55)}
        return default_policy(name, payload)

    fake = FakeD1(last_action).fail("central", [2], "raise").fail("central", [5], "off_menu")
    env = ViZDoomBridge(scenario="deadly_corridor.cfg", window_visible=False, seed=2)
    pressed = []
    execute_action, execute_idle = env.execute_action, env.execute_idle
    env.execute_action = lambda action: pressed.append(action.id) or execute_action(action)
    env.execute_idle = lambda frames: pressed.append(("idle", frames)) or execute_idle(frames)
    ctrl = DoomDecisionController(
        env=env, config=ControllerConfig(log_dir=str(tmp_path), enable_slow_llm=False), api_key="liquid_test_key", transport=fake
    )
    try:
        traces = ctrl.run_ticks(7)
    finally:
        ctrl.close()
    assert len(pressed) == 7
    for trace, keys, payload_index in zip(traces, pressed, range(7)):
        central = trace.instances["central"]
        if trace.missed:
            assert keys == ("idle", 8) and central.missed and trace.pick.action is None
        else:
            menu = menu_of(fake.payloads("central")[payload_index])
            assert keys == trace.executed_action == trace.pick.action == central.action == menu[-1]
            assert central.action_probabilities[keys] == max(central.action_probabilities.values())
    assert [t.missed for t in traces] == [False, False, True, False, False, True, False]
    assert traces[5].instances["central"].miss_reason == "off_menu"
    assert traces[5].instances["central"].raw_answer["choice"] == "teleport_hack"
