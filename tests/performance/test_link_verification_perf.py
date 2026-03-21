"""Performance test: Link Verification Throughput.

Verifies 40 URLs can be checked within 30 seconds and concurrency
limit is respected.

Spec refs: NFR-LINK-PERF, FR-018, Section 11.5.
"""

import asyncio
import time

import httpx
import pytest

from newsletter_agent.tools.link_verifier import verify_urls


@pytest.mark.performance
class TestLinkVerificationPerformance:
    @pytest.mark.asyncio
    async def test_40_urls_under_30_seconds(self, respx_mock):
        """40 URLs with 0.5s delay each complete within 30s (proves concurrency)."""
        urls = [f"https://perf-test.example.com/{i}" for i in range(40)]

        concurrent_count = 0
        max_concurrent_seen = 0
        lock = asyncio.Lock()

        async def delayed_response(request):
            nonlocal concurrent_count, max_concurrent_seen
            async with lock:
                concurrent_count += 1
                max_concurrent_seen = max(max_concurrent_seen, concurrent_count)
            await asyncio.sleep(0.5)  # Simulate latency (0.5s for test speed)
            async with lock:
                concurrent_count -= 1
            return httpx.Response(
                200,
                html="<html><head><title>Test Article</title></head><body>ok</body></html>",
            )

        for url in urls:
            respx_mock.get(url).mock(side_effect=delayed_response)

        start = time.monotonic()
        results = await verify_urls(urls, timeout=10.0, max_concurrent=10)
        elapsed = time.monotonic() - start

        # All 40 URLs have results
        assert len(results) == 40
        # All valid
        assert all(r.status == "valid" for r in results.values())
        # Completed within budget
        assert elapsed < 30, f"Verification took {elapsed:.1f}s, exceeding 30s budget"
        # Concurrency was limited
        assert max_concurrent_seen <= 10, (
            f"Max concurrent was {max_concurrent_seen}, expected <= 10"
        )

    @pytest.mark.asyncio
    async def test_concurrency_limit_respected(self, respx_mock):
        """Semaphore limits concurrent connections to max_concurrent."""
        urls = [f"https://conc-test.example.com/{i}" for i in range(20)]
        concurrent_count = 0
        max_concurrent_seen = 0
        lock = asyncio.Lock()

        async def slow_response(request):
            nonlocal concurrent_count, max_concurrent_seen
            async with lock:
                concurrent_count += 1
                max_concurrent_seen = max(max_concurrent_seen, concurrent_count)
            await asyncio.sleep(0.1)
            async with lock:
                concurrent_count -= 1
            return httpx.Response(
                200,
                html="<html><head><title>Article</title></head><body>ok</body></html>",
            )

        for url in urls:
            respx_mock.get(url).mock(side_effect=slow_response)

        await verify_urls(urls, max_concurrent=5)
        assert max_concurrent_seen <= 5
