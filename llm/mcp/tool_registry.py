"""
工具注册表：统一管理所有工具的元信息（名称、函数、描述）
作用：
1. 避免工具信息硬编码在Agent配置中
2. 支持动态注册/卸载工具
3. 统一工具描述，让Agent调用更精准
"""
from typing import Callable, Optional, Dict, Tuple

# 工具注册表类型定义：工具名称 → (工具函数, 工具描述)
ToolRegistryType = Dict[str, Tuple[Optional[Callable], str]]

# 初始化空的工具注册表
TOOL_REGISTRY: ToolRegistryType = {}


# -------------------------- 注册内置工具 --------------------------
def register_builtin_tools():
    """注册项目中已有的内置工具"""
    try:
        # 延迟导入，避免循环导入问题
        from llm.tools import CalculatorTool, WeatherTool, SQLiteTool

        # 注册计算器工具
        TOOL_REGISTRY["Calculator"] = (
            CalculatorTool.calculate,
            "用于计算数学表达式。支持数字/中文数字（一、二、三...）和+、-、*、/、()运算符（加、减、乘、除也可），输入如'3+5*2'、'(15+3)*4'、'三加二乘五'的表达式"
        )

        # 注册天气工具
        TOOL_REGISTRY["Weather"] = (
            WeatherTool.get_weather,
            "用于查询城市的实时天气信息。输入应为城市名称，如'北京'、'上海'"
        )

        # 注册SQLite工具
        TOOL_REGISTRY["SQLiteDatabase"] = (
            SQLiteTool.handle_db_command,
            """
            SQLite数据库操作工具，支持以下功能：
            1. 连接/创建数据库：输入"connect db [数据库名]"（如"connect db user_info"）
            2. 创建表：输入"create table [库名].[表名] 字段1:类型1,字段2:类型2"（如"create table user_info.user id:INTEGER PRIMARY KEY,name:TEXT NOT NULL"）
            3. 插入数据：输入"insert into [库名].[表名] 字段1=值1,字段2=值2"（如"insert into user_info.user name=张三,age=28"）
            4. 查询数据：输入"select from [库名].[表名] [条件]"（如"select from user_info.user age>18"或"select from user_info.user"）
            5. 更新数据：输入"update [库名].[表名] 字段1=值1,字段2=值2 where 条件"（如"update user_info.user age=29,score=95 where id=1"）
            6. 删除数据：输入"delete from [库名].[表名] 条件"（如"delete from user_info.user id=3"）
            7. 修改表结构：①新增字段："alter table [库名].[表名] add column 字段名:类型"（如"alter table user_info.user add column phone:TEXT"）；②重命名表："alter table [库名].[表名] rename to 新表名"（如"alter table user_info.user rename to user_info_v2"）
            8. 删除表：输入"drop table [库名].[表名]"（如"drop table user_info.user"）
            注意：①更新/删除数据需指定条件；②删除表会触发二次确认；③SQLite不支持删除/修改现有字段
            9. 执行原生SQL：execute sql [数据库名] SQL语句（如"execute sql user_info SELECT name,age FROM user WHERE score>90;"）
            10. 查看所有数据库：list databases 或 查看数据库列表
            """
        )

        # 注册Reminder工具（先占位，函数后续动态绑定）
        # TOOL_REGISTRY["Reminder"] = (
        #     None,
        #     """
        #     定时提醒管理，支持3类命令：
        #     1. 设置提醒：输入含"时间+内容"（如"明天9点开会"、"30分钟后喝水"、"每周五交周报"）
        #     2. 查询提醒：输入"list"或"查看提醒"
        #     3. 删除提醒：输入"delete+ID"或"删除提醒ID"（如"delete 1"，ID通过list查询）
        #     调用要求：必须完整传递用户原始输入，包含时间和内容，不可省略！
        #     """
        # )

    except ImportError as e:
        raise ImportError(f"注册内置工具失败：{str(e)}，请检查tools目录下的文件是否存在")


# -------------------------- 工具注册/获取方法 --------------------------
def register_tool(tool_name: str, tool_func: Callable, description: str):
    """
    动态注册新工具
    :param tool_name: 工具名称（唯一）
    :param tool_func: 工具执行函数
    :param description: 工具描述（给Agent看）
    """
    if tool_name in TOOL_REGISTRY:
        print(f"警告：工具 {tool_name} 已存在，将覆盖原有配置")
    TOOL_REGISTRY[tool_name] = (tool_func, description)


def unregister_tool(tool_name: str):
    """卸载指定工具"""
    if tool_name in TOOL_REGISTRY:
        del TOOL_REGISTRY[tool_name]


def get_tool(tool_name: str) -> Tuple[Optional[Callable], str]:
    """
    获取工具函数和描述
    :param tool_name: 工具名称
    :return: (工具函数, 工具描述)，未找到则返回 (None, "")
    """
    return TOOL_REGISTRY.get(tool_name, (None, ""))


def list_all_tools() -> list:
    """列出所有已注册的工具名称"""
    return list(TOOL_REGISTRY.keys())


# 初始化：注册所有内置工具
register_builtin_tools()