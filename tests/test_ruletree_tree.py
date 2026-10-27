"""The tree: rules are added as exceptions, groups and focus questions included; actions are checked where they
are placed; a tree is a folder that loads with its cornerstones' screens."""

import pytest

from system1_doom.ruletree.codes import ActionError
from system1_doom.ruletree.tree import Cornerstone, Proposal, SkillCall, load_tree, save_tree, tree_lines, with_rule
from tests.ruletree_fixtures import general_tree, screen_b64


def test_one_rule_becomes_an_exception_with_the_next_free_id():
    tree = general_tree()
    p = Proposal(trace="s9-00", frame=12, condition="The outgoing channel says the last 5 or more decisions in which I fired hit nothing.",
                 action={"skill": "aim", "then": "F001"}, why="stalled firing at a sliver")
    new, ids = with_rule(tree, p, attach_to="r1", writer="claude")
    assert ids == ["r11"]
    assert new.nodes["r11"].parent == "r1" and new.nodes["r1"].children == ["r2", "r11"]
    assert new.nodes["r11"].action == SkillCall(skill="aim", then="F001")
    assert new.nodes["r11"].provenance == {"trace": "s9-00", "frame": 12, "why": "stalled firing at a sliver", "writer": "claude"}
    # The tree it came from is unchanged.
    assert "r11" not in tree.nodes and tree.nodes["r1"].children == ["r2"]


def test_a_group_nests_by_index_and_ids_stay_unique():
    tree = general_tree()
    p = Proposal.model_validate({
        "trace": "s12-01", "frame": 24, "group": [
            {"condition": "a", "action": {"skill": "aim", "then": "0R01"}, "under": "frame"},
            {"condition": "b", "action": {"skill": "aim", "then": "0L01"}, "under": "frame"},
            {"condition": "c", "action": "0001", "under": 0},
        ]})
    new, ids = with_rule(tree, p, attach_to="r2")
    assert ids == ["r11", "r12", "r13"]
    assert new.nodes["r2"].children == ["r11", "r12"] and new.nodes["r11"].children == ["r13"]
    again, more = with_rule(new, Proposal(trace="x", frame=1, condition="d", action="0001"), attach_to="r1")
    assert more == ["r14"] and len(set(again.nodes)) == len(again.nodes)


def test_a_rule_may_have_its_own_focus_from_known_channels():
    tree = general_tree()
    focus = {"from": ["threats"], "question": "Which of these enemies is closest to the edge of a wall?"}
    new, (rid,) = with_rule(tree, Proposal(trace="x", frame=3, condition="c", action="0001", focus=focus), attach_to="r1")
    assert new.nodes[rid].focus.from_channels == ["threats"]
    with pytest.raises(ValueError):
        with_rule(tree, Proposal(trace="x", frame=3, condition="c", action="0001",
                                 focus={"from": ["engine"], "question": "q"}), attach_to="r1")


def test_a_partial_action_only_inside_a_skill():
    tree = general_tree()
    new, (rid,) = with_rule(tree, Proposal(trace="x", frame=3, condition="1 or 2 degrees right", action="00R0:1"), attach_to="r4")
    assert new.top(rid) == "aim"
    with pytest.raises(ActionError):
        with_rule(tree, Proposal(trace="x", frame=3, condition="c", action="00R0:1"), attach_to="r1")
    with pytest.raises(ActionError):
        with_rule(tree, Proposal(trace="x", frame=3, condition="c", action={"skill": "dodge", "then": "0001"}), attach_to="r1")
    with pytest.raises(ActionError):
        with_rule(tree, Proposal(trace="x", frame=3, condition="c", action="random"), attach_to="r1")
    with pytest.raises(ActionError):
        with_rule(tree, Proposal(trace="x", frame=3, condition="c", action="then"), attach_to="r1")


def test_tree_lines_print_the_skill_after_the_tree():
    lines = tree_lines(general_tree())
    assert lines[0] == "root: default -> random walk"
    assert lines[1].startswith("  r1: if 'The threats list shows at least one enemy.' [focus: 'Which of these enemies")
    assert lines[1].endswith("-> use skill aim, then fire")
    skill = lines.index("skill aim:")
    assert skill == 4 and lines[skill + 1] == "  aim: default -> the caller's action"
    assert lines[skill + 2] == "    r4: if 'The focus channel says it is between 3 and 7 degrees to the right.' -> turn right for 3 tics, then the caller's action (00R0:3)"


def test_a_tree_is_a_folder_with_its_cornerstones_screens(tmp_path):
    tree = general_tree()
    new, (rid,) = with_rule(tree, Proposal(trace="x", frame=2, condition="c", action="F001"), attach_to="r1")
    screen = screen_b64((200, 10, 10))
    c = Cornerstone(seed=9, prefix=["F000", "0001"], state_text="[vitals]\nhealth 90", frame="", expect="r1/" + rid,
                    event_at=7, horizon=31, standing=(1, 0, 90.0, 300.0))
    new.add_cornerstone(rid, c, screen)
    save_tree(new, tmp_path / "t")
    assert (tmp_path / "t" / "cornerstones" / f"{rid}-0.jpg").is_file()
    back = load_tree(tmp_path / "t")
    (kept,) = back.nodes[rid].cornerstones
    assert kept.frame == f"cornerstones/{rid}-0.jpg" and kept.decision == 2
    assert back.frame_b64(kept) == screen
    assert back.nodes["r1"].focus.question.startswith("Which of these enemies")
    # Saving elsewhere copies the screens along.
    save_tree(back, tmp_path / "u")
    assert load_tree(tmp_path / "u" / "tree.json").frame_b64(kept) == screen


def test_the_shipped_trees_play_on_their_own():
    from system1_doom.ruletree.codes import segments
    from system1_doom.ruletree.tree import shipped_trees

    assert {"general-9", "general-11", "codex-11"} <= set(shipped_trees())
    rules = {"general-9": 9, "general-11": 11, "codex-11": 11}
    for name, n in rules.items():
        tree = load_tree(name)
        assert tree.name == name and sum(1 for nid in tree.nodes if nid not in ("root", "aim")) == n
        assert tree.skills == ["aim"]
        for node in tree.nodes.values():
            for child in node.children:
                assert tree.nodes[child].parent == node.id
            for c in node.cornerstones:
                assert tree.frame_b64(c).startswith("/9j/")  # a JPEG
                assert all(segments(code) for code in c.prefix)
                assert c.expect.split("/")[-1] in tree.nodes and node.id in c.expect.split("/")
    assert load_tree("general-11").nodes["r12"].parent == "r11"
    assert load_tree("codex-11").nodes["r11"].action == SkillCall(skill="aim", then="0R01")
