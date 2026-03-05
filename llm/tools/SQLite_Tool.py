import re, os
from typing import Any, List, Mapping, Optional, Dict, Tuple
import sqlite3




class SQLiteTool:
    """SQLite数据库操作工具类，支持连接、创建表、增删改查等基础操作"""
    # 默认数据库存储路径（自动创建resource目录）
    DEFAULT_DB_DIR = "../fastapi_chat/databases/sqlite_db"
    os.makedirs(DEFAULT_DB_DIR, exist_ok=True)

    @staticmethod
    def _get_db_path(db_name: str) -> str:
        """获取数据库文件完整路径，自动补全.db后缀"""
        if not db_name.endswith(".db"):
            db_name += ".db"
        return os.path.join(SQLiteTool.DEFAULT_DB_DIR, db_name)

    @staticmethod
    def _connect_db(db_name: str) -> Optional[sqlite3.Connection]:
        """创建数据库连接，若不存在则自动创建数据库文件"""
        try:
            db_path = SQLiteTool._get_db_path(db_name)
            conn = sqlite3.connect(
                db_path,
                check_same_thread=False,  # 允许跨线程操作（适合多线程场景）
                detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES
            )
            # 设置行工厂，使查询结果以字典格式返回（便于阅读）
            conn.row_factory = sqlite3.Row
            return conn
        except sqlite3.Error as e:
            return f"数据库连接失败：{str(e)}"


    @staticmethod
    def list_databases() -> str:
        """
        查看当前已创建的所有SQLite数据库
        无需输入参数，自动扫描默认存储目录（databases/sqlite_db）
        """
        try:
            # 1. 检查数据库存储目录是否存在
            if not os.path.exists(SQLiteTool.DEFAULT_DB_DIR):
                return "📂 当前暂无任何数据库（存储目录未创建）"

            # 2. 扫描目录下所有.db文件（过滤非.db文件）
            db_files = [
                f for f in os.listdir(SQLiteTool.DEFAULT_DB_DIR)
                if f.endswith(".db") and os.path.isfile(os.path.join(SQLiteTool.DEFAULT_DB_DIR, f))
            ]

            if not db_files:
                return "📂 当前暂无已创建的数据库"

            # 3. 格式化输出（显示数据库名+文件路径，支持LLM识别）
            result = ["📂 已创建的数据库列表："]
            for idx, db_file in enumerate(db_files, 1):
                # 提取数据库名（去掉.db后缀）
                db_name = db_file[:-3] if db_file.endswith(".db") else db_file
                db_path = os.path.abspath(os.path.join(SQLiteTool.DEFAULT_DB_DIR, db_file))
                result.append(f"{idx}. 数据库名：{db_name} | 文件路径：{db_path}")

            return "\n".join(result)

        except Exception as e:
            return f"❌ 查看数据库列表失败：{str(e)}"


    @staticmethod
    def connect_database(db_name: str) -> str:
        """
        连接指定SQLite数据库（不存在则创建）
        输入格式：数据库名称（如"user_data"、"sales_db.db"）
        """
        conn_result = SQLiteTool._connect_db(db_name)
        if isinstance(conn_result, str):
            return conn_result  # 返回错误信息

        db_path = SQLiteTool._get_db_path(db_name)
        conn_result.close()  # 连接测试成功后关闭临时连接
        return f"✅ 成功连接/创建数据库\n数据库路径：{db_path}"

    @staticmethod
    def create_table(db_name: str, table_name: str, columns: Dict[str, str]) -> str:
        """
        创建数据库表
        输入格式：db_name=数据库名, table_name=表名, columns=字段字典（如{"id":"INTEGER PRIMARY KEY AUTOINCREMENT", "name":"TEXT NOT NULL"}）
        支持字段类型：INTEGER、TEXT、REAL（浮点）、BLOB（二进制）、NULL
        """
        # 参数合法性校验
        if not table_name or not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', table_name):
            return "❌ 表名不合法：仅支持字母、数字和下划线，且不能以数字开头"
        if not columns:
            return "❌ 字段配置不能为空，请指定至少一个表字段"

        # 构造创建表SQL语句
        columns_str = ", ".join([f"{col} {col_type}" for col, col_type in columns.items()])
        create_sql = f"CREATE TABLE IF NOT EXISTS {table_name} ({columns_str});"

        # 执行SQL
        conn_result = SQLiteTool._connect_db(db_name)
        if isinstance(conn_result, str):
            return conn_result

        try:
            cursor = conn_result.cursor()
            cursor.execute(create_sql)
            conn_result.commit()
            return f"✅ 成功创建表\n数据库：{db_name}\n表名：{table_name}\n字段：{list(columns.keys())}"
        except sqlite3.Error as e:
            return f"❌ 创建表失败：{str(e)}"
        finally:
            conn_result.close()

    @staticmethod
    def insert_data(db_name: str, table_name: str, data: Dict[str, Any]) -> str:
        """
        插入单条数据到表中
        输入格式：db_name=数据库名, table_name=表名, key_data=数据字典（如{"name":"张三", "age":25, "score":92.5}）
        """
        if not data:
            return "❌ 插入数据不能为空"

        # 构造插入数据SQL语句
        cols = ", ".join(data.keys())
        placeholders = ", ".join(["?" for _ in data.values()])
        insert_sql = f"INSERT INTO {table_name} ({cols}) VALUES ({placeholders});"
        values = list(data.values())

        # 执行SQL
        conn_result = SQLiteTool._connect_db(db_name)
        if isinstance(conn_result, str):
            return conn_result

        try:
            cursor = conn_result.cursor()
            cursor.execute(insert_sql, values)
            conn_result.commit()
            return f"✅ 成功插入1条数据\n表名：{table_name}\n插入ID：{cursor.lastrowid}\n数据：{data}"
        except sqlite3.Error as e:
            return f"❌ 插入数据失败：{str(e)}"
        finally:
            conn_result.close()

    @staticmethod
    def query_data(db_name: str, table_name: str,
                   conditions: Optional[Tuple[str, List[Any]]] = None,
                   limit: int = 100) -> str:
        """
        查询表数据
        输入格式：
        - 基础查询：db_name=数据库名, table_name=表名
        - 条件查询：conditions=("age > ? AND score >= ?", [18, 60])
        - 限制条数：limit=50（默认最多返回100条）
        """
        # 构造查询SQL语句
        base_sql = f"SELECT * FROM {table_name}"
        query_sql = base_sql + (" WHERE " + conditions[0] if conditions else "") + f" LIMIT {limit};"
        params = conditions[1] if (conditions and len(conditions) >= 2) else []

        # 执行SQL
        conn_result = SQLiteTool._connect_db(db_name)
        if isinstance(conn_result, str):
            return conn_result

        try:
            cursor = conn_result.cursor()
            cursor.execute(query_sql, params)
            rows = cursor.fetchall()

            if not rows:
                return f"📊 查询结果：{table_name}表中无匹配数据"

            # 格式化查询结果（表头+数据行）
            columns = [desc[0] for desc in cursor.description]
            result = [f"📊 查询结果（共{len(rows)}条，限制{limit}条）", f"表头：{columns}"]
            for idx, row in enumerate(rows, 1):
                row_data = {col: row[col] for col in columns}
                result.append(f"第{idx}行：{row_data}")

            return "\n".join(result)
        except sqlite3.Error as e:
            return f"❌ 查询数据失败：{str(e)}"
        finally:
            conn_result.close()

    @staticmethod
    def delete_data(db_name: str, table_name: str,
                    conditions: Tuple[str, List[Any]]) -> str:
        """
        删除表中数据（需指定条件，防止误删全表）
        输入格式：db_name=数据库名, table_name=表名, conditions=("id = ?", [5]) 或 ("name = ? AND age < ?", ["李四", 20])
        """
        if not conditions or not conditions[0]:
            return "❌ 禁止无条件删除！请指定conditions参数（如\"id = ?\", [1]）"

        # 构造删除SQL语句
        delete_sql = f"DELETE FROM {table_name} WHERE {conditions[0]};"
        params = conditions[1] if len(conditions) >= 2 else []

        # 执行SQL
        conn_result = SQLiteTool._connect_db(db_name)
        if isinstance(conn_result, str):
            return conn_result

        try:
            cursor = conn_result.cursor()
            cursor.execute(delete_sql, params)
            conn_result.commit()
            if cursor.rowcount == 0:
                return f"⚠️  未找到匹配条件的数据，删除条数：0"
            return f"✅ 成功删除{cursor.rowcount}条数据\n条件：{conditions[0]}\n参数：{params}"
        except sqlite3.Error as e:
            return f"❌ 删除数据失败：{str(e)}"
        finally:
            conn_result.close()

    @staticmethod
    def drop_table(db_name: str, table_name: str, confirm: bool = True) -> str:
        """
        删除指定表（谨慎操作！会删除表结构及所有数据）
        输入格式：db_name=数据库名, table_name=表名
        """
        if confirm:
            user_confirm = input("⚠️  确认删除表「{table_name}」？此操作不可恢复！输入'yes'确认：")
            if user_confirm.lower() != "yes":
                return "❌ 已取消删除操作"

        drop_sql = f"DROP TABLE IF EXISTS {table_name};"
        conn_result = SQLiteTool._connect_db(db_name)
        if isinstance(conn_result, str):
            return conn_result

        try:
            cursor = conn_result.cursor()
            cursor.execute(drop_sql)
            conn_result.commit()
            return f"✅ 成功删除表：{table_name}"
        except sqlite3.Error as e:
            return f"❌ 删除表失败：{str(e)}"
        finally:
            conn_result.close()

    @staticmethod
    def update_data(db_name: str, table_name: str,
                    update_data: Dict[str, Any],
                    conditions: Tuple[str, List[Any]]) -> str:
        """
        更新表中已有数据（需指定条件，防止误更新全表）
        输入格式：
        - db_name=数据库名, table_name=表名
        - update_data=更新内容（如{"age":26, "score":98}）
        - conditions=筛选条件（如("id = ?", [3]) 或 ("name = ? AND class = ?", ["张三", "一班"])
        """
        if not update_data:
            return "❌ 更新内容不能为空"
        if not conditions or not conditions[0]:
            return "❌ 禁止无条件更新！请指定conditions参数（如\"id = ?\", [1]）"

        # 构造更新SQL语句（如"UPDATE user SET age=?, score=? WHERE id=?"）
        set_clause = ", ".join([f"{col} = ?" for col in update_data.keys()])
        update_sql = f"UPDATE {table_name} SET {set_clause} WHERE {conditions[0]};"
        # 拼接参数：更新值在前，条件值在后
        params = list(update_data.values()) + conditions[1]

        # 执行SQL
        conn_result = SQLiteTool._connect_db(db_name)
        if isinstance(conn_result, str):
            return conn_result

        try:
            cursor = conn_result.cursor()
            cursor.execute(update_sql, params)
            conn_result.commit()
            if cursor.rowcount == 0:
                return f"⚠️  未找到匹配条件的数据，更新条数：0"
            return f"✅ 成功更新{cursor.rowcount}条数据\n更新内容：{update_data}\n条件：{conditions[0]}\n参数：{conditions[1]}"
        except sqlite3.Error as e:
            return f"❌ 更新数据失败：{str(e)}"
        finally:
            conn_result.close()

    @staticmethod
    def alter_table(db_name: str, table_name: str,
                    operation: str, **kwargs) -> str:
        """
        修改表结构（SQLite支持有限，仅实现常用功能）
        支持操作：
        1. 新增字段：operation="add_column", col_name=字段名, col_type=字段类型（如{"col_name":"email", "col_type":"TEXT"}）
        2. 重命名表：operation="rename_table", new_table_name=新表名
        输入格式示例：
        - 新增字段：alter_table("user_db", "user", "add_column", col_name="phone", col_type="TEXT")
        - 重命名表：alter_table("user_db", "user", "rename_table", new_table_name="user_info")
        """
        conn_result = SQLiteTool._connect_db(db_name)
        if isinstance(conn_result, str):
            return conn_result

        try:
            cursor = conn_result.cursor()
            if operation == "add_column":
                # 1. 新增字段（需指定字段名和类型）
                col_name = kwargs.get("col_name")
                col_type = kwargs.get("col_type")
                if not col_name or not col_type:
                    return "❌ 新增字段需指定col_name（字段名）和col_type（字段类型，如TEXT/INTEGER）"
                if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', col_name):
                    return "❌ 字段名不合法：仅支持字母、数字和下划线，且不能以数字开头"

                alter_sql = f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type};"
                cursor.execute(alter_sql)
                conn_result.commit()
                return f"✅ 成功为表「{table_name}」新增字段：{col_name}（类型：{col_type}）"

            elif operation == "rename_table":
                # 2. 重命名表（需指定新表名）
                new_table_name = kwargs.get("new_table_name")
                if not new_table_name or not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', new_table_name):
                    return "❌ 新表名不合法：仅支持字母、数字和下划线，且不能以数字开头"

                alter_sql = f"ALTER TABLE {table_name} RENAME TO {new_table_name};"
                cursor.execute(alter_sql)
                conn_result.commit()
                return f"✅ 成功将表「{table_name}」重命名为「{new_table_name}」"

            else:
                # 提示不支持的操作（SQLite限制）
                return f"❌ 不支持该ALTER操作！SQLite仅支持：\n1. add_column（新增字段）\n2. rename_table（重命名表）\n不支持删除/修改现有字段"

        except sqlite3.Error as e:
            return f"❌ 修改表结构失败：{str(e)}"
        finally:
            conn_result.close()

    @staticmethod
    def execute_sql(db_name: str, sql: str) -> str:
        """
        直接执行原生SQL语句（支持所有SQLite语法）
        输入格式：db_name=数据库名, sql=完整SQL语句（如"SELECT * FROM user WHERE age > 18;"）
        安全提示：避免执行DROP TABLE、DELETE等危险操作，除非确认无误
        """
        # 基础安全检查（拦截高风险操作，可根据需求调整）
        dangerous_commands = ['drop table', 'drop database', 'delete from', 'truncate', 'alter table']
        sql_lower = sql.lower()
        for cmd in dangerous_commands:
            if cmd in sql_lower and 'where' not in sql_lower and cmd != 'alter table':
                return f"❌ 禁止执行无WHERE条件的危险操作：{cmd}\n如需执行，请手动确认并添加WHERE条件"

        # 连接数据库并执行SQL
        conn_result = SQLiteTool._connect_db(db_name)
        if isinstance(conn_result, str):
            return conn_result

        try:
            cursor = conn_result.cursor()
            # 执行SQL（支持查询/插入/更新/删除等所有操作）
            cursor.execute(sql)
            conn_result.commit()

            # 区分查询类和非查询类语句
            if sql_lower.startswith(('select', 'pragma', 'show', 'desc')):
                # 查询类：返回结果集
                rows = cursor.fetchall()
                if not rows:
                    return f"📊 SQL执行成功（查询无结果）\n执行语句：{sql}"

                columns = [desc[0] for desc in cursor.description]
                result = [f"📊 SQL执行成功（返回{len(rows)}条结果）", f"表头：{columns}"]
                for idx, row in enumerate(rows, 1):
                    row_data = {col: row[col] for col in columns}
                    result.append(f"第{idx}行：{row_data}")
                return "\n".join(result)
            else:
                # 非查询类（插入/更新/删除等）：返回影响行数
                return f"✅ SQL执行成功\n执行语句：{sql}\n影响行数：{cursor.rowcount}"

        except sqlite3.Error as e:
            return f"❌ SQL执行失败：{str(e)}\n错误语句：{sql}"
        finally:
            conn_result.close()

    @staticmethod
    def handle_db_command(user_input: str) -> str:
        """
        统一处理数据库操作命令（适配LLM自然语言输入）
        支持命令格式及示例：
        1. 连接/创建数据库：connect db [数据库名]
           - 示例："connect db user_info"（不存在则自动创建）
        2. 创建表：create table [数据库名].[表名] 字段1:类型1,字段2:类型2,...
           - 示例："create table user_info.student id:INTEGER PRIMARY KEY AUTOINCREMENT,name:TEXT NOT NULL,age:INTEGER,score:REAL"
        3. 插入数据：insert into [数据库名].[表名] 字段1=值1,字段2=值2,...
           - 示例："insert into user_info.student name=张三,age=20,score=92.5"
        4. 查询数据：select from [数据库名].[表名] [可选条件]
           - 示例1（无条件）："select from user_info.student"
           - 示例2（有条件）："select from user_info.student age>18 and score>=90"
        5. 更新数据：update [数据库名].[表名] 字段1=值1,字段2=值2,... where 条件
           - 示例："update user_info.student age=21,score=95 where id=1"
        6. 删除数据：delete from [数据库名].[表名] 条件
           - 示例："delete from user_info.student id=3"
        7. 修改表结构（SQLite支持有限）：
           - 新增字段：alter table [数据库名].[表名] add column 字段名:类型
             示例："alter table user_info.student add column phone:TEXT"
           - 重命名表：alter table [数据库名].[表名] rename to 新表名
             示例："alter table user_info.student rename to user_info.student_v2"
        8. 删除表（谨慎！不可恢复）：drop table [数据库名].[表名]
           - 示例："drop table user_info.student_v2"（执行时需手动输入yes确认）
        9. 执行原生SQL（支持复杂操作）：execute sql [数据库名] [完整SQL语句]
           - 示例1（查询）："execute sql user_info SELECT name,score FROM student WHERE age<=22;"
           - 示例2（插入）："execute sql user_info INSERT INTO student(name,age) VALUES('李四',19);"
        10. 查看所有数据库：list databases 或 查看数据库列表
           - 示例："list databases" 或 "查看数据库"
        注意事项：
        - 更新/删除数据必须带条件（防止误操作全表），无WHERE条件会被拦截
        - 字段/表名仅支持字母、数字、下划线，且不能以数字开头
        - SQLite不支持删除/修改已存在的字段，仅支持新增字段和重命名表
        """
        user_input = user_input.strip().lower()

        # 1. 连接数据库
        if user_input.startswith("connect db "):
            db_name = user_input.replace("connect db ", "").strip()
            return SQLiteTool.connect_database(db_name)

        # 2. 创建表（匹配：create table 库.表 字段1:类型1,字段2:类型2）
        create_match = re.match(r'create table (\w+)\.(\w+) (.+)', user_input)
        if create_match:
            db_name, table_name, cols_str = create_match.groups()
            cols = {}
            for col_item in cols_str.split(","):
                if ":" not in col_item:
                    return f"❌ 字段格式错误：{col_item}（正确格式：字段名:类型，如name:TEXT）"
                col, col_type = col_item.strip().split(":", 1)
                cols[col.strip()] = col_type.strip()
            return SQLiteTool.create_table(db_name, table_name, cols)

        # 3. 插入数据（匹配：insert into 库.表 字段1=值1,字段2=值2）
        insert_match = re.match(r'insert into (\w+)\.(\w+) (.+)', user_input)
        if insert_match:
            db_name, table_name, data_str = insert_match.groups()
            data = {}
            for data_item in data_str.split(","):
                if "=" not in data_item:
                    return f"❌ 数据格式错误：{data_item}（正确格式：字段名=值，如name=张三）"
                key, val = data_item.strip().split("=", 1)
                key = key.strip()
                val = val.strip()
                # 自动转换值类型（数字→int/float，其他→str）
                if val.isdigit():
                    val = int(val)
                elif re.match(r'^\d+\.\d+$', val):
                    val = float(val)
                data[key] = val
            return SQLiteTool.insert_data(db_name, table_name, data)

        # 4. 查询数据（匹配：select from 库.表 [条件]）
        select_match = re.match(r'select from (\w+)\.(\w+)( .*)?', user_input)
        if select_match:
            db_name, table_name, condition_str = select_match.groups()
            conditions = None
            if condition_str and condition_str.strip():
                cond = condition_str.strip()
                params = re.findall(r'\d+', cond)
                params = [int(p) if p.isdigit() else p for p in params]
                cond_sql = re.sub(r'\d+', '?', cond)
                conditions = (cond_sql, params)
            return SQLiteTool.query_data(db_name, table_name, conditions)

        # 5. 更新数据（匹配：update 库.表 字段1=值1... where 条件）
        update_match = re.match(r'update (\w+)\.(\w+) (.+) where (.+)', user_input)
        if update_match:
            db_name, table_name, data_str, cond_str = update_match.groups()
            # 解析更新数据
            update_data = {}
            for data_item in data_str.split(","):
                if "=" not in data_item:
                    return f"❌ 数据格式错误：{data_item}（正确格式：字段名=值，如age=21）"
                key, val = data_item.strip().split("=", 1)
                key = key.strip()
                val = val.strip()
                if val.isdigit():
                    val = int(val)
                elif re.match(r'^\d+\.\d+$', val):
                    val = float(val)
                update_data[key] = val
            # 解析条件
            cond = cond_str.strip()
            params = re.findall(r'\d+', cond)
            params = [int(p) if p.isdigit() else p for p in params]
            cond_sql = re.sub(r'\d+', '?', cond)
            conditions = (cond_sql, params)
            return SQLiteTool.update_data(db_name, table_name, update_data, conditions)

        # 6. 删除数据（匹配：delete from 库.表 条件）
        delete_match = re.match(r'delete from (\w+)\.(\w+) (.+)', user_input)
        if delete_match:
            db_name, table_name, cond_str = delete_match.groups()
            cond = cond_str.strip()
            params = re.findall(r'\d+', cond)
            params = [int(p) if p.isdigit() else p for p in params]
            cond_sql = re.sub(r'\d+', '?', cond)
            conditions = (cond_sql, params)
            return SQLiteTool.delete_data(db_name, table_name, conditions)

        # 7. 修改表结构（新增字段/重命名表）
        # 7.1 新增字段（匹配：alter table 库.表 add column 字段:类型）
        alter_add_match = re.match(r'alter table (\w+)\.(\w+) add column (\w+):(\w+)', user_input)
        if alter_add_match:
            db_name, table_name, col_name, col_type = alter_add_match.groups()
            return SQLiteTool.alter_table(db_name, table_name, "add_column", col_name=col_name, col_type=col_type)
        # 7.2 重命名表（匹配：alter table 库.表 rename to 新表名）
        alter_rename_match = re.match(r'alter table (\w+)\.(\w+) rename to (\w+)', user_input)
        if alter_rename_match:
            db_name, table_name, new_table_name = alter_rename_match.groups()
            return SQLiteTool.alter_table(db_name, table_name, "rename_table", new_table_name=new_table_name)

        # 8. 删除表（匹配：drop table 库.表）
        drop_match = re.match(r'drop table (\w+)\.(\w+)', user_input)
        if drop_match:
            db_name, table_name = drop_match.groups()
            return SQLiteTool.drop_table(db_name, table_name)

        # 9. 执行原生SQL（匹配：execute sql 库名 SQL语句）
        execute_match = re.match(r'execute sql (\w+) (.+)', user_input)
        if execute_match:
            db_name, sql = execute_match.groups()
            # 补全SQL结尾分号（避免语法错误）
            if not sql.strip().endswith(';'):
                sql += ';'
            return SQLiteTool.execute_sql(db_name, sql)

        # 10. 查看所有数据库（格式：list databases 或 查看数据库列表）
        if user_input in ["list databases", "查看数据库", "查看数据库列表"]:
            return SQLiteTool.list_databases()

        # 未匹配任何命令
        return f"❌ 未识别到有效命令！请参考以下支持格式：\n{SQLiteTool.handle_db_command.__doc__}"