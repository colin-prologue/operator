from operator_router.fastpath import match_fastpath


def test_core_commands_hit():
    for text, intent in [("stop", "stop"), ("cancel", "cancel"),
                         ("pause", "pause"), ("resume", "resume"),
                         ("status", "status")]:
        hit = match_fastpath(text, awaiting=False)
        assert hit is not None and hit.intent == intent


def test_switch_to_surface_extracts_name():
    hit = match_fastpath("switch to proxy pilot", awaiting=False)
    assert hit is not None
    assert hit.intent == "switch_surface"
    assert hit.args["name"] == "proxy pilot"


def test_mode_and_profile_switches():
    assert match_fastpath("command mode", awaiting=False).intent == "mode_command"
    assert match_fastpath("dictation mode", awaiting=False).intent == "mode_dictation"
    assert match_fastpath("work mode", awaiting=False).intent == "profile_work"
    assert match_fastpath("personal mode", awaiting=False).intent == "profile_personal"


def test_confirmation_keywords_live_only_inside_awaiting():
    assert match_fastpath("confirm move", awaiting=False) is None
    hit = match_fastpath("confirm move", awaiting=True)
    assert hit is not None and hit.intent == "confirmation"


def test_unknown_text_misses():
    assert match_fastpath("summarize the repo deltas", awaiting=False) is None
