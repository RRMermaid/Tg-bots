"""SQL is authoritative. No growing in-memory diary or conversation buffer."""
import asyncio

async def query(function, *args, **kwargs):
    return await asyncio.to_thread(function, *args, **kwargs)
