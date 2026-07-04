import openai
import asyncio
from typing import List, Dict, Optional
from .config import settings

openai.api_key = settings.OPENAI_API_KEY

async def embed_text(text: str) -> List[float]:
    # run in thread because openai is sync
    loop = asyncio.get_event_loop()
    def _call():
        resp = openai.Embedding.create(model=settings.OPENAI_EMBEDDING_MODEL, input=text)
        return resp['data'][0]['embedding']
    emb = await loop.run_in_executor(None, _call)
    return emb

async def chat_completion(messages: List[Dict], temperature: Optional[float] = None) -> Dict:
    loop = asyncio.get_event_loop()
    def _call():
        return openai.ChatCompletion.create(model=settings.OPENAI_CHAT_MODEL, messages=messages, temperature=(temperature if temperature is not None else settings.TEMPERATURE))
    resp = await loop.run_in_executor(None, _call)
    return resp

async def generate_image(prompt: str, size: str = "1024x1024") -> Optional[str]:
    loop = asyncio.get_event_loop()
    def _call():
        resp = openai.Image.create(prompt=prompt, size=size)
        return resp['data'][0]['url']
    url = await loop.run_in_executor(None, _call)
    return url
