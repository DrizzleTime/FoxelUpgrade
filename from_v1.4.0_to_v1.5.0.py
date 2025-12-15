from tortoise import transactions


async def run_migration():
    """
    v1.4.0 -> v1.5.0

    - plugins 表新增 open_app 字段，用于声明插件是否支持“独立打开应用”。
    """
    async with transactions.in_transaction() as tx_conn:
        try:
            await tx_conn.execute_query_dict("SELECT 1 FROM plugins LIMIT 1")
            print("找到 `plugins` 表。开始迁移...")
        except Exception:
            print("未找到 `plugins` 表，跳过迁移。")
            return

        try:
            await tx_conn.execute_script(
                "ALTER TABLE plugins ADD COLUMN open_app BOOLEAN NOT NULL DEFAULT 0;"
            )
            print(" -> 列 'open_app' 添加成功。")
        except Exception as e:
            print(f" -> 无法添加列，可能它已经存在: {e}")

    print("从 v1.4.0 到 v1.5.0 的迁移成功完成！")

