from tortoise import transactions


async def _table_exists(tx_conn, table: str) -> bool:
    rows = await tx_conn.execute_query_dict(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        [table],
    )
    return bool(rows)


async def _column_exists(tx_conn, table: str, column: str) -> bool:
    rows = await tx_conn.execute_query_dict(f"PRAGMA table_info('{table}')")
    return any(row.get("name") == column for row in rows)


async def _add_column(tx_conn, table: str, column: str, ddl: str) -> None:
    if await _column_exists(tx_conn, table, column):
        print(f" -> 列 `{table}.{column}` 已存在，跳过。")
        return
    await tx_conn.execute_script(f'ALTER TABLE "{table}" ADD COLUMN {ddl};')
    print(f" -> 列 `{table}.{column}` 添加成功。")


async def run_migration():
    """
    v1.7.4 -> v2.0.0

    主要变更：新增多用户权限系统
    - user 表新增字段：is_admin, created_by_id, created_at, last_login
    - 新增表：roles, user_roles, role_permissions, path_rules
    - 初始化内置角色（Admin/User/Viewer），并为 Admin/Viewer 预置权限与路径规则
    - 将旧用户全部设置为管理员，并绑定 Admin 角色
    """
    async with transactions.in_transaction() as tx_conn:
        if not await _table_exists(tx_conn, "user"):
            print("未找到 `user` 表，跳过迁移。")
            return

        print("找到 `user` 表。开始迁移字段...")

        await _add_column(tx_conn, "user", "is_admin", "is_admin BOOLEAN NOT NULL DEFAULT 0")
        await _add_column(tx_conn, "user", "created_by_id", "created_by_id INT")
        if not await _column_exists(tx_conn, "user", "created_at"):
            try:
                await tx_conn.execute_script(
                    'ALTER TABLE "user" ADD COLUMN created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;'
                )
                print(" -> 列 `user.created_at` 添加成功。")
            except Exception:
                # SQLite 部分版本不允许 ALTER TABLE 添加非“常量默认值”的列
                await tx_conn.execute_script(
                    'ALTER TABLE "user" ADD COLUMN created_at TIMESTAMP;'
                )
                print(" -> 列 `user.created_at` 添加成功（无默认值）。")
        await _add_column(tx_conn, "user", "last_login", "last_login TIMESTAMP")

        # 兜底：确保旧数据 created_at 有值（避免接口序列化失败）
        await tx_conn.execute_query('UPDATE "user" SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL')

        print("开始创建权限相关表...")
        await tx_conn.execute_script(
            """
            CREATE TABLE IF NOT EXISTS roles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name VARCHAR(50) NOT NULL UNIQUE,
                description VARCHAR(255),
                is_system BOOLEAN NOT NULL DEFAULT 0,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS user_roles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INT NOT NULL REFERENCES "user" ("id") ON DELETE CASCADE,
                role_id INT NOT NULL REFERENCES roles ("id") ON DELETE CASCADE,
                UNIQUE (user_id, role_id)
            );

            CREATE TABLE IF NOT EXISTS role_permissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role_id INT NOT NULL REFERENCES roles ("id") ON DELETE CASCADE,
                permission_code VARCHAR(50) NOT NULL,
                UNIQUE (role_id, permission_code)
            );

            CREATE TABLE IF NOT EXISTS path_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role_id INT NOT NULL REFERENCES roles ("id") ON DELETE CASCADE,
                path_pattern VARCHAR(512) NOT NULL,
                is_regex BOOLEAN NOT NULL DEFAULT 0,
                can_read BOOLEAN NOT NULL DEFAULT 1,
                can_write BOOLEAN NOT NULL DEFAULT 0,
                can_delete BOOLEAN NOT NULL DEFAULT 0,
                can_share BOOLEAN NOT NULL DEFAULT 0,
                priority INT NOT NULL DEFAULT 0,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        print(" -> 权限相关表创建完成。")

        from domain.permission.types import PERMISSION_DEFINITIONS
        from domain.role.types import SystemRoles

        system_roles = [
            {
                "name": SystemRoles.ADMIN,
                "description": "管理员角色，拥有所有系统和适配器权限",
                "is_system": 1,
            },
            {
                "name": SystemRoles.USER,
                "description": "普通用户角色，需要管理员配置路径权限",
                "is_system": 1,
            },
            {
                "name": SystemRoles.VIEWER,
                "description": "只读用户角色，仅可查看文件",
                "is_system": 1,
            },
        ]

        print("开始初始化内置角色...")
        for role_data in system_roles:
            await tx_conn.execute_query(
                "INSERT OR IGNORE INTO roles (name, description, is_system) VALUES (?, ?, ?)",
                [role_data["name"], role_data["description"], role_data["is_system"]],
            )
        print(" -> 内置角色初始化完成。")

        role_rows = await tx_conn.execute_query_dict(
            "SELECT id, name FROM roles WHERE name IN (?, ?, ?)",
            [SystemRoles.ADMIN, SystemRoles.USER, SystemRoles.VIEWER],
        )
        role_id_by_name = {row["name"]: row["id"] for row in role_rows}
        admin_role_id = role_id_by_name.get(SystemRoles.ADMIN)
        user_role_id = role_id_by_name.get(SystemRoles.USER)
        viewer_role_id = role_id_by_name.get(SystemRoles.VIEWER)

        if admin_role_id:
            print("开始为 Admin 角色写入系统权限...")
            all_codes = [item["code"] for item in PERMISSION_DEFINITIONS]
            for code in all_codes:
                await tx_conn.execute_query(
                    "INSERT OR IGNORE INTO role_permissions (role_id, permission_code) VALUES (?, ?)",
                    [admin_role_id, code],
                )
            print(f" -> Admin 权限写入完成，共 {len(all_codes)} 条。")

            # Admin 全路径全操作
            exists = await tx_conn.execute_query_dict(
                "SELECT 1 FROM path_rules WHERE role_id=? AND path_pattern=? AND is_regex=? LIMIT 1",
                [admin_role_id, "/**", 0],
            )
            if not exists:
                await tx_conn.execute_query(
                    """
                    INSERT INTO path_rules
                    (role_id, path_pattern, is_regex, can_read, can_write, can_delete, can_share, priority)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [admin_role_id, "/**", 0, 1, 1, 1, 1, 100],
                )
                print(" -> Admin 路径规则 `/**` 初始化完成。")

        if viewer_role_id:
            # Viewer 全路径只读（可按需在 UI 中改成更细粒度）
            exists = await tx_conn.execute_query_dict(
                "SELECT 1 FROM path_rules WHERE role_id=? AND path_pattern=? AND is_regex=? LIMIT 1",
                [viewer_role_id, "/**", 0],
            )
            if not exists:
                await tx_conn.execute_query(
                    """
                    INSERT INTO path_rules
                    (role_id, path_pattern, is_regex, can_read, can_write, can_delete, can_share, priority)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [viewer_role_id, "/**", 0, 1, 0, 0, 0, 0],
                )
                print(" -> Viewer 路径规则 `/**`（只读）初始化完成。")

        print("开始绑定旧用户权限...")
        await tx_conn.execute_query('UPDATE "user" SET is_admin = 1 WHERE is_admin IS NULL OR is_admin != 1')
        print(" -> 所有旧用户已设置为管理员（is_admin=1）。")

        if admin_role_id:
            user_rows = await tx_conn.execute_query_dict('SELECT id FROM "user"')
            for row in user_rows:
                await tx_conn.execute_query(
                    "INSERT OR IGNORE INTO user_roles (user_id, role_id) VALUES (?, ?)",
                    [row["id"], admin_role_id],
                )
            print(f" -> 已为 {len(user_rows)} 个用户绑定 Admin 角色。")

        # 设置默认注册角色（便于后续开启开放注册）
        if user_role_id and await _table_exists(tx_conn, "configurations"):
            existing = await tx_conn.execute_query_dict(
                "SELECT value FROM configurations WHERE key=? LIMIT 1",
                ["AUTH_DEFAULT_REGISTER_ROLE_ID"],
            )
            if not existing or not str(existing[0].get("value") or "").strip():
                await tx_conn.execute_query(
                    "INSERT OR REPLACE INTO configurations (key, value) VALUES (?, ?)",
                    ["AUTH_DEFAULT_REGISTER_ROLE_ID", str(user_role_id)],
                )
                print(f" -> 已设置默认注册角色 AUTH_DEFAULT_REGISTER_ROLE_ID={user_role_id}。")

    print("从 v1.7.4 到 v2.0.0 的迁移成功完成！")
