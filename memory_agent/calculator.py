"""Safe arithmetic evaluator (AST whitelist, no eval)."""
import ast
import operator
import re

MAX_EXPR_LEN = 200
MAX_POW_BITS = 10_000
FAIL = "I couldn't calculate that."


class CalcError(ValueError):
    pass


_BIN = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
}
_UNARY = {ast.USub: operator.neg, ast.UAdd: operator.pos}


def _pow(base, exp):
    if isinstance(base, int) and isinstance(exp, int) and exp >= 0:
        if max(abs(base).bit_length(), 1) * exp > MAX_POW_BITS:
            raise CalcError("result too large")
    elif abs(exp) > 10_000:
        raise CalcError("exponent too large")
    result = base ** exp
    if isinstance(result, complex):
        raise CalcError("not a real number")
    return result


def _eval(node):
    if isinstance(node, ast.Constant):
        if type(node.value) in (int, float):  # excludes bool/str/complex
            return node.value
        raise CalcError("unsupported value")
    if isinstance(node, ast.BinOp):
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow):
            return _pow(left, right)
        op = _BIN.get(type(node.op))
        if op is None:
            raise CalcError("unsupported operator")
        return op(left, right)
    if isinstance(node, ast.UnaryOp):
        op = _UNARY.get(type(node.op))
        if op is None:
            raise CalcError("unsupported operator")
        return op(_eval(node.operand))
    raise CalcError("unsupported expression")


def calculate(expression):
    """Return the numeric result or raise CalcError / ZeroDivisionError."""
    expression = expression.replace("?", "").replace("^", "**").strip()
    if not expression or len(expression) > MAX_EXPR_LEN:
        raise CalcError("empty or too long")
    try:
        tree = ast.parse(expression, mode="eval")
        result = _eval(tree.body)
    except (SyntaxError, RecursionError, MemoryError, OverflowError) as exc:
        raise CalcError(str(exc)) from exc
    if isinstance(result, float) and (result != result or result in (float("inf"), float("-inf"))):
        raise CalcError("not finite")
    return result


def format_number(value):
    if isinstance(value, float):
        if value.is_integer() and abs(value) < 1e15:
            return str(int(value))
        return format(value, ".10g")
    return str(value)


def safe_calculate(expression):
    try:
        return format_number(calculate(expression))
    except ZeroDivisionError:
        return "Division by zero is undefined."
    except CalcError:
        return FAIL


_PREFIX = re.compile(
    r"^\s*(?:please\s+)?(?:calculate|calc|compute|evaluate|solve|"
    r"what\s+is|what's|whats|how\s+much\s+is)\s*:?\s*", re.I)
_MATH_ONLY = re.compile(r"^[\d\s+\-*/%^().]+$")


_SYMBOLS = str.maketrans({"\u00d7": "*", "\u2715": "*", "\u2a2f": "*", "\u00b7": "*", "\u00f7": "/", "\u2797": "/",
                         "\u2212": "-", "\u2013": "-", "\u2014": "-"})
_WORDS = [(r"\b(?:multiplied by|times)\b", "*"), (r"\bdivided by\b", "/"), (r"\bplus\b", "+"),
          (r"\bminus\b", "-"), (r"\bto the power of\b", "**"), (r"\b(?:modulo|mod)\b", "%")]
_X_BETWEEN_NUMBERS = re.compile(r"(?<=[\d)])\s*[xX]\s*(?=[\d(.])")


def _normalise_operators(text):
    text = text.translate(_SYMBOLS)
    for pattern, symbol in _WORDS:
        text = re.sub(pattern, f" {symbol} ", text, flags=re.I)
    return _X_BETWEEN_NUMBERS.sub(" * ", text)


def extract_expression(text):
    """Return an arithmetic expression if `text` is one, else None."""
    candidate = _normalise_operators(_PREFIX.sub("", text.strip())).rstrip("?= ").strip()
    if (candidate and _MATH_ONLY.match(candidate)
            and re.search(r"\d", candidate)
            and re.search(r"[-+*/%^]", candidate.lstrip("-+"))):
        return candidate
    return None
