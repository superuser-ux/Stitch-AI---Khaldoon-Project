"""#427 — additive API-contract test for the final-review projection route.

Runtime-free and dependency-free: it parses `gates/api.py` with the stdlib `ast` module (no FastAPI,
no server, no DB, no network) and asserts, from source truth, that the change is strictly ADDITIVE:

  * the existing #423 V1 route `GET /gates/{gate_id}/slots/{slot_id}/target-package` is still declared,
    and its handler still delegates to `final_review_target_package.read` (unchanged V1 surface);
  * a NEW route `GET /gates/{gate_id}/slots/{slot_id}/final-review-projection` is declared, delegating
    to `final_review_projection.read`;
  * the new path collides with no existing route path (additive, never an override).

Run:  python3 gates/final_review_projection_apicontract_test.py
"""
import ast
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
API = os.path.join(HERE, "api.py")

FAIL = []


def check(name, cond):
    print(f"  {'PASS' if cond else 'FAIL'}: {name}")
    if not cond:
        FAIL.append(name)


def _const_str(node):
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _routes_and_handlers(tree):
    """Return ({(method, path)}, {path: handler_ast_node}) for every @app.<method>("<path>") route."""
    routes, handlers = set(), {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)
                    and isinstance(dec.func.value, ast.Name) and dec.func.value.id == "app"
                    and dec.func.attr in ("get", "post", "put", "delete", "patch") and dec.args):
                path = _const_str(dec.args[0])
                if path is not None:
                    routes.add((dec.func.attr, path))
                    handlers[path] = node
    return routes, handlers


def _delegates_to(handler, module, func):
    """True iff the handler body contains a call `<module>.<func>(...)`."""
    for n in ast.walk(handler):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == func
                and isinstance(n.func.value, ast.Name) and n.func.value.id == module):
            return True
    return False


def main():
    print("#427 final_review_projection additive API-contract test")
    tree = ast.parse(open(API, "r", encoding="utf-8").read(), filename=API)
    routes, handlers = _routes_and_handlers(tree)

    TP = "/gates/{gate_id}/slots/{slot_id}/target-package"
    FR = "/gates/{gate_id}/slots/{slot_id}/final-review-projection"

    check("existing #423 V1 target-package GET route still declared", ("get", TP) in routes)
    check("existing target-package handler still delegates to final_review_target_package.read",
          TP in handlers and _delegates_to(handlers[TP], "final_review_target_package", "read"))

    check("new final-review-projection GET route declared (additive)", ("get", FR) in routes)
    check("new handler delegates to final_review_projection.read",
          FR in handlers and _delegates_to(handlers[FR], "final_review_projection", "read"))

    # additive: the new path is distinct from every other declared route path (never an override).
    other_paths = {p for (_, p) in routes if p != FR}
    check("new route path collides with no existing route path", FR not in other_paths)
    check("module imports the new read model", "import final_review_projection" in open(API).read())

    print()
    if FAIL:
        print(f"FAILED ({len(FAIL)}): " + "; ".join(FAIL))
        return 1
    print("ALL #427 API-contract checks PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
