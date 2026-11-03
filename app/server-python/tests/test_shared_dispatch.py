"""``dispatch_command``: what the web API answers for a command, before any receiver sees it."""

from __future__ import annotations

import logging

from fastapi import HTTPException

from pswamp_core.command_routing import CommandRefused, NoReceiver
from pswamp_models.player import PlayCommand
from shared import dispatch_command

LOG = logging.getLogger("test_shared_dispatch")


class Run:
    """A run whose ``dispatch`` raises ``error``, or takes the command."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.dispatched = []

    def dispatch(self, command) -> None:
        if self.error is not None:
            raise self.error
        self.dispatched.append(command)


class Registry:
    def __init__(self, run: Run | None) -> None:
        self.run = run

    def peek(self, key: str):
        return self.run


def answer(run: Run | None):
    try:
        return dispatch_command(Registry(run), PlayCommand(client_id="7"), LOG)
    except HTTPException as error:
        return error


def test_a_command_is_acknowledged_once_its_run_takes_it():
    run = Run()
    ack = answer(run)
    assert ack.applied == "play" and run.dispatched[0].request_id == ack.request_id


def test_no_run_is_a_404_and_a_refusal_a_409():
    assert answer(None).status_code == 404
    refused = answer(Run(CommandRefused("not now")))
    assert (refused.status_code, refused.detail) == (409, "not now")


def test_a_command_nothing_in_the_pipeline_takes_is_a_503():
    # The deployment lacks its receiver (a live source not configured): nothing to retry against.
    missing = answer(Run(NoReceiver("app has no receiver for PlayCommand")))
    assert (missing.status_code, missing.detail) == (503, "app has no receiver for PlayCommand")
