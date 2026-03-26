from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional
from uuid import uuid4

from apps.api.types import JobEvent, JobRecord, JobStatus, now_iso

ProgressFn = Callable[[str], Awaitable[None]]
JobOp = Callable[[ProgressFn], Awaitable[Optional[str]]]


@dataclass
class _JobState:
    record: JobRecord
    events: list[JobEvent] = field(default_factory=list)
    subscribers: list[asyncio.Queue[JobEvent]] = field(default_factory=list)


class JobRegistry:
    def __init__(self) -> None:
        self._jobs: dict[str, _JobState] = {}
        self._lock = asyncio.Lock()

    async def _broadcast(self, state: _JobState, event: JobEvent) -> None:
        state.events.append(event)
        for queue in list(state.subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # Drop event for a saturated subscriber; terminal event is still persisted.
                continue

    async def _emit(self, job_id: str, event_type: str, status: JobStatus, message: str) -> None:
        async with self._lock:
            state = self._jobs.get(job_id)
            if state is None:
                return
            event = JobEvent(
                job_id=job_id,
                type=event_type,
                status=status,
                message=message,
            )
            await self._broadcast(state, event)

    async def _run_job(self, job_id: str, kind: str, operation: JobOp) -> None:
        async with self._lock:
            state = self._jobs[job_id]
            state.record.status = JobStatus.running
            state.record.started_at = now_iso()
        await self._emit(job_id, "running", JobStatus.running, f"{kind} started")

        async def progress(message: str) -> None:
            await self._emit(job_id, "progress", JobStatus.running, message)

        try:
            graph_updated_at = await operation(progress)
            async with self._lock:
                state = self._jobs[job_id]
                state.record.status = JobStatus.succeeded
                state.record.finished_at = now_iso()
                state.record.graph_updated_at = graph_updated_at
            await self._emit(job_id, "completed", JobStatus.succeeded, f"{kind} completed")
        except Exception as exc:  # pragma: no cover - exercised in API tests
            async with self._lock:
                state = self._jobs[job_id]
                state.record.status = JobStatus.failed
                state.record.finished_at = now_iso()
                state.record.error = str(exc)
            await self._emit(job_id, "failed", JobStatus.failed, str(exc))

    async def submit(self, kind: str, operation: JobOp) -> JobRecord:
        job_id = str(uuid4())
        record = JobRecord(
            id=job_id,
            kind=kind,
            status=JobStatus.queued,
        )
        state = _JobState(record=record)
        queued_event = JobEvent(
            job_id=job_id,
            type="queued",
            status=JobStatus.queued,
            message=f"{kind} queued",
        )

        async with self._lock:
            self._jobs[job_id] = state
            await self._broadcast(state, queued_event)

        asyncio.create_task(self._run_job(job_id, kind, operation))
        return record.model_copy(deep=True)

    async def get(self, job_id: str) -> JobRecord:
        async with self._lock:
            state = self._jobs.get(job_id)
            if state is None:
                raise KeyError(job_id)
            return state.record.model_copy(deep=True)

    async def iter_events(self, job_id: str):
        queue: asyncio.Queue[JobEvent] = asyncio.Queue(maxsize=128)
        async with self._lock:
            state = self._jobs.get(job_id)
            if state is None:
                raise KeyError(job_id)
            snapshot = [event.model_copy(deep=True) for event in state.events]
            state.subscribers.append(queue)

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
                except TimeoutError:
                    # Keep-alive ping support.
                    continue
        finally:
            async with self._lock:
                state = self._jobs.get(job_id)
                if state is not None:
                    state.subscribers = [item for item in state.subscribers if item is not queue]
