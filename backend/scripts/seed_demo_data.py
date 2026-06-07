"""手动导入演示用户、教练知识库与知识图谱。

用法（在 backend 目录下）:
    python scripts/seed_demo_data.py
    python scripts/seed_demo_data.py --knowledge-only
    python scripts/seed_demo_data.py --graph-only
    python scripts/seed_demo_data.py --users-only
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.seed_graph import seed_demo_graph
from app.db.seed_knowledge import seed_demo_knowledge
from app.db.seed_users import DEMO_PASSWORD, DEMO_USERS, seed_demo_users
from app.db.session import AsyncSessionLocal

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def main(*, users: bool, knowledge: bool, graph: bool) -> None:
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

    if graph:
        async with AsyncSessionLocal() as db:
            imported = await seed_demo_graph(db)
            await db.commit()
            if imported:
                logger.info("已导入 %s 条图谱实体/边", imported)
            else:
                logger.info("图谱实体与边均已存在或未配置嵌入 API，未重复导入。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="导入演示用户、知识库与知识图谱")
    parser.add_argument("--users-only", action="store_true", help="仅导入演示用户")
    parser.add_argument("--knowledge-only", action="store_true", help="仅导入知识库")
    parser.add_argument("--graph-only", action="store_true", help="仅导入知识图谱")
    args = parser.parse_args()
    exclusive = sum(bool(x) for x in (args.users_only, args.knowledge_only, args.graph_only))
    if exclusive > 1:
        parser.error("--users-only、--knowledge-only、--graph-only 不能同时使用")
    seed_users = args.users_only or exclusive == 0
    seed_knowledge = args.knowledge_only or exclusive == 0
    seed_graph = args.graph_only or exclusive == 0
    asyncio.run(main(users=seed_users, knowledge=seed_knowledge, graph=seed_graph))
