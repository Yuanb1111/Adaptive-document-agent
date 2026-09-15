"""Allowlisted arithmetic expression evaluator."""

import ast
import math
import operator

_BINARY = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def evaluate_formula(expression: str, variables: dict[str, float]) -> float:
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ValueError("Invalid formula syntax.") from exc

    def visit(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.Name):
            if node.id not in variables:
                raise ValueError(f"Unknown formula variable: {node.id}")
            return float(variables[node.id])
        if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
            right = visit(node.right)
            if isinstance(node.op, ast.Div) and right == 0:
                raise ValueError("Formula division by zero.")
            return float(_BINARY[type(node.op)](visit(node.left), right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
            return float(_UNARY[type(node.op)](visit(node.operand)))
        raise ValueError("Formula contains a disallowed operation.")

    result = visit(tree)
    if not math.isfinite(result):
        raise ValueError("Formula produced a non-finite result.")
    return result

