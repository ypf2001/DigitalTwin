"""
马铃薯施肥灌溉数字孪生系统 — FastAPI 入口
==========================================
Spring-style 分层: routers → services → models
启动: python app.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import matplotlib
matplotlib.use('Agg')

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from routers import router

app = FastAPI(title="数字孪生 API", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(router)

_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

if __name__ == '__main__':
    import uvicorn
    print("\n" + "=" * 50)
    print("  数字孪生 API 服务")
    print("  http://localhost:5000")
    print("=" * 50 + "\n")
    uvicorn.run(app, host="0.0.0.0", port=5000)
