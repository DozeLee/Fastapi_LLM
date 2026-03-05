import time,requests,json,warnings,asyncio
from typing import Optional, List, Mapping, Any
from langchain.llms.base import LLM

# 过滤LangChain弃用警告
warnings.filterwarnings('ignore', category=DeprecationWarning, module='langchain.agents.agent')


class VolcengineLLM(LLM):
    api_key: str
    model_name: str = "doubao-seed-1-6-thinking-250715"
    temperature: float = 0.5
    max_tokens: int = 1024

    @property
    def _llm_type(self) -> str:
        return "volcengine"

    def _call(self, prompt: str, stop: Optional[List[str]] = None) -> str:
        """同步调用方法"""
        url = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        payload = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stop": stop
        }

        try:
            response = requests.post(url, headers=headers, data=json.dumps(payload), timeout=25)
            response.raise_for_status()
            response_data = response.json()
            return response_data["choices"][0]["message"]["content"]
        except requests.exceptions.Timeout:
            return "LLM调用超时，请稍后再试"
        except Exception as e:
            return f"LLM调用失败：{str(e)}"

    async def ainvoke(self, prompt: str, stop: Optional[List[str]] = None) -> str:
        """新增：异步调用方法（适配ReminderTool的await self.llm.ainvoke）"""
        # 使用线程池包装同步调用，避免阻塞事件循环
        return await asyncio.to_thread(self._call, prompt, stop)

    def invoke(self, prompt: str, stop: Optional[List[str]] = None) -> str:
        """invoke方法，与LangChain兼容"""
        return self._call(prompt, stop)

    @property
    def _identifying_params(self) -> Mapping[str, Any]:
        return {"model_name": self.model_name, "temperature": self.temperature}
