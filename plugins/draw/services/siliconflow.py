from .base import DrawingService
import httpx
from typing import Dict, Any
import asyncio
from nonebot.log import logger

class SiliconFlowService(DrawingService):
    def __init__(
        self,
        api_key: str,
        api_url: str,
        model: str,
        timeout: int = 60,
        max_retries: int = 3,
        retry_delay: int = 5
    ):
        self.api_key = api_key
        self.api_url = api_url
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        
    async def generate_image(
        self,
        prompt: str,
        size: str,
        steps: int,
        **kwargs
    ) -> tuple[bytes, float]:
        """调用 Silicon Flow API 生成图片"""
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": self.model,
            "prompt": prompt,
            "image_size": size,
            "num_inference_steps": steps
        }
        
        # 重试逻辑
        for i in range(self.max_retries):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(
                        self.api_url,
                        json=payload,
                        headers=headers
                    )
                    
                    if response.status_code != 200:
                        logger.error(f"API 错误响应: {response.text}")
                        raise Exception(f"API返回错误: {response.status_code}")
                        
                    result = response.json()
                    image_url = result["images"][0]["url"]
                    inference_time = result["timings"]["inference"]
                    
                    # 下载图片
                    img_response = await client.get(image_url)
                    
                    if img_response.status_code != 200:
                        logger.error(f"图片下载失败: {img_response.text}")
                        raise Exception("图片下载失败")
                        
                    return img_response.content, inference_time
                    
            except Exception as e:
                if i < self.max_retries - 1:
                    logger.warning(f"第{i+1}次重试失败: {str(e)}")
                    await asyncio.sleep(self.retry_delay)
                else:
                    logger.error("已达到最大重试次数，放弃重试")
                    raise