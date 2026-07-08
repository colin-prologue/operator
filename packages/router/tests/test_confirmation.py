
from operator_router.classes import OpClass
from operator_router.confirmation import ArmedOp, ConfirmationMachine


async def noop() -> str:
    return "done"


def arm_op(label="move", op="ticket_transition", cls=OpClass.C, token=None):
    return ArmedOp(label=label, op_name=op, op_class=cls,
                   readback=f"Read-back for {label}. Say \"confirm {label}\".",
                   token=token, execute=noop)


def test_arm_enters_awaiting_and_returns_readback():
    m = ConfirmationMachine()
    rb = m.arm(arm_op(), now=0.0)
    assert m.state == "AWAITING"
    assert 'confirm move' in rb


def test_exact_keyword_confirms():
    m = ConfirmationMachine()
    m.arm(arm_op("move"), now=0.0)
    out = m.handle("confirm move", now=1.0)
    assert out.kind == "confirmed" and out.armed.label == "move"
    assert m.state == "IDLE"


def test_bare_affirmatives_are_inert():
    m = ConfirmationMachine()
    m.arm(arm_op("move"), now=0.0)
    for text in ("yes", "yeah", "sure", "do it"):
        assert m.handle(text, now=1.0).kind == "pass"
    assert m.state == "AWAITING"


def test_bare_confirm_reprompts_without_executing():
    m = ConfirmationMachine()
    m.arm(arm_op("move"), now=0.0)
    out = m.handle("confirm", now=1.0)
    assert out.kind == "reprompt"
    assert m.state == "AWAITING"


def test_wrong_operation_word_reprompts():
    m = ConfirmationMachine()
    m.arm(arm_op("move"), now=0.0)
    out = m.handle("confirm remove", now=1.0)
    assert out.kind == "reprompt"
    assert m.state == "AWAITING"


def test_universal_aborts():
    for word in ("cancel", "stop", "never mind"):
        m = ConfirmationMachine()
        m.arm(arm_op(), now=0.0)
        out = m.handle(word, now=1.0)
        assert out.kind == "aborted"
        assert m.state == "IDLE"


def test_ttl_expiry_lets_it_go():
    m = ConfirmationMachine()
    m.arm(arm_op(), now=0.0)
    out = m.handle("confirm move", now=15.1)
    assert out.kind == "expired"
    assert "letting that go" in out.message.lower()
    assert m.state == "IDLE"


def test_new_arm_drops_pending_op():
    m = ConfirmationMachine()
    m.arm(arm_op("move"), now=0.0)
    m.arm(arm_op("send"), now=1.0)
    assert m.handle("confirm move", now=2.0).kind == "reprompt"
    assert m.handle("confirm send", now=3.0).kind == "confirmed"


def test_idle_machine_passes_everything():
    m = ConfirmationMachine()
    assert m.handle("confirm move", now=0.0).kind == "pass"


def test_new_arm_announces_the_drop():
    m = ConfirmationMachine()
    m.arm(arm_op("move"), now=0.0)
    rb = m.arm(arm_op("send"), now=1.0)
    assert rb.startswith("Dropping the pending move.")
    assert 'confirm send' in rb
