import json

from tortoise import transactions


async def run_migration():
    """
    v1.7.1 -> v1.7.2

    AutomationTask table change:
    - remove columns: path_pattern, filename_regex
    - add column: trigger_config
    - migrate old data into trigger_config
    """
    async with transactions.in_transaction() as tx_conn:
        try:
            await tx_conn.execute_query_dict("SELECT 1 FROM automation_tasks LIMIT 1")
            print("Found `automation_tasks` table. Starting migration...")
        except Exception:
            print("`automation_tasks` table not found. Skip migration.")
            return

        try:
            await tx_conn.execute_script(
                """
                DROP TABLE IF EXISTS automation_tasks_new;
                CREATE TABLE automation_tasks_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name VARCHAR(100) NOT NULL,
                    event VARCHAR(50) NOT NULL,
                    trigger_config TEXT,
                    processor_type VARCHAR(100) NOT NULL,
                    processor_config TEXT NOT NULL,
                    enabled BOOLEAN NOT NULL DEFAULT 1
                );
                """
            )
            print(" -> New `automation_tasks_new` table created.")
        except Exception as e:
            print(f" -> Failed to create new table: {e}")
            raise

        rows = await tx_conn.execute_query_dict(
            """
            SELECT id, name, event, path_pattern, filename_regex,
                   processor_type, processor_config, enabled
            FROM automation_tasks
            """
        )

        if not rows:
            print(" -> No rows found, skipping data migration.")
        else:
            print(f" -> Migrating {len(rows)} rows.")
            for row in rows:
                trigger_config = {}
                path_pattern = row.get("path_pattern")
                filename_regex = row.get("filename_regex")
                if path_pattern:
                    trigger_config["path_prefix"] = path_pattern
                if filename_regex:
                    trigger_config["filename_regex"] = filename_regex
                trigger_config_value = json.dumps(trigger_config) if trigger_config else None

                await tx_conn.execute_query(
                    """
                    INSERT INTO automation_tasks_new
                    (id, name, event, trigger_config, processor_type, processor_config, enabled)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    """,
                    [
                        row.get("id"),
                        row.get("name"),
                        row.get("event"),
                        trigger_config_value,
                        row.get("processor_type"),
                        row.get("processor_config"),
                        row.get("enabled"),
                    ],
                )
            print(" -> Data migration completed.")

        try:
            await tx_conn.execute_script(
                """
                DROP TABLE automation_tasks;
                ALTER TABLE automation_tasks_new RENAME TO automation_tasks;
                """
            )
            print(" -> Table swap completed.")
        except Exception as e:
            print(f" -> Failed to swap tables: {e}")
            raise

    print("Migration from v1.7.1 to v1.7.2 completed.")
