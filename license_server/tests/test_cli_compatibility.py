from __future__ import annotations

import contextlib
import importlib
import importlib.util
import inspect
import io
import pickle
import subprocess
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

from _support import LICENSE_SERVER_ROOT
from test_license_flow import load_server


ROOT = Path(__file__).resolve().parents[2]
RUNTIME_ROOT = ROOT
if not (
    RUNTIME_ROOT / "openclaw_new_launcher" / "python-runtime" / "python.exe"
).is_file():
    RUNTIME_ROOT = ROOT.parent.parent
PYTHON = RUNTIME_ROOT / "openclaw_new_launcher" / "python-runtime" / "python.exe"
SERVER = LICENSE_SERVER_ROOT / "server.py"


class _CliFacade:
    DEFAULT_FEATURES = ["default-a", "default-b"]
    DEFAULT_GATEWAY_BASE_URL = "https://gateway.example/v1"
    DEFAULT_GATEWAY_IMAGE_BASE_URL = "https://image.example/v1"
    DEFAULT_GATEWAY_VIDEO_BASE_URL = "https://video.example/v1"
    DEFAULT_GATEWAY_TOKEN = "gateway-token"
    DEFAULT_GATEWAY_IMAGE_TOKEN = "image-token"
    DEFAULT_GATEWAY_VIDEO_TOKEN = "video-token"
    DEFAULT_GATEWAY_DEFAULT_MODEL = "default-model"
    DEFAULT_GATEWAY_IMAGE_MODEL = "image-model"
    DEFAULT_GATEWAY_VIDEO_MODEL = "video-model"
    DEFAULT_GATEWAY_MODELS = ["model-a", "model-b"]
    HOST = "127.0.0.1"
    PORT = 8123

    def __init__(self) -> None:
        self.licenses = SimpleNamespace(create_codes=lambda *_args, **_kwargs: None)

    @staticmethod
    def public_key_b64() -> str:
        return "test-public-key"


class CliCompatibilityTests(unittest.TestCase):
    def load_cli(self):
        spec = importlib.util.find_spec("luming_license.cli")
        self.assertIsNotNone(spec, "luming_license.cli must own the extracted CLI")
        return importlib.import_module("luming_license.cli")

    def test_help_keeps_existing_commands(self) -> None:
        result = subprocess.run(
            [str(PYTHON), str(SERVER), "--help"],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(0, result.returncode, result.stderr)
        for command in ("serve", "create-code", "list-codes", "public-key"):
            self.assertIn(command, result.stdout)

    def test_no_args_keeps_stderr_and_exit_behavior(self) -> None:
        result = subprocess.run(
            [str(PYTHON), str(SERVER)],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(2, result.returncode)
        self.assertEqual("", result.stdout)
        self.assertIn("the following arguments are required", result.stderr)
        self.assertIn("serve,create-code,list-codes,public-key", result.stderr)

    def test_cli_module_exports_the_compatibility_interface(self) -> None:
        cli = self.load_cli()
        for name in (
            "serve",
            "create_codes",
            "list_codes",
            "public_key",
            "build_parser",
            "main",
        ):
            self.assertTrue(callable(getattr(cli, name, None)), name)

    def test_cli_module_parser_callbacks_are_top_level_and_pickleable(self) -> None:
        cli = self.load_cli()
        commands = {
            "serve": cli.serve,
            "create-code": cli.create_codes,
            "list-codes": cli.list_codes,
            "public-key": cli.public_key,
        }

        for command, expected in commands.items():
            callback = cli.build_parser().parse_args([command]).func
            self.assertIs(expected, callback, command)
            self.assertEqual(expected.__name__, callback.__name__)
            self.assertEqual(expected.__qualname__, callback.__qualname__)
            self.assertEqual(cli.__name__, callback.__module__)
            self.assertEqual(
                inspect.signature(expected), inspect.signature(callback), command
            )
            self.assertIs(callback, pickle.loads(pickle.dumps(callback)), command)

    def test_bound_parser_keeps_create_code_options_and_defaults(self) -> None:
        cli = self.load_cli()
        facade = _CliFacade()

        args = cli.bind_cli(facade).build_parser().parse_args(["create-code"])

        self.assertEqual(1, args.count)
        self.assertEqual("客户", args.licensee)
        self.assertEqual("pro", args.edition)
        self.assertEqual("default-a,default-b", args.features)
        self.assertEqual("2027-05-01", args.expires)
        self.assertEqual(1, args.max_activations)
        self.assertFalse(args.member_mode)
        self.assertEqual("monthly", args.plan)
        self.assertEqual("https://gateway.example/v1", args.gateway_base_url)
        self.assertEqual("https://image.example/v1", args.gateway_image_base_url)
        self.assertEqual("https://video.example/v1", args.gateway_video_base_url)
        self.assertEqual("gateway-token", args.gateway_token)
        self.assertEqual("image-token", args.gateway_image_token)
        self.assertEqual("video-token", args.gateway_video_token)
        self.assertEqual("default-model", args.gateway_default_model)
        self.assertEqual("image-model", args.gateway_image_model)
        self.assertEqual("video-model", args.gateway_video_model)
        self.assertEqual("model-a,model-b", args.gateway_models)
        self.assertEqual("{}", args.quotas)

    def test_bound_public_key_command_keeps_stdout_and_exit_behavior(self) -> None:
        cli = self.load_cli()
        commands = cli.bind_cli(_CliFacade())
        parser = commands.build_parser()
        stdout = io.StringIO()

        with contextlib.redirect_stdout(stdout):
            args = parser.parse_args(["public-key"])
            result = args.func(args)

        self.assertIsNone(result)
        self.assertEqual("test-public-key\n", stdout.getvalue())

        stderr = io.StringIO()
        with (
            contextlib.redirect_stderr(stderr),
            self.assertRaises(SystemExit) as raised,
        ):
            parser.parse_args([])
        self.assertEqual(2, raised.exception.code)
        self.assertIn("the following arguments are required", stderr.getvalue())

    def test_bound_create_codes_keeps_facade_collaborators_patchable(self) -> None:
        cli = self.load_cli()
        facade = _CliFacade()
        calls: list[tuple[Namespace, dict[str, object]]] = []
        facade.create_code_records = object()
        facade.parse_models = object()
        facade.parse_json_object = object()
        facade.licenses.create_codes = lambda args, **kwargs: calls.append(
            (args, kwargs)
        )
        args = Namespace(marker="create")

        cli.bind_cli(facade).create_codes(args)

        self.assertEqual(args, calls[0][0])
        self.assertIs(facade.create_code_records, calls[0][1]["create_code_records_fn"])
        self.assertIs(facade.parse_models, calls[0][1]["parse_models_fn"])
        self.assertIs(facade.parse_json_object, calls[0][1]["parse_json_object_fn"])
        self.assertIs(facade.DEFAULT_FEATURES, calls[0][1]["default_features"])

    def test_server_cli_callables_keep_base_metadata_and_signatures(self) -> None:
        expected_signatures = {
            "serve": "(_args: 'argparse.Namespace') -> 'None'",
            "create_codes": "(args: 'argparse.Namespace') -> 'None'",
            "list_codes": "(_args: 'argparse.Namespace') -> 'None'",
            "public_key": "(_args: 'argparse.Namespace') -> 'None'",
            "build_parser": "() -> 'argparse.ArgumentParser'",
            "main": "() -> 'None'",
        }
        with tempfile.TemporaryDirectory() as directory:
            server = load_server(Path(directory))

            for name, expected_signature in expected_signatures.items():
                function = getattr(server, name)
                self.assertEqual(name, function.__name__)
                self.assertEqual(name, function.__qualname__)
                self.assertEqual(server.__name__, function.__module__)
                self.assertEqual(expected_signature, str(inspect.signature(function)))

    def test_server_cli_callables_pickle_by_top_level_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            server = load_server(Path(directory))

            for name in (
                "serve",
                "create_codes",
                "list_codes",
                "public_key",
                "build_parser",
                "main",
            ):
                function = getattr(server, name)
                self.assertIs(function, pickle.loads(pickle.dumps(function)), name)

    def test_server_parser_callbacks_are_owning_top_level_wrappers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            server = load_server(Path(directory))
            commands = {
                "serve": server.serve,
                "create-code": server.create_codes,
                "list-codes": server.list_codes,
                "public-key": server.public_key,
            }

            for command, expected in commands.items():
                callback = server.build_parser().parse_args([command]).func
                self.assertIs(expected, callback, command)
                self.assertEqual(expected.__name__, callback.__name__)
                self.assertEqual(expected.__qualname__, callback.__qualname__)
                self.assertEqual(server.__name__, callback.__module__)
                self.assertEqual(
                    inspect.signature(expected), inspect.signature(callback), command
                )
                self.assertIs(callback, pickle.loads(pickle.dumps(callback)), command)

    def test_server_main_dispatches_through_owning_parser(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            server = load_server(Path(directory))
            dispatched: list[Namespace] = []
            parsed = Namespace(marker="server-main")
            parsed.func = lambda args: dispatched.append(args)

            class Parser:
                @staticmethod
                def parse_args() -> Namespace:
                    return parsed

            original_build_parser = server.build_parser
            server.build_parser = Parser
            self.addCleanup(setattr, server, "build_parser", original_build_parser)

            server.main()

            self.assertEqual([parsed], dispatched)

    def test_two_server_cli_bindings_keep_dependencies_isolated(self) -> None:
        with (
            tempfile.TemporaryDirectory() as first_directory,
            tempfile.TemporaryDirectory() as second_directory,
        ):
            first = load_server(Path(first_directory))
            second = load_server(Path(second_directory))
            first_marker = object()
            second_marker = object()
            first.create_code_records = first_marker
            second.create_code_records = second_marker
            first.DEFAULT_FEATURES.append("first-cli-only")
            create_calls: list[dict[str, object]] = []
            original_create_codes = first.licenses.create_codes
            first.licenses.create_codes = lambda _args, **kwargs: create_calls.append(
                kwargs
            )
            self.addCleanup(
                setattr, first.licenses, "create_codes", original_create_codes
            )

            first_create = first.build_parser().parse_args(["create-code"])
            second_create = second.build_parser().parse_args(["create-code"])
            self.assertIs(first.create_codes, first_create.func)
            self.assertIs(second.create_codes, second_create.func)
            first_create.func(first_create)
            second_create.func(second_create)

            self.assertIs(first_marker, create_calls[0]["create_code_records_fn"])
            self.assertIs(second_marker, create_calls[1]["create_code_records_fn"])
            self.assertIn("first-cli-only", create_calls[0]["default_features"])
            self.assertNotIn("first-cli-only", create_calls[1]["default_features"])

            serve_calls: list[tuple[str, tuple[str, int], type]] = []

            def server_factory(label: str):
                class FakeServer:
                    def __init__(self, address, handler) -> None:
                        serve_calls.append((label, address, handler))

                    def serve_forever(self) -> None:
                        serve_calls.append((label, ("serve", 0), object))

                return FakeServer

            first.HOST, first.PORT = "first-host", 8101
            second.HOST, second.PORT = "second-host", 8102
            first.ThreadingHTTPServer = server_factory("first")
            second.ThreadingHTTPServer = server_factory("second")
            first.seed_default_templates = lambda: serve_calls.append(
                ("first-seed", ("seed", 0), object)
            )
            second.seed_default_templates = lambda: serve_calls.append(
                ("second-seed", ("seed", 0), object)
            )
            first.print = lambda _message: None
            second.print = lambda _message: None

            first_serve = first.build_parser().parse_args(["serve"])
            second_serve = second.build_parser().parse_args(["serve"])
            self.assertIs(first.serve, first_serve.func)
            self.assertIs(second.serve, second_serve.func)
            first_serve.func(first_serve)
            second_serve.func(second_serve)

            self.assertIn(("first", ("first-host", 8101), first.Handler), serve_calls)
            self.assertIn(
                ("second", ("second-host", 8102), second.Handler), serve_calls
            )

            key_calls: list[str] = []
            first.public_key_b64 = lambda: "first-public-key"
            second.public_key_b64 = lambda: "second-public-key"
            first.print = lambda value: key_calls.append(f"first:{value}")
            second.print = lambda value: key_calls.append(f"second:{value}")
            first_key = first.build_parser().parse_args(["public-key"])
            second_key = second.build_parser().parse_args(["public-key"])
            self.assertIs(first.public_key, first_key.func)
            self.assertIs(second.public_key, second_key.func)
            first_key.func(first_key)
            second_key.func(second_key)
            self.assertEqual(
                ["first:first-public-key", "second:second-public-key"], key_calls
            )

    def test_server_is_a_thin_facade(self) -> None:
        self.assertLessEqual(len(SERVER.read_text(encoding="utf-8").splitlines()), 300)
