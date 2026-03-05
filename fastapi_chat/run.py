import uvicorn
from fastapi import FastAPI,Request
from fastapi.staticfiles import StaticFiles
from router import chat
import time
from fastapi.middleware.cors import CORSMiddleware


app = FastAPI(title="Chat_robot",description="learning",version="1.0")

app.mount("/static", StaticFiles(directory="static"), name="static")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True
)

@app.middleware("http")
async def procees_time_header(request: Request, call_next): # call_next:将接收到的request请求作为参数
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(process_time)
    return response

# app.include_router(app1, prefix="/app1", tags=["请求参数"])
app.include_router(chat, prefix="/chat", tags=["聊天接口"])

if __name__ == '__main__':
    uvicorn.run('run:app', host="127.0.0.1", port=8000, reload=True, workers=1)


