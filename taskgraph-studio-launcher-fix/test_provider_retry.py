import asyncio
import unittest
from unittest.mock import Mock, patch
from provider_retry import RateLimited, request_with_retry


class RetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_retry_then_success_counts_and_waits(self):
        request = Mock(side_effect=[RateLimited({"retry-after": "15"}), {"ok": True}])
        count, event = Mock(), Mock()
        with patch("provider_retry.asyncio.sleep") as sleep:
            result = await request_with_retry(request, count, event)
        self.assertTrue(result["ok"])
        self.assertEqual(count.call_count, 1)
        self.assertGreaterEqual(sleep.call_args.args[0], 15)

    async def test_bounded_retries_and_long_retry_after(self):
        for headers, calls in [({}, 4), ({"retry-after": "120"}, 1)]:
            request = Mock(side_effect=RateLimited(headers))
            with patch("provider_retry.asyncio.sleep"), self.assertRaises(RateLimited):
                await request_with_retry(request)
            self.assertEqual(request.call_count, calls)

    async def test_quota_errors_and_cancel_are_not_retried(self):
        request = Mock(side_effect=RuntimeError("billing quota"))
        with self.assertRaises(RuntimeError):
            await request_with_retry(request)
        self.assertEqual(request.call_count, 1)
        request = Mock(side_effect=RateLimited())
        with patch("provider_retry.asyncio.sleep", side_effect=asyncio.CancelledError), self.assertRaises(asyncio.CancelledError):
            await request_with_retry(request)
        self.assertEqual(request.call_count, 1)
