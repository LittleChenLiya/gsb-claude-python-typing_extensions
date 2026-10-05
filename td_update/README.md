# TypedDict 更新计划（Update Plan）

`td_update_plan.plan_update(td, record, patch=None, deletes=())` 对 TypedDict 记录做
**稀疏修改 + 显式删除** 的校验与规划，全部通过才返回独立结果，原记录绝不被修改。

## 语义规则

| 规则 | 行为 |
| --- | --- |
| 稀疏 patch | 只覆盖显式给出的键；**省略的键保留，不当作删除** |
| 删除 | 独立操作，只能经 `deletes` 显式声明 |
| Required / total 字段 | 删除失败 |
| ReadOnly 字段 | 删除失败；改值失败（同值安全标量视为无操作） |
| NotRequired 普通字段 | 可改、可显式删除 |
| 未知键 | 报错，整体失败 |
| 类型校验 | 仅支持安全类型 `str/int/float/bool/bytes/None`，用 `type(v) is T` 精确判断，**不调用 isinstance**（不触发用户 `__instancecheck__`）；`bool` 与 `int` 视为不同类型 |
| 未知类型 | 自定义类、容器、Union、未绑定 TypeVar 等**一律不予通过** |
| 结果 | 全通过 → `UpdatePlan(ok=True, result=<新 dict>)`；任一失败 → `ok=False, result=None` |
| 继承 / 泛型 | 继承字段合并解析；泛型按实际绑定（`Box[int]`、`class S(Box[str])`）替换 TypeVar |

## 三字段例子

```python
import typing_extensions as te
from td_update_plan import plan_update

class UserRecord(te.TypedDict):
    id: te.ReadOnly[int]        # 只读
    name: te.NotRequired[str]   # 可选
    email: str                  # 必需

rec = {"id": 1, "name": "alice", "email": "a@example.com"}

plan_update(UserRecord, rec, patch={"id": 2})          # 失败：只读 id 拒绝改值
plan_update(UserRecord, rec, patch={"email": "b@x"})   # 通过：name 省略即保留
plan_update(UserRecord, rec, deletes=["name"])         # 通过：可选字段显式删除
plan_update(UserRecord, rec, deletes=["email"])        # 失败：必需字段禁止删除
# 任何情况下 rec 保持 {"id": 1, "name": "alice", "email": "a@example.com"} 不变
```

## 运行测试

```bash
# 仓库根目录（Windows cmd）
set PYTHONPATH=src&& python -m pytest td_update/test_td_update_plan.py -q
# 或 bash / PowerShell
PYTHONPATH=src python -m pytest td_update/test_td_update_plan.py -q
```
