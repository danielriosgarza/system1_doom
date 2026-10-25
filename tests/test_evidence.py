"""Evidence channels: golden text, scopes render only their channels, the caps, and the criteria."""

import json

import pytest

from system1_doom.actions import ActionVocabulary
from system1_doom.archive import DEFAULT_STRATEGIES
from system1_doom.configuration import CHANNELS, default_configuration
from system1_doom.evidence import (
    EvidenceCounters,
    EvidenceInputs,
    Message,
    ProjectionLine,
    ValueLine,
    build_inputs,
    render_channel,
    render_scope,
)
from system1_doom.instance import build_questions, central_spec, sense_spec
from system1_doom.relevance import RelevanceCounts
from system1_doom.state import (
    ControllerMemory,
    EnemyObservation,
    LandmarkObservation,
    Observation,
    PickupObservation,
    Pose3D,
    WorldState,
)


def golden_state() -> WorldState:
    obs = Observation(
        tick=42,
        health=64.0,
        armor=25.0,
        ammo=17,
        current_weapon="pistol",
        visible_enemies=(
            EnemyObservation(
                enemy_id="imp_2", name="DoomImp", distance=410.4, angle_offset=-21.3, screen_x=230, screen_y=110,
                width=20, height=40, is_attacking=True,
            ),
            EnemyObservation(
                enemy_id="zombie_1", name="Zombieman", distance=180.0, angle_offset=2.0, screen_x=158, screen_y=120,
                width=24, height=56,
            ),
        ),
        visible_pickups=(PickupObservation(pickup_id="med_1", name="Medikit", category="health", distance=150.0, angle_offset=5.0),),
        recent_incoming_damage=8.0,
        recent_outgoing_damage=40.0,
        recent_hits=2,
        recent_kills=1,
        movement_state="moving",
        recent_actions=("move_forward", "shoot", "strafe_left+turn_left", "shoot"),
        position=Pose3D(x=120.4, y=-64.6, angle=90.0),
        episode_progress={"tick": 42.0, "episode_tick": 12.0, "reward_so_far": 35.5, "kills": 1.0, "last_displacement": 18.2, "last_reward": -2.46},
        wall_distance_front=300.0,
        wall_distance_left=96.5,
        wall_distance_right=140.0,
        landmarks=(
            LandmarkObservation(
                landmark_id="armor_0", name="GreenArmor", category="armor", x=1312.0, y=0.0, distance=1192.4, bearing=-86.9,
                in_view=False, last_seen_tick=30, reward_agreement=1.0, reward_moves=26,
            ),
            LandmarkObservation(
                landmark_id="med_1", name="Medikit", category="health", x=120.0, y=85.0, distance=150.0, bearing=5.0,
                in_view=True, last_seen_tick=42,
            ),
            LandmarkObservation(
                landmark_id="clip_3", name="Clip", category="ammo", x=160.0, y=-110.0, distance=60.2, bearing=-131.3,
                in_view=False, last_seen_tick=39, reward_agreement=-0.62, reward_moves=8, approaches_nowhere=3,
            ),
        ),
    )
    memory = ControllerMemory(
        recent_state_summaries=(
            "tick=10 act=shoot hp=72 r=+1.0",
            "tick=11 act=strafe_left hp=64 r=-0.5",
            "tick=12 act=shoot hp=64 r=+100.0",
        )
    )
    return WorldState(observation=obs, memory=memory)


def golden_inputs() -> EvidenceInputs:
    vocab = ActionVocabulary.default()
    menu = [vocab.get("shoot"), vocab.get("strafe_left"), vocab.get("approach_pickup")]
    inputs = build_inputs(
        golden_state(),
        menu,
        novelty={"shoot": 3, "strafe_left": 1},
        archive=DEFAULT_STRATEGIES[:2],
        active_strategy="strat_tactical_combat",
        exploration_level="exploit",
        relevance={
            "survival": RelevanceCounts(
                spoke=14, followed=9, followed_paid=7, overruled=5, overruled_paid=2,
                strength_paid_sum=7.29, strength_paid_n=9, strength_unpaid_sum=3.2, strength_unpaid_n=5,
            ),
            "combat": RelevanceCounts(
                spoke=2, followed=2, followed_paid=1, strength_paid_sum=0.9, strength_paid_n=1, strength_unpaid_sum=0.7, strength_unpaid_n=1
            ),
        },
        counters=EvidenceCounters(decisions=12, under_fire_streak=2, stall_streak=0, sectors_discovered=3),
        frame_ref="frames/00042.jpg",
    )
    return inputs.model_copy(
        update={
            "projections": {
                "shoot": ProjectionLine(expected_value=3.336, damage_taken=3.21, damage_dealt=31.0, survival=0.77, progress=0.0, resource=0.0),
                "strafe_left": ProjectionLine(expected_value=-0.25, damage_taken=2.4, damage_dealt=0.0, survival=0.78, progress=0.15, resource=0.0),
            },
            "values": {
                "shoot": ValueLine(predictions={"survival": -0.1, "combat": 0.8, "navigation": -0.2, "resource": 0.0, "goal": 0.4}, tried=12),
                "strafe_left": ValueLine(
                    predictions={"survival": 0.05, "combat": -0.3, "navigation": 0.1, "resource": 0.0, "goal": -0.01}, tried=0
                ),
            },
            "messages": (
                Message(sense="survival", action="strafe_left", reason="under_fire", strength=0.82),
                Message(
                    sense="combat", action="shoot", reason="target_aimed", strength=0.9, target="zombie_1", target_kind="enemy",
                    target_line="Zombieman at distance 180, 2 deg left, size 24x56 px, under the crosshair",
                ),
            ),
        }
    )


GOLDEN = {
    "vitals": "[vitals]\nhealth 64, armor 25, ammo 17, weapon pistol",
    "threats": (
        "[threats]\n2 enemies visible, nearest first:\n"
        "- Zombieman at distance 180, 2 deg left, size 24x56 px, under the crosshair\n"
        "- DoomImp at distance 410, 21 deg right, size 20x40 px, attacking"
    ),
    "incoming": "[incoming]\ndamage taken since the last decision 8; consecutive decisions under fire 2",
    "outgoing": "[outgoing]\ndamage dealt since the last decision 40, hits 2, kills 1",
    "pickups": "[pickups]\n1 pickup visible, nearest first:\n- Medikit (health) at distance 150, 5 deg left",
    "landmarks": (
        "[landmarks]\n3 pickups seen this episode and not picked up, where each lies now from your position and facing, "
        "nearest first:\n"
        "- Clip (ammo): cannot be walked to from here, 3 walks at it got no closer; 60 away, 131 deg right, behind you, "
        "out of view, last seen 3 decisions ago\n"
        "- Medikit (health): 150 away, 5 deg left, in view; no reward link yet\n"
        "- GreenArmor (armor): 1192 away, 87 deg right, out of view, last seen 12 decisions ago; "
        "reward rose as you got closer (agreement +1.00 over 26 moves)"
    ),
    "geometry": "[geometry]\nwall distance ahead 300, left 96, right 140; moving",
    "position": "[position]\nx 120, y -65, facing 90 deg; 3 sectors discovered this episode",
    "progress": (
        "[progress]\ndecisions so far 12, reward so far 35.5, reward from the last decision -2.5, kills 1, "
        "last displacement 18 units, stall streak 0"
    ),
    "history": (
        "[history]\nlast 4 primitives executed, oldest first: move_forward, shoot, strafe_left+turn_left, shoot\n"
        "last 3 decisions, oldest first:\n- tick=10 act=shoot hp=72 r=+1.0\n- tick=11 act=strafe_left hp=64 r=-0.5\n"
        "- tick=12 act=shoot hp=64 r=+100.0"
    ),
    "frame": "[frame]\nthe screen at this decision is attached as the image (320x240)",
    "menu": (
        "[menu]\nthe legal actions now:\n- shoot: Turn onto the chosen enemy and fire the current weapon once it is centred\n"
        "- strafe_left: Sidestep left without walking forward; the aim keeps turning onto the chosen enemy while it is in view\n"
        "- approach_pickup: Walk to the pickup the resource sense chose, turning toward where it lies, even when it is out of view"
    ),
    "projections": (
        "[projections]\na rough projection from a hand-written simulator, not the game; per legal action:\n"
        "- shoot: expected value +3.34, damage in 3.2, damage out 31.0, survival 0.77, progress 0.00\n"
        "- strafe_left: expected value -0.25, damage in 2.4, damage out 0.0, survival 0.78, progress 0.15\n"
        "- approach_pickup: not projected"
    ),
    "values": (
        "[values]\nlearned from past play: each value network's predicted return (standardised) and how often the "
        "action was tried in this situation in training; per legal action:\n"
        "- shoot: survival -0.10, combat +0.80, navigation -0.20, resource +0.00, goal +0.40; tried 12 here\n"
        "- strafe_left: survival +0.05, combat -0.30, navigation +0.10, resource +0.00, goal -0.01; tried 0 here\n"
        "- approach_pickup: no prediction"
    ),
    "novelty": (
        "[novelty]\nhow often each legal action has been taken in this situation so far:\n"
        "- shoot: 3\n- strafe_left: 1\n- approach_pickup: 0"
    ),
    "archive": (
        "[archive]\nstrategies (active: strat_tactical_combat):\n"
        "- strat_tactical_combat (active): peek_and_fire, circle_strafe_left, shoot; reward 5.00, success 0.75, used 1 times\n"
        "- strat_evasive_survival: retreat_to_cover, strafe_left, approach_pickup; reward 4.00, success 0.70, used 1 times"
    ),
    "exploration": "[exploration]\nlevel exploit: the action you give the highest probability is executed.",
    "messages": (
        "[messages]\nsurvival says strafe_left, strength 0.82, reason under fire.\n"
        "combat says shoot, strength 0.90, reason target aimed, aim at Zombieman at distance 180, 2 deg left, size 24x56 px, "
        "under the crosshair."
    ),
    "relevance": (
        "[relevance]\neach sense's record in this situation "
        "(hp:medium|ammo:stocked|enemies:2:mid|dmg:under_fire|pickup:pickup_visible):\n"
        "survival here: spoke 14, followed 9, paid off 7 of 9; overruled 5, the chosen action paid off 2 of 5; "
        "mean strength 0.81 when it paid off, 0.64 when not.\n"
        "combat here: spoke 2, followed 2, paid off 1 of 2; overruled 0, the chosen action paid off 0 of 0; "
        "mean strength 0.90 over 1 tick when it paid off, 0.70 over 1 tick when not.\n"
        "navigation here: no record here.\nresource here: no record here.\ngoal here: no record here."
    ),
}


@pytest.mark.parametrize("channel", CHANNELS)
def test_each_channel_renders_its_golden_text(channel):
    assert render_channel(golden_inputs(), channel) == GOLDEN[channel]


def test_the_empty_cases_say_so():
    vocab = ActionVocabulary.default()
    calm = build_inputs(WorldState(observation=Observation()), [vocab.get("move_forward")])
    assert render_channel(calm, "threats") == "[threats]\nno enemy visible"
    assert render_channel(calm, "pickups") == "[pickups]\nno pickup visible"
    assert render_channel(calm, "landmarks") == (
        "[landmarks]\nno pickup remembered: none seen yet this episode, or every one seen was picked up"
    )
    assert render_channel(calm, "frame") == "[frame]\nno screen image at this decision"
    assert render_channel(calm, "values") == "[values]\nno value networks are loaded"
    assert render_channel(calm, "messages") == "[messages]\nno sense spoke this tick."
    assert render_channel(calm, "archive") == "[archive]\nno strategy archived"
    explore = calm.model_copy(update={"exploration_level": "explore"})
    assert "prefer a less-tried action when the messages do not demand otherwise" in render_channel(explore, "exploration")


def test_a_scope_renders_only_its_channels_in_channel_order():
    inputs = golden_inputs()
    configuration = default_configuration()
    for name, sense in configuration.senses.items():
        rendered = render_scope(inputs, sense.scope)
        headers = [line[1:-1] for line in rendered.text.splitlines() if line.startswith("[") and line.endswith("]")]
        assert headers == [c for c in CHANNELS if c in sense.scope], name
        assert rendered.text == "\n\n".join(GOLDEN[c] for c in headers)
    survival = render_scope(inputs, configuration.senses["survival"].scope).text
    assert "Medikit" not in survival and "[pickups]" not in survival and "says" not in survival
    resource = render_scope(inputs, configuration.senses["resource"].scope).text
    assert "Zombieman" not in resource and "expected value" not in resource and "GreenArmor" in resource
    with pytest.raises(ValueError):
        render_scope(inputs, ("vitals", "menu", "telepathy"))


def test_the_caps_hold():
    state = golden_state()
    obs = state.observation.model_copy(
        update={
            "visible_enemies": tuple(
                EnemyObservation(enemy_id=f"e{i}", name="DoomImp", distance=100.0 + i, angle_offset=0.0) for i in range(9)
            ),
            "visible_pickups": tuple(
                PickupObservation(pickup_id=f"p{i}", name="Clip", category="ammo", distance=50.0 + i) for i in range(8)
            ),
            "recent_actions": tuple(f"step_{i}" for i in range(10)),
        }
    )
    memory = state.memory.model_copy(update={"recent_state_summaries": tuple(f"summary {i}" for i in range(5))})
    inputs = build_inputs(WorldState(observation=obs, memory=memory), [ActionVocabulary.default().get("shoot")])
    threats = render_channel(inputs, "threats").splitlines()
    assert threats[1] == "9 enemies visible, nearest first (nearest 6 shown):" and len(threats) == 2 + 6
    pickups = render_channel(inputs, "pickups").splitlines()
    assert pickups[1] == "8 pickups visible, nearest first (nearest 6 shown):" and len(pickups) == 2 + 6
    history = render_channel(inputs, "history").splitlines()
    assert history[1] == "last 6 primitives executed, oldest first: step_4, step_5, step_6, step_7, step_8, step_9"
    assert history[3:] == ["- summary 2", "- summary 3", "- summary 4"]


def test_frame_attaches_the_image_only_when_in_scope():
    inputs = golden_inputs()
    assert render_scope(inputs, ("frame", "menu")).image_ref == "frames/00042.jpg"
    assert render_scope(inputs, ("vitals", "menu")).image_ref is None
    assert render_scope(inputs.model_copy(update={"frame_ref": None}), ("frame", "menu")).image_ref is None


def test_choice_criteria_are_exactly_the_legal_menu_and_never_carry_evidence():
    inputs = golden_inputs()
    configuration = default_configuration()
    menu = {item.id: item.description for item in inputs.menu}
    for spec in [sense_spec(n, s) for n, s in configuration.senses.items()] + [central_spec(configuration.central)]:
        questions = build_questions(spec, inputs.menu)
        key = "choose" if spec.kind == "central" else "action"
        criteria = questions[key].criteria
        assert criteria == menu and list(criteria) == inputs.menu_ids()
        text = json.dumps({k: q.to_payload() for k, q in questions.items()})
        for leak in ("expected value", "survival 0.", "tried", "predicted", "strength", "paid off", "+3.34"):
            assert leak not in text, (spec.name, leak)


def test_rendering_is_deterministic_and_survives_a_json_round_trip():
    inputs = golden_inputs()
    stored = EvidenceInputs.model_validate_json(inputs.model_dump_json())
    for scope in [s.scope for s in default_configuration().senses.values()] + [CHANNELS]:
        assert render_scope(stored, scope).text == render_scope(inputs, scope).text
