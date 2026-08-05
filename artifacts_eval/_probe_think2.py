"""長 prompt + think:false 的完整回應檢查（容器內執行）。"""
import asyncio
import sys

sys.path.insert(0, "/code")

from openai import AsyncOpenAI
from app.services import source_verifier as sv


async def main():
    client = AsyncOpenAI(base_url="http://host.docker.internal:11434/v1", api_key="ollama")
    # 模擬真實長度：12 段各 ~800 字 + 長回答
    chunks = [("【文件%d.pdf】\n" % i) + "營利事業所得稅結算申報相關說明文字，包含各項扣除額與稅率規定。" * 25 for i in range(12)]
    answer = ("根據文件，公司名稱是八策數位股份有限公司，統一編號為 83028948。"
              "本期應納稅額為 1,234 元。此外，文件提到多項扣除額規定，包括薪資特別扣除、"
              "身心障礙扣除、以及長期照顧扣除等項目，每項都有其適用條件與上限。" * 3)
    parts = [f"【片段 #{i}】\n{c}" for i, c in enumerate(chunks, 1)]
    user_prompt = (f"問題：基本資料？\n\n回答草稿：\n{answer}\n\n文件片段：\n"
                   + "\n\n".join(parts) + "\n\n" + sv._INSTRUCTION)
    print("prompt chars:", len(user_prompt))

    resp = await client.chat.completions.create(
        model="qwen3.6:35b",
        messages=[{"role": "system", "content": sv._SYSTEM},
                  {"role": "user", "content": user_prompt}],
        max_tokens=4096, temperature=0.0,
        extra_body={"think": False},
    )
    ch = resp.choices[0]
    print("finish:", ch.finish_reason)
    print("content len:", len(ch.message.content or ""))
    msg = ch.message
    print("has reasoning_content:", hasattr(msg, "reasoning_content"),
          repr(getattr(msg, "reasoning_content", None))[:120])
    if resp.usage:
        print("usage:", resp.usage)


asyncio.run(main())
