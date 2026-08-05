"""測試 Ollama OpenAI 端點的 think:false 是否生效（容器內執行）。"""
import asyncio
import sys

sys.path.insert(0, "/code")

from openai import AsyncOpenAI


async def main():
    client = AsyncOpenAI(base_url="http://host.docker.internal:11434/v1", api_key="ollama")
    resp = await client.chat.completions.create(
        model="qwen3.6:35b",
        messages=[{"role": "user", "content": 'Reply with JSON only: {"answer": 2}'}],
        max_tokens=4096,
        temperature=0.0,
        extra_body={"think": False},
    )
    print("finish:", resp.choices[0].finish_reason)
    print("content:", repr(resp.choices[0].message.content))

    # 對照組：不帶 think
    resp2 = await client.chat.completions.create(
        model="qwen3.6:35b",
        messages=[{"role": "user", "content": 'Reply with JSON only: {"answer": 2}'}],
        max_tokens=4096,
        temperature=0.0,
    )
    print("no-think-param finish:", resp2.choices[0].finish_reason)
    print("no-think-param content:", repr((resp2.choices[0].message.content or "")[:200]))


asyncio.run(main())
