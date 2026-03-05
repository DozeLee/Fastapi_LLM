import pandas as pd
import requests, re
from llm.key_data import data
from typing import Any, List, Mapping, Optional, Dict, Tuple

class WeatherTool:
    """高德地图天气查询工具类"""

    @staticmethod
    def get_weather(city: str) -> str:
        """调用高德地图天气API，返回指定城市的实时天气
        参数: city - 城市名称（如：北京、上海）
        """
        WEATHER_API_URL = data.WEATHER_API_URL
        WEATHER_API_KEY = data.WEATHER_API_KEY  # 高德API Key

        try:
            # 提取城市名称，移除可能的天气相关关键词
            city = re.sub(r'天气|气温|温度|晴雨|今天|明天|后天', '', city).strip()

            # 如果城市名为空，返回错误信息
            if not city:
                return "请提供有效的城市名称"

            # 尝试直接使用城市名查询
            params = {
                "city": city,
                "key": WEATHER_API_KEY,
                "extensions": "base",
                "output": "JSON"
            }

            response = requests.get(WEATHER_API_URL, params=params, timeout=10)
            response.raise_for_status()
            weather_data = response.json()

            # 如果查询失败，尝试使用城市编码
            if weather_data.get("status") != "1":
                city_code = WeatherTool._get_city_code(city)
                if city_code:
                    params["city"] = city_code
                    response = requests.get(WEATHER_API_URL, params=params, timeout=10)
                    weather_data = response.json()
                else:
                    return f"未找到城市'{city}'的编码，无法查询天气"

            if weather_data.get("status") == "1" and weather_data.get("lives"):
                lives = weather_data["lives"][0]
                return (
                    f"{lives['province']}{lives['city']}当前天气：{lives['weather']}，"
                    f"温度：{lives['temperature']}°C，"
                    f"风向：{lives['winddirection']}，"
                    f"风力：{lives['windpower']}级，"
                    f"湿度：{lives['humidity']}%，"
                    f"发布时间：{lives['reporttime']}"
                )
            else:
                return f"查询天气失败：{weather_data.get('info', '未知错误')}（状态码：{weather_data.get('status')}）"

        except requests.exceptions.RequestException as e:
            return f"网络请求错误：{str(e)}"
        except Exception as e:
            return f"查询失败：{str(e)}"

    @staticmethod
    def _get_city_code(city_name: str) -> Optional[str]:
        """读取城市编码"""
        try:
            # 读取Excel数据
            df = pd.read_excel('databases/AMap_citycode.xlsx', sheet_name='Sheet1')
            city_list = df[['中文名', 'adcode']].to_dict('records')

            # 1. 精确匹配（完全一致）
            for city in city_list:
                if city['中文名'] == city_name:
                    return str(city['adcode'])

            # 2. 按字符级别的包含度评分（解决"北京朝阳"匹配"北京市朝阳区"的问题）
            def char_coverage_score(city):
                """计算输入名称字符在城市名中的覆盖率"""
                input_chars = set(city_name)
                city_chars = set(city['中文名'])
                # 输入字符在城市名中出现的比例
                coverage = len(input_chars & city_chars) / len(input_chars) if input_chars else 0
                # 优先匹配长度更长的城市名（更具体的区域）
                return (coverage, len(city['中文名']))

            # 3. 过滤并排序：覆盖率高、名称更长的城市优先
            candidates = [
                city for city in city_list
                if any(char in city['中文名'] for char in city_name)  # 至少有一个字符匹配
            ]
            candidates.sort(key=char_coverage_score, reverse=True)

            # 4. 进一步验证：输入名称的连续片段是否在城市名中出现
            for city in candidates:
                # 检查"北京朝阳"是否有连续片段（如"北京"或"朝阳"）出现在城市名中
                if re.search(rf"{re.escape(city_name[:2])}|{re.escape(city_name[-2:])}", city['中文名']):
                    return str(city['adcode'])

            # 5. 兜底：返回覆盖率最高的结果
            if candidates:
                return str(candidates[0]['adcode'])

            return None

        except Exception as e:
            print(f"获取城市编码失败：{str(e)}")
            return None


