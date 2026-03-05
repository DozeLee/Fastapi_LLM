import time,requests,json,warnings,asyncio
from llm import tools as tl
from typing import Optional, List, Mapping, Any
from langchain.agents import AgentExecutor, Tool, initialize_agent
from langchain.llms.base import LLM
from langchain.memory import ConversationBufferMemory  # 自带的memory存在一定问题，因此自建history本地
from llm.key_data import llm_key
from llm.VolcengineLLM import VolcengineLLM

# 新增：导入MCP核心类
from llm.mcp import ModelContextProtocol, get_tool, list_all_tools

# 过滤LangChain弃用警告
warnings.filterwarnings('ignore', category=DeprecationWarning, module='langchain.agents.agent')

# 主程序
class SmartAgent:
    def __init__(self, volcengine_api_key: str,prompt_template: str = None):
        self.llm = VolcengineLLM(api_key=volcengine_api_key)
        # self.reminder_tool = tl.ReminderTool(llm=self.llm)

        # 核心修改：初始化MCP
        self.mcp = ModelContextProtocol(
            llm=self.llm,
            # custom_tools={"Reminder": self.reminder_tool.handle_command} # Reminder工具类独是提醒事务会延迟返回，因此单独构建
        )
        # 自定义 Prompt 模板（默认+可配置）
        self.prompt_template = prompt_template or """
                你是一个智能助手，回答用户问题时要简洁、准确，不要多余标点符号，只输出回复的第一行
                用户当前问题：{user_query}
                """
        self.tools = self._init_tools()
        self.memory = ConversationBufferMemory(
            memory_key="chat_history",
            return_messages=True,
            output_key="output"
        )
        self.agent = self._create_agent()
        self.direct_history = []

    def _init_tools(self) -> List[Tool]:
        """初始化工具集（改为调用MCP）"""
        return [
            Tool(
                name="Calculator",
                # 改为调用MCP的call_tool方法
                func=lambda input: self.mcp.call_tool("Calculator", input),
                description=get_tool("Calculator")[1]  # 从注册表获取描述
            ),
            Tool(
                name="Weather",
                func=lambda input: self.mcp.call_tool("Weather", input),
                description=get_tool("Weather")[1]
            ),
            Tool(
                name="Reminder",
                func=lambda input: self.mcp.call_tool("Reminder", input),
                description=get_tool("Reminder")[1]
            ),
            Tool(
                name="SQLiteDatabase",
                func=lambda input: self.mcp.call_tool("SQLiteDatabase", input),
                description=get_tool("SQLiteDatabase")[1]
            ),
        ]

    def _create_agent(self) -> AgentExecutor:
        """创建智能代理 - 使用支持记忆的代理"""
        agent = initialize_agent(
            tools=self.tools,
            llm=self.llm,
            agent="conversational-react-description",
            verbose=True,
            max_iterations=10,
            handle_parsing_errors=True,
            memory=self.memory,
            return_intermediate_steps=False,
        )
        return agent

    def invoke(self, query: str) -> str:
        """主要LLM部分调用代码，执行查询并维护历史记录"""
        try:
            self.direct_history.append(f"用户: {query}")

            if any(phrase in query for phrase in ["我刚才问的啥", "我之前问了什么", "历史记录", "对话历史"]):
                return self._handle_history_query(query)

            custom_prompt = self.prompt_template.format(user_query=query)
            response = self.agent.invoke({"input": custom_prompt})
            answer = response["output"]

            self.direct_history.append(f"助手: {answer}")
            return answer
        except Exception as e:
            error_msg = f"Agent执行失败：{str(e)}"
            self.direct_history.append(f"助手: {error_msg}")
            return error_msg

    # def invoke(self, query: str) -> str:
    #     """执行查询并自动判断工具调用（原有逻辑保留）"""
    #     try:
    #         custom_prompt = self.prompt_template.format(user_query=query)
    #         response = self.agent.invoke({"input": custom_prompt})
    #         return response['output']
    #     except Exception as e:
    #         return f"Agent执行失败：{str(e)}"

    def get_chat_history(self) -> List[str]:
        """获取对话历史"""
        try:
            return self.direct_history
        except AttributeError:
            print("对话历史为空")
            return []

    def get_recent_history(self, num_exchanges: int = 5) -> List[str]:
        """获取最近的几轮对话"""
        if num_exchanges <= 0:
            return self.direct_history
        return self.direct_history[-num_exchanges * 2:]

    def clear_history(self):
        """清空历史记录"""
        self.direct_history = []
        self.memory.clear()

    def get_previous_questions(self, count: int = 5) -> List[str]:
        """获取之前的问题"""
        try:
            questions = []
            for entry in self.direct_history:
                if entry.startswith("用户: "):
                    questions.append(entry[4:])
            return questions[-count:] if count > 0 else questions
        except AttributeError:
            return []

    def _handle_history_query(self, query: str) -> str:
        """处理关于历史记录的查询"""
        recent_history = self.get_recent_history(5)

        if not recent_history:
            return "我们还没有进行过对话呢。"
        if len(recent_history) > 10:
            recent_history = recent_history[-10:]

        history_context = "\n".join(recent_history)

        prompt = f"""
        根据以下对话历史回答问题，请注意在回答时使用以下称呼：
        - 用户：指代提问的人
        - 助手：指代回答的助手

        {history_context}

        用户当前的问题：{query}

        请根据上面的对话历史回答用户的问题。如果历史中没有相关信息，请如实告知。
        """

        try:
            response = self.llm._call(prompt)
            self.direct_history.append(f"助手: {response}")
            return response
        except Exception as e:
            return f"这是我们最近的对话：\n{history_context}"


# 测试用例
if __name__ == "__main__":
    # 测试MCP工具注册
    print("已注册的工具列表：", list_all_tools())

    api_key = llm_key.api_key
    agent = SmartAgent(volcengine_api_key=api_key)

    print("\n智能助手已启动，输入'q'退出，'history'查看历史，'clear'清空历史，'questions'查看之前的问题")
    while True:
        user_input = input("您的问题: ").strip()
        if user_input.lower() == 'q':
            print("再见！")
            break
        elif user_input.lower() == 'history':
            history = agent.get_chat_history()
            print("\n=== 对话历史 ===")
            for msg in history:
                print(msg)
            continue
        elif user_input.lower() == 'clear':
            agent.clear_history()
            print("历史记录已清空")
            continue
        elif user_input.lower() == 'questions':
            questions = agent.get_previous_questions()
            print("\n=== 之前的问题 ===")
            for i, question in enumerate(questions, 1):
                print(f"{i}. {question}")
            continue

        result = agent.invoke(user_input)
        print(f"回答: {result}\n")
        time.sleep(1)