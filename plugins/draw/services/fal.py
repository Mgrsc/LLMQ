from .base import DrawingService
import fal_client
import base64
from typing import Dict, Any
import os
from nonebot.log import logger

class FALService(DrawingService):
    def __init__(
        self,
        api_key: str,
        model: str = "fal-ai/flux-pro/v1.1-ultra",
        enable_safety_checker: bool = False,
        safety_tolerance: str = "5",
        output_format: str = "jpeg",
        sync_mode: bool = True,
        aspect_ratios: Dict[str, str] = None,
        timeout: int = 60,
        max_retries: int = 3,
        retry_delay: int = 5
    ):
        self.model = model
        self.enable_safety_checker = enable_safety_checker
        self.safety_tolerance = safety_tolerance
        self.output_format = output_format
        self.sync_mode = sync_mode
        self.aspect_ratios = aspect_ratios or {
            "landscape": "16:9",
            "portrait": "9:16",
            "square": "1:1"
        }
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        # 设置 FAL API key
        os.environ["FAL_KEY"] = api_key
        
    def _get_aspect_ratio(self, size: str) -> str:
        """根据尺寸获取宽高比"""
        try:
            width, height = map(int, size.split('x'))
            if width > height:
                return self.aspect_ratios["landscape"]
            elif width < height:
                return self.aspect_ratios["portrait"]
            else:
                return self.aspect_ratios["square"]
        except:
            return self.aspect_ratios["square"]  # 默认正方形
            
    async def generate_image(
        self,
        prompt: str,
        size: str,
        steps: int,  # 这个参数会被忽略
        **kwargs
    ) -> tuple[bytes, float]:
        """调用 FAL API 生成图片"""
        try:
            # 准备参数
            arguments = {
                "prompt": prompt,
                "enable_safety_checker": self.enable_safety_checker,
                "safety_tolerance": self.safety_tolerance,
                "output_format": self.output_format,
                "aspect_ratio": self._get_aspect_ratio(size),
                "sync_mode": self.sync_mode
            }
            
            logger.info(f"调用 FAL API，模型：{self.model}")
            logger.info(f"参数：{arguments}")
            
            # 提交请求
            result = fal_client.submit(
                self.model,
                arguments=arguments
            )
            
            request_id = result.request_id
            logger.info(f"FAL 请求 ID: {request_id}")
            
            # 获取结果
            result = fal_client.result(self.model, request_id)
            
            if not result.get('images'):
                raise Exception("未获取到图片结果")
                
            # 获取第一张图片的 base64 数据
            image_data = result['images'][0]['url']
            
            if not image_data.startswith("data:image"):
                raise Exception("图片数据格式错误")
                
            # 解码 base64 数据
            base64_data = image_data.split(",")[1]
            image_bytes = base64.b64decode(base64_data)
            
            # FAL API 不返回推理时间，这里返回 0
            return image_bytes, 0.0
            
        except Exception as e:
            logger.error(f"FAL 服务生成图片失败: {str(e)}")
            raise