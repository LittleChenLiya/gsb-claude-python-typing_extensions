"""Tests for plan_typeddict_update.

Run with::

    pytest src/test_typeddict_update.py
"""

from typing import Generic, Literal, Optional, TypeVar

import pytest

from typing_extensions import (
    DELETE,
    NotRequired,
    ReadOnly,
    TypedDict,
    plan_typeddict_update,
)


# Three-field example used throughout the acceptance tests.
class User(TypedDict):
    id: ReadOnly[int]
    name: NotRequired[str]
    age: int


@pytest.fixture
def record():
    return User(id=1, age=30)


def test_readonly_id_refuses_value_change(record):
    # 只读id拒绝改值: a read-only field cannot be modified.
    with pytest.raises(TypeError, match="read-only"):
        plan_typeddict_update(User, record, {"id": 2})
    assert record == {"id": 1, "age": 30}


def test_optional_name_omitted_is_preserved(record):
    # 可选name省略保留: an omitted key is preserved, not deleted.
    updated = plan_typeddict_update(User, record, {"age": 31})
    assert updated == {"id": 1, "age": 31}
    assert record == {"id": 1, "age": 30}


def test_optional_name_explicit_delete_allowed():
    # 显式删允许: an optional, mutable field can be explicitly deleted.
    record = User(id=1, name="Alice", age=30)
    updated = plan_typeddict_update(User, record, {"name": DELETE})
    assert updated == {"id": 1, "age": 30}
    assert record == {"id": 1, "name": "Alice", "age": 30}


def test_required_field_delete_fails(record):
    # 必需字段删除失败: a required field cannot be deleted.
    with pytest.raises(TypeError, match="read-only"):
        plan_typeddict_update(User, record, {"id": DELETE})
    assert record == {"id": 1, "age": 30}


def test_original_record_remains_complete(record):
    # 原记录仍完整: the original record is never modified.
    before = dict(record)
    plan_typeddict_update(User, record, {"age": 31, "name": "Bob"})
    assert record == before


def test_unknown_type_does_not_pass():
    # 未知这类未知类型不当通过: unknown types are rejected.
    class Custom:
        pass

    class HasUnknown(TypedDict):
        x: int
        y: Custom

    record = HasUnknown(x=1)
    with pytest.raises(TypeError, match="not a supported safe type"):
        plan_typeddict_update(HasUnknown, record, {"x": 2})


def test_forward_ref_unknown_type_does_not_pass():
    # A forward-reference to an unknown type is also rejected.
    class HasForwardRef(TypedDict):
        x: int
        y: "未知"  # noqa: F821

    record = HasForwardRef(x=1)
    with pytest.raises(TypeError, match="not a supported safe type"):
        plan_typeddict_update(HasForwardRef, record, {"x": 2})


def test_type_mismatch_fails(record):
    with pytest.raises(TypeError, match="expected int"):
        plan_typeddict_update(User, record, {"age": "old"})


def test_type_check_uses_exact_type_not_isinstance():
    # bool is not accepted where int is expected (no user isinstance logic).
    class TD(TypedDict):
        count: int

    record = TD(count=1)
    with pytest.raises(TypeError, match="expected int"):
        plan_typeddict_update(TD, record, {"count": True})


def test_container_types_checked():
    class TD(TypedDict):
        items: list
        mapping: dict
        pair: tuple

    record = TD(items=[1, 2], mapping={"a": 1}, pair=(1, "x"))
    updated = plan_typeddict_update(TD, record, {"items": [3, 4]})
    assert updated == {"items": [3, 4], "mapping": {"a": 1}, "pair": (1, "x")}


def test_container_element_types_checked():
    class TD(TypedDict):
        items: list[int]

    record = TD(items=[1, 2])
    with pytest.raises(TypeError, match="expected int"):
        plan_typeddict_update(TD, record, {"items": ["a"]})


def test_literal_type_checked():
    class TD(TypedDict):
        status: Literal["active", "inactive"]

    record = TD(status="active")
    updated = plan_typeddict_update(TD, record, {"status": "inactive"})
    assert updated == {"status": "inactive"}
    with pytest.raises(TypeError, match="not one of"):
        plan_typeddict_update(TD, record, {"status": "unknown"})


def test_optional_type_checked():
    class TD(TypedDict):
        name: Optional[str]

    record = TD(name="Alice")
    updated = plan_typeddict_update(TD, record, {"name": None})
    assert updated == {"name": None}
    with pytest.raises(TypeError, match="does not match"):
        plan_typeddict_update(TD, record, {"name": 42})


def test_any_type_passes():
    class TD(TypedDict):
        anything: object

    record = TD(anything=1)
    updated = plan_typeddict_update(TD, record, {"anything": "value"})
    assert updated == {"anything": "value"}


def test_omitted_keys_preserved(record):
    updated = plan_typeddict_update(User, record, {"age": 31})
    assert updated == {"id": 1, "age": 31}


def test_unknown_field_in_update_fails(record):
    with pytest.raises(TypeError, match="unknown field"):
        plan_typeddict_update(User, record, {"unknown": 1})


def test_delete_readonly_field_fails():
    class TD(TypedDict):
        id: ReadOnly[int]
        name: NotRequired[str]

    record = TD(id=1, name="Alice")
    with pytest.raises(TypeError, match="read-only"):
        plan_typeddict_update(TD, record, {"id": DELETE})


def test_delete_optional_field_not_in_record_is_noop():
    record = User(id=1, age=30)  # name is absent
    updated = plan_typeddict_update(User, record, {"name": DELETE})
    assert updated == {"id": 1, "age": 30}


def test_empty_update_returns_copy(record):
    updated = plan_typeddict_update(User, record, {})
    assert updated == record
    assert updated is not record


T = TypeVar("T")


class Box(TypedDict, Generic[T]):
    item: T
    label: NotRequired[str]


def test_generic_typeddict_alias_resolves_typevar():
    record = Box[int](item=1)
    updated = plan_typeddict_update(Box[int], record, {"item": 2})
    assert updated == {"item": 2}
    with pytest.raises(TypeError, match="expected int"):
        plan_typeddict_update(Box[int], record, {"item": "x"})


def test_generic_typeddict_subclass_resolves_typevar():
    class StrBox(Box[str]):
        extra: int

    record = StrBox(item="a", extra=1)
    updated = plan_typeddict_update(StrBox, record, {"item": "b"})
    assert updated == {"item": "b", "extra": 1}
    with pytest.raises(TypeError, match="expected str"):
        plan_typeddict_update(StrBox, record, {"item": 1})


def test_inherited_fields_checked():
    class Base(TypedDict):
        id: ReadOnly[int]

    class Child(Base):
        name: NotRequired[str]

    record = Child(id=1)
    updated = plan_typeddict_update(Child, record, {"name": "Alice"})
    assert updated == {"id": 1, "name": "Alice"}
    with pytest.raises(TypeError, match="read-only"):
        plan_typeddict_update(Child, record, {"id": 2})


def test_record_must_be_dict():
    with pytest.raises(TypeError, match="record must be a dict"):
        plan_typeddict_update(User, [1, 2], {})


def test_update_must_be_dict(record):
    with pytest.raises(TypeError, match="update must be a dict"):
        plan_typeddict_update(User, record, [1, 2])


def test_typeddict_must_be_typeddict(record):
    with pytest.raises(TypeError, match="expected a TypedDict"):
        plan_typeddict_update(dict, record, {})
