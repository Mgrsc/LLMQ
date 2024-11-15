from typing import Dict, Optional
from .services.base import DrawingService
from .services.siliconflow import SiliconFlowService
from nonebot.log import logger

class DrawingManager:
    def __init__(self):
        self.services: Dict[str, DrawingService] = {}
        
    def register_service(self, name: str, service: DrawingService):
        """注册绘画服务"""
        self.services[name] = service
        
    async def generate_image(
        self,
        service_name: str,
        prompt: str,
        size: str,
        steps: int,
        **kwargs
    ) -> tuple[bytes, float]:
        """使用指定服务生成图片"""
        if service_name not in self.services:
            logger.error(f"未找到服务: {service_name}")
            raise ValueError(f"未知的服务: {service_name}")
            
        service = self.services[service_name]
        try:
            result = await service.generate_image(prompt, size, steps, **kwargs)
            return result
        except Exception as e:
            logger.error(f"服务 {service_name} 生成图片失败: {str(e)}", exc_info=True)
            raise 