import requests, re, json, datetime, os, calendar
from typing import Any, List, Mapping, Optional, Dict, Tuple
from datetime import datetime, timedelta
import sqlite3
from langchain.llms.base import LLM
import asyncio



class ReminderTool:
    """基于SQLite数据库和LLM解析的提醒管理工具（支持多场景提醒）"""

    # 数据库配置
    DB_NAME = "../fastapi_chat/databases/sqlite_db/reminder_db"
    TABLE_NAME = "wechat_reminders"

    # 重复类型映射（数字→中文，与数据库字段对应）
    REPEAT_TYPE_MAP = {
        0: "无",
        1: "每日",
        2: "每周",
        3: "每月",
        4: "自定义天数"
    }


    def __init__(self, llm: Optional[LLM] = None):
        """初始化工具，可传入LLM实例用于自然语言解析"""
        self.llm = llm
        self._init_database()  # 初始化数据库表结构

    def _init_database(self) -> None:
        """初始化数据库和表结构（确保字段完整）"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            create_table_sql = f"""
            CREATE TABLE IF NOT EXISTS {self.TABLE_NAME} (
                reminder_id INTEGER PRIMARY KEY AUTOINCREMENT,
                reminder_content TEXT NOT NULL,       -- 提醒内容
                remind_time DATETIME NOT NULL,        -- 下次提醒时间
                is_repeat TINYINT NOT NULL DEFAULT 0, -- 是否重复（1=是，0=否）
                repeat_type TINYINT DEFAULT 0,        -- 重复类型（对应REPEAT_TYPE_MAP）
                repeat_interval INT DEFAULT 1,        -- 重复间隔（如每周→间隔1，每2周→间隔2）
                repeat_end_time DATETIME,             -- 重复结束时间（默认1年后）
                remind_type TINYINT NOT NULL DEFAULT 0,-- 提醒类型（预留）
                group_name TEXT,                      -- 群聊名称（预留）
                registrant_name TEXT NOT NULL,        -- 登记人
                register_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, -- 登记时间
                is_triggered TINYINT NOT NULL DEFAULT 0, -- 是否触发过（单次提醒用）
                last_trigger_time DATETIME,           -- 最后触发时间
                is_completed TINYINT NOT NULL DEFAULT 0, -- 是否完成（停止重复）
                remark TEXT                           -- 备注
            )
            """
            cursor.execute(create_table_sql)
            conn.commit()
        except sqlite3.Error as e:
            print(f"数据库初始化失败: {e}")
        finally:
            conn.close()

    def _get_connection(self) -> sqlite3.Connection:
        """获取数据库连接（返回字典格式结果）"""
        try:
            conn = sqlite3.connect(f"{self.DB_NAME}.db", check_same_thread=False)
            conn.row_factory = sqlite3.Row  # 使查询结果可按字段名访问
            return conn
        except sqlite3.Error as e:
            raise Exception(f"数据库连接失败: {e}")

    async def parse_with_llm(self, user_input: str) -> Optional[Dict]:
        """使用LLM解析自然语言输入为结构化数据（优先LLM，失败回退正则）"""
        # 星期映射（中文→数字，用于解析“周三”“周五”等）
        weekday_map = {
            "周一": 0, "周二": 1, "周三": 2, "周四": 3,
            "周五": 4, "周六": 5, "周日": 6
        }
        reverse_weekday_map = {v: k for k, v in weekday_map.items()}
        now = datetime.now()
        weekday_num = now.weekday()
        chinese_weekday = reverse_weekday_map[weekday_num]

        if not self.llm:
            return self._parse_with_regex(user_input)

        # 优化Prompt：明确要求解析所有场景
        prompt = f"""
        请严格按照以下规则解析中文提醒语句，输出JSON格式（仅返回JSON，无其他内容，字段顺序无关）：
        ### 一、必须输出的字段（共9个，适配数据库表结构）
        | 字段名           | 类型       | 规则说明（必须严格遵守）                                                                                                                                                                                                 |
        |------------------|------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
        | content          | 字符串     | 提醒核心内容，**必须去除所有时间描述、周期词、群名、备注**（如“写周报”“项目会”，禁止含“每周三”“产品群”等信息）                                                                                                          |
        | time             | 字符串     | 首次提醒时间，绝对时间格式：`YYYY-MM-DD HH:MM:SS`（含秒，秒填00），必须是当前时间之后的最早可能时间；相对时间（如“30分钟后”）需转换为绝对时间                                                                             |
        | is_repeat        | 布尔值     | 是否为周期提醒：含“每周”“每月”“每日”“每X天”则为true，否则为false                                                                                                                                                        |
        | repeat_type      | 整数       | 仅is_repeat=true时有效，否则填0：<br>- 每日/每天 → 1<br>- 每周 → 2<br>- 每月 → 3<br>- 每X天（自定义天数） → 4<br>- 非周期 → 0                                                                                            |
        | repeat_interval  | 整数       | 仅is_repeat=true时有效，默认填1：<br>- 每日/每周/每月 → 填1（默认）<br>- 每2周/每3天 → 填对应数字（如每2周填2，每3天填3）                                                                                                  |
        | repeat_end_time  | 字符串     | 仅is_repeat=true时需解析，否则填null：<br>- 若输入含“到XX时间截止”“持续到XX”（如“到2025年12月31日”），转换为`YYYY-MM-DD 23:59:59`格式<br>- 若无结束时间，填null（表示无限循环，需谨慎）                                                                 |
        | remind_type      | 整数       | 区分提醒类型，默认填0：<br>- 输入含“群”“群聊”“@全体”“@all”等词（如“产品部群提醒”） → 填1（群提醒）<br>- 无群相关描述 → 填0（个人提醒）                                                                                          |
        | group_name       | 字符串     | 仅remind_type=1时需解析，否则填null：<br>- 提取群聊名称（如“产品部沟通群”“测试1群”），若未明确群名（仅提“群提醒”），填“未知群聊”                                                                                          |
        | registrant_name  | 字符串     | 固定填“用户”（无需解析，直接赋值）                                                                                                                                                                                        |
        | remark           | 字符串     | 提取输入中的附加备注信息（如会议ID、地点、参与人等），若无备注则填null：<br>- 示例：输入“每周三10点项目会，腾讯会议ID：123” → remark填“腾讯会议ID：123”<br>- 仅提取非核心内容、非时间/群名的信息                                                                 |


        ### 二、输入信息（强化日期-星期唯一性）
        - 待解析提醒语句：{user_input}
        - 当前时间：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}（⚠️ 唯一基准：{datetime.now().strftime("%Y-%m-%d")} 这一天的星期固定为 {chinese_weekday}，禁止参考任何其他日期-星期对应关系）
        - 星期数字映射（强制使用）：周一=0，周二=1，周三=2，周四=3，周五=4，周六=5，周日=6

        ### 三、输出要求
        1. 仅返回JSON字符串，无任何多余内容（包括注释、空格、换行说明）；
        2. 字段严格对应上述10个，不新增、不遗漏；
        3. 布尔值用true/false（小写），整数不带引号，null不省略；
        4. 计算“time”时，必须先参考“输入信息”中的“日期-星期对应关系”，再按示例步骤计算，禁止自行假设日期与星期的对应。
        """

        try:
            response = await self.llm.ainvoke(prompt)
            # 提取并清理JSON
            json_str = response.strip().strip('`').replace('json', '', 1).strip()
            parsed = json.loads(json_str)
            # 补全默认值
            # 补全默认值（确保字段完整、类型与业务/数据库一致）
            # 1. 核心内容字段（若LLM漏返回，用合理默认值，避免空值）
            parsed.setdefault("content", "未指定提醒内容")  # 核心字段，避免空字符串

            # 2. 时间字段（time是核心，若缺失需兜底，但LLM通常不会漏，此处防极端情况）
            parsed.setdefault("time", (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"))

            # 3. 周期相关字段（类型与数据库一致：整数/布尔/None）
            parsed.setdefault("is_repeat", False)  # 布尔值，默认非周期
            parsed.setdefault("repeat_type", 0)  # 整数：0=非周期（与数据库映射一致），原"none"错误
            parsed.setdefault("repeat_interval", 1)  # 整数，默认间隔1
            parsed.setdefault("repeat_end_time", None)  # None=数据库NULL，原"none"错误

            # 4. 提醒对象字段（贴合表结构默认值）
            parsed.setdefault("remind_type", 0)  # 整数：0=个人提醒（默认），1=群提醒
            parsed.setdefault("group_name", None)  # None=数据库NULL（群提醒时才填）

            # 5. 登记人与备注字段
            parsed.setdefault("registrant_name", "用户")  # 字符串，默认“用户”
            parsed.setdefault("remark", None)  # None=数据库NULL（无备注时填）
            print(f"[LLM解析结果] user_input: {user_input}, parsed: {parsed}")
            return parsed
        except Exception as e:
            print(f"LLM解析失败，使用正则回退: {e}")
            return self._parse_with_regex(user_input)

    def _parse_with_regex(self, user_input: str) -> Dict:
        """解析提醒信息的主方法（内部嵌套所有解析逻辑）"""

        # 嵌套内部函数：复用原ReminderParser的解析逻辑
        def parse_reminder(input_str: str) -> Dict:
            now = datetime.now()
            # 初始化返回结果结构
            result = {
                "content": "默认提醒",
                "time": (now + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"),
                "is_repeat": False,
                "repeat_type": 0,
                "repeat_interval": 1,
                "repeat_end_time": None,
                "remind_type": 0,
                "group_name": None,
                "registrant_name": "用户",
                "remark": None
            }

            patterns = [
                # 1. 提醒+周几+时间格式（如"提醒周二10点10分吃饭"）
                {
                    "pattern": r'提醒(?:我|我们)?周([一二三四五六日])\s*(\d{1,2})[:点](\d{2})?分?\s*(.+)',
                    "handler": _handle_remind_weekday
                },
                # 2. 周几提醒（如"周五上午10点提醒吃饭"）
                {
                    "pattern": r'周([一二三四五六日])\s*(上|下|中)?午?(\d{1,2})[:点](\d{2})?分?\s*提醒?(.+)',
                    "handler": _handle_weekday
                },
                # 3. 提醒在前的周几格式
                {
                    "pattern": r'提醒(.+?)在\s*周([一二三四五六日])\s*(上|下|中)?午?(\d{1,2})[:点](\d{2})?分?',
                    "handler": _handle_reminder_first_weekday
                },
                # 4. 每天提醒（周期）
                {
                    "pattern": r'每天\s*(\d{1,2})[:点](\d{2})?分?\s*提醒?(.+)',
                    "handler": _handle_daily
                },
                # 5. 相对时间
                {
                    "pattern": r'(\d+)\s*(分钟|小时|天)后\s*提醒?(.+)',
                    "handler": _handle_relative_time
                },
                # 6. 绝对时间
                {
                    "pattern": r'(\d{4}[-/]\d{1,2}[-/]\d{1,2}\s+\d{1,2}:\d{2})\s*提醒?(.+)',
                    "handler": _handle_absolute_time
                },
                # 7. 简单群提醒
                {
                    "pattern": r'(.+?)(群|群聊)\s*(\d{1,2})[:点](\d{2})?分?\s*提醒?(.+)',
                    "handler": _handle_group_reminder
                }
            ]

            for item in patterns:
                match = re.search(item["pattern"], input_str)
                if match:
                    parsed = item["handler"](match, now)
                    result.update(parsed)
                    return result

            # 兜底逻辑
            content_only = re.sub(
                r'\d+\s*(分钟|小时|天)后|周[一二三四五六日]|每天|\d{4}[-/]\d{1,2}[-/]\d{1,2}|群|群聊|提醒|[:点分]',
                '', input_str
            )
            content_only = re.sub(r'在|的', '', content_only).strip() or "默认提醒"
            result["content"] = content_only
            return result

        # 嵌套辅助函数：解析小时和分钟
        def _parse_hour_minute(hour_str, minute_str, am_pm):
            hour = int(hour_str)
            minute = int(minute_str) if minute_str else 0

            if am_pm == "下" and hour < 12:
                hour += 12
            elif am_pm == "上" and hour == 12:
                hour = 0

            return hour, minute

        # 嵌套辅助函数：中文星期几转数字
        def _get_weekday_num(weekday_cn):
            weekday_map = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6}
            return weekday_map.get(weekday_cn, 0)

        # 嵌套处理器函数
        def _handle_remind_weekday(match, now):
            weekday_cn, hour, minute, content = match.groups()
            weekday_num = _get_weekday_num(weekday_cn)
            hour, minute = _parse_hour_minute(hour, minute, None)

            days_delta = (weekday_num - now.weekday()) % 7
            if days_delta == 0 and (now.hour > hour or (now.hour == hour and now.minute >= minute)):
                days_delta = 7

            target_time = (now + timedelta(days=days_delta)).replace(
                hour=hour, minute=minute, second=0, microsecond=0
            )

            return {
                "content": content.strip(),
                "time": target_time.strftime("%Y-%m-%d %H:%M:%S"),
                "is_repeat": True,
                "repeat_type": 2  # 每周
            }

        def _handle_weekday(match, now):
            weekday_cn, am_pm, hour, minute, content = match.groups()
            weekday_num = _get_weekday_num(weekday_cn)
            hour, minute = _parse_hour_minute(hour, minute, am_pm)

            days_delta = (weekday_num - now.weekday()) % 7
            if days_delta == 0 and (now.hour > hour or (now.hour == hour and now.minute >= minute)):
                days_delta = 7

            target_time = (now + timedelta(days=days_delta)).replace(
                hour=hour, minute=minute, second=0, microsecond=0
            )

            return {
                "content": content.strip(),
                "time": target_time.strftime("%Y-%m-%d %H:%M:%S"),
                "is_repeat": True,
                "repeat_type": 2
            }

        def _handle_daily(match, now):
            hour, minute, content = match.groups()
            hour, minute = _parse_hour_minute(hour, minute, None)
            target_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if target_time <= now:
                target_time += timedelta(days=1)
            return {
                "content": content.strip(),
                "time": target_time.strftime("%Y-%m-%d %H:%M:%S"),
                "is_repeat": True,
                "repeat_type": 1
            }

        def _handle_group_reminder(match, now):
            group_prefix, _, hour, minute, content = match.groups()
            group_name = f"{group_prefix}群"
            hour, minute = _parse_hour_minute(hour, minute, None)
            target_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if target_time <= now:
                target_time += timedelta(days=1)
            return {
                "content": content.strip(),
                "time": target_time.strftime("%Y-%m-%d %H:%M:%S"),
                "remind_type": 1,
                "group_name": group_name
            }

        def _handle_relative_time(match, now):
            num, unit, content = match.groups()
            num = int(num)

            if unit == "分钟":
                target_time = now + timedelta(minutes=num)
            elif unit == "小时":
                target_time = now + timedelta(hours=num)
            else:
                target_time = now + timedelta(days=num)

            return {
                "content": content.strip(),
                "time": target_time.strftime("%Y-%m-%d %H:%M:%S"),
                "is_repeat": False,
                "repeat_type": 0
            }

        def _handle_absolute_time(match, now):
            time_str, content = match.groups()
            time_str = time_str.replace("/", "-")
            try:
                target_time = datetime.strptime(time_str, "%Y-%m-%d %H:%M")
                return {
                    "content": content.strip(),
                    "time": target_time.strftime("%Y-%m-%d %H:%M:%S"),
                    "is_repeat": False,
                    "repeat_type": 0
                }
            except ValueError:
                return {"content": content.strip()}

        def _handle_reminder_first_weekday(match, now):
            content, weekday_cn, am_pm, hour, minute = match.groups()
            weekday_num = _get_weekday_num(weekday_cn)
            hour, minute = _parse_hour_minute(hour, minute, am_pm)

            days_delta = (weekday_num - now.weekday()) % 7
            if days_delta == 0 and (now.hour > hour or (now.hour == hour and now.minute >= minute)):
                days_delta = 7

            target_time = (now + timedelta(days=days_delta)).replace(
                hour=hour, minute=minute, second=0, microsecond=0
            )

            return {
                "content": content.strip(),
                "time": target_time.strftime("%Y-%m-%d %H:%M:%S"),
                "is_repeat": True,
                "repeat_type": 2
            }

        # 执行解析并返回结果
        return parse_reminder(user_input)



    def _convert_llm_result_to_db_format(self, llm_result: Dict, user_input: str, registrant_name: str) -> Dict:
        """LLM返回结果调整符合数据库格式（优化版）"""
        now = datetime.now()
        register_time = now.strftime("%Y-%m-%d %H:%M:%S")

        # 1. 处理提醒时间（增强容错）
        time_str = llm_result.get("time", "")
        try:
            remind_time = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
            if remind_time <= now:
                # 时间在过去，自动调整并提示
                remind_time = now + timedelta(hours=1)
                warning = f"提醒时间在过去，已自动调整为1小时后（{remind_time.strftime('%Y-%m-%d %H:%M:%S')}）"
        except (ValueError, TypeError):
            # 解析失败，使用兜底时间并提示
            remind_time = now + timedelta(hours=1)
            warning = f"时间格式解析失败，已自动设置为1小时后（{remind_time.strftime('%Y-%m-%d %H:%M:%S')}），建议检查输入格式"

        # 2. 处理周期类型（直接使用LLM返回的整数，无需映射）
        # LLM返回的repeat_type已为整数（1=每日，2=每周，3=每月，4=自定义天数，0=非周期）
        repeat_type = llm_result.get("repeat_type", 0)
        # 确保类型合法（防止LLM返回无效值）
        if repeat_type not in [0, 1, 2, 3, 4]:
            repeat_type = 0

        # 3. 处理周期结束时间（优先用LLM返回的，否则默认1年）
        is_repeat = llm_result.get("is_repeat", False)
        repeat_end_time = None
        if is_repeat:
            # 优先使用LLM解析的结束时间
            llm_end_time = llm_result.get("repeat_end_time")
            if llm_end_time:
                try:
                    repeat_end_time = datetime.strptime(llm_end_time, "%Y-%m-%d %H:%M:%S")
                except (ValueError, TypeError):
                    # LLM返回的结束时间格式错误，用默认值
                    repeat_end_time = now + timedelta(days=365)
            else:
                # LLM未返回结束时间，用默认1年
                repeat_end_time = now + timedelta(days=365)
            # 确保结束时间在提醒时间之后
            if repeat_end_time <= remind_time:
                repeat_end_time = remind_time + timedelta(days=365)

        # 4. 组装数据库字段（确保所有必要字段存在）
        db_data = {
            # 核心字段：LLM结果优先，user_input兜底
            "reminder_content": llm_result.get("content", user_input.strip() or "未指定内容"), # 提醒内容
            "remind_time": remind_time.strftime("%Y-%m-%d %H:%M:%S"), # 时间
            "is_repeat": 1 if is_repeat else 0,  # 是否周期性
            "repeat_type": repeat_type, # 周期类型
            "repeat_interval": max(1, llm_result.get("repeat_interval", 1)),  # 周期间隔
            "repeat_end_time": repeat_end_time.strftime("%Y-%m-%d %H:%M:%S") if repeat_end_time else None,
            # 周期结束时间：参数registrant_name优先，LLM结果兜底，最后用默认值
            "remind_type": llm_result.get("remind_type", 0),  # 提醒类型（个人提醒默认0）
            "group_name": llm_result.get("group_name"), # 群名
            "registrant_name": registrant_name or llm_result.get("registrant_name") or "用户", # 用户名
            "remark": llm_result.get("remark"),  # 备注内容
            # 可选字段：确保存在，非LLM结果或默认null
            "register_time": register_time,  # 注册时间为当前时间
            "is_triggered": 0,  # 是否触发，初始未触发
            "is_completed": 0,  # 是否完成，初始未完成
            "last_trigger_time": None # 最近触发时间
        }

        return db_data

    def delete_all_reminders(self, registrant_name: str = None) -> str:
        """删除所有提醒（可按登记人筛选，默认删除全部）"""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            if registrant_name:
                # 仅删除指定登记人的提醒
                sql = f"DELETE FROM {self.TABLE_NAME} WHERE registrant_name = ?"
                cursor.execute(sql, (registrant_name,))
            else:
                # 删除所有提醒（谨慎！）
                sql = f"DELETE FROM {self.TABLE_NAME}"
                cursor.execute(sql)

            conn.commit()
            return f"✅ 已删除{cursor.rowcount}条提醒" if cursor.rowcount > 0 else "❌ 暂无提醒可删除"
        except sqlite3.Error as e:
            return f"❌ 批量删除失败: {e}"
        finally:
            conn.close()


    async def set_reminder(self, user_input: str, registrant_name: str,
                           remind_type: int = 0, group_name: str = "", remark: str = "") -> str:
        """设置提醒（主入口，支持所有场景）"""
        llm_result = await self.parse_with_llm(user_input)
        if not llm_result:
            return "❌ 无法解析提醒内容，请重新输入（如“30分钟后提醒吃饭”“每周五下午3点提醒吃饭”）"

        db_data = self._convert_llm_result_to_db_format(
            llm_result, user_input, registrant_name
        )

        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            columns = list(db_data.keys())
            values = [db_data[k] for k in columns]
            placeholders = ["?"] * len(columns)

            sql = f"""
            INSERT INTO {self.TABLE_NAME} ({', '.join(columns)})
            VALUES ({', '.join(placeholders)})
            """
            cursor.execute(sql, values)
            conn.commit()
            reminder_id = cursor.lastrowid # 输出的ID号

            remind_time = datetime.strptime(db_data["remind_time"], "%Y-%m-%d %H:%M:%S")
            repeat_desc = self.REPEAT_TYPE_MAP[db_data["repeat_type"]]
            response = (
                f"✅ 提醒设置成功\n"
                f"ID：{reminder_id}\n"
                f"内容：{db_data['reminder_content']}\n"
                f"首次提醒：{remind_time.strftime('%Y-%m-%d %H:%M')}\n"
                f"类型：{'周期性' if db_data['is_repeat'] else '单次'} | {repeat_desc}\n"
            )
            # 回复内容输出
            if db_data["is_repeat"]:
                response += f"重复间隔：每{db_data['repeat_interval']}{'天' if repeat_desc == '每日' else '周' if repeat_desc == '每周' else '月'}\n"
            response += f"登记人：{registrant_name} | {'群提醒：' + group_name if group_name else '个人提醒'}"
            return response

        except sqlite3.Error as e:
            return f"❌ 数据库保存失败: {e}"
        finally:
            if 'conn' in locals() and conn:
                conn.close()

    def get_reminders(self, registrant_name: str = None) -> List[Dict]:
        """获取提醒列表（支持按登记人筛选）"""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            if registrant_name:
                sql = f"SELECT * FROM {self.TABLE_NAME} WHERE registrant_name = ? ORDER BY remind_time"
                cursor.execute(sql, (registrant_name,))
            else:
                sql = f"SELECT * FROM {self.TABLE_NAME} ORDER BY remind_time"
                cursor.execute(sql)

            return [dict(row) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            print(f"获取提醒列表失败: {e}")
            return []
        finally:
            conn.close()

    def delete_reminder(self, reminder_id: int) -> str:
        """删除提醒（按ID）"""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            sql = f"DELETE FROM {self.TABLE_NAME} WHERE reminder_id = ?"
            cursor.execute(sql, (reminder_id,))
            conn.commit()

            return f"✅ 已删除提醒 ID: {reminder_id}" if cursor.rowcount > 0 else f"❌ 未找到提醒 ID: {reminder_id}"
        except sqlite3.Error as e:
            return f"❌ 删除失败: {e}"
        finally:
            conn.close()


    def check_and_trigger_reminders(self, conn: Optional[sqlite3.Connection] = None) -> List[Dict]:
        """完整修正版：周期性提醒可以重复触发"""
        now = datetime.now()
        triggered_reminders = []

        close_conn = False
        if conn is None:
            conn = self._get_connection()
            close_conn = True

        try:
            cursor = conn.cursor()

            # 🔥 必须修改查询条件：区分单次和周期性提醒
            sql = f"""
            SELECT * FROM {self.TABLE_NAME} 
            WHERE is_completed = 0
              AND (
                (is_repeat = 1) 
                OR 
                (is_repeat = 0 AND is_triggered = 0)
              )
              AND remind_time <= ? 
            ORDER BY remind_time ASC
            """
            cursor.execute(sql, (now.strftime("%Y-%m-%d %H:%M:%S"),))
            due_reminders = [dict(row) for row in cursor.fetchall()]

            for reminder in due_reminders:
                triggered_reminders.append(reminder)

                if reminder["is_repeat"]:
                    # 周期性提醒：更新下次时间，并重置触发状态
                    success = self._update_recurring_reminder(reminder, now, cursor)
                    if success:
                        print(f"🔁 周期提醒已更新 - ID:{reminder['reminder_id']}")
                else:
                    # 单次提醒：标记为触发完成
                    success = self._mark_single_reminder_triggered(reminder, now, cursor)
                    if success:
                        print(f"✅ 单次提醒已完成 - ID:{reminder['reminder_id']}")

            conn.commit()

        except Exception as e:
            print(f"❌ 检查提醒失败: {e}")
            conn.rollback()
        finally:
            if close_conn and conn:
                conn.close()

        return triggered_reminders

    def _handle_missed_reminder(self, reminder: Dict, now: datetime, time_diff: timedelta, cursor):
        """统一处理错过时间的提醒"""
        reminder_id = reminder["reminder_id"]
        content = reminder["reminder_content"]

        if time_diff > timedelta(hours=24):
            print(f"⏰ [错过处理] ID:{reminder_id} 已错过 {time_diff}")

            if reminder["is_repeat"]:
                # 错过很久的周期提醒：直接更新到下次时间
                self._update_recurring_reminder(reminder, now, cursor)
                print(f"🔁 错过周期提醒已更新到下次时间")
            else:
                # 错过很久的单次提醒：标记为触发，添加错过标记
                current_remark = reminder.get("remark", "") or ""
                new_remark = f"{current_remark} [错过提醒，于{now.strftime('%Y-%m-%d %H:%M')}补发]".strip()

                update_sql = f"""
                UPDATE {self.TABLE_NAME} 
                SET is_triggered = 1, 
                    last_trigger_time = ?,
                    is_completed = 1,
                    remark = ?
                WHERE reminder_id = ?
                """
                cursor.execute(update_sql, (
                    now.strftime("%Y-%m-%d %H:%M:%S"),
                    new_remark,
                    reminder_id
                ))
                print(f"✅ 错过单次提醒已补发")
        else:
            # 正常到期的提醒（错过时间在24小时内）
            if reminder["is_repeat"]:
                self._update_recurring_reminder(reminder, now, cursor)
            else:
                self._mark_single_reminder_triggered(reminder, now, cursor)

    def _mark_single_reminder_triggered(self, reminder: Dict, trigger_time: datetime, cursor) -> bool:
        """标记单次提醒为已触发并完成"""
        try:
            update_sql = f"""
            UPDATE {self.TABLE_NAME} 
            SET is_triggered = 1, 
                last_trigger_time = ?,
                is_completed = 1  -- 单次提醒触发后即完成
            WHERE reminder_id = ?
            """
            cursor.execute(update_sql, (
                trigger_time.strftime("%Y-%m-%d %H:%M:%S"),
                reminder["reminder_id"]
            ))
            return cursor.rowcount > 0
        except Exception as e:
            print(f"❌ 标记单次提醒失败 ID:{reminder['reminder_id']}: {e}")
            return False

    def _update_recurring_reminder(self, reminder: Dict, trigger_time: datetime, cursor) -> bool:
        """更新周期性提醒的下次时间"""
        try:
            current_remind_time = datetime.strptime(reminder["remind_time"], "%Y-%m-%d %H:%M:%S")
            repeat_interval = reminder["repeat_interval"]
            repeat_type = reminder["repeat_type"]

            # 计算下一次提醒时间
            next_time = self._calculate_next_reminder_time(
                current_remind_time, repeat_type, repeat_interval
            )

            # 检查是否超过结束时间
            if reminder["repeat_end_time"]:
                end_time = datetime.strptime(reminder["repeat_end_time"], "%Y-%m-%d %H:%M:%S")
                if next_time > end_time:
                    # 超过结束时间，标记为已完成
                    return self._mark_recurring_reminder_completed(reminder, trigger_time, cursor, "周期结束")

            # 更新提醒时间和触发状态
            update_sql = f"""
            UPDATE {self.TABLE_NAME} 
            SET remind_time = ?, 
                last_trigger_time = ?,
                is_triggered = 0  -- 标记为已触发（下次会重置）
            WHERE reminder_id = ?
            """
            cursor.execute(update_sql, (
                next_time.strftime("%Y-%m-%d %H:%M:%S"),
                trigger_time.strftime("%Y-%m-%d %H:%M:%S"),
                reminder["reminder_id"]
            ))

            return cursor.rowcount > 0

        except Exception as e:
            print(f"❌ 更新周期性提醒失败 ID:{reminder['reminder_id']}: {e}")
            return False

    def _calculate_next_reminder_time(self, current_time: datetime, repeat_type: int, interval: int) -> datetime:
        """计算下一次提醒时间"""
        if repeat_type == 1:  # 每日
            return current_time + timedelta(days=interval)
        elif repeat_type == 2:  # 每周
            return current_time + timedelta(weeks=interval)
        elif repeat_type == 3:  # 每月
            return self._add_months(current_time, interval)
        elif repeat_type == 4:  # 自定义天数
            return current_time + timedelta(days=interval)
        else:
            print("周期类型不符，时间默认加一天")
            return current_time + timedelta(days=1)  # 默认

    def _mark_recurring_reminder_completed(self, reminder: Dict, trigger_time: datetime, cursor, reason: str) -> bool:
        """标记周期性提醒为已完成"""
        try:
            # 使用SQLite的字符串连接方式
            current_remark = reminder.get("remark", "") or ""
            new_remark = f"{current_remark} [已完成: {reason}]".strip()

            update_sql = f"""
            UPDATE {self.TABLE_NAME} 
            SET is_completed = 1, 
                last_trigger_time = ?,
                remark = ?
            WHERE reminder_id = ?
            """
            cursor.execute(update_sql, (
                trigger_time.strftime("%Y-%m-%d %H:%M:%S"),
                new_remark,
                reminder["reminder_id"]
            ))
            print(f"[周期结束] ID:{reminder['reminder_id']} - 原因: {reason}")
            return cursor.rowcount > 0
        except Exception as e:
            print(f"❌ 标记周期提醒完成失败 ID:{reminder['reminder_id']}: {e}")
            return False

    def _add_months(self, source_date: datetime, months: int) -> datetime:
        """安全添加月份"""
        year = source_date.year
        month = source_date.month + months
        day = source_date.day

        while month > 12:
            month -= 12
            year += 1
        while month < 1:
            month += 12
            year -= 1

        max_day = calendar.monthrange(year, month)[1]
        target_day = day if day <= max_day else max_day

        return source_date.replace(year=year, month=month, day=target_day)


    def handle_command(self, user_input: str, registrant_name: str = "用户") -> str:
        """处理用户命令（适配LangChain，同步接口）"""
        user_input = user_input.strip().lower()

        # 1. 查看提醒列表
        fixed_commands = {"list", "查看提醒", "提醒列表", "待办事项"}
        if user_input in fixed_commands or re.search(r'查看.*(提醒|待办)', user_input, re.IGNORECASE):
            reminders = self.get_reminders(registrant_name)
            if not reminders:
                return "📝 暂无提醒事项"
            result = ["📝 您的提醒列表："]
            for remind in reminders:
                if remind["is_completed"]:
                    status = "✅"
                elif remind["is_triggered"]:
                    status = "⏰"
                else:
                    status = "🕒"
                repeat_info = f"（{self.REPEAT_TYPE_MAP[remind['repeat_type']]}）" if remind["is_repeat"] else ""
                result.append(
                    f"{status} ID:{remind['reminder_id']} | "
                    f"{remind['reminder_content']} | "
                    f"时间：{remind['remind_time'][:16]} {repeat_info}"
                )
            return "\n".join(result)

        # 2. 删除提醒（兼容单个删除和批量删除）
        elif user_input.startswith(("delete", "删除")):
            # 先判断是否是“删除所有”
            if re.search(r'所有|全部', user_input, re.IGNORECASE):
                # 可选：添加确认逻辑（防止误操作）
                confirm = input("⚠️  确认删除所有提醒？此操作不可恢复！输入'yes'确认：")
                if confirm.lower() != "yes":
                    return "❌ 已取消删除所有提醒"
                # 调用批量删除方法（可指定登记人，如仅删除当前用户的）
                return self.delete_all_reminders(registrant_name)

            # 否则按单个ID删除
            id_match = re.search(r'(\d+)', user_input)
            if id_match:
                return self.delete_reminder(int(id_match.group(1)))
            return "❌ 请提供有效提醒ID（如“删除1”），或使用“删除所有提醒”批量删除"

        # 3. 设置提醒
        else:
            try:
                # 定义要执行的异步任务
                async def async_task():
                    return await self.set_reminder(user_input, registrant_name)
                try:
                    # 尝试获取当前运行的事件循环
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    # 情况1：无运行中的事件循环 → 直接用asyncio.run启动
                    return asyncio.run(async_task())
                else:
                    # 情况2：有运行中的事件循环 → 在当前循环中执行
                    if loop.is_running():
                        try:
                            # 等待任务完成（30秒超时）
                            result = asyncio.wait_for(async_task(), timeout=30)
                            return result
                        except asyncio.TimeoutError:
                            return "❌ 设置提醒超时，请稍后重试"
                    else:
                        # 循环存在但未运行 → 直接运行直到完成
                        return loop.run_until_complete(async_task())

            except Exception as e:
                error_msg = f"[处理命令异常] 错误: {str(e)}"
                print(error_msg)
                return f"❌ 设置提醒失败: {str(e)}"