import logging
from typing import Dict, Any, Optional
from .tool_registry import get_tool

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MCP")


class ModelContextProtocol:
    """轻量MCP核心类：统一调度工具和LLM"""

    def __init__(self, llm, custom_tools: Optional[Dict[str, Any]] = None):
        self.llm = llm  # 传入LLM实例
        self.custom_tools = custom_tools or {}  # 动态绑定的工具（如ReminderTool实例）

    def call_tool(self, tool_name: str, tool_input: str) -> str:
        """
        统一调用工具的入口
        :param tool_name: 工具名称（如Calculator）
        :param tool_input: 工具输入参数
        :return: 统一格式的工具返回结果
        """
        try:
            # 1. 获取工具函数
            tool_func, _ = get_tool(tool_name)
            if tool_name == "Reminder":
                # 动态绑定的Reminder工具（需传入实例方法）
                tool_func = self.custom_tools.get("Reminder")
                if not tool_func:
                    return "Reminder工具未初始化，请先绑定实例方法"

            if not tool_func:
                return f"未找到工具：{tool_name}"

            # 2. 调用工具并记录日志
            logger.info(f"调用工具 {tool_name}，输入：{tool_input}")
            result = tool_func(tool_input)

            # 3. 统一结果格式（方便Agent处理）
            return f"{result}"

        except Exception as e:
            error_msg = f"工具 {tool_name} 调用失败：{str(e)}"
            logger.error(error_msg)
            return error_msg

    def call_llm(self, prompt: str) -> str:
        """统一调用LLM的入口（支持多模型扩展）"""
        try:
            logger.info(f"调用LLM，Prompt长度：{len(prompt)}")
            return self.llm.invoke(prompt)
        except Exception as e:
            error_msg = f"LLM调用失败：{str(e)}"
            logger.error(error_msg)
            return error_msg