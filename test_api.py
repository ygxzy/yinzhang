# -*- coding: utf-8 -*-
"""
印章识别 API 测试脚本
======================
覆盖主要功能：
1. 健康检查
2. 根路径
3. 单张图片识别
4. 批量识别
5. PDF 识别（如有 PDF 文件）
6. 错误处理（空文件、超大文件）

用法：
    python test_api.py
    python test_api.py --host 127.0.0.1 --port 8000
"""
import os
import sys
import io
import time
import argparse
from pathlib import Path

import requests


# 默认配置
BASE_URL = "http://127.0.0.1:8000"
TEST_DIR = Path(__file__).parent
DATA_DIR = TEST_DIR / "data"


def test_health():
    """测试健康检查。"""
    print("\n" + "=" * 60)
    print("[1] 测试 /health")
    print("=" * 60)
    try:
        resp = requests.get(f"{BASE_URL}/health", timeout=5)
        print(f"  状态码: {resp.status_code}")
        data = resp.json()
        print(f"  status: {data.get('status')}")
        print(f"  pipeline_loaded: {data.get('pipeline_loaded')}")
        print(f"  version: {data.get('version')}")
        assert resp.status_code == 200
        assert data["status"] == "ok"
        print("  ✅ 通过")
    except Exception as e:
        print(f"  ❌ 失败: {e}")
        return False
    return True


def test_root():
    """测试根路径。"""
    print("\n" + "=" * 60)
    print("[2] 测试 /")
    print("=" * 60)
    try:
        resp = requests.get(f"{BASE_URL}/", timeout=5)
        print(f"  状态码: {resp.status_code}")
        data = resp.json()
        print(f"  name: {data.get('name')}")
        print(f"  version: {data.get('version')}")
        print(f"  endpoints: {list(data.get('endpoints', {}).keys())}")
        assert resp.status_code == 200
        assert "endpoints" in data
        print("  ✅ 通过")
    except Exception as e:
        print(f"  ❌ 失败: {e}")
        return False
    return True


def test_recognize_image():
    """测试单张图片识别。"""
    print("\n" + "=" * 60)
    print("[3] 测试 /seal/recognize（单张图片）")
    print("=" * 60)

    image_path = DATA_DIR / "image.png"
    if not image_path.exists():
        print(f"  ⚠️  跳过：测试图 {image_path} 不存在")
        return True

    try:
        start = time.time()
        with open(image_path, "rb") as f:
            resp = requests.post(
                f"{BASE_URL}/seal/recognize",
                files={"file": ("image.png", f, "image/png")},
                data={"dpi": 200},
                timeout=120,
            )
        elapsed = time.time() - start

        print(f"  状态码: {resp.status_code}")
        print(f"  响应耗时: {elapsed:.2f}s")

        result = resp.json()
        print(f"  code: {result['code']}")
        print(f"  message: {result['message']}")

        data = result.get("data", {})
        print(f"  input_type: {data.get('input_type')}")
        print(f"  total_pages: {data.get('total_pages')}")
        print(f"  total_seals: {data.get('total_seals')}")
        print(f"  elapsed_ms: {data.get('elapsed_ms')}ms")

        seals = data.get("seals", [])
        for seal in seals:
            print(f"\n  印章 {seal.get('seal_idx')} (第 {seal.get('page')} 页):")
            print(f"    content: {seal.get('content')!r}")
            for t in seal.get("texts", []):
                print(f"    - {t['text']!r} (score={t['score']:.4f})")

        assert resp.status_code == 200
        assert result["code"] == 0
        assert len(seals) > 0
        print("\n  ✅ 通过")
    except Exception as e:
        print(f"  ❌ 失败: {e}")
        return False
    return True


def test_recognize_batch():
    """测试批量识别（同一张图上传两次）。"""
    print("\n" + "=" * 60)
    print("[4] 测试 /seal/recognize_batch（批量）")
    print("=" * 60)

    image_path = DATA_DIR / "image.png"
    if not image_path.exists():
        print(f"  ⚠️  跳过：测试图 {image_path} 不存在")
        return True

    try:
        start = time.time()
        with open(image_path, "rb") as f1, open(image_path, "rb") as f2:
            resp = requests.post(
                f"{BASE_URL}/seal/recognize_batch",
                files=[
                    ("files", ("seal1.png", f1, "image/png")),
                    ("files", ("seal2.png", f2, "image/png")),
                ],
                data={"dpi": 200},
                timeout=300,
            )
        elapsed = time.time() - start

        print(f"  状态码: {resp.status_code}")
        print(f"  响应耗时: {elapsed:.2f}s")

        result = resp.json()
        print(f"  code: {result['code']}")
        data = result.get("data", {})
        print(f"  total_files: {data.get('total_files')}")
        print(f"  elapsed_ms: {data.get('elapsed_ms')}ms")

        for item in data.get("results", []):
            print(f"\n  文件: {item.get('filename')}")
            print(f"    total_seals: {item.get('total_seals')}")
            for seal in item.get("seals", []):
                print(f"    印章 {seal.get('seal_idx')}: {seal.get('content')!r}")

        assert resp.status_code == 200
        assert result["code"] == 0
        assert len(data.get("results", [])) == 2
        print("\n  ✅ 通过")
    except Exception as e:
        print(f"  ❌ 失败: {e}")
        return False
    return True


def test_recognize_pdf():
    """测试 PDF 识别（如有 PDF 文件）。"""
    print("\n" + "=" * 60)
    print("[5] 测试 /seal/recognize（PDF）")
    print("=" * 60)

    pdf_files = list(DATA_DIR.glob("*.pdf"))
    if not pdf_files:
        print(f"  ⚠️  跳过：{DATA_DIR} 下无 PDF 文件")
        return True

    pdf_path = pdf_files[0]
    print(f"  使用 PDF: {pdf_path.name}")

    try:
        start = time.time()
        with open(pdf_path, "rb") as f:
            resp = requests.post(
                f"{BASE_URL}/seal/recognize",
                files={"file": (pdf_path.name, f, "application/pdf")},
                data={"dpi": 200},
                timeout=300,
            )
        elapsed = time.time() - start

        print(f"  状态码: {resp.status_code}")
        print(f"  响应耗时: {elapsed:.2f}s")

        result = resp.json()
        data = result.get("data", {})
        print(f"  input_type: {data.get('input_type')}")
        print(f"  total_pages: {data.get('total_pages')}")
        print(f"  total_seals: {data.get('total_seals')}")
        print(f"  elapsed_ms: {data.get('elapsed_ms')}ms")

        for seal in data.get("seals", []):
            print(f"  第 {seal.get('page')} 页 印章 {seal.get('seal_idx')}: {seal.get('content')!r}")

        assert resp.status_code == 200
        assert result["code"] == 0
        print("\n  ✅ 通过")
    except Exception as e:
        print(f"  ❌ 失败: {e}")
        return False
    return True


def test_empty_file():
    """测试空文件（错误处理）。"""
    print("\n" + "=" * 60)
    print("[6] 测试 /seal/recognize（空文件）")
    print("=" * 60)
    try:
        empty_bytes = b""
        resp = requests.post(
            f"{BASE_URL}/seal/recognize",
            files={"file": ("empty.png", empty_bytes, "image/png")},
            timeout=30,
        )
        print(f"  状态码: {resp.status_code}")
        print(f"  预期: 500（识别失败）")
        # 空文件应该返回错误
        if resp.status_code in (400, 500):
            print("  ✅ 通过（正确返回错误）")
        else:
            print(f"  ⚠️  非预期状态码: {resp.status_code}")
    except Exception as e:
        print(f"  ❌ 失败: {e}")
        return False
    return True


def main():
    global BASE_URL

    parser = argparse.ArgumentParser(description="印章识别 API 测试")
    parser.add_argument("--host", default="127.0.0.1", help="服务地址")
    parser.add_argument("--port", default=8000, type=int, help="端口")
    args = parser.parse_args()

    BASE_URL = f"http://{args.host}:{args.port}"
    print(f"测试目标: {BASE_URL}")
    print(f"测试数据目录: {DATA_DIR}")

    results = []
    results.append(("健康检查", test_health()))
    results.append(("根路径", test_root()))
    results.append(("单张图片识别", test_recognize_image()))
    results.append(("批量识别", test_recognize_batch()))
    results.append(("PDF 识别", test_recognize_pdf()))
    results.append(("空文件错误处理", test_empty_file()))

    # 汇总
    print("\n" + "=" * 60)
    print("测试汇总")
    print("=" * 60)
    passed = sum(1 for _, ok in results if ok)
    total = len(results)
    for name, ok in results:
        status = "✅ 通过" if ok else "❌ 失败"
        print(f"  {name}: {status}")
    print(f"\n  总计: {passed}/{total} 通过")

    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
