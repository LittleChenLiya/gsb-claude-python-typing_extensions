"""Focused, deterministic tests for ``instantiate_type_alias``.

These tests cover the *explicit instantiation plan* for a stored
:class:`typing_extensions.TypeAliasType`: substitute type parameters into the
stored value of the alias, returning an
:class:`~typing_extensions.InstantiatedTypeAlias`.

Acceptance scenarios
--------------------
1. ``type Alias[T] = list[Annotated[T, "x"]]`` instantiated with ``int`` gives
   ``list[Annotated[int, "x"]]`` (annotation metadata is retained in order).
2. Recursive aliases keep finite back-edges: a bare self-reference becomes an
   identity back-edge and an applied self-reference becomes a finite
   :class:`~typing_extensions.TypeAliasReference` node. Nothing is expanded
   infinitely.
3. Defaults bind after explicit arguments; defaults may refer to earlier
   parameters. Explicit arguments always win.
4. ``typing.ForwardRef`` nodes (string forward references) are resolved
   **only** through the provided ``names`` mapping. They are never evaluated
   with ``eval`` and lazy bare-string expressions are never forced to run.
5. Unknown (unprovided) names are returned as locatable
   :class:`~typing_extensions.PendingType` items (collected in
   ``result.__pending__``) instead of raising.

Support scope
-------------
* Supported on the same Python versions as ``typing_extensions`` itself
  (CPython 3.9+ and PyPy), with both ``typing.TypeAliasType`` and the
  ``typing_extensions.TypeAliasType`` backport.
* Fully supported parameter kind: :data:`~typing_extensions.TypeVar`,
  including PEP 696 ``default=`` values.
* Rebuilt expression nodes: ``typing.Union[...]`` and PEP 604 ``X | Y``
  unions (union flavor is preserved where possible), PEP 585 built-in
  generics (``list[...]``, ``dict[...]``, ...), ``typing`` generics
  (``List[...]``, ``Tuple[...]``), ``Callable[...]``, ``Concatenate``,
  ``Unpack`` and ``Annotated[...]`` (metadata order preserved).
* ``TypeVarTuple`` and ``ParamSpec`` parameters are bound and substituted as
  whole values (e.g. ``Unpack[Ts]`` receives the whole bound value); positional
  splatting and parameter-list decomposition are intentionally out of scope.
* Only string :class:`~typing.ForwardRef` nodes are looked up in ``names``;
  plain annotation metadata strings are names, not expressions, and are never
  resolved or evaluated.

How to run
----------
From the repository root (``src`` is importable in the editable/source
layout)::

    python -m pytest src/test_instantiate_type_alias.py -q

With cache/temp directories redirected to the D: drive (as required by the
task runner on Windows)::

    set TMPDIR=D:\\Codex\\.tmp
    set TEMP=D:\\Codex\\.tmp
    set TMP=D:\\Codex\\.tmp
    set PYTHONPYCACHEPREFIX=D:\\Codex\\.pycache
    python -m pytest src/test_instantiate_type_alias.py -q
"""

from __future__ import annotations

import typing
from typing import Callable, Dict, List, Optional, Tuple, Union

import pytest

from typing_extensions import (
    Annotated,
    Concatenate,
    InstantiatedTypeAlias,
    ParamSpec,
    PendingType,
    TypeAliasReference,
    TypeAliasType,
    TypeVar,
    TypeVarTuple,
    Unpack,
    instantiate_type_alias,
)


T = TypeVar("T")
U = TypeVar("U")


def test_acceptance_annotated_substitution_preserves_metadata():
    # type Alias[T] = list[Annotated[T, "x"]]
    Alias = TypeAliasType("Alias", List[Annotated[T, "x"]], type_params=(T,))
    result = instantiate_type_alias(Alias, int)

    assert isinstance(result, InstantiatedTypeAlias)
    assert result.__value__ == List[Annotated[int, "x"]]
    annotated = result.__value__.__args__[0]
    assert annotated.__origin__ is int
    assert annotated.__metadata__ == ("x",)
    assert result.__name__ == "Alias[int]"
    assert result.__type_args__ == (int,)
    assert result.__type_params__ == (T,)
    assert result.__parameters__ == ()
    assert result.__pending__ == ()


def test_metadata_order_is_preserved_for_multiple_entries():
    Alias = TypeAliasType(
        "Alias",
        Annotated[T, "first", 1, "second", 2, "third"],
        type_params=(T,),
    )
    result = instantiate_type_alias(Alias, str)
    assert result.__value__.__metadata__ == (
        "first", 1, "second", 2, "third",
    )
    # Plain metadata strings are not treated as names to resolve.
    assert result.__pending__ == ()


def test_pep604_and_typing_unions_and_generics_are_rebuilt():
    Alias = TypeAliasType(
        "Alias", Union[int, List[U], Dict[U, Optional[U]]], type_params=(U,)
    )
    result = instantiate_type_alias(Alias, str)
    assert result.__value__ == Union[int, List[str], Dict[str, Optional[str]]]

    # PEP 604 flavor is preserved.
    XAlias = TypeAliasType("XAlias", U | None, type_params=(U,))
    x_result = instantiate_type_alias(XAlias, bytes)
    assert x_result.__value__ == (bytes | None)
    assert type(x_result.__value__) is type(bytes | None)


def test_explicit_arguments_bind_before_defaults():
    T_default = TypeVar("T_default", default=int)
    Alias = TypeAliasType("Alias", List[T_default], type_params=(T_default,))
    assert instantiate_type_alias(Alias).__value__ == List[int]
    # Explicit value wins over the default.
    assert instantiate_type_alias(Alias, str).__value__ == List[str]


def test_default_may_refer_to_earlier_parameter():
    T1 = TypeVar("T1")
    T2 = TypeVar("T2", default=List[T1])
    Alias = TypeAliasType("Alias", Dict[T1, T2], type_params=(T1, T2))
    result = instantiate_type_alias(Alias, str)
    assert result.__value__ == Dict[str, List[str]]
    assert result.__type_args__ == (str,)

    # An explicit second argument overrides the default.
    assert instantiate_type_alias(Alias, str, bytes).__value__ == Dict[
        str, bytes
    ]


def test_missing_argument_without_default_is_an_error():
    NoDefaultT = TypeVar("NoDefaultT")
    Alias = TypeAliasType("Alias", List[NoDefaultT], type_params=(NoDefaultT,))
    with pytest.raises(TypeError, match="No argument supplied"):
        instantiate_type_alias(Alias)


def test_too_many_arguments_is_an_error():
    Alias = TypeAliasType("Alias", List[T], type_params=(T,))
    with pytest.raises(TypeError, match="Too many arguments"):
        instantiate_type_alias(Alias, int, str)


def test_non_alias_is_rejected():
    with pytest.raises(TypeError, match="Expected a TypeAliasType"):
        instantiate_type_alias(List[int], int)


def test_recursive_alias_bare_self_reference_keeps_identity_backedge():
    # type Rec = int | Rec (self-reference supplied as a ForwardRef name)
    Rec = TypeAliasType("Rec", Union[int, typing.ForwardRef("Rec")])
    result = instantiate_type_alias(Rec, names={"Rec": Rec})

    assert result.__pending__ == ()
    # The union's second member is the result itself: an identity back-edge.
    assert result.__value__.__args__[1] is result
    # Repeatedly following the value terminates because the edge is finite.
    node = result.__value__
    for _ in range(5):
        node = node.__args__[1].__value__
        assert node is not None


def test_recursive_alias_applied_self_reference_is_a_finite_reference():
    # type Rec[T] = T | Rec[list[T]]
    # Build the exact self-referential object graph that the native type
    # statement stores: a GenericAlias whose origin is the alias itself.
    import types as _types

    Rec = TypeAliasType.__new__(TypeAliasType)
    TypeAliasType.__init__(
        Rec,
        "Rec",
        Union[T, _types.GenericAlias(Rec, (List[T],))],
        type_params=(T,),
    )

    result = instantiate_type_alias(Rec, int)
    assert result.__pending__ == ()
    head, backedge = result.__value__.__args__
    assert head is int
    assert isinstance(backedge, TypeAliasReference)
    # The reference points back at the instantiated result with substituted
    # arguments; it is a finite node and is never expanded.
    assert backedge.__alias__ is result
    assert backedge.__args__ == (List[int],)
    assert backedge.__name__ == "Rec"
    assert repr(backedge) == "Rec[typing.List[int]]"


def test_mutual_recursion_through_names_is_finite():
    A = TypeAliasType("A", Union[int, typing.ForwardRef("B")])
    B = TypeAliasType("B", Union[str, typing.ForwardRef("A")])
    result_a = instantiate_type_alias(A, names={"A": A, "B": B})
    assert result_a.__pending__ == ()
    # The other alias is kept nominal rather than expanded, keeping the graph
    # finite.
    assert result_a.__value__.__args__ == (int, B)
    result_b = instantiate_type_alias(B, names={"A": A, "B": B})
    assert result_b.__value__.__args__ == (str, A)


def test_unknown_forward_reference_becomes_locatable_pending_item():
    Alias = TypeAliasType(
        "Alias",
        Union[int, List[typing.ForwardRef("Unknown")]],
        type_params=(T,),
    )
    result = instantiate_type_alias(Alias, int, names={"Other": int})

    assert len(result.__pending__) == 1
    pending = result.__pending__[0]
    assert isinstance(pending, PendingType)
    assert pending.__pending_name__ == "Unknown"
    # Located at Union member 1 -> List argument 0.
    assert pending.locate() == (1, 0)
    assert pending.format_location("Alias") == "Alias.__value__[1][0]"
    # The original unevaluated ForwardRef is retained.
    assert isinstance(pending.__forward_ref__, typing.ForwardRef)
    assert pending.__forward_ref__.__forward_arg__ == "Unknown"


def test_pending_in_annotated_origin_and_metadata_is_located():
    Alias = TypeAliasType(
        "Alias",
        Annotated[
            typing.ForwardRef("Missing"),
            "keep",
            typing.ForwardRef("MetaMissing"),
        ],
        type_params=(T,),
    )
    result = instantiate_type_alias(Alias, int, names={})
    located = {p.__pending_name__: p.locate() for p in result.__pending__}
    assert set(located) == {"Missing", "MetaMissing"}
    assert located["Missing"] == ()
    assert located["MetaMissing"] == ("metadata", 1)
    # Plain metadata strings are left untouched.
    assert "keep" in result.__value__.__metadata__


def test_forward_refs_are_resolved_only_through_names():
    Other = TypeAliasType("Other", List[int])
    Alias = TypeAliasType(
        "Alias",
        Union[typing.ForwardRef("Other"), typing.ForwardRef("Nope")],
    )
    result = instantiate_type_alias(Alias, names={"Other": Other})
    # Known name resolves nominally; unknown name stays pending (never eval'd).
    assert Other in result.__value__.__args__
    assert result.__pending__[0].__pending_name__ == "Nope"


def test_lazy_bare_string_value_is_never_forced():
    Alias = TypeAliasType("Alias", "some.undefined.Module.attr")
    result = instantiate_type_alias(Alias)
    assert result.__value__ == "some.undefined.Module.attr"
    assert result.__pending__ == ()


def test_pending_item_repr_and_call():
    Alias = TypeAliasType("Alias", Union[int, typing.ForwardRef("Mystery")])
    result = instantiate_type_alias(Alias, names={})
    pending = result.__value__.__args__[1]
    assert isinstance(pending, PendingType)
    assert repr(pending) == "PendingType('Mystery')"
    with pytest.raises(TypeError):
        pending()


def test_nested_generic_alias_application_stays_nominal():
    Other = TypeAliasType("Other", List[int])
    Alias = TypeAliasType("Alias", List[typing.ForwardRef("Other")])
    result = instantiate_type_alias(Alias, names={"Other": Other})
    assert result.__value__ == List[Other]
    assert result.__value__.__args__ == (Other,)
    assert result.__pending__ == ()


def test_callable_and_concatenate_substitution():
    P = ParamSpec("P")
    CallableAlias = TypeAliasType(
        "CallableAlias", Callable[[T], T], type_params=(T,)
    )
    assert instantiate_type_alias(CallableAlias, int).__value__ == Callable[
        [int], int
    ]

    ConcatAlias = TypeAliasType(
        "ConcatAlias",
        Callable[Concatenate[T, P], None],
        type_params=(T, P),
    )
    result = instantiate_type_alias(ConcatAlias, int, [str, bytes])
    # On 3.12, Callable[...] compares the None return as NoneType; compare
    # the normalized argument list rather than relying on full == here.
    from typing import get_args

    params, ret = get_args(result.__value__)
    assert list(params) == [int, str, bytes]
    assert ret is type(None)


def test_typevartuple_is_bound_as_a_whole_value():
    Ts = TypeVarTuple("Ts")
    Alias = TypeAliasType(
        "Alias", Tuple[int, Unpack[Ts]], type_params=(Ts,)
    )
    result = instantiate_type_alias(Alias, (str, bytes))
    # The whole tuple is substituted at the Unpack position (no positional
    # splat expansion: a documented support-scope limitation).
    assert result.__type_args__ == ((str, bytes),)
    assert int in result.__value__.__args__


def test_result_is_frozen_after_instantiation():
    Alias = TypeAliasType("Alias", List[T], type_params=(T,))
    result = instantiate_type_alias(Alias, int)
    with pytest.raises(AttributeError):
        result.__value__ = str  # type: ignore[misc]
    with pytest.raises(AttributeError):
        result.__name__ = "Other"  # type: ignore[misc]


def test_non_generic_alias_passes_through():
    Simple = TypeAliasType("Simple", int)
    result = instantiate_type_alias(Simple)
    assert result.__value__ is int
    assert result.__type_args__ == ()
    assert result.__name__ == "Simple"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))

