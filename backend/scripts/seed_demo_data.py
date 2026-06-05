"""手动导入演示用户。

用法（在 backend 目录下）:
    python scripts/seed_demo_data.py
"""

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.seed_users import DEMO_PASSWORD, DEMO_USERS, seed_demo_users
from app.db.session import AsyncSessionLocal

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def main() -> None:
    async with AsyncSessionLocal() as db:
        created = await seed_demo_users(db)
        await db.commit()
        if created:
            logger.info("已创建演示账号: %s", ", ".join(created))
        else:
            logger.info("演示账号均已存在，未重复创建。")

    print("\n演示账号（密码均为 Demo@123456）:")
    for spec in DEMO_USERS:
        print(f"  - {spec.username:16} role={spec.role}")


if __name__ == "__main__":
    asyncio.run(main())
