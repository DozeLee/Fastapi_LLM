# llm/pdf_processor.py
import fitz  # PyMuPDF
import re
import os
import warnings

# 忽略无关警告
warnings.filterwarnings("ignore")


class PDFProcessor:
    """独立的PDF处理工具类：提取内容、清理文本、智能分块"""

    def __init__(self):
        pass

    def check_pdf_file(self, pdf_path):
        """检查PDF文件是否存在且可访问"""
        if not os.path.exists(pdf_path):
            print(f"❌ 文件不存在: {pdf_path}")
            return False

        file_size = os.path.getsize(pdf_path)
        if file_size == 0:
            print("❌ 文件为空")
            return False

        return True

    def extract_pdf_content(self, pdf_path):
        """改进的PDF内容提取：优化空格清理、符号保留、逻辑适配"""
        try:
            doc = fitz.open(pdf_path)
            page_texts = []

            # 逐页处理
            for page_num in range(len(doc)):
                page = doc[page_num]
                page_idx = page_num + 1  # 页码从1开始

                # 1. 优先用"text"模式提取（保留段落逻辑）
                text = page.get_text("text", sort=True)
                # 2. 质量判断：若不合格，切换"words"模式（按坐标排序，避免乱序）
                if not self._text_quality_check(text):
                    words = page.get_text("words", sort=True)  # sort=True按阅读顺序排序
                    if words:
                        # 拼接words为文本（仅保留非空单词）
                        text = " ".join([word[4] for word in words if word[4].strip()])
                        print(f"   第 {page_idx} 页：切换words模式提取")

                # 3. 文本深度清理与修复
                text = self._clean_all_spaces(text)  # 清理所有冗余空格
                text = self._repair_url(text)  # 修复URL格式
                text = self._filter_special_chars(text)  # 过滤乱码，保留实用符号

                # 4. 组装页面数据
                page_data = {
                    "page": page_idx,
                    "text": text,
                    "length": len(text)
                }
                page_texts.append(page_data)

                # 调试信息：简洁展示处理结果
                print(f"第 {page_idx} 页: 清理后{len(text)}字符 | 前50字符：{text[:50]}...")

            doc.close()

            # 5. 过滤空/无效页面（仅保留文本长度>10的页面）
            page_texts = [p for p in page_texts if p["length"] > 10]
            total_valid_pages = len(page_texts)
            print(f"✅ 提取完成: 共{total_valid_pages}页有效内容 | 总字符数：{sum(p['length'] for p in page_texts)}")

            # 6. 显示清理效果示例（取第一页非空文本）
            if page_texts:
                sample_text = page_texts[0]["text"]
                print(f"📝 清理效果示例: {sample_text[:100]}...")

            # 生成全文档文本（拼接所有有效页面）
            full_text = " ".join([p["text"] for p in page_texts])
            return full_text, page_texts

        except Exception as e:
            print(f"❌ PDF提取失败: {str(e)}")
            return None, None

    def enhanced_chunking(self, text, target_size=400, overlap=50):
        """针对清晰段落文本的优化分块：段落分块关闭重叠，避免重复"""
        # 1. 预处理：清理冗余空格，保留原始段落结构
        text = self._clean_text_light(text)
        if len(text) <= target_size:
            return [text.strip()] if text.strip() else []

        # 2. 第一步：优先按段落分块（核心：段落分块关闭重叠，避免重复）
        paragraphs = re.split(r'\n\s*\n', text)  # 空行分隔段落
        paragraphs = [p.strip() for p in paragraphs if p.strip()]
        # 段落分块条件：段落数>1 且 最大段落<目标大小1.5倍
        if len(paragraphs) > 1 and max(len(p) for p in paragraphs) < target_size * 1.5:
            # 关键：段落分块用overlap=0，关闭重叠（段落本身语义完整）
            return self._build_chunks_with_overlap(
                parts=paragraphs,
                target_size=target_size,
                overlap=0,  # 段落分块关闭重叠
                part_sep="\n\n"
            )

        # 3. 第二步：非段落文本（如长句）才用带重叠的分隔符分块
        separators = [
            r'(?<=[。！？.!?])\s*', "。\n", ".\n", "。", ". ",
            "；", ";", "\n", "，", ","
        ]
        best_sep = None
        for sep in separators:
            if not re.search(sep, text):
                continue
            parts = [p.strip() for p in re.split(sep, text) if p.strip()]
            if not parts:
                continue
            avg_size = sum(len(p) for p in parts) / len(parts)
            if avg_size < target_size * 1.2:
                best_sep = sep
                break
        if best_sep:
            parts = [p.strip() for p in re.split(best_sep, text) if p.strip()]
            if best_sep in [r'(?<=[。！？.!?])\s*', "。", ". "]:
                parts = [p + ("。" if p.endswith(("。", "！", "？")) else "") for p in parts]
            # 非段落文本保留重叠，避免语义断裂
            return self._build_chunks_with_overlap(parts, target_size, overlap)

        # 4. 第三步：固定长度兜底（带重叠）
        return self._fixed_size_chunking(text, target_size, overlap)

    # ------------------------------
    # 内部工具函数（私有化，外部无需调用）
    # ------------------------------
    def _clean_all_spaces(self, text):
        """彻底清理所有类型冗余空格（半角、全角、不间断空格）"""
        # 1. 替换特殊空格为普通半角空格
        text = text.replace('　', ' ').replace('\xa0', ' ').replace('\u3000', ' ')
        # 2. 合并连续空格为1个，去除首尾空格
        text = re.sub(r' +', ' ', text).strip()
        return text

    def _repair_url(self, text):
        """修复PDF提取中丢失的URL格式（如https:→https://）"""
        # 匹配 "https:" "http:" 后直接跟域名的情况，补全 "//"
        text = re.sub(r'(https?:)(\w+\.)', r'\1//\2', text)
        return text

    def _text_quality_check(self, text):
        """更精准的文本质量判断：避免短文本页面误判"""
        if not text:
            return False
        # 有效文本占比（非空格字符比例）+ 文本长度双重判断
        non_space_ratio = len(re.sub(r'\s', '', text)) / len(text)
        # 规则：有效占比>50% 且 长度>10字符 → 质量合格
        return non_space_ratio > 0.5 and len(text.strip()) > 10

    def _filter_special_chars(self, text):
        """保留更多实用符号（如//、%、×等），仅过滤特殊乱码"""
        return re.sub(
            r'[^\u4e00-\u9fa5a-zA-Z0-9\s\.\,\!\?\;:\-\（\）\《\》\“\”\'\"//%×÷]',
            '',
            text
        )

    def _clean_text_light(self, text):
        """轻量清理：仅清理冗余空格，不破坏段落结构"""
        if not text:
            return ""
        # 替换特殊空格为普通空格
        text = text.replace('　', ' ').replace('\xa0', ' ').replace('\u3000', ' ')
        # 合并连续3个及以上空格为1个，保留段落空行
        text = re.sub(r' {3,}', ' ', text)
        # 去除首尾空白
        return text.strip()

    def _build_chunks_with_overlap(self, parts, target_size, overlap, part_sep=""):
        """按零件拼接，重叠逻辑仅在非段落场景生效"""
        chunks = []
        current_chunk = ""
        for part in parts:
            new_len = len(current_chunk) + len(part_sep) + len(part)
            if new_len <= target_size:
                current_chunk = f"{current_chunk}{part_sep}{part}" if current_chunk else part
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                # 仅当overlap>0时才添加重叠（段落分块时overlap=0，直接用新part）
                if overlap > 0 and chunks:
                    last_chunk = chunks[-1]
                    overlap_text = last_chunk[-overlap:] if len(last_chunk) > overlap else last_chunk
                    current_chunk = f"{overlap_text}{part_sep}{part}".strip()
                else:
                    current_chunk = part.strip()
        if current_chunk:
            chunks.append(current_chunk.strip())
        return chunks

    def _fixed_size_chunking(self, text, target_size, overlap):
        """固定长度兜底，在标点处截断"""
        chunks = []
        start = 0
        text_len = len(text)
        while start < text_len:
            end = min(start + target_size, text_len)
            chunk = text[start:end]
            # 优先在标点处截断
            for punct in ["。", "！", "？", ";", "；", "，", ","]:
                last_pos = chunk.rfind(punct)
                if last_pos != -1 and last_pos > target_size * 0.7:
                    chunk = chunk[:last_pos + 1]
                    end = start + last_pos + 1
                    break
            chunks.append(chunk.strip())
            start = end - overlap if overlap > 0 else end
        return chunks

    def clean_text(self, text):
        """兼容旧接口的文本清理方法"""
        # 移除多余的空格和换行
        text = re.sub(r'\s+', ' ', text)
        # 移除特殊字符但保留中文、英文、数字和常用标点
        text = re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9\s\.\,\!\?\;\\:\-\（\）\《\》\“\”\'\"]', '', text)
        return text.strip()