"""td_update_plan 的验收测试。

运行方式（仓库根目录）：
    python -m pytest td_update/test_td_update_plan.py -q
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from typing import Generic, TypeVar

import typing_extensions as te

from td_update_plan import plan_update


# ---- 三字段例子：只读 id / 可选 name / 必需 email ----
class UserRecord(te.TypedDict):
    id: te.ReadOnly[int]
    name: te.NotRequired[str]
    email: str


BASE_RECORD = {"id": 1, "name": "alice", "email": "a@example.com"}


def test_readonly_id_rejects_change():
    plan = plan_update(UserRecord, BASE_RECORD, patch={"id": 2})
    assert not plan.ok
    assert plan.result is None
    assert any("只读" in e and "id" in e for e in plan.errors)


def test_readonly_id_same_value_is_noop():
    plan = plan_update(UserRecord, BASE_RECORD, patch={"id": 1, "email": "b@x.com"})
    assert plan.ok
    assert plan.result == {"id": 1, "name": "alice", "email": "b@x.com"}


def test_optional_name_omitted_is_preserved():
    # 省略键 = 保留，不是删除
    plan = plan_update(UserRecord, BASE_RECORD, patch={"email": "b@x.com"})
    assert plan.ok
    assert plan.result["name"] == "alice"


def test_optional_name_explicit_delete_allowed():
    plan = plan_update(UserRecord, BASE_RECORD, deletes=["name"])
    assert plan.ok
    assert "name" not in plan.result
    assert plan.result == {"id": 1, "email": "a@example.com"}


def test_required_email_delete_fails():
    plan = plan_update(UserRecord, BASE_RECORD, deletes=["email"])
    assert not plan.ok
    assert plan.result is None
    assert any("必需" in e and "email" in e for e in plan.errors)


def test_readonly_id_delete_fails():
    plan = plan_update(UserRecord, BASE_RECORD, deletes=["id"])
    assert not plan.ok
    assert plan.result is None


def test_original_record_untouched_and_result_independent():
    snapshot = dict(BASE_RECORD)
    plan = plan_update(
        UserRecord, BASE_RECORD, patch={"email": "c@x.com"}, deletes=["name"]
    )
    assert plan.ok
    assert BASE_RECORD == snapshot          # 原记录仍完整
    assert plan.result is not BASE_RECORD
    plan.result["email"] = "hacker@x.com"   # 结果是独立副本
    assert BASE_RECORD["email"] == "a@example.com"


def test_all_or_nothing():
    # 一个合法修改 + 一个非法修改 => 整体失败，不给结果
    plan = plan_update(
        UserRecord, BASE_RECORD, patch={"email": "ok@x.com", "id": 99}
    )
    assert not plan.ok
    assert plan.result is None
    assert BASE_RECORD["email"] == "a@example.com"


def test_unknown_key_rejected():
    plan = plan_update(UserRecord, BASE_RECORD, patch={"ghost": 1})
    assert not plan.ok
    assert any("未知键" in e for e in plan.errors)


def test_wrong_safe_type_rejected_and_bool_is_not_int():
    plan = plan_update(UserRecord, BASE_RECORD, patch={"email": 123})
    assert not plan.ok
    plan = plan_update(UserRecord, BASE_RECORD, patch={"id": True})
    assert not plan.ok  # bool 不是 int（精确类型匹配）


# ---- 未知类型不当通过 ----
class Custom:
    pass


class WithUnknown(te.TypedDict):
    id: int
    payload: Custom  # 不在安全类型清单内


def test_unknown_type_field_not_passed():
    rec = {"id": 1, "payload": Custom()}
    plan = plan_update(WithUnknown, rec, patch={"payload": Custom()})
    assert not plan.ok
    assert plan.result is None
    assert any("安全类型" in e for e in plan.errors)
    # 未触碰该字段时，合法修改仍可通过
    plan = plan_update(WithUnknown, rec, patch={"id": 2})
    assert plan.ok and plan.result["id"] == 2


# ---- 继承：子类继承只读 id 与必需 email ----
class AdminRecord(UserRecord):
    level: te.NotRequired[int]


def test_inherited_fields_enforced():
    rec = {"id": 1, "email": "a@x.com", "level": 3}
    assert not plan_update(AdminRecord, rec, patch={"id": 2}).ok
    assert not plan_update(AdminRecord, rec, deletes=["email"]).ok
    plan = plan_update(AdminRecord, rec, deletes=["level"])
    assert plan.ok and "level" not in plan.result


# ---- 泛型：按实际绑定处理 ----
T = TypeVar("T")


class Box(te.TypedDict, Generic[T]):
    item: T


class StrBox(Box[str]):
    pass


def test_generic_binding_applied():
    rec = {"item": 1}
    assert plan_update(Box[int], rec, patch={"item": 2}).ok
    assert not plan_update(Box[int], rec, patch={"item": "x"}).ok
    # 经继承绑定
    srec = {"item": "a"}
    assert plan_update(StrBox, srec, patch={"item": "b"}).ok
    assert not plan_update(StrBox, srec, patch={"item": 3}).ok
    # 未绑定的 TypeVar 属于未知类型，不予通过
    assert not plan_update(Box, rec, patch={"item": 2}).ok
