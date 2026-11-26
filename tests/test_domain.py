from hakoniwa.domain.contract import check_code, check_spec, clean_params
from hakoniwa.domain.decisions import default_action, mock_decision, normalize_action
from hakoniwa.domain.pricing import cost_usd, price_for
from hakoniwa.domain.text import extract_json, fenced_block

REQ = {"key": "k", "agent": "a", "mode": "split",
       "options": [{"id": "x"}, {"id": "y"}],
       "numbers": [{"id": "n", "min": 0, "max": 10}],
       "default": {"weights": {"x": 3, "y": 1}, "numbers": {"n": 4}}}


def test_normalize_action_makes_any_answer_safe():
    a = normalize_action(REQ, {"weights": {"x": "2", "y": -5, "z": 9}, "numbers": {"n": 99}})
    assert a["weights"] == {"x": 1.0, "y": 0.0}
    assert a["numbers"]["n"] == 10
    b = normalize_action(REQ, {"weights": "nonsense"})
    assert b["weights"] == {"x": 0.75, "y": 0.25} and b["numbers"]["n"] == 4


def test_pick_falls_back_to_default_choice():
    req = {"key": "k", "agent": "a", "mode": "pick", "options": [{"id": "x"}, {"id": "y"}], "default": {"choice": "y"}}
    assert normalize_action(req, {"choice": "nope"})["choice"] == "y"
    assert default_action(req)["choice"] == "y"


def test_mock_decision_is_deterministic():
    assert mock_decision(REQ, 1, 3) == mock_decision(REQ, 1, 3)
    assert mock_decision(REQ, 1, 3) != mock_decision(REQ, 2, 3)


def test_check_code_blocks_unsafe_models():
    ok = "def init(p, r):\n    return {}\ndef step(s, p, r, t):\n    return None\ndef metrics(s, p, t):\n    return {}\n"
    assert check_code(ok) == []
    assert any("import" in e for e in check_code("import os\n" + ok))
    assert any("open" in e for e in check_code(ok + "x = open('/etc/passwd')\n"))
    assert any("dunder" in e for e in check_code(ok + "y = ().__class__\n"))
    assert any("missing required function" in e for e in check_code("def init(p, r):\n    return {}\n"))


def test_check_spec_and_params():
    spec = {"slug": "w", "title": "t", "summary": "s", "tick": {"default_ticks": 3},
            "parameters": [{"id": "a", "type": "int", "default": 2, "min": 0, "max": 5},
                           {"id": "b", "type": "choice", "default": "p", "choices": [{"id": "p"}, {"id": "q"}], "runtime": False}],
            "agents": [{"id": "x", "persona": "p"}], "metrics": [{"id": "m"}]}
    assert check_spec(spec) == []
    assert clean_params(spec, {"a": 99.4, "b": "zzz", "nope": 1}) == {"a": 5, "b": "p"}
    assert clean_params(spec, {"a": 1, "b": "q"}, runtime_only=True) == {"a": 1}
    bad = dict(spec, charts=[{"id": "c", "metrics": ["ghost"]}])
    assert any("unknown metric" in e for e in check_spec(bad))


def test_text_and_pricing_helpers():
    assert extract_json('noise ```json\n{"a": {"b": "}"}}\n``` more') == {"a": {"b": "}"}}
    assert fenced_block("```python\nx = 1\n```", "python") == "x = 1"
    prices = {"models": {"m": {"in": 1.0, "out": 2.0}}}
    assert price_for(prices, "m-2026") == {"in": 1.0, "out": 2.0}
    assert cost_usd(prices, "m", 1_000_000, 500_000) == 2.0
    assert cost_usd(prices, "other", 1, 1) is None


def test_residents_who_share_a_description_get_names_of_their_own():
    from hakoniwa.domain.names import display_name, resident_names
    spec = {"agents": [{"id": "pupil", "kind": "cohort"}, {"id": "head", "kind": "individual"}, {"id": "twin", "kind": "individual"}]}
    cast = [{"key": "pupil:1", "agent": "pupil", "given": None}, {"key": "head", "agent": "head", "given": None},
            {"key": "pupil:2", "agent": "pupil", "given": None}, {"key": "twin:a", "agent": "twin", "given": None},
            {"key": "twin:b", "agent": "twin", "given": {"en": "Bo", "ja": "ボー"}}]
    names = resident_names(spec, cast)
    assert names["pupil:1"] == {"en": "Yamada", "ja": "山田"} and names["pupil:2"] == {"en": "Sato", "ja": "佐藤"}
    assert names["head"] is None                       # the only one of its kind keeps the name in the spec
    assert names["twin:a"] and names["twin:b"] == {"en": "Bo", "ja": "ボー"}
    assert resident_names(spec, cast + [{"key": "pupil:3", "agent": "pupil", "given": None}])["pupil:1"] == names["pupil:1"]   # stable as the cast grows
    assert display_name(names["pupil:1"], 40) == {"en": "Yamada's group", "ja": "山田さんたち"}
    assert display_name(names["pupil:1"], None) == names["pupil:1"] and display_name(None, 40) is None
    assert len({(resident_names(spec, [{"key": str(i), "agent": "pupil", "given": None} for i in range(300)])[str(i)]["en"]) for i in range(300)}) == 300


def test_a_life_world_is_checked_for_what_it_needs():
    from hakoniwa.domain.contract import clean_life, life_focus, life_problems
    assert clean_life({"protagonist": {"profile": "too short"}, "options": [{"id": "a"}, {"id": "b"}]}) is None
    life = clean_life({"protagonist": {"profile": "A backend engineer of 32 with a family, a mortgage and an offer from a friend's startup."},
                       "options": [{"id": "stay", "label": {"en": "Stay", "ja": "残る"}}, {"id": "go", "label": "Go"}], "question": "Stay or go?"})
    assert life["protagonist"]["name"] == {"en": "You", "ja": "あなた"} and life["options"][1]["label"] == {"en": "Go", "ja": "Go"}
    spec = {"parameters": [{"id": "path", "type": "choice", "default": "stay", "choices": [{"id": "stay"}, {"id": "go"}]}, {"id": "x", "type": "bool", "default": False}],
            "metrics": [{"id": "satisfaction"}, {"id": "regret"}, {"id": "regard"}, {"id": "money"}],
            "events": [{"id": f"e{i}", "chance": 0.3, "patch": {"x": True}} for i in range(3)], "focus": {"outcomes": ["money", "nope"]}}
    assert life_problems(spec, life) == []
    assert life_focus(spec, life)["outcomes"] == ["satisfaction", "regret", "regard", "money"] and life_focus(spec, life)["key"] == "you"
    broken = dict(spec, parameters=[], metrics=[{"id": "satisfaction"}], events=[])
    assert len(life_problems(broken, life)) == 4            # no path, two metrics missing, no chance events
