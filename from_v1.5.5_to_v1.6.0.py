from tortoise import transactions


async def run_migration():
    """
    v1.5.5 -> v1.6.0

    由于插件系统重构，旧版本插件已不兼容，直接删除并重建 plugins 表。

    主要变更：
    - 删除字段: url, enabled
    - key 字段改为必填且唯一
    - 新增字段: license, manifest, loaded_routes, loaded_processors
    """
    async with transactions.in_transaction() as tx_conn:
        try:
            await tx_conn.execute_query_dict("SELECT 1 FROM plugins LIMIT 1")
            print("找到 `plugins` 表。开始迁移...")
        except Exception:
            print("未找到 `plugins` 表，跳过迁移。")
            return

        try:
            # 删除旧的 plugins 表
            await tx_conn.execute_script("DROP TABLE plugins;")
            print(" -> 旧的 `plugins` 表删除成功。")

            # 创建新的 plugins 表
            await tx_conn.execute_script(
                """
                CREATE TABLE plugins (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key VARCHAR(100) NOT NULL UNIQUE,
                    name VARCHAR(255),
                    version VARCHAR(50),
                    description TEXT,
                    author VARCHAR(255),
                    website VARCHAR(2048),
                    github VARCHAR(2048),
                    license VARCHAR(100),
                    manifest TEXT,
                    open_app BOOLEAN NOT NULL DEFAULT 0,
                    supported_exts TEXT,
                    default_bounds TEXT,
                    default_maximized BOOLEAN,
                    icon VARCHAR(2048),
                    loaded_routes TEXT,
                    loaded_processors TEXT,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            print(" -> 新的 `plugins` 表创建成功。")

        except Exception as e:
            print(f" -> 表重建过程出错: {e}")
            raise

    print("从 v1.5.5 到 v1.6.0 的迁移成功完成！")
