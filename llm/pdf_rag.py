import torch
from chromadb import PersistentClient
from sentence_transformers import SentenceTransformer
import os
import warnings
import time
import fitz  # PyMuPDF
import re
from collections import Counter
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import requests
from llm.pdf_chunk import PDFProcessor
from llm.VolcengineLLM import VolcengineLLM
from llm.key_data import llm_key
# 忽略所有警告
warnings.filterwarnings("ignore")


class OptimizedRAGSystem:
    def __init__(self, chroma_path="../fastapi_chat/databases/chroma_db", collection_name="pdf_document"):
        """初始化 RAG 系统，支持PDF文档处理"""
        # 设置环境
        os.environ['TRANSFORMERS_OFFLINE'] = '1'

        self.performance_stats = {}
        start_time = time.time()

        # 设备选择 - 强制使用 CPU（避免兼容性问题）
        self.device = "cpu"
        print("ℹ️ 使用 CPU 运行")

        # 初始化向量数据库
        print("📁 初始化向量数据库...")
        db_start = time.time()
        self.client = PersistentClient(path=chroma_path)
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"}  # 使用余弦相似度
        )
        db_time = time.time() - db_start
        print(f"  数据库初始化完成: {db_time:.2f}秒")

        # 加载嵌入模型 - 使用更小的模型
        print("🧠 加载嵌入模型...")
        model_start = time.time()

        # 使用更小的模型加速加载
        model_name = "/Users/dozelee/PycharmProjects/FastAPIProject/LLM/all-MiniLM-L6-v2"

        try:
            self.embed_model = SentenceTransformer(model_name, device=self.device)
            # 简单的预热
            self.embed_model.encode(["warmup"])
            model_time = time.time() - model_start
            print(f"  模型加载完成: {model_time:.2f}秒")
            print(f"  模型名称: {model_name}")
            print(f"  向量维度: {self.embed_model.get_sentence_embedding_dimension()}")
        except Exception as e:
            print(f"❌ 模型加载失败: {e}")
            raise

        # 初始化大模型客户端
        print("🌐 初始化大模型客户端...")
        llm_start = time.time()
        try:
            self.llm_client = VolcengineLLM(
                api_key=llm_key.api_key,
                model_name="doubao-seed-1-6-thinking-250715",
                temperature=0.5,
                max_tokens=1024
            )
            llm_time = time.time() - llm_start
            print(f"  大模型客户端就绪: {llm_time:.2f}秒")
        except Exception as e:
            print(f"❌ 大模型客户端初始化失败: {e}")
            self.llm_client = None

        # 初始化PDF处理器（核心：复用独立模块）
        self.pdf_processor = PDFProcessor()

        # 总初始化时间
        total_time = time.time() - start_time
        print(f"🎯 系统初始化总时间: {total_time:.2f}秒")
        print("=" * 50)

        self.performance_stats['init_time'] = total_time

    # ------------------------------
    # 复用PDF处理器的核心方法
    # ------------------------------
    # def process_pdf_optimized(self, pdf_path, chunk_size=400, overlap=50):
    #     """优化的PDF处理流程（复用独立的PDFProcessor）"""
    #     print(f"📚 处理PDF文档: {pdf_path}")
    #
    #     # 复用PDF处理器的文件检查
    #     if not self.pdf_processor.check_pdf_file(pdf_path):
    #         return None
    #
    #     # 复用PDF处理器的内容提取
    #     full_text, page_texts = self.pdf_processor.extract_pdf_content(pdf_path)
    #     if not page_texts:
    #         return None
    #
    #     print("使用优化分块策略...")
    #     documents = []
    #     metadatas = []
    #     ids = []
    #
    #     for page_info in page_texts:
    #         page_num = page_info["page"]
    #         text = page_info["text"]
    #
    #         if not text.strip():
    #             continue
    #
    #         # 复用PDF处理器的增强分块
    #         chunks = self.pdf_processor.enhanced_chunking(text, chunk_size, overlap)
    #
    #         for i, chunk in enumerate(chunks):
    #             if len(chunk.strip()) < 20:  # 过滤太短的块
    #                 continue
    #
    #             chunk_id = f"page{page_num}_chunk{i + 1}"
    #
    #             # 存储原始文本（不添加额外标记，避免干扰向量化）
    #             documents.append(chunk.strip())
    #
    #             # 元数据
    #             metadatas.append({
    #                 "page": page_num,
    #                 "chunk_id": chunk_id,
    #                 "source": pdf_path,
    #                 "length": len(chunk)
    #             })
    #
    #             ids.append(chunk_id)
    #
    #     print(f"✅ 处理完成: {len(documents)} 个文本块")
    #     return documents, metadatas, ids

    def process_pdf_optimized(self, pdf_path, chunk_size=400, overlap=50):
        """优化的PDF处理流程（极简调用）"""
        print(f"📚 处理PDF文档: {pdf_path}")
        # 直接调用PDFProcessor的封装接口，无需手动遍历/过滤
        documents, metadatas, ids = self.pdf_processor.get_pdf_chunks_for_rag(pdf_path, chunk_size, overlap)
        return documents, metadatas, ids


    def load_pdf_document(self, pdf_path, chunk_size=400, overlap=50):
        """加载PDF文档到向量数据库"""
        print(f"\n📂 开始处理PDF文档: {pdf_path}")
        start_time = time.time()

        result = self.process_pdf_optimized(pdf_path, chunk_size, overlap)
        if not result:
            return False

        documents, metadatas, ids = result

        if not documents:
            print("❌ 未能从PDF中提取有效文本块")
            return False

        # 添加到向量数据库
        self.add_documents_optimized(
            documents=documents,
            metadatas=metadatas,
            ids=ids
        )

        total_time = time.time() - start_time
        print(f"✅ PDF文档处理完成，总耗时: {total_time:.2f}秒")
        print("=" * 50)
        return True

    # ------------------------------
    # 保留RAG核心功能（向量库、查询、LLM调用）
    # ------------------------------
    def add_documents_optimized(self, documents, metadatas=None, ids=None, batch_size=16):
        """优化的文档添加，提高处理速度"""
        if not documents:
            print("⚠️ 没有文档可添加")
            return

        print(f"📝 开始处理 {len(documents)} 个文档...")
        start_time = time.time()

        # 单批次处理，减少编码开销
        embeddings = self.embed_model.encode(
            documents,
            convert_to_tensor=False,
            show_progress_bar=True,  # 显示进度条
            normalize_embeddings=True,
            batch_size=batch_size
        )

        # 准备文档ID
        if ids is None:
            ids = [f"doc_{i}" for i in range(len(documents))]

        # 存入向量数据库
        self.collection.add(
            documents=documents,
            embeddings=embeddings.tolist(),
            metadatas=metadatas,
            ids=ids
        )

        total_time = time.time() - start_time
        print(f"✅ 文档添加完成! 总计 {total_time:.2f}秒")
        print("=" * 50)

        self.performance_stats['add_docs_time'] = total_time
        self.performance_stats['total_documents'] = len(documents)

    def query_optimized(self, question, n_results=5, similarity_threshold=0.6):
        """优化的查询方法"""
        if not question.strip():
            return "查询问题不能为空"

        print(f"🔍 查询: '{question}'")
        start_time = time.time()

        # 编码查询
        query_embedding = self.embed_model.encode(question, normalize_embeddings=True)

        # 检索
        results = self.collection.query(
            query_embeddings=[query_embedding.tolist()],
            n_results=min(n_results * 2, 20),
            include=["documents", "metadatas", "distances"]
        )

        retrieved_docs = results["documents"][0] if results["documents"] else []
        retrieved_metadatas = results["metadatas"][0] if results["metadatas"] else []
        distances = results["distances"][0] if results["distances"] else []

        # 筛选结果
        filtered_docs = []
        filtered_metadatas = []

        for doc, meta, distance in zip(retrieved_docs, retrieved_metadatas, distances):
            similarity = 1 - distance
            if similarity >= similarity_threshold:
                filtered_docs.append(doc)
                filtered_metadatas.append(meta)
                print(f"  相似度: {similarity:.3f}")

        print(f"  找到 {len(filtered_docs)} 个相关文档")

        if not filtered_docs:
            print("⚠️ 未找到高相似度文档")

            # 使用最高相似度结果
            if retrieved_docs:
                print("  使用最高相似度结果...")
                best_doc = retrieved_docs[0]
                best_meta = retrieved_metadatas[0]
                best_similarity = 1 - distances[0]
                print(f"  最高相似度: {best_similarity:.3f}")
                prompt = self._build_enhanced_prompt([best_doc], [best_meta], question)
                answer = self._call_llm(prompt)
            else:
                answer = "抱歉，在文档中未找到相关信息。"
        else:
            prompt = self._build_enhanced_prompt(filtered_docs, filtered_metadatas, question)
            answer = self._call_llm(prompt)

        total_time = time.time() - start_time
        print(f"🤖 回答: {answer}")
        print(f"⏱️ 查询耗时: {total_time:.2f}秒")
        return answer

    def _build_enhanced_prompt(self, documents, metadatas, question):
        """构建增强的提示词"""
        context_parts = []

        for i, (doc, meta) in enumerate(zip(documents, metadatas)):
            page_info = f"（第{meta.get('page', '未知')}页）" if meta else ""
            context_parts.append(f"【片段{i + 1}{page_info}】\n{doc}")

        context_str = "\n\n".join(context_parts)

        prompt = f"""请仔细分析以下文档片段，然后回答问题。请确保回答基于提供的资料。

        文档内容：
        {context_str}
    
        问题：{question}
        
        要求：
        1. 如果资料中有相关信息，请基于资料回答
        2. 如果资料中没有相关信息，请明确说明"资料中未找到相关信息"
        3. 回答时请注明信息来源的页码（如果资料中提供了页码）
        4. 如果上下文强烈暗示了答案，即便未说明也可以推理回答
        
        请开始回答："""
        return prompt

    def _call_llm(self, prompt):
        """LLM调用方法：添加限流重试和请求间隔"""
        if self.llm_client is None:
            return "大模型服务暂不可用"

        # 定义重试逻辑：最多重试3次，间隔2s→4s→8s（指数退避）
        @retry(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=2, max=10),
            retry=retry_if_exception_type((requests.exceptions.HTTPError, requests.exceptions.RequestException))
        )
        def send_llm_request():
            # 每次请求前加1秒间隔，降低QPS（核心：避免短时间内多次调用）
            time.sleep(1)
            try:
                # 调用 VolcengineLLM，捕获HTTP错误（如429）
                response = self.llm_client.invoke(prompt)
                # 若返回的是错误提示（如VolcengineLLM内部捕获429后返回字符串），手动抛出异常触发重试
                if isinstance(response, str) and ("429" in response or "Too Many Requests" in response):
                    raise requests.exceptions.HTTPError(f"429 Too Many Requests: {response}")
                return response
            except Exception as e:
                # 捕获 VolcengineLLM 内部抛出的HTTP错误
                if isinstance(e, requests.exceptions.HTTPError) and "429" in str(e):
                    print(f"⚠️ 触发限流，将重试... 错误信息：{str(e)[:100]}")
                    raise  # 抛出异常，触发重试
                # 其他错误（如500）也重试，但限制次数
                print(f"⚠️ LLM调用异常，将重试... 错误信息：{str(e)[:50]}")
                raise

        try:
            return send_llm_request()
        except Exception as e:
            # 重试3次后仍失败，返回友好提示
            error_msg = f"抱歉，当前请求过于频繁，请稍后再试。错误详情：{str(e)[:100]}"
            print(f"❌ LLM调用最终失败: {error_msg}")
            return error_msg

    def query_with_debug(self, question, n_results=5):
        """带调试信息的查询，用于分析问题"""
        print(f"🔍 调试查询: '{question}'")

        # 编码查询问题
        query_embedding = self.embed_model.encode(question)

        # 检索结果
        results = self.collection.query(
            query_embeddings=[query_embedding.tolist()],
            n_results=n_results,
            include=["documents", "metadatas", "distances"]
        )

        temp = []
        print("📊 检索结果分析:")
        for i, (doc, meta, dist) in enumerate(zip(
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0]
        )):
            similarity = 1 - dist
            page = meta.get('page', '未知') if meta else '未知'
            print(f"  {i + 1}. 相似度: {similarity:.4f} | 页码: {page}")
            print(f"     内容: {doc[:100]}...")
            temp.append(doc+"\n")

        # with open("temp1.txt", 'w', encoding='utf-8') as f:
        #     f.write(''.join(temp))
        return self.query_optimized(question, n_results)

    def get_collection_info(self):
        """获取集合信息"""
        try:
            count = self.collection.count()
            print(f"📊 集合信息: 文档数量: {count}")
            return count
        except Exception as e:
            print(f"❌ 获取集合信息失败: {e}")
            return 0

    def clear_collection(self):
        """清空当前集合"""
        try:
            count_before = self.collection.count()
            self.client.delete_collection(name=self.collection.name)
            self.collection = self.client.get_or_create_collection(name=self.collection.name)
            print(f"🧹 已清空集合，之前有 {count_before} 个文档")
        except Exception as e:
            print(f"❌ 清空集合失败: {e}")


if __name__ == "__main__":
    """测试优化后的RAG系统"""
    rag = OptimizedRAGSystem(collection_name="optimized_pdf")

    # 清空并重新加载
    rag.clear_collection()

    # 加载PDF文档
    pdf_path = "/Users/dozelee/PycharmProjects/FastAPIProject/LLM/resource/mac_user.pdf"
    if not rag.load_pdf_document(pdf_path, chunk_size=350, overlap=30):
        print("❌ PDF加载失败")

    # 显示集合信息，分块数量
    rag.get_collection_info()

    # 测试查询
    test_queries = [
        # "电池保养有什么建议？",
        # "Touch ID有哪些功能？",
        # "MacBook如何连接WiFi？",
        # "如何延长电池寿命？",
        # "'延长电池寿命'这个关键词相关语句有哪些",
        "MacBook Air的重量是多少？",
        # "优化MacBookAir4的续航有哪些可行的操作方法"
    ]

    print("\n🧪 开始优化查询测试...")
    for i, query in enumerate(test_queries, 1):
        print(f"\n{'=' * 60}")
        print(f"测试查询 {i}/{len(test_queries)}: {query}")
        print(f"{'=' * 60}")

        # 使用带调试的查询来查看检索过程
        answer = rag.query_with_debug(query, n_results=3)
        print(f"✅ 最终回答: {answer}")



