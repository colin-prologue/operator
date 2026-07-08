from operator_router.classes import OperationRegistry, OpClass


def test_default_class_is_x_for_unassigned_ops():
    reg = OperationRegistry()
    assert reg.classify("brand_new_capability") is OpClass.X
    assert not reg.is_assigned("brand_new_capability")


def test_assigned_class_is_returned():
    reg = OperationRegistry()
    reg.assign("ticket_list", OpClass.R)
    reg.assign("gate_stamp", OpClass.G)
    assert reg.classify("ticket_list") is OpClass.R
    assert reg.classify("gate_stamp") is OpClass.G
    assert reg.is_assigned("ticket_list")
