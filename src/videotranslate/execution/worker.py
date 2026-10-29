"""Independent durable worker; handler work never owns a database transaction."""

import argparse
import json
import signal
import threading
import uuid

from ..config import Settings
from ..db import make_engine, make_session_factory
from ..models.core import utcnow
from ..storage import make_storage
from .context import RunContext
from .contracts import CancellationRequested, FailureCode, LeaseLost, StageFailure, StagePending
from .registry import STAGES
from .service import (
    _lock_run_project,
    _valid_lease,
    claim_run,
    defer_run,
    fail_run,
    finish_run,
    heartbeat,
)


class Worker:
    def __init__(self, settings, *, registry=None):
        self.settings = settings
        self.engine = make_engine(settings)
        self.session_factory = make_session_factory(self.engine)
        self.storage = make_storage(settings)
        self.registry = STAGES if registry is None else registry
        self.stop = threading.Event()
        self.owner = str(uuid.uuid4())

    def run_once(self):
        with self.session_factory.begin() as db:
            run = claim_run(
                db,
                self.owner,
                lease_seconds=self.settings.worker_lease_seconds,
                registry=self.registry,
            )
        if run is None:
            return False
        context = RunContext(
            self.session_factory, self.storage, self.settings, run.id, run.lease_token, self.stop
        )
        finished = threading.Event()

        def pulse():
            while not finished.wait(self.settings.worker_heartbeat_seconds):
                try:
                    with self.session_factory.begin() as db:
                        if not heartbeat(
                            db, run.id, run.lease_token, self.settings.worker_lease_seconds
                        ):
                            return
                except Exception:
                    return

        thread = threading.Thread(target=pulse, daemon=True)
        thread.start()
        try:
            # Existing remote jobs remain pollable after cancellation or staleness.
            if not run.remote_id:
                context.check_active()
            definition = self.registry[run.stage]
            if definition.publication_guard and not run.remote_id:
                with self.session_factory.begin() as db:
                    _, active = context._locked(db)
                    current = definition.publication_guard(db, active)
                    if not current:
                        active.is_stale = True
                if not current:
                    raise CancellationRequested()
            result = definition.handle(context)
            with self.session_factory.begin() as db:
                finish_run(db, run.id, run.lease_token, result, registry=self.registry)
        except CancellationRequested:
            with self.session_factory.begin() as db:
                project, active = _lock_run_project(db, run.id)
                if _valid_lease(active, run.lease_token, utcnow()):
                    if active.cancel_requested_at or project.deleted_at is not None:
                        context_action = "cancel"
                    elif active.is_stale:
                        context_action = "stale"
                    else:
                        active.lease_expires_at = utcnow()
                        context_action = "released"
                else:
                    context_action = "released"
            if context_action == "cancel":
                context.confirm_cancel()
            elif context_action == "stale":
                with self.session_factory.begin() as db:
                    fail_run(db, run.id, run.lease_token, StageFailure(FailureCode.INTERNAL_ERROR))
        except StagePending:
            with self.session_factory.begin() as db:
                defer_run(db, run.id, run.lease_token)
        except LeaseLost:
            pass
        except StageFailure as failure:
            with self.session_factory.begin() as db:
                fail_run(db, run.id, run.lease_token, failure)
        except Exception:
            with self.session_factory.begin() as db:
                fail_run(db, run.id, run.lease_token, StageFailure(FailureCode.INTERNAL_ERROR))
        finally:
            finished.set()
            thread.join()
        return True

    def run(self):
        while not self.stop.is_set():
            if not self.run_once():
                self.stop.wait(self.settings.worker_poll_seconds)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    worker = Worker(Settings())
    signal.signal(signal.SIGTERM, lambda *_: worker.stop.set())
    signal.signal(signal.SIGINT, lambda *_: worker.stop.set())
    if args.once:
        print(json.dumps({"claimed": worker.run_once()}))
    else:
        worker.run()


if __name__ == "__main__":
    main()
