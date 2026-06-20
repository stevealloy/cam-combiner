import re
from typing import Dict, Any

TOK = re.compile(r"\s*(\!|\&\&|\|\||==|[A-Za-z_]\w*|true|false|True|False|None)\s*")

def _truthy(v):
    if v in (None, "", 0, False):
        return False
    if isinstance(v, str):
        low = v.strip().lower()
        if low in ("false","no","none","null","0",""):
            return False
        if low in ("true","yes","on","1"):
            return True
    return bool(v)

def eval_condition(expr: str, params: Dict[str, Any]) -> bool:
    if not expr or str(expr).strip().lower() in ("none",""):
        return True
    tokens = TOK.findall(expr)
    values = []
    for t in tokens:
        if t in ("&&","||","!","=="):
            values.append(t)
        else:
            key = t
            if t.lower() in ("true","false"):
                values.append(str(t.lower()=="true"))
            elif t in ("True","False"):
                values.append(str(t=="True"))
            elif t == "None":
                values.append("False")
            elif re.match(r"^[A-Za-z_]\w*$", t):
                v = params.get(t, False)
                values.append(str(_truthy(v)))
            else:
                values.append("False")
    def reduce_nots(seq):
        out = []
        i = 0
        while i < len(seq):
            if seq[i] == "!":
                lit = seq[i+1] if i+1 < len(seq) else "False"
                val = not (lit == "True")
                out.append("True" if val else "False")
                i += 2
            else:
                out.append(seq[i]); i += 1
        return out
    seq = reduce_nots(values)
    def reduce_and(seq):
        out = []
        i = 0
        while i < len(seq):
            if i+2 < len(seq) and seq[i+1] == "&&":
                a = (seq[i] == "True")
                b = (seq[i+2] == "True")
                out.append("True" if (a and b) else "False")
                i += 3
            else:
                out.append(seq[i]); i += 1
        return out
    seq = reduce_and(seq)
    def reduce_or(seq):
        out = []
        i = 0
        while i < len(seq):
            if i+2 < len(seq) and seq[i+1] == "||":
                a = (seq[i] == "True")
                b = (seq[i+2] == "True")
                out.append("True" if (a or b) else "False")
                i += 3
            else:
                out.append(seq[i]); i += 1
        return out
    seq = reduce_or(seq)
    return seq[-1] == "True" if seq else False
