import re


class CalculatorTool:
    """数学计算工具类，支持基本算术运算"""

    @staticmethod
    def calculate(expression: str) -> str:
        """
        计算数学表达式的结果，支持+、-、*、/、()运算符
        输入示例："2+3*4"、"(5+8)*2"、"10/2-3"
        """
        try:
            # 第一步：彻底清洗输入（关键修复）
            # 1. 移除所有空白字符（空格、换行、制表符等）
            expression = re.sub(r'\s+', '', expression)
            # 2. 只保留数字、运算符、括号，过滤所有其他字符
            cleaned_expr = re.sub(r'[^0-9+\-*/().]', '', expression)

            # 如果清洗后为空，提示用户
            if not cleaned_expr:
                return "未检测到有效的数学表达式，请输入如'3+2'、'(5-2)*4'的格式"

            # 第二步：安全验证（基于清洗后的表达式）
            if not re.match(r'^[\d+\-*/().]+$', cleaned_expr):
                return f"表达式包含无效字符，仅支持数字和+、-、*、/、()运算符（清洗后：{cleaned_expr}）"

            # 第三步：安全计算（限制计算复杂度，防止恶意表达式）
            # 额外防护：限制表达式长度，防止超长表达式阻塞
            if len(cleaned_expr) > 50:
                return "表达式过长，最多支持50个字符"

            # 使用eval计算（仅用空的全局/局部变量，避免安全风险）
            allowed_globals = {}
            allowed_locals = {}
            result = eval(cleaned_expr, allowed_globals, allowed_locals)

            # 格式化返回结果（保留原始输入+清洗后表达式+结果）
            return f"{expression} = {result}（清洗后表达式：{cleaned_expr}）"

        except SyntaxError:
            return "表达式语法错误，请检查格式（例如：2+3*4、(5+8)/2）"
        except ZeroDivisionError:
            return "错误：除数不能为0"
        except Exception as e:
            return f"计算失败：{str(e)}（原始输入：{expression}）"