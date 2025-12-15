import asyncio
import importlib.util
import os
import re
import sys
from pathlib import Path

from tortoise import Tortoise, exceptions

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..')))

try:
    from domain.config.service import ConfigService
except ImportError:
    print("错误: 无法导入 ConfigService。请确保项目结构正确。")
    sys.exit(1)


DB_PATH = "data/db/db.sqlite3"
DB_URL = f"sqlite://{DB_PATH}"

MIGRATION_FILE_PATTERN = re.compile(
    r"from_(v\d+\.\d+\.\d+)_to_(v\d+\.\d+\.\d+)\.py")


def version_to_tuple(v: str) -> tuple:
    """将版本字符串 'vX.Y.Z' 转换为可比较的元组 (X, Y, Z)"""
    return tuple(map(int, v.lstrip('v').split('.')))


def discover_migrations():
    """
    动态发现并加载所有迁移脚本。
    返回一个按来源版本正确排序的迁移列表。
    """
    migrations = []
    migrate_dir = Path(__file__).parent

    for file in os.listdir(migrate_dir):
        match = MIGRATION_FILE_PATTERN.match(file)
        if match:
            from_version, to_version = match.groups()
            module_name = file[:-3]

            spec = importlib.util.spec_from_file_location(
                f"migrate.{module_name}", migrate_dir / file
            )
            migration_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(migration_module)

            if hasattr(migration_module, "run_migration"):
                migrations.append({
                    "from_version": from_version,
                    "to_version": to_version,
                    "run": migration_module.run_migration
                })
                print(f"发现迁移: {from_version} -> {to_version}")

    migrations.sort(key=lambda m: version_to_tuple(m["from_version"]))
    return migrations


async def get_db_version():
    """
    从 'configurations' 表中获取当前数据库版本。
    如果表或版本键不存在，默认为 'v1.0.0'。
    """
    try:
        await Tortoise.get_connection("default").execute_query_dict("SELECT 1 FROM configurations LIMIT 1")
    except (exceptions.OperationalError, exceptions.DBConnectionError):
        print("警告: 未找到 `configurations` 表。假设版本为 v1.0.0。")
        return "v1.0.0"

    version = await ConfigService.get("APP_VERSION")
    return version if version else "v1.0.0"


async def set_db_version(version: str):
    """
    在 'configurations' 表中更新数据库版本。
    """
    await ConfigService.set("APP_VERSION", version)
    print(f"数据库版本成功更新至 {version}。")


async def run_migrations():
    """
    检查数据库版本并按顺序运行所有必要的迁移，直到达到最新版本。
    """
    if not os.path.exists(DB_PATH):
        print(f"数据库未在 '{DB_PATH}' 找到。无需迁移。")
        return

    print(f"正在连接到数据库: {DB_URL}")
    await Tortoise.init(
        db_url=DB_URL,
        modules={"models": ["models.database"]}
    )

    all_migrations = discover_migrations()

    try:
        while True:
            db_version_str = await get_db_version()
            db_version_tuple = version_to_tuple(db_version_str)
            print(f"当前数据库版本: {db_version_str}")

            next_migration = None
            for migration in all_migrations:
                from_version_tuple = version_to_tuple(
                    migration["from_version"])
                if from_version_tuple >= db_version_tuple:
                    next_migration = migration
                    break

            if next_migration:
                from_v = next_migration["from_version"]
                to_v = next_migration["to_version"]

                if version_to_tuple(from_v) > db_version_tuple:
                    print(f"注意: 从版本 {db_version_str} 跳跃到 {from_v} 进行迁移。")

                print(f"-> 发现从 {from_v} 到 {to_v} 的可用迁移，正在执行...")
                await next_migration["run"]()
                await set_db_version(to_v)
                print(f"-> 已成功从 {from_v} 迁移到 {to_v}。")
            else:
                print("未找到更多可用的迁移。")
                break

        final_version = await get_db_version()
        print(f"最终数据库版本: {final_version}。迁移检查完成。")

    except Exception as e:
        print(f"迁移过程中发生错误: {e}")
    finally:
        await Tortoise.close_connections()
        print("数据库连接已关闭。")


if __name__ == "__main__":
    print("开始数据库迁移检查...")
    asyncio.run(run_migrations())
