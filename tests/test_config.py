import copy
import json

import pytest

from mxd_jev.config import DEFAULT, load, write_default


def test_default_and_no_overwrite(tmp_path):
    path = tmp_path / "local/config.json"
    write_default(path)
    assert load(path)["jev"]["model"] == "typesafe/jev-1.13"
    with pytest.raises(ValueError):
        write_default(path)


@pytest.mark.parametrize("section,key,value", [
    ("control", "pulse_ms", 5000), ("control", "hp_threshold", float("nan")),
    ("keys", "attack", "f9"), ("keys", "attack", "left"),
    ("jev", "endpoint", "https://user:secret@example.com/test"),
    ("jev", "endpoint", "http://example.com/test"),
    ("vision", "hp_roi", [.9, .9, .9, .9]),
])
def test_rejects_unsafe_configuration(tmp_path, section, key, value):
    config = copy.deepcopy(DEFAULT)
    config[section][key] = value
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(ValueError):
        load(path)
