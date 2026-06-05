"""手动导入演示用户与教练知识库。

用法（在 backend 目录下）:
    python scripts/seed_demo_data.py
    python scripts/seed_demo_data.py --knowledge-only
    python scripts/seed_demo_data.py --users-only
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.seed_knowledge import seed_demo_knowledge
from app.db.seed_users import DEMO_PASSWORD, DEMO_USERS, seed_demo_users
from app.db.session import AsyncSessionLocal

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def main(*, users: bool, knowledge: bool) -> None:
    if users:
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

    if knowledge:
        async with AsyncSessionLocal() as db:
            imported = await seed_demo_knowledge(db)
            await db.commit()
            if imported:
                logger.info("已导入 %s 篇知识库文档", imported)
            else:
                logger.info("知识库文档均已存在或未配置嵌入 API，未重复导入。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="导入演示用户与教练知识库")
    parser.add_argument("--users-only", action="store_true", help="仅导入演示用户")
    parser.add_argument("--knowledge-only", action="store_true", help="仅导入知识库")
    args = parser.parse_args()
    seed_users = not args.knowledge_only
    seed_knowledge = not args.users_only
    asyncio.run(main(users=seed_users, knowledge=seed_knowledge))
