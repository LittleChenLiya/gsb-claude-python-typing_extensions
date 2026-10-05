"""TypedDict 稀疏更新计划器（update planner）。

语义约定（计划要点）：
1. ``patch`` 是稀疏修改：只覆盖显式给出的键；**省略的键一律保留，绝不视为删除**。
2. 删除是独立操作，只能经由 ``deletes`` 显式声明。
3. 必需（Required / total）字段与只读（ReadOnly）字段**不可删除**。
4. 只读字段**不可改值**；赋予与现值相同的安全标量值视为无操作。
5. 类型校验只支持下列文档列明的安全类型，且用 ``type(value) is T`` 精确判断，
   不调用 ``isinstance``，因而不会触发任何用户自定义的 ``__instancecheck__``：
   ``str``、``int``、``float``、``bool``、``bytes``、``None``（NoneType）。
   注意 ``bool`` 与 ``int`` 视为不同类型（精确类型匹配）。
6. 未知/未列明类型（自定义类、容器、Union、未绑定的 TypeVar 等）**一律不予通过**，
   绝不默认放行。
7. 全部校验通过才返回独立的新 dict 结果；任一失败则整体失败（result=None），
   原记录在任何情况下都不被修改。
8. 继承字段按 ``get_type_hints(..., include_extras=True)`` 合并解析；
   泛型字段按实际绑定（如 ``Box[int]`` 或 ``class S(Box[str])``）替换 TypeVar。
"""

from __future__ import annotations

import dataclasses
import typing
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

import typing_extensions as te

# 文档列明的安全类型：仅此几种参与精确类型校验。
SAFE_TYPES: Tuple[type, ...] = (str, int, float, bool, bytes, type(None))

_MISSING = object()  # 哨兵：区分“键不存在”与“值为 None”

_QUALIFIERS_REQUIRED = {te.Required, getattr(typing, "Required", te.Required)}
_QUALIFIERS_NOT_REQUIRED = {te.NotRequired, getattr(typing, "NotRequired", te.NotRequired)}
_QUALIFIERS_READONLY = {te.ReadOnly, getattr(typing, "ReadOnly", te.ReadOnly)}


@dataclasses.dataclass(frozen=True)
class FieldSpec:
    name: str
    type: Any          # 解包限定符并按泛型绑定替换后的类型
    required: bool
    readonly: bool


@dataclasses.dataclass(frozen=True)
class UpdatePlan:
    ok: bool
    result: Optional[Dict[str, Any]]  # 全通过时为独立新 dict；否则为 None
    errors: Tuple[str, ...]


def _collect_bindings(td: Any, bindings: Dict[typing.TypeVar, Any]) -> None:
    """沿 __orig_bases__ 收集 TypeVar -> 实际类型 的绑定（含继承链）。"""
    cls = te.get_origin(td)
    if cls is not None:
        params = getattr(cls, "__parameters__", ())
        for p, a in zip(params, te.get_args(td)):
            bindings.setdefault(p, a)
        td = cls
    for base in getattr(td, "__orig_bases__", ()):
        _collect_bindings(base, bindings)


def _resolve_typevars(hint: Any, bindings: Mapping[typing.TypeVar, Any]) -> Any:
    seen = set()
    while isinstance(hint, typing.TypeVar) and hint in bindings and hint not in seen:
        seen.add(hint)
        hint = bindings[hint]
    return hint


def _field_specs(td: Any) -> Dict[str, FieldSpec]:
    cls = te.get_origin(td) or td
    bindings: Dict[typing.TypeVar, Any] = {}
    _collect_bindings(td, bindings)

    hints = te.get_type_hints(cls, include_extras=True)
    required_keys = set(getattr(cls, "__required_keys__", ()))

    specs: Dict[str, FieldSpec] = {}
    for name, hint in hints.items():
        required = name in required_keys
        readonly = False
        # 解包 Required / NotRequired / ReadOnly（可嵌套）
        while True:
            origin = te.get_origin(hint)
            if origin in _QUALIFIERS_READONLY:
                readonly = True
                hint = te.get_args(hint)[0]
            elif origin in _QUALIFIERS_REQUIRED:
                required = True
                hint = te.get_args(hint)[0]
            elif origin in _QUALIFIERS_NOT_REQUIRED:
                required = False
                hint = te.get_args(hint)[0]
            else:
                break
        hint = _resolve_typevars(hint, bindings)
        specs[name] = FieldSpec(name=name, type=hint, required=required, readonly=readonly)
    return specs


def _check_value(expected: Any, value: Any) -> Optional[str]:
    """返回 None 表示通过；否则返回错误信息。未知类型一律不通过。"""
    if isinstance(expected, type) and expected in SAFE_TYPES:
        if type(value) is expected:  # 精确判断，不走 isinstance / 用户钩子
            return None
        return (
            f"值类型不匹配：期望精确类型 {expected.__name__}，"
            f"实际 {type(value).__name__}"
        )
    return f"字段类型 {expected!r} 不在安全类型清单内，无法安全校验，拒绝放行"


def plan_update(
    td: Any,
    record: Mapping[str, Any],
    patch: Optional[Mapping[str, Any]] = None,
    deletes: Iterable[str] = (),
) -> UpdatePlan:
    """对 ``record`` 应用稀疏 ``patch`` 与显式 ``deletes``，返回更新计划。

    - 省略的键保留原值；删除只能经 ``deletes`` 显式声明。
    - 必需/只读字段不可删；只读字段不可改值。
    - 全部通过才返回独立结果；任何情况下不修改 ``record``。
    """
    patch = {} if patch is None else dict(patch)
    deletes = tuple(deletes)
    specs = _field_specs(td)
    errors = []

    unknown = sorted((set(patch) | set(deletes)) - set(specs))
    for key in unknown:
        errors.append(f"未知键 {key!r}：不在 TypedDict 字段中")

    result = dict(record)  # 独立副本，原记录不动

    # 1) 显式删除（独立操作）
    for key in deletes:
        if key not in specs:
            continue
        spec = specs[key]
        if spec.required:
            errors.append(f"字段 {key!r} 为必需字段，禁止删除")
        elif spec.readonly:
            errors.append(f"字段 {key!r} 为只读字段，禁止删除")
        else:
            result.pop(key, None)  # 可选字段：存在则删，不存在为无操作

    # 2) 稀疏修改
    for key, value in patch.items():
        if key not in specs:
            continue
        spec = specs[key]
        if spec.readonly:
            current = record.get(key, _MISSING)
            if (
                current is not _MISSING
                and type(current) in SAFE_TYPES
                and type(value) is type(current)
                and value == current
            ):
                continue  # 同值无操作
            errors.append(f"字段 {key!r} 为只读字段，禁止改值")
            continue
        err = _check_value(spec.type, value)
        if err is not None:
            errors.append(f"字段 {key!r}：{err}")
            continue
        result[key] = value

    if errors:
        return UpdatePlan(ok=False, result=None, errors=tuple(errors))
    return UpdatePlan(ok=True, result=result, errors=())
