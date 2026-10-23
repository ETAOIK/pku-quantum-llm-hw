"""A small historical-data expression language. No eval, imports or Python access."""
import ast
import operator

import numpy as np
import pandas as pd


FIELDS = {"close", "open", "high", "low", "amount", "num_trades"}
WINDOW_FUNCTIONS = {"lag", "returns", "ts_mean", "ts_std", "ts_min", "ts_max"}
ARITY = {**dict.fromkeys(WINDOW_FUNCTIONS, 2), "rank": 1, "abs": 1, "where": 3}
BINARY = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
          ast.Div: operator.truediv, ast.BitAnd: operator.and_, ast.BitOr: operator.or_}
COMPARE = {ast.Lt: operator.lt, ast.LtE: operator.le, ast.Gt: operator.gt,
           ast.GtE: operator.ge, ast.Eq: operator.eq, ast.NotEq: operator.ne}


def validate_expression(expression):
    if not isinstance(expression, str) or not expression.strip() or len(expression) > 600:
        raise ValueError("公式需为 1–600 字符的表达式")
    try:
        tree = ast.parse(expression.strip(), mode="eval")
    except SyntaxError as error:
        raise ValueError(f"公式语法错误：{error.msg}") from None
    if len(list(ast.walk(tree))) > 100:
        raise ValueError("公式过长，请简化计算步骤")

    def check(node):
        if isinstance(node, ast.Expression):
            check(node.body)
        elif isinstance(node, ast.Constant):
            if not isinstance(node.value, (int, float, bool)) or not np.isfinite(node.value) or abs(node.value) > 1e12:
                raise ValueError("只支持有限数值常量")
        elif isinstance(node, ast.Name):
            if node.id not in FIELDS:
                raise ValueError(f"未知字段 {node.id}；可用：{', '.join(sorted(FIELDS))}")
        elif isinstance(node, ast.BinOp) and type(node.op) in BINARY:
            check(node.left)
            check(node.right)
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd, ast.Invert, ast.Not)):
            check(node.operand)
        elif isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
            for value in node.values:
                check(value)
        elif isinstance(node, ast.Compare) and all(type(op) in COMPARE for op in node.ops):
            for value in [node.left, *node.comparators]:
                check(value)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ARITY:
            name = node.func.id
            if node.keywords or len(node.args) != ARITY[name]:
                raise ValueError(f"{name} 需要 {ARITY[name]} 个位置参数")
            for arg in node.args:
                check(arg)
            if name in WINDOW_FUNCTIONS:
                window = node.args[1]
                if not isinstance(window, ast.Constant) or type(window.value) is not int or not 1 <= window.value <= 252:
                    raise ValueError(f"{name} 的窗口必须为 1–252 的正整数；不允许未来引用")
        else:
            raise ValueError("不支持此语法；仅允许历史字段、算术、比较、逻辑及列出的函数")

    check(tree)
    return tree


def evaluate(expression, panels, market, condition=False):
    tree = validate_expression(expression)
    close = market["close"]
    cache = {"close": close, "amount": panels["amt"], "num_trades": panels["num_trades"]}

    def field(name):
        if name not in cache:
            cache[name] = panels[name] * panels["cumadj"]
        return cache[name]

    def frame(value):
        if isinstance(value, pd.DataFrame):
            return value
        return pd.DataFrame(value, index=close.index, columns=close.columns)

    def truth(value):
        value = frame(value)
        return value.notna() & value.ne(0)

    def visit(node):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            return field(node.id)
        if isinstance(node, ast.BinOp):
            left, right = visit(node.left), visit(node.right)
            if isinstance(node.op, (ast.BitAnd, ast.BitOr)):
                left, right = truth(left), truth(right)
            return BINARY[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp):
            value = visit(node.operand)
            if isinstance(node.op, ast.USub):
                return -value
            if isinstance(node.op, ast.UAdd):
                return value
            return ~truth(value)
        if isinstance(node, ast.BoolOp):
            values = [truth(visit(v)) for v in node.values]
            result = values[0]
            for value in values[1:]:
                result = result & value if isinstance(node.op, ast.And) else result | value
            return result
        if isinstance(node, ast.Compare):
            left, result = visit(node.left), frame(True)
            for op, other in zip(node.ops, node.comparators):
                right = visit(other)
                # Missing observations must not satisfy e.g. NaN != 0.
                result &= truth(COMPARE[type(op)](left, right)) & frame(left).notna() & frame(right).notna()
                left = right
            return result
        name = node.func.id
        args = [visit(arg) for arg in node.args]
        first = frame(args[0])
        if name == "rank":
            return first.where(market["eligible"]).rank(axis=1, pct=True)
        if name == "abs":
            return first.abs()
        if name == "where":
            return frame(args[1]).where(truth(first), frame(args[2]))
        window = args[1]
        if name == "lag":
            return first.shift(window)
        if name == "returns":
            return first / first.shift(window) - 1
        rolling = first.rolling(window, min_periods=window)
        return getattr(rolling, {"ts_mean": "mean", "ts_std": "std", "ts_min": "min", "ts_max": "max"}[name])()

    with np.errstate(divide="ignore", invalid="ignore"):
        result = frame(visit(tree.body)).replace([np.inf, -np.inf], np.nan)
    return truth(result).to_numpy() if condition else result.to_numpy(dtype=np.float32)
