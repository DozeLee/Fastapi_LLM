import requests
import json
import asyncio
import sys
import os
from typing import Any, List, Mapping, Optional, Dict, Tuple
from langchain.llms.base import LLM

# 添加项目根目录到Python搜索路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from llm.key_data import llm_key  # 绝对导入，适配项目结构
from llm.VolcengineLLM import VolcengineLLM


# 测试用例（仅在直接运行该文件时执行）
if __name__ == "__main__":
    llm = VolcengineLLM(
        api_key=llm_key.api_key,
        model_name="doubao-seed-1-6-thinking-250715",
        temperature=0.5,
        max_tokens=1024,
    )
    try:
        response = llm.invoke("你好，你多大了")
        print(response)
    except Exception as e:
        print(f"调用失败：{e}")