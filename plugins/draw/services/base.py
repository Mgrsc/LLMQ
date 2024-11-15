from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from pathlib import Path

class DrawingService(ABC):
    """绘画服务基类"""
    
    @abstractmethod
    async def generate_image(
        self,
        prompt: str,
        size: str,
        steps: int,
        **kwargs
    ) -> tuple[bytes, float]:
        """
        生成图片的抽象方法
        
        Args:
            prompt (str): 提示词
            size (str): 图片尺寸
            steps (int): 生成步数
            **kwargs: 其他参数
            
        Returns:
            tuple[bytes, float]: (图片数据, 生成用时)
        """
        pass 