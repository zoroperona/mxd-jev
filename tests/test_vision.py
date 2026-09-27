import cv2
import numpy as np

from mxd_jev.vision import bar_ratio, matches


def test_bar_fill_and_ambiguous_empty_bar():
    img = np.full((12, 100, 3), 30, dtype=np.uint8)
    img[:, :42] = (0, 0, 255)
    assert bar_ratio(img, "hp") == .42
    assert bar_ratio(img, "mp") is None
    img[:, :42] = (255, 0, 0)
    assert bar_ratio(img, "mp") == .42


def test_right_side_colored_object_is_not_a_valid_bar():
    img = np.full((12, 100, 3), 30, dtype=np.uint8)
    img[:, 70:] = (0, 0, 255)
    assert bar_ratio(img, "hp") is None


def test_template_detection_and_duplicate_suppression():
    rng = np.random.default_rng(42)
    template = rng.integers(0, 255, (20, 20), dtype=np.uint8)
    gray = np.zeros((120, 160), dtype=np.uint8)
    gray[20:40, 30:50] = template
    gray[70:90, 100:120] = template
    found = matches(gray, template, .95, 10)
    assert {(d.x, d.y) for d in found} == {(30, 20), (100, 70)}
    assert matches(gray, np.zeros((10, 10), np.uint8), .8, 10) == []


def test_player_variants_merge_by_nameplate_not_body_offset(tmp_path):
    import copy
    from mxd_jev.config import DEFAULT
    from mxd_jev.vision import Vision
    config = copy.deepcopy(DEFAULT)
    config["reference_size"] = [400, 300]
    rng = np.random.default_rng(123)
    template = rng.integers(0, 255, (15, 50), dtype=np.uint8)
    cv2.imwrite(str(tmp_path / "player.png"), template)
    config["vision"].update(player_template="player.png", player_offset=[0, -40],
        player_variants=[{"path": "player.png", "offset": [35, -40]}], play_roi=[0, 0, 1, 1])
    frame = np.full((300, 400, 3), 80, dtype=np.uint8)
    frame[200:215, 150:200] = cv2.cvtColor(template, cv2.COLOR_GRAY2BGR)
    obs, _ = Vision(config, tmp_path).analyze(frame, 1, 0)
    assert obs.player is not None
