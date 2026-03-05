"""LLM聊天接口"""
from fastapi import APIRouter, HTTPException, Request, UploadFile, File, Form
from pydantic import BaseModel
import json,os,sys
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from llm.llm_main import SmartAgent
from llm.key_data import llm_key
from llm.pdf_rag import OptimizedRAGSystem
import tempfile


chat = APIRouter()
# 初始化全局智能助手实例（只初始化一次，避免重复创建）
agent = SmartAgent(volcengine_api_key=llm_key.api_key)

rag_system = OptimizedRAGSystem(
    chroma_path="../fastapi_chat/databases/chroma_db",
    collection_name="optimized_pdf_collection"
)

class ChatRequest(BaseModel):
    message: str  # 用户发送的消息

class RAGQueryRequest(BaseModel):
    question: str  # 用户的提问
    n_results: int = 5  # 检索结果数量
    similarity_threshold: float = 0.6  # 相似度阈值

@chat.get("/")
async def read_index():
    """返回根路径，提供前端聊天界面"""
    return FileResponse('./static/index.html')


@chat.get("/health")
async def health_check():
    return {"status": "ok"}


# 聊天接口：接收用户消息，返回 AI 回答
@chat.post("/send")
async def send_message(request: ChatRequest):
    """
    接收用户消息，调用智能助手返回回答
    请求示例：{"message": "3+2等于多少"}
    响应示例：{"message": "3+2等于多少", "answer": "3+2 = 5", "success": true}
    """
    try:
        # 调用智能助手获取回答
        answer = agent.invoke(request.message)
        re_answer = answer[:-3]  # 为了修正使用agent后返回值带有```的工具格式问题，是LLM返回文字问题
        return {
            "message": request.message,
            "answer": re_answer,
            "success": True
        }
    except Exception as e:
        # 异常处理，返回友好提示
        raise HTTPException(
            status_code=500,
            detail=f"聊天接口调用失败：{str(e)}"
        )

# 额外接口：获取聊天历史
@chat.get("/history")
async def get_chat_history():
    """获取当前会话的聊天历史"""
    try:
        history = agent.get_chat_history()
        print(history)
        return {
            "history": history,
            "success": True
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"获取历史记录失败：{str(e)}"
        )

# 额外接口：清空聊天历史
@chat.post("/clear")
async def clear_chat_history():
    """清空聊天历史"""
    try:
        agent.clear_history()
        return {
            "message": "聊天历史已清空",
            "success": True
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"清空历史记录失败：{str(e)}"
        )


@chat.post("/rag/upload-pdf")
async def upload_pdf(
        file: UploadFile = File(...),
        chunk_size: int = Form(default=400),
        overlap: int = Form(default=30)
):
    """
    上传PDF文件并加载到向量数据库
    - file: PDF文件
    - chunk_size: 文本分块大小
    - overlap: 分块重叠长度
    """
    # 1. 校验文件类型
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="仅支持PDF文件上传")

    # 2. 创建临时文件（避免文件残留）
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_file:
            # 写入上传的文件内容
            content = await file.read()
            temp_file.write(content)
            temp_file_path = temp_file.name

        # 3. 加载PDF到向量库
        success = rag_system.load_pdf_document(
            pdf_path=temp_file_path,
            chunk_size=chunk_size,
            overlap=overlap
        )

        # 4. 删除临时文件
        os.unlink(temp_file_path)

        if success:
            # 获取向量库文档数量
            doc_count = rag_system.get_collection_info()
            return JSONResponse({
                "success": True,
                "message": f"PDF文件上传并加载成功！已处理为{doc_count}个文本块",
                "doc_count": doc_count
            })
        else:
            raise HTTPException(status_code=500, detail="PDF文件加载失败")

    except Exception as e:
        # 确保临时文件被删除
        if 'temp_file_path' in locals() and os.path.exists(temp_file_path):
            os.unlink(temp_file_path)
        raise HTTPException(
            status_code=500,
            detail=f"PDF上传失败：{str(e)}"
        )


@chat.post("/rag/query")
async def rag_query(request: RAGQueryRequest):
    """
    对已加载的PDF文档进行提问
    """
    try:
        # 调用RAG查询
        answer = rag_system.query_optimized(
            question=request.question,
            n_results=request.n_results,
            similarity_threshold=request.similarity_threshold
        )

        return JSONResponse({
            "success": True,
            "question": request.question,
            "answer": answer
        })
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"RAG查询失败：{str(e)}"
        )


@chat.post("/rag/clear")
async def clear_rag_collection():
    """清空向量数据库"""
    try:
        rag_system.clear_collection()
        return JSONResponse({
            "success": True,
            "message": "向量数据库已清空"
        })
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"清空向量库失败：{str(e)}"
        )


@chat.get("/rag/info")
async def get_rag_info():
    """获取向量库信息"""
    try:
        doc_count = rag_system.get_collection_info()
        return JSONResponse({
            "success": True,
            "collection_name": rag_system.collection.name,
            "document_count": doc_count,
            "chroma_path": rag_system.client.path
        })
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"获取向量库信息失败：{str(e)}"
        )