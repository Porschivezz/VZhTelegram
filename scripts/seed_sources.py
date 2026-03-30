"""Validate all source URLs are reachable and print a status report."""

from __future__ import annotations

import asyncio
import sys
import os

import aiohttp
import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def check_source(
    session: aiohttp.ClientSession, source: dict, semaphore: asyncio.Semaphore
) -> dict:
    """Check if a source URL is reachable."""
    async with semaphore:
        try:
            async with session.head(
                source["url"],
                timeout=aiohttp.ClientTimeout(total=15),
                allow_redirects=True,
                headers={"User-Agent": "VZhTelegram/1.0 (Source Validator)"},
            ) as resp:
                return {
                    "id": source["id"],
                    "name": source["name"],
                    "url": source["url"],
                    "status": resp.status,
                    "ok": 200 <= resp.status < 400,
                }
        except Exception as e:
            return {
                "id": source["id"],
                "name": source["name"],
                "url": source["url"],
                "status": str(e)[:60],
                "ok": False,
            }


async def main() -> None:
    with open("config/sources.yaml") as f:
        config = yaml.safe_load(f)

    sources = config.get("sources", [])
    semaphore = asyncio.Semaphore(10)

    print(f"Checking {len(sources)} sources...\n")

    async with aiohttp.ClientSession() as session:
        tasks = [check_source(session, src, semaphore) for src in sources]
        results = await asyncio.gather(*tasks)

    ok = [r for r in results if r["ok"]]
    failed = [r for r in results if not r["ok"]]

    print(f"\n{'='*60}")
    print(f"RESULTS: {len(ok)}/{len(results)} sources reachable\n")

    if failed:
        print("FAILED SOURCES:")
        for r in failed:
            print(f"  \u274c {r['id']:30s} {r['status']:>6} {r['url']}")

    print(f"\nOK SOURCES:")
    for r in ok:
        print(f"  \u2705 {r['id']:30s} {r['status']:>6} {r['url']}")


if __name__ == "__main__":
    asyncio.run(main())
