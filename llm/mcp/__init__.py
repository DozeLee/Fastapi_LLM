"""
MCP（Model Context Protocol）层：统一调度LLM和工具
核心能力：
1. 工具统一注册/调用
2. LLM统一调用（支持多模型扩展）
3. 通用能力（日志、重试、缓存等）
"""
from .tool_registry import (
    TOOL_REGISTRY,
    register_tool,
    unregister_tool,
    get_tool,
    list_all_tools
)
from .mcp_core import ModelContextProtocol

# 导出核心类和方法，方便外部导入
__all__ = [
    "ModelContextProtocol",
    "TOOL_REGISTRY",
    "register_tool",
    "unregister_tool",
    "get_tool",
    "list_all_tools"
]