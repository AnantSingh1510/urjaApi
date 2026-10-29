"""Clearly synthetic fixtures. No portal credentials or downloaded customer data."""

from datetime import datetime, timedelta


class DemoPortal:
    async def close(self):
        pass

    async def export_meters(self):
        rows = []
        for i in range(12):
            group = i % 3 + 1
            hierarchy = {
                "zone": {"code": "DEMO-Z1", "name": "Demo zone"},
                "circle": {"code": "DEMO-C1", "name": "Demo circle"},
                "division": {"code": "DEMO-D1", "name": "Demo division"},
                "subdivision": {"code": "DEMO-SD1", "name": "Demo subdivision"},
                "substation": {"code": "DEMO-SS1", "name": "Demo substation"},
                "feeder": {"code": f"DEMO-F{group}", "name": f"Demo feeder {group}"},
                "dt": {"code": f"DEMO-DT{group}", "name": f"Demo transformer {group}"},
            }
            if i == 10:
                hierarchy["circle"]["code"] = ""
            if i == 11:
                hierarchy["dt"]["name"] = "Old demo transformer name"
                hierarchy["feeder"] = {"code": "DEMO-F1", "name": "Demo feeder 1"}
            rows.append(
                {
                    "meterId": f"DEMO-{i + 1:03d}",
                    "serialNo": f"SYNTH-{i + 1:04d}",
                    "make": ["Demo Alpha", "Demo Beta"][i % 2],
                    "phaseType": "single" if i % 3 else "three",
                    "installStatus": ["Installed", "Installed", "Faulty", "Decommissioned"][i % 4],
                    "installType": "Whole Current",
                    "build": "legacy" if i % 2 else "v2",
                    "dtCode": f"DEMO-DT{group}",
                    "hierarchy": hierarchy,
                    "geo": {"lat": 26.85 + i * 0.008, "lng": 75.72 + (i % 4) * 0.025},
                }
            )
        return {"data": rows, "total": len(rows)}

    async def transformers(self):
        return [
            {
                "code": f"DEMO-DT{i}",
                "name": f"Demo transformer {i}",
                "feederCode": f"DEMO-F{i}",
                "capacityKva": 100 * i,
            }
            for i in range(1, 4)
        ]

    async def readings(self, meter_id):
        start = datetime(2026, 6, 30)
        return {
            "data": [
                {
                    "timestamp": (start + timedelta(minutes=30 * i)).strftime("%d/%m/%Y %H:%M"),
                    "kwh": str(1000 + i * 0.4),
                    "kvah": str(1080 + i * 0.43),
                    "voltR": str(225 + i % 10),
                }
                for i in range(48)
            ]
        }
