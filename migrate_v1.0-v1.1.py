import asyncio
import os
from tortoise import Tortoise, connections, transactions


class Mount(object):
    def __init__(self, id, path, sub_path, adapter_id):
        self.id = id
        self.path = path
        self.sub_path = sub_path
        self.adapter_id = adapter_id


async def run_migration():
    """
    数据迁移脚本，用于将 Mount 表合并到 StorageAdapter 表中。
    """
    db_path = "data/db/db.sqlite3"
    db_url = f"sqlite://{db_path}"

    if not os.path.exists(db_path):
        print(f"数据库文件未在 '{db_path}' 找到。跳过迁移。")
        return

    await Tortoise.init(
        db_url=db_url,
        modules={"models": ["models.database"]}
    )
    conn = connections.get("default")

    async with transactions.in_transaction() as tx_conn:
        try:
            await tx_conn.execute_query_dict("SELECT * FROM mounts LIMIT 1")
            print("找到 `mounts` 表。开始迁移...")
        except Exception:
            return

        try:
            await tx_conn.execute_script(
                """
                ALTER TABLE storage_adapters ADD COLUMN path VARCHAR(255);
                ALTER TABLE storage_adapters ADD COLUMN sub_path VARCHAR(1024);
                """
            )
            print(" -> 列添加成功。")
        except Exception as e:
            print(f" -> 无法添加列，可能它们已经存在: {e}")

        mounts_data = await tx_conn.execute_query_dict("SELECT id, path, sub_path, adapter_id FROM mounts")

        if not mounts_data:
            print(" -> 在 `mounts` 表中未找到数据。跳过数据传输。")
        else:
            print(f" -> 找到 {len(mounts_data)} 条记录需要迁移。")

            print("\n第 3 步：将数据迁移到 `storage_adapters` 表...")
            for mount_dict in mounts_data:
                mount = Mount(**mount_dict)
                print(
                    f"  - 正在迁移挂载 ID {mount.id} (路径: {mount.path}) 到适配器 ID {mount.adapter_id}")
                await tx_conn.execute_query(
                    "UPDATE storage_adapters SET path = $1, sub_path = $2 WHERE id = $3",
                    [mount.path, mount.sub_path, mount.adapter_id]
                )
            print(" -> 数据迁移完成。")

        await tx_conn.execute_script("DROP TABLE mounts;")
        print(" -> `mounts` 表删除成功。")

        try:
            await tx_conn.execute_script("CREATE UNIQUE INDEX uix_storage_adapters_path ON storage_adapters (path);")
            print(" -> 唯一索引创建成功。")
        except Exception as e:
            print(f" -> 无法创建唯一索引，它可能已经存在: {e}")

    print("\n迁移成功完成！")


if __name__ == "__main__":
    print("开始数据库迁移 Mount -> StorageAdapter...")
    asyncio.run(run_migration())
