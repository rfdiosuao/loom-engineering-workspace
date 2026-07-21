from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class CliCallbacks:
    serve: Callable[[argparse.Namespace], None]
    create_codes: Callable[[argparse.Namespace], None]
    list_codes: Callable[[argparse.Namespace], None]
    public_key: Callable[[argparse.Namespace], None]


@dataclass(frozen=True)
class CliBindings:
    serve: Callable[[argparse.Namespace], None]
    create_codes: Callable[[argparse.Namespace], None]
    list_codes: Callable[[argparse.Namespace], None]
    public_key: Callable[[argparse.Namespace], None]
    build_parser: Callable[[CliCallbacks | None], argparse.ArgumentParser]
    main: Callable[[], None]


def _default_facade() -> Any:
    from . import facade

    return facade


def _serve(api: Any, _args: argparse.Namespace) -> None:
    api.seed_default_templates()
    httpd = api.ThreadingHTTPServer((api.HOST, api.PORT), api.Handler)
    printer = getattr(api, "print", print)
    printer(f"OpenClaw license server listening on {api.HOST}:{api.PORT}")
    httpd.serve_forever()


def _create_codes(api: Any, args: argparse.Namespace) -> None:
    api.licenses.create_codes(
        args,
        create_code_records_fn=api.create_code_records,
        parse_models_fn=api.parse_models,
        parse_json_object_fn=api.parse_json_object,
        default_features=api.DEFAULT_FEATURES,
    )


def _list_codes(api: Any, args: argparse.Namespace) -> None:
    api.licenses.list_codes(args, connect_fn=api.connect)


def _public_key(api: Any, _args: argparse.Namespace) -> None:
    printer = getattr(api, "print", print)
    printer(api.public_key_b64())


def _build_parser(
    api: Any,
    callbacks: CliCallbacks,
) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OpenClaw license server")
    sub = parser.add_subparsers(required=True)

    serve_parser = sub.add_parser("serve")
    serve_parser.set_defaults(func=callbacks.serve)

    create_parser = sub.add_parser("create-code")
    create_parser.add_argument("--count", type=int, default=1)
    create_parser.add_argument("--licensee", default="客户")
    create_parser.add_argument("--edition", default="pro")
    create_parser.add_argument("--features", default=",".join(api.DEFAULT_FEATURES))
    create_parser.add_argument("--expires", default="2027-05-01")
    create_parser.add_argument("--max-activations", type=int, default=1)
    create_parser.add_argument("--member-mode", action="store_true")
    create_parser.add_argument("--plan", default="monthly")
    create_parser.add_argument(
        "--gateway-base-url", default=api.DEFAULT_GATEWAY_BASE_URL
    )
    create_parser.add_argument(
        "--gateway-image-base-url", default=api.DEFAULT_GATEWAY_IMAGE_BASE_URL
    )
    create_parser.add_argument(
        "--gateway-video-base-url", default=api.DEFAULT_GATEWAY_VIDEO_BASE_URL
    )
    create_parser.add_argument("--gateway-token", default=api.DEFAULT_GATEWAY_TOKEN)
    create_parser.add_argument(
        "--gateway-image-token", default=api.DEFAULT_GATEWAY_IMAGE_TOKEN
    )
    create_parser.add_argument(
        "--gateway-video-token", default=api.DEFAULT_GATEWAY_VIDEO_TOKEN
    )
    create_parser.add_argument(
        "--gateway-default-model", default=api.DEFAULT_GATEWAY_DEFAULT_MODEL
    )
    create_parser.add_argument(
        "--gateway-image-model", default=api.DEFAULT_GATEWAY_IMAGE_MODEL
    )
    create_parser.add_argument(
        "--gateway-video-model", default=api.DEFAULT_GATEWAY_VIDEO_MODEL
    )
    create_parser.add_argument(
        "--gateway-models", default=",".join(api.DEFAULT_GATEWAY_MODELS)
    )
    create_parser.add_argument("--quotas", default="{}")
    create_parser.set_defaults(func=callbacks.create_codes)

    list_parser = sub.add_parser("list-codes")
    list_parser.set_defaults(func=callbacks.list_codes)

    key_parser = sub.add_parser("public-key")
    key_parser.set_defaults(func=callbacks.public_key)
    return parser


def bind_cli(api: Any) -> CliBindings:
    def bound_serve(args: argparse.Namespace) -> None:
        return _serve(api, args)

    def bound_create_codes(args: argparse.Namespace) -> None:
        return _create_codes(api, args)

    def bound_list_codes(args: argparse.Namespace) -> None:
        return _list_codes(api, args)

    def bound_public_key(args: argparse.Namespace) -> None:
        return _public_key(api, args)

    default_callbacks = CliCallbacks(
        serve=bound_serve,
        create_codes=bound_create_codes,
        list_codes=bound_list_codes,
        public_key=bound_public_key,
    )

    def bound_build_parser(
        callbacks: CliCallbacks | None = None,
    ) -> argparse.ArgumentParser:
        return _build_parser(api, default_callbacks if callbacks is None else callbacks)

    def bound_main() -> None:
        args = bound_build_parser().parse_args()
        args.func(args)

    return CliBindings(
        serve=bound_serve,
        create_codes=bound_create_codes,
        list_codes=bound_list_codes,
        public_key=bound_public_key,
        build_parser=bound_build_parser,
        main=bound_main,
    )


def serve(args: argparse.Namespace) -> None:
    return _serve(_default_facade(), args)


def create_codes(args: argparse.Namespace) -> None:
    return _create_codes(_default_facade(), args)


def list_codes(args: argparse.Namespace) -> None:
    return _list_codes(_default_facade(), args)


def public_key(_args: argparse.Namespace) -> None:
    return _public_key(_default_facade(), _args)


def build_parser() -> argparse.ArgumentParser:
    api = _default_facade()
    return _build_parser(
        api,
        CliCallbacks(
            serve=serve,
            create_codes=create_codes,
            list_codes=list_codes,
            public_key=public_key,
        ),
    )


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


__all__ = [
    "CliBindings",
    "CliCallbacks",
    "bind_cli",
    "build_parser",
    "create_codes",
    "list_codes",
    "main",
    "public_key",
    "serve",
]
