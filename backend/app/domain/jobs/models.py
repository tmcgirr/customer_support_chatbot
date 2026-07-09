"""Durable background-job model (contracts §7).

The worker (`app/worker.py`) claims jobs atomically, runs a handler, and marks
them done / retried / dead-lettered. On-demand jobs (delivery, indexing) are
enqueued by app code; periodic jobs (sweeps, aggregates, reminders) are enqueued
by the worker's scheduler. Mirrors the conversation turn-lock discipline: a lease
(`lock_expires_at`) lets a crashed worker's job be reclaimed.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# On-demand types are enqueued by app code; the rest are periodic (worker scheduler).
JobType = Literal[
    "deliver_request",  # V4: deliver a request to CRM/ticketing
    "poll_indexing",  # V5: poll a knowledge file's indexing status
    "retention_sweep",  # V6: periodic — delete data past its retention class
    "privacy_delete",  # V6: on-demand — execute a verified subject-erasure request
    "privacy_reconcile",  # V6: periodic — re-enqueue verified erasures whose job was lost
    "daily_aggregates",  # periodic: snapshot conversation/request/feedback counts
    "label_conversations",  # V1.5 periodic: topic/intent-label ended conversations
    "generate_insights",  # V1.5 periodic + on-demand: build daily/weekly/monthly reports
    "knowledge_review_reminder",  # periodic: flag knowledge sources past review_date
    "stale_lock_sweep",  # periodic: release leaked conversation run-locks
    "abandonment_sweep",  # periodic: mark inactive conversations abandoned
    "delivery_reconcile",  # periodic: park/re-enqueue requests orphaned by a dead delivery job
]

JobStatus = Literal["pending", "running", "done", "failed", "dead_letter"]


class Job(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(alias="_id")
    type: JobType
    resource_id: str | None = None  # the entity a job acts on (e.g. request_id); None for periodic
    status: JobStatus = "pending"
    attempts: int = 0
    max_attempts: int = 5
    available_at: datetime  # not eligible to run before this (scheduling + backoff)
    lock_owner: str | None = None
    lock_expires_at: datetime | None = None
    last_error: str | None = None  # error CODE only — never a provider/PII message
    created_at: datetime
    terminal_at: datetime | None = None  # set on done/dead_letter; drives the TTL cleanup
