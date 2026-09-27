import copy

from mxd_jev.config import DEFAULT
from mxd_jev.policy import Policy, scene_signature
from mxd_jev.state import Detection, Observation


def observed(**kwargs):
    values = dict(frame_id=1, timestamp=10.0, player=(300, 300), hp=0.8, mp=0.8,
                  minimap=(0.5, 0.5), valid=True, reason="ok")
    values.update(kwargs)
    return Observation(**values)


def test_survival_preempts_attacks_and_potions_have_cooldown():
    p = Policy(copy.deepcopy(DEFAULT))
    obs = observed(hp=0.2, monsters=[Detection(320, 280, 40, 40, 0.9)])
    d = p.decide(obs, 10)
    assert d.action == "heal"
    p.executed(d, obs, 10, 0.09)
    assert p.decide(obs, 10.1).action == "wait"


def test_failed_potions_eventually_pause():
    p = Policy(copy.deepcopy(DEFAULT))
    for n in range(3):
        now = 10 + 2 * n
        obs = observed(timestamp=now, hp=0.2)
        d = p.decide(obs, now)
        assert d.action == "heal"
        p.executed(d, obs, now, 0.09)
    assert p.decide(observed(timestamp=18, hp=0.2), 18).action == "pause"


def test_stale_invalid_or_future_observation_never_attacks():
    p = Policy(copy.deepcopy(DEFAULT))
    assert p.decide(observed(), 11).action == "pause"
    assert p.decide(observed(), 9).action == "pause"
    assert p.decide(observed(valid=False), 10).action == "pause"


def test_ignores_other_floor_and_chooses_visible_attack_side():
    p = Policy(copy.deepcopy(DEFAULT))
    obs = observed(monsters=[Detection(280, 100, 40, 40, 0.99), Detection(320, 280, 40, 40, 0.95)])
    assert p.decide(obs, 10).action == "attack_right"
    assert "attack_left" not in p.candidates(obs)


def test_no_blind_patrol_without_route():
    p = Policy(copy.deepcopy(DEFAULT))
    assert p.decide(observed(), 10).action == "wait"


def test_stuck_movement_uses_minimap_instead_of_scrolling_screen():
    config = copy.deepcopy(DEFAULT)
    p = Policy(config)
    obs = observed(monsters=[Detection(650, 280, 40, 40, .95)])
    d = p.decide(obs, 10)
    for _ in range(50):
        p.executed(d, obs, 10, .09)
    assert p.decide(obs, 10).reason == "movement_not_observed"
    p.executed(d, observed(minimap=(0.6, 0.5)), 10, .09)
    assert p.decide(obs, 10).action == "move_right"


def test_route_requires_minimap_and_advances_only_on_arrival():
    config = copy.deepcopy(DEFAULT)
    config["route"].update(enabled=True, waypoints=[
        {"x": .6, "y": .5, "action": "move_right"},
        {"x": .3, "y": .5, "action": "move_left"},
    ])
    p = Policy(config)
    assert p.decide(observed(minimap=None), 10).action == "pause"
    assert p.decide(observed(), 10).action == "move_right"
    assert p.decide(observed(minimap=(.6, .5)), 10).action == "move_left"
