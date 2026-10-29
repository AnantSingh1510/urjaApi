"""Opt-in read-only live verification. Run from the repository root with credentials configured."""

import asyncio
import json
from collections import Counter

from urja_api.config import Settings
from urja_api.normalize import with_intervals
from urja_api.portal import PortalClient
from urja_api.service import Service


async def main():
    settings = Settings(demo=False)
    portal = PortalClient(settings)
    try:
        service = Service(portal, settings)
        catalog = await service.catalog()
        # One representative per source build; avoid fetching every meter's readings.
        samples = {}
        for meter in catalog.meters:
            if meter.source_build not in samples:
                entry = await service.readings(meter.id)
                readings = with_intervals(entry.data)
                samples[meter.source_build or "unknown"] = {
                    "meter_id": meter.id,
                    "readings": len(readings),
                    "first": readings[0].raw_timestamp if readings else None,
                    "last": readings[-1].raw_timestamp if readings else None,
                }
        print(
            json.dumps(
                {
                    "meters": len(catalog.meters),
                    "transformers": len(catalog.transformers),
                    "network_nodes": len(catalog.nodes),
                    "network_issues": dict(Counter(i.code for i in catalog.issues)),
                    "samples": samples,
                    "source": catalog.freshness.source,
                },
                indent=2,
            )
        )
    finally:
        await portal.close()


if __name__ == "__main__":
    asyncio.run(main())
