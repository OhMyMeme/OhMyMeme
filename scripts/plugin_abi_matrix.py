import ast
import inspect
import json
import re
import sys
from argparse import ArgumentParser
from pathlib import Path
from types import SimpleNamespace

from plugin_parity_json import load_json, validate_schema, write_json

from ohmymeme.core.plugins.manifest import ENTRY_POINT_GROUP, validate_manifest
from ohmymeme.core.plugins.registry import PluginRegistry
from ohmymeme.presentation.desktop.api.main_facade import MainBridgeFacade
from ohmymeme.presentation.desktop.api.plugin_dispatch import (
    ACTIONS,
    CONTRACTS,
    IMPORT_ACTIONS,
    SYNC_PROVIDERS,
    HostActionAdapter,
    HostDispatcher,
    action_spec,
    validate_arguments,
    validate_contribution,
)
from ohmymeme.presentation.desktop.api.settings_facade import SettingsBridgeFacade

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schemas/plugin/abi-matrix.schema.json"
FACADES = {"main": MainBridgeFacade, "settings": SettingsBridgeFacade}
FRONTEND = "src/ohmymeme/presentation/frontend"
PROGRESS_SOURCES = {
    "qqnt_get_progress": (
        "plugins/source.qqnt/src/ohmymeme_plugin_qqnt/__init__.py",
        "_QQNT_STATE",
    ),
    "get_tg_import_progress": (
        "plugins/source.telegram/src/ohmymeme_plugin_telegram/__init__.py",
        "_TG_STATE",
    ),
    "get_douyin_import_progress": (
        "plugins/source.douyin/src/ohmymeme_plugin_douyin/__init__.py",
        "_DOUYIN_STATE",
    ),
    "get_wechat_import_progress": (
        "plugins/source.wechat/src/ohmymeme_plugin_wechat/__init__.py",
        "_WECHAT_STATE",
    ),
    "get_sync_progress": ("src/ohmymeme/services/sync/service.py", "_sync_state"),
}
EXCLUDED = ["adb.qq", "qq.mobile"]


def _call_arity(text, start):
    # Count top-level arguments in existing JS calls without evaluating JavaScript.
    stack, quote, escaped, count = [], None, False, 0
    for char in text[start:]:
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        elif char in "\"'`":
            quote = char
        elif char in "([{":
            stack.append(char)
        elif char in ")]}":
            if not stack:
                return count
            stack.pop()
        elif char == "," and not stack:
            count += 1
    raise ValueError("caller: unterminated invocation")


def _callers(root, surface, action):
    # Reconcile actual call expressions, including the two fixed sync wrappers.
    directory = "settings-vue" if surface == "settings" else surface
    files = sorted((root / FRONTEND / directory).rglob("*"))
    result = []
    for path in files:
        if path.suffix not in (".js", ".ts", ".vue") or "generated" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        arities = {
            _call_arity(text, match.end())
            for match in re.finditer(
                r"\b(?:api|call)\(\s*['\"]" + re.escape(action) + r"['\"]", text
            )
        }
        indirect = action in ("sync_push", "sync_pull") and (
            f"doSyncWithProgress('{action}'," in text or f".start('{action}'," in text
        )
        indirect = indirect or (
            action == "delete_all_cloud" and "api('delete_all_' +" in text
        )
        if indirect:
            arities.add(0)
        if arities:
            result.append(
                {"path": path.relative_to(root).as_posix(), "arities": sorted(arities)}
            )
    return result


def _progress(root, action):
    # Freeze actual legacy state keys rather than inventing generic progress DTOs.
    if action not in PROGRESS_SOURCES:
        return []
    path, variable = PROGRESS_SOURCES[action]
    tree = ast.parse((root / path).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == variable for t in node.targets
        ):
            return list(ast.literal_eval(node.value))
    raise ValueError(f"progress.{action}: source state missing")


def source_matrices(root=ROOT):
    # Derive contracts from facades, the Bridge table and reachable fixed callers.
    abi_rows, action_rows = [], []
    for surface, facade in FACADES.items():
        tree = ast.parse(
            (
                root / f"src/ohmymeme/presentation/desktop/api/{surface}_facade.py"
            ).read_text(encoding="utf-8")
        )
        methods = {
            node.name: node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
        }
        for action, (provider, names, failure, label) in ACTIONS[surface].items():
            node = methods[action]
            signature = inspect.signature(getattr(facade, action))
            parameters = list(signature.parameters.values())[1:]
            if (
                tuple(p.name for p in parameters) != names
                or tuple(arg.arg for arg in node.args.args[1:]) != names
            ):
                raise ValueError(
                    f"facade.{surface}.{action}.arguments: dispatcher mismatch"
                )
            call = next(
                n
                for n in ast.walk(node)
                if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and n.func.attr == "_call"
            )
            if (
                ast.literal_eval(call.args[0]) != action
                or tuple(ast.unparse(arg) for arg in call.args[1].elts) != names
            ):
                raise ValueError(
                    f"facade.{surface}.{action}.dispatch: action/argument drift"
                )
            if _differences(ast.literal_eval(call.args[2]), failure, "failure"):
                raise ValueError(
                    f"facade.{surface}.{action}.failure: dispatcher mismatch"
                )
            spec = CONTRACTS[surface]._specs[action]
            arguments, samples = [], []
            for parameter, adapter in zip(parameters, spec.arguments, strict=True):
                schema = adapter.json_schema()
                required = parameter.default is inspect.Parameter.empty
                argument = {
                    "name": parameter.name,
                    "schema": schema,
                    "required": required,
                }
                if not required:
                    argument["default"] = parameter.default
                arguments.append(argument)
                samples.append(
                    parameter.default
                    if not required
                    else {"string": "fixture", "boolean": False, "integer": 1}[
                        schema["type"]
                    ]
                )
            callers = _callers(root, surface, action)
            minimum = sum(p.default is inspect.Parameter.empty for p in parameters)
            for caller in callers:
                if any(
                    not minimum <= count <= len(parameters)
                    for count in caller["arities"]
                ):
                    raise ValueError(
                        f"callers.{surface}.{action}: argument count drift"
                    )
            result_type = spec.result.json_schema().get("type", "json")
            if result_type not in ("object", "string", "boolean", "null", "json"):
                raise ValueError(f"bridge.{surface}.{action}.result: unknown shape")
            abi_rows.append(
                {
                    "surface": surface,
                    "method": action,
                    "signature": str(signature),
                    "arguments": arguments,
                    "result_type": result_type,
                    "failure": failure,
                    "callers": callers,
                }
            )
            action_rows.append(
                {
                    "surface": surface,
                    "action": action,
                    "providers": (
                        [provider] if isinstance(provider, str) else list(provider)
                    ),
                    "arguments": arguments,
                    "sample_args": samples,
                    "label": label,
                    "screen": (
                        "imports"
                        if action in IMPORT_ACTIONS
                        else ("lan" if action.startswith("lan_") else "sync")
                    ),
                    "owner": (
                        "host-import-adapter"
                        if action in IMPORT_ACTIONS
                        else "host-service"
                    ),
                    "progress_fields": _progress(root, action),
                }
            )
    return (
        {"schema_version": 1, "methods": abi_rows, "excluded_plugins": EXCLUDED},
        {
            "schema_version": 1,
            "actions": action_rows,
            "sync_providers": dict(SYNC_PROVIDERS),
            "excluded_plugins": EXCLUDED,
        },
    )


def _differences(actual, expected, field):
    # Report exact fields, with strict JSON scalar types and no fixture assertions.
    if type(actual) is not type(expected):
        return [f"{field}: unexpected type"]
    errors = []
    if isinstance(expected, dict):
        for key in sorted(expected.keys() - actual.keys()):
            errors.append(f"{field}.{key}: missing field")
        for key in sorted(actual.keys() - expected.keys()):
            errors.append(f"{field}.{key}: unexpected field")
        for key in expected.keys() & actual.keys():
            errors.extend(_differences(actual[key], expected[key], f"{field}.{key}"))
    elif isinstance(expected, list):
        if len(actual) != len(expected):
            errors.append(f"{field}: fixed row count mismatch")
        for index, (item, target) in enumerate(zip(actual, expected)):
            errors.extend(_differences(item, target, f"{field}[{index}]"))
    elif actual != expected:
        errors.append(f"{field}: differs from host contract")
    return sorted(errors)


def _runtime_row(row, descriptors):
    # Exercise the real facade/dispatcher/registry chain using only inert callbacks.
    calls = []
    surface, action = row.get("surface"), row.get("action")
    record = {
        "surface": surface,
        "action": action,
        "provider_calls": calls,
        "accepted": False,
    }
    try:
        if surface not in ACTIONS:
            raise ValueError("surface: unknown fixed surface")
        provider, _, _, label = action_spec(surface, action)
        for field in ("html", "script", "javascript", "bridge_methods", "ui"):
            if field in row:
                raise ValueError(f"contribution.{field}: forbidden field")
        if row.get("label") != label:
            raise ValueError("label: expected fixed host label")
        args = validate_arguments(surface, action, row.get("sample_args"))
        if surface == "settings":
            providers = row.get("providers")
            if not isinstance(providers, list) or not providers:
                raise ValueError("providers: expected explicit providers")
            contribution = {
                "provider": providers[0],
                "action": action,
                "label": label,
                "args": list(args),
            }
            validate_contribution(contribution)
        result_type = (
            CONTRACTS[surface]._specs[action].result.json_schema().get("type", "json")
        )
        result = {
            "object": {"ok": True},
            "json": {"ok": True},
            "boolean": True,
            "string": "ok",
            "null": None,
        }[result_type]
        if action in PROGRESS_SOURCES:
            result = {"status": "done", "progress": 100, "message": "fixture"}

        def handler(*received):
            # The trace proves dispatch actually occurred and received only arguments.
            calls.append(
                {
                    "provider": provider,
                    "action": action,
                    "argument_count": len(received),
                }
            )
            return result

        builtins, host_actions = {}, {}
        if action in IMPORT_ACTIONS:
            adapter = HostActionAdapter(provider, {action: handler})
            builtins[provider] = lambda: adapter
        else:
            host_actions[action] = handler
        registry = PluginRegistry(descriptors, builtins, ())
        facade = FACADES[surface].__new__(FACADES[surface])
        facade._legacy = SimpleNamespace()
        facade._contract = CONTRACTS[surface]
        facade._plugin_dispatcher = HostDispatcher(surface, registry, host_actions)
        observed = getattr(facade, action)(*args)
        record["observed"] = observed
        record["accepted"] = observed == result and len(calls) == 1
        if not record["accepted"]:
            raise ValueError("runtime: facade did not return the callback result")
    except (ValueError, TypeError, KeyError) as error:
        record["error"] = str(error)
    return record


def _runtime_unavailable(descriptors):
    # Prove missing/disabled/incompatible providers never trigger another factory.
    records = []
    for mode in ("missing", "disabled", "incompatible"):
        calls = []

        def forbidden_factory():
            # This must never be reached by any unavailable-provider case.
            calls.append("factory")
            return object()

        current = tuple(
            (
                d._replace(api_version=99)
                if mode == "incompatible" and d.id == "source.telegram"
                else d
            )
            for d in descriptors
        )
        builtins = {"source.douyin": forbidden_factory}
        if mode != "missing":
            builtins["source.telegram"] = forbidden_factory
        registry = PluginRegistry(current, builtins, ())
        facade = SettingsBridgeFacade.__new__(SettingsBridgeFacade)
        facade._legacy = SimpleNamespace()
        facade._contract = CONTRACTS["settings"]
        facade._plugin_dispatcher = HostDispatcher(
            "settings", registry, enabled=() if mode == "disabled" else None
        )
        observed = [
            facade.start_tg_import(),
            facade.get_tg_import_progress(),
            facade.cancel_tg_import(),
        ]
        records.append(
            {
                "case": mode,
                "observed": observed,
                "provider_calls": calls,
                "passed": observed == [{"ok": False}, {}, None] and not calls,
            }
        )
    return records


def check(abi_path, actions_path, root=ROOT):
    # Evaluate file schemas, source parity and runtime observations independently.
    errors, runtime = [], []
    schema = load_json(SCHEMA)
    expected_abi, expected_actions = source_matrices(root)
    documents = {}
    for name, path, expected in (
        ("abi", abi_path, expected_abi),
        ("actions", actions_path, expected_actions),
    ):
        try:
            value = load_json(path)
            documents[name] = value
            errors.extend(validate_schema(value, schema["$defs"][name], schema, name))
            errors.extend(_differences(value, expected, name))
        except (OSError, ValueError) as error:
            errors.append(f"{name}: {error}")
    descriptors = validate_manifest(
        load_json(ROOT / "config/plugin-manifest.json"), ENTRY_POINT_GROUP
    )
    rows = documents.get("actions", {}).get("actions", [])
    if isinstance(rows, list):
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            observation = _runtime_row(row, descriptors)
            runtime.append(observation)
            if not observation["accepted"]:
                errors.append(
                    f"actions.actions[{index}]."
                    f"{observation.get('error', 'runtime rejected')}"
                )
    unavailable = _runtime_unavailable(descriptors)
    for case in unavailable:
        if not case["passed"]:
            errors.append(
                f"runtime.{case['case']}: sentinel or provider isolation mismatch"
            )
    return {
        "schema_version": 1,
        "status": "REJECTED" if errors else "PASS",
        "verdict": "changes_requested" if errors else "approved",
        "errors": sorted(set(errors)),
        "runtime": runtime,
        "unavailable": unavailable,
        "method_count": len(expected_abi["methods"]),
        "action_count": len(expected_actions["actions"]),
    }


def main(argv=None):
    # Direct CLI is the supported QA surface and always reports actual observations.
    parser = ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    parser.add_argument("--abi", type=Path, required=True)
    parser.add_argument("--actions", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    if args.check and args.report is None:
        parser.error("--check requires --report")
    try:
        if args.write:
            abi, actions = source_matrices()
            write_json(args.abi, abi)
            write_json(args.actions, actions)
            return 0
        report = check(args.abi, args.actions)
    except (OSError, ValueError, TypeError, KeyError, StopIteration) as error:
        report = {
            "status": "REJECTED",
            "verdict": "changes_requested",
            "errors": [str(error)],
        }
    if args.report is not None:
        write_json(args.report, report)
    print(
        json.dumps(
            {"status": report["status"], "errors": report["errors"]}, ensure_ascii=False
        )
    )
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
