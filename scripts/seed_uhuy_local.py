"""Seed the 3 Uhuy test sessions straight into the LOCAL SQLite database.

Why local (not Neon): sessions/payments are operational push-only data --
sync/engine.py PULL_ORDER never downloads them, so Neon-seeded sessions are
invisible to GET /sessions on the kiosk. Config (campaign/booth/assignment)
does pull down, and is already here; sessions must be created where the
kiosk reads them.

Idempotent: same deterministic ids as scripts/seed_uhuy.py (Neon copy).

Prerequisite: kiosk must have pulled config first (Uhuy Booth 1 present).
Run from the project root:  python scripts/seed_uhuy_local.py
"""

import sys
import uuid
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from config import resolve_device_id  # noqa: E402
from database import init_db, local_session  # noqa: E402
from models.booth import Booth  # noqa: E402
from models.device import Device  # noqa: E402
from models.session import SessionModel  # noqa: E402
from sync import engine  # noqa: E402


def sid(name: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"ourlilphotobooth/seed-uhuy/{name}"))


SESSION_IDS = [sid(f"session-{i}") for i in (1, 2, 3)]


def main() -> None:
    init_db()
    with local_session() as db:
        device_id = resolve_device_id()
        device = db.get(Device, device_id)
        if device is None:
            device = engine.ensure_local_device(db)
            db.flush()

        booth = db.query(Booth).filter(Booth.name == "Uhuy Booth 1").first()
        if booth is None or booth.campaign_id is None:
            raise SystemExit(
                "Uhuy Booth 1 (with campaign) not found locally. "
                "Sync first: restart the service or POST /sync/trigger, then re-run."
            )

        for i, sess_id in enumerate(SESSION_IDS, start=1):
            row = db.get(SessionModel, sess_id)
            if row is None:
                db.add(
                    SessionModel(
                        id=sess_id,
                        campaign_id=booth.campaign_id,
                        booth_id=booth.id,
                        device_id=device.id,
                        activation_mode="qr",
                        state="started",
                        offline=False,
                    )
                )
        db.commit()

        rows = (
            db.query(SessionModel)
            .filter(SessionModel.id.in_(SESSION_IDS))
            .order_by(SessionModel.id)
            .all()
        )
        assert len(rows) == 3, [r.id for r in rows]
        for r in rows:
            print(f"  {r.id} state={r.state.value} mode={r.activation_mode.value}")
    print("LOCAL SEED OK: 3 started sessions ready for payment tests")


if __name__ == "__main__":
    main()
