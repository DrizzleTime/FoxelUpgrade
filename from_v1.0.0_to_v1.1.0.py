from tortoise import connections, transactions


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
    conn = connections.get("default")

    async with transactions.in_transaction() as tx_conn:
        try:
            # 检查 `mounts` 表是否存在，如果不存在则无需迁移
            await tx_conn.execute_query_dict("SELECT * FROM mounts LIMIT 1")
            print("找到 `mounts` 表。开始迁移...")
        except Exception:
            print("未找到 `mounts` 表，跳过迁移。")
            return

        try:
            # 为 `storage_adapters` 表添加新列
            await tx_conn.execute_script(
                """
                ALTER TABLE storage_adapters ADD COLUMN path VARCHAR(255);
                ALTER TABLE storage_adapters ADD COLUMN sub_path VARCHAR(1024);
                """
            )
            print(" -> 列 'path' 和 'sub_path' 添加成功。")
        except Exception as e:
            print(f" -> 无法添加列，可能它们已经存在: {e}")

        # 从 `mounts` 表中获取所有数据
        mounts_data = await tx_conn.execute_query_dict("SELECT id, path, sub_path, adapter_id FROM mounts")

        if not mounts_data:
            print(" -> 在 `mounts` 表中未找到数据。跳过数据传输。")
        else:
            print(f" -> 找到 {len(mounts_data)} 条记录需要迁移。")
            
            # 将数据从 `mounts` 迁移到 `storage_adapters`
            for mount_dict in mounts_data:
                mount = Mount(**mount_dict)
                print(f"  - 正在迁移挂载 ID {mount.id} (路径: {mount.path}) 到适配器 ID {mount.adapter_id}")
                await tx_conn.execute_query(
                    "UPDATE storage_adapters SET path = $1, sub_path = $2 WHERE id = $3",
                    [mount.path, mount.sub_path, mount.adapter_id]
                )
            print(" -> 数据迁移完成。")

        # 删除旧的 `mounts` 表
        await tx_conn.execute_script("DROP TABLE mounts;")
        print(" -> `mounts` 表删除成功。")

        try:
            # 为 `path` 列创建唯一索引
            await tx_conn.execute_script("CREATE UNIQUE INDEX uix_storage_adapters_path ON storage_adapters (path);")
            print(" -> 唯一索引 'uix_storage_adapters_path' 创建成功。")
        except Exception as e:
            print(f" -> 无法创建唯一索引，它可能已经存在: {e}")

    print("从 v1.0.0 到 v1.1.0 的迁移成功完成！")
