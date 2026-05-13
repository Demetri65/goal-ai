from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from threading import Lock, Thread
from typing import Any, Awaitable, Callable, Optional
from uuid import uuid4

from apps.api.types import JobEvent, JobRecord, JobStatus, now_iso

ProgressFn = Callable[..., Awaitable[None]]
JobOp = Callable[[ProgressFn], Awaitable[Optional[str]]]


@dataclass
class _Subscriber:
    queue: asyncio.Queue[JobEvent]
    loop: asyncio.AbstractEventLoop


@dataclass
class _JobState:
    record: JobRecord
    events: list[JobEvent] = field(default_factory=list)
    subscribers: list[_Subscriber] = field(default_factory=list)
    next_sequence: int = 1


class JobRegistry:
    def __init__(self) -> None:
        self._jobs: dict[str, _JobState] = {}
        self._lock = Lock()

    def _broadcast_locked(self, state: _JobState, event: JobEvent) -> None:
        state.events.append(event)
        for subscriber in list(state.subscribers):
            event_copy = event.model_copy(deep=True)

            def enqueue() -> None:
                try:
                    subscriber.queue.put_nowait(event_copy)
                except asyncio.QueueFull:
                    pass

            try:
                subscriber.loop.call_soon_threadsafe(enqueue)
            except RuntimeError:
                state.subscribers = [item for item in state.subscribers if item is not subscriber]

    def _emit(
        self,
        job_id: str,
        event_type: str,
        status: JobStatus,
        message: str,
        *,
        changed_node_ids: Optional[list[str]] = None,
        graph_snapshot: Optional[dict[str, Any]] = None,
    ) -> None:
        with self._lock:
            state = self._jobs.get(job_id)
            if state is None:
                return
            event = JobEvent(
                job_id=job_id,
                type=event_type,
                status=status,
                message=message,
                sequence=state.next_sequence,
                changed_node_ids=changed_node_ids or [],
                graph_snapshot=graph_snapshot,
            )
            state.next_sequence += 1
            self._broadcast_locked(state, event)

    def _run_job(self, job_id: str, kind: str, operation: JobOp) -> None:
        with self._lock:
            state = self._jobs[job_id]
            state.record.status = JobStatus.running
            state.record.started_at = now_iso()
        self._emit(job_id, "running", JobStatus.running, f"{kind} started")

        async def progress(
            message: str,
            *,
            changed_node_ids: Optional[list[str]] = None,
            graph_snapshot: Optional[dict[str, Any]] = None,
            event_type: str = "progress",
        ) -> None:
            self._emit(
                job_id,
                event_type,
                JobStatus.running,
                message,
                changed_node_ids=changed_node_ids,
                graph_snapshot=graph_snapshot,
            )

        try:
            graph_updated_at = asyncio.run(operation(progress))
            with self._lock:
                state = self._jobs[job_id]
                state.record.status = JobStatus.succeeded
                state.record.finished_at = now_iso()
                state.record.graph_updated_at = graph_updated_at
            self._emit(job_id, "completed", JobStatus.succeeded, f"{kind} completed")
        except Exception as exc:  # pragma: no cover - exercised in API tests
            with self._lock:
                state = self._jobs[job_id]
                state.record.status = JobStatus.failed
                state.record.finished_at = now_iso()
                state.record.error = str(exc)
            self._emit(job_id, "failed", JobStatus.failed, str(exc))

    async def submit(self, kind: str, operation: JobOp) -> JobRecord:
        job_id = str(uuid4())
        record = JobRecord(
            id=job_id,
            kind=kind,
            status=JobStatus.queued,
        )
        state = _JobState(record=record)

        with self._lock:
            self._jobs[job_id] = state
        self._emit(job_id, "queued", JobStatus.queued, f"{kind} queued")

        Thread(
            target=self._run_job,
            args=(job_id, kind, operation),
            daemon=True,
        ).start()
        return record.model_copy(deep=True)

    async def get(self, job_id: str) -> JobRecord:
        with self._lock:
            state = self._jobs.get(job_id)
            if state is None:
                raise KeyError(job_id)
            return state.record.model_copy(deep=True)

    async def iter_events(self, job_id: str):
        queue: asyncio.Queue[JobEvent] = asyncio.Queue(maxsize=128)
        loop = asyncio.get_running_loop()
        with self._lock:
            state = self._jobs.get(job_id)
            if state is None:
                raise KeyError(job_id)
            snapshot = [event.model_copy(deep=True) for event in state.events]
            subscriber = _Subscriber(queue=queue, loop=loop)
            state.subscribers.append(subscriber)

        try:
            for event in snapshot:
                yield event

            while True:
                record = await self.get(job_id)
                if record.status in {JobStatus.succeeded, JobStatus.failed} and queue.empty():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                    yield event
                except asyncio.TimeoutError:
                    continue
        finally:
            with self._lock:
                state = self._jobs.get(job_id)
                if state is not None:
                    state.subscribers = [
                        item for item in state.subscribers if item is not subscriber
                    ]
