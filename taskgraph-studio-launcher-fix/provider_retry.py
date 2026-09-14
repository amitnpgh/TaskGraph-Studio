"""Bounded, cancellable retries of rejected provider requests only."""
import asyncio
import random
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime


class RateLimited(RuntimeError):
    def __init__(self, headers=None):
        super().__init__("OpenAI's request limit persisted. Reduce parallelism in Run limits or check your API rate limits. Saved work remains available.")
        value = (headers or {}).get("retry-after", "")
        try:
            self.delay = max(0, float(value))
        except (TypeError, ValueError):
            try:
                self.delay = max(0, (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds())
            except (TypeError, ValueError, OverflowError):
                self.delay = 0


async def request_with_retry(request, count_retry=None, on_wait=None):
    for attempt in range(4):
        try:
            return await asyncio.to_thread(request)
        except RateLimited as exc:
            delay = max(exc.delay, 8 * (2 ** attempt) + random.uniform(0, 1))
            if attempt == 3 or delay > 60:
                raise
            if on_wait:
                on_wait(attempt + 1, delay)
            await asyncio.sleep(delay)
            if count_retry:
                count_retry()
