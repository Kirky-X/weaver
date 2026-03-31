- aiping API 速率限制：100 RPM

### llm chat 1

```python
from openai import OpenAI

openai_client = OpenAI(
    base_url="https://www.aiping.cn/api/v1",
    api_key="QC-6d94b3348de6a3fa2a286f887d5d8e9f-dfa9d1d5329f0914943035febbe28f28"
)

response = openai_client.chat.completions.create(
    model="GLM-4-9B-0414",
    stream=True,
    extra_body={
        "provider": {
            "only": [],
            "order": [],
            "sort": "input_price",
            "input_price_range": [0, 0],
            "output_price_range": [0, 0],
            "input_length_range": [],
            "output_length_range": [],
            "throughput_range": [],
            "latency_range": []
        }
    },
    messages=[
        {"role": "user", "content": "Hello"}
    ]
)

for chunk in response:
    if not getattr(chunk, "choices", None):
        continue

    reasoning_content = getattr(chunk.choices[0].delta, "reasoning_content", None)
    if reasoning_content:
        print(reasoning_content, end="", flush=True)

    content = getattr(chunk.choices[0].delta, "content", None)
    if content:
        print(content, end="", flush=True)
```

### llm chat 2

```python
from openai import OpenAI

openai_client = OpenAI(
    base_url="https://www.aiping.cn/api/v1",
    api_key="QC-aef60423ca9cf0daa26036c5538c2cef-4d2e85c55e8f9664a518c16dbebf65b9"
)

response = openai_client.chat.completions.create(
    model="GLM-Z1-9B-0414",
    stream=True,
    extra_body={
        "provider": {
            "only": [],
            "order": [],
            "sort": "input_price",
            "input_price_range": [0, 0],
            "output_price_range": [0, 0],
            "input_length_range": [],
            "output_length_range": [],
            "throughput_range": [],
            "latency_range": []
        }
    },
    messages=[
        {"role": "user", "content": "Hello"}
    ]
)

for chunk in response:
    if not getattr(chunk, "choices", None):
        continue

    reasoning_content = getattr(chunk.choices[0].delta, "reasoning_content", None)
    if reasoning_content:
        print(reasoning_content, end="", flush=True)

    content = getattr(chunk.choices[0].delta, "content", None)
    if content:
        print(content, end="", flush=True)
```

### embedding

```python
from openai import OpenAI

openai_client = OpenAI(
    base_url="https://www.aiping.cn/api/v1",
    api_key="QC-6d94b3348de6a3fa2a286f887d5d8e9f-dfa9d1d5329f0914943035febbe28f28",
)

response = openai_client.embeddings.create(
    model="Qwen3-Embedding-0.6B",
    input=["这是一段文本", "第二段文本"],
    extra_body={
        "provider": {
            "only": [],
            "order": [],
            "sort": "input_price",
            "input_price_range": [0, 0],
            "output_price_range": [],
            "input_length_range": [],
            "output_length_range": [],
            "throughput_range": [],
            "latency_range": []
        },
        "consume_type": "api"
    },
)

print(response)

```

### rerank

```python
import requests
import json

headers = {
    "Authorization": "Bearer QC-aef60423ca9cf0daa26036c5538c2cef-4d2e85c55e8f9664a518c16dbebf65b9",
    "Content-Type": "application/json"
}

payload = {
    "model": "Qwen3-Reranker-0.6B",
    "query": "什么是机器学习？",
    "documents": [
        "机器学习是人工智能的一个分支，它使计算机能够从数据中学习。",
        "深度学习是机器学习的一个子集，使用神经网络进行学习。",
        "Python是一种流行的编程语言，广泛用于数据科学。"
    ],
    "top_n": 2,
    "return_documents": True,
    "extra_body": {
        "provider": {
            "only": [],
            "order": [],
            "sort": "input_price",
            "input_price_range": [0, 0],
            "output_price_range": [],
            "input_length_range": [],
            "output_length_range": [],
            "throughput_range": [],
            "latency_range": []
        },
        "consume_type": "api"
    }
}

response = requests.post(
    "https://www.aiping.cn/api/v1/rerank",
    headers=headers,
    json=payload,
    timeout=30
)

print(response.status_code)
print(json.dumps(response.json(), ensure_ascii=False, indent=2))

```
