"""Bounded JSON IPC for trusted, importable Python workers (not an OS sandbox)."""

import json
import multiprocessing
from collections.abc import Callable
from multiprocessing.process import BaseProcess
from typing import Any, Protocol

MAX_MESSAGE_BYTES = 2 * 1024 * 1024


class Connection(Protocol):
    def send_bytes(self, buf: bytes) -> None: ...
    def recv_bytes(self, maxlength: int) -> bytes: ...
    def poll(self, timeout: float) -> bool: ...
    def close(self) -> None: ...


def send_json(connection: Connection, message: dict[str, Any]) -> None:
    payload = json.dumps(message, allow_nan=False).encode()
    if len(payload) > MAX_MESSAGE_BYTES:
        raise ValueError("worker message exceeds limit")
    connection.send_bytes(payload)


def receive_json(connection: Connection) -> dict[str, Any]:
    value = json.loads(connection.recv_bytes(MAX_MESSAGE_BYTES))
    if not isinstance(value, dict):
        raise TypeError("invalid worker message")
    return value


def start_worker(
    target: Callable[..., None],
    *arguments: object,
) -> tuple[BaseProcess, Connection]:
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    process = context.Process(target=target, args=(child, *arguments), daemon=True)
    try:
        process.start()
    except BaseException:
        parent.close()
        process.close()
        raise
    finally:
        child.close()
    return process, parent


def stop_worker(process: BaseProcess, connection: Connection) -> None:
    connection.close()
    if process.is_alive():
        process.terminate()
    process.join(timeout=1)
    if process.is_alive():
        process.kill()
        process.join(timeout=1)
    process.close()
