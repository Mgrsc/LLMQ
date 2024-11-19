import re
import random
import os
import base64
from pathlib import Path
from nonebot import on_message
from nonebot.rule import Rule
from nonebot.adapters.onebot.v11 import MessageSegment, Message
from nonebot.typing import T_State
from nonebot.adapters.onebot.v11 import Bot, Event
from PIL import Image
import io
import logging

from .config import config

def merge_money_images(amount: int, offset_x: int = 60, offset_y: int = 40) -> Image.Image:
    """根据金额合成重叠的人民币图片"""
    try:
        if not 1 <= amount <= config.max_amount:
            return None

        image_dir = Path(config.image_dir)
        images = {
            1: str(image_dir / "1.png"),
            5: str(image_dir / "5.png"),
            10: str(image_dir / "10.png"),
            20: str(image_dir / "20.png"),
            50: str(image_dir / "50.png"),
            100: str(image_dir / "100.png"),
        }

        counts = {denomination: 0 for denomination in images}
        remaining_amount = amount

        for denomination in sorted(images.keys(), reverse=True):
            while remaining_amount >= denomination:
                counts[denomination] += 1
                remaining_amount -= denomination

        # 如果只需要一张钞票，直接返回该面额的图片
        if sum(counts.values()) == 1:
            denomination = next(d for d, c in counts.items() if c > 0)
            try:
                with Image.open(images[denomination]) as img:
                    # 创建副本避免文件锁定
                    return img.copy().convert("RGBA")
            except Exception as e:
                logging.error(f"打开图片失败: {str(e)}")
                return None

        # 多张钞票的合成逻辑
        first_image_path = next((path for path in images.values() if os.path.exists(path)), None)
        if not first_image_path:
            return None

        with Image.open(first_image_path) as first_image:
            width, height = first_image.size
            total_offset_y = offset_y * (sum(counts.values()) - 1) if sum(counts.values()) > 1 else 0
            base_image = Image.new("RGBA", (width, height + total_offset_y), (255, 255, 255, 0))

            x_offset = 0
            y_offset = 0

            for denomination, count in counts.items():
                if count > 0:
                    try:
                        with Image.open(images[denomination]) as money_image:
                            for _ in range(count):
                                base_image.paste(money_image, (x_offset, y_offset), money_image)
                                y_offset += offset_y
                    except Exception as e:
                        logging.error(f"处理面额 {denomination} 时出错: {str(e)}")
                        return None

            return base_image

    except Exception as e:
        logging.error(f"合成图片时出错: {str(e)}")
        return None

def image_to_base64(image: Image.Image) -> str:
    """将 PIL Image 对象转换为 base64 字符串"""
    try:
        buffer = io.BytesIO()
        # 优化保存参数
        image.save(buffer, format="PNG", optimize=True, quality=85)
        return f"base64://{base64.b64encode(buffer.getvalue()).decode()}"
    except Exception as e:
        logging.error(f"图片转base64失败: {str(e)}")
        raise

async def check_money_message(event: Event) -> bool:
    """检查消息是否匹配转账模式"""
    msg = event.get_plaintext()
    for keyword in config.keywords:
        pattern = f"{keyword}(-?\\d+)"
        match = re.search(pattern, msg)
        if match:
            return True
    return False

money_matcher = on_message(rule=Rule(check_money_message))

@money_matcher.handle()
async def handle_money(bot: Bot, event: Event, state: T_State):
    msg = event.get_plaintext()
    amount = 0
    
    # 提取金额
    for keyword in config.keywords:
        pattern = f"{keyword}(-?\\d+)"
        match = re.search(pattern, msg)
        if match:
            amount = int(match.group(1))
            break
    
    # 检查负数
    if amount < 0:
        await money_matcher.finish(random.choice(config.negative_messages))
        return
    
    # 检查零元
    if amount == 0:
        await money_matcher.finish("？")
        return
    
    # 检查金额范围
    if amount > config.max_amount:
        await money_matcher.finish(random.choice(config.exceed_messages))
        return
    
    # 合成图片
    result_image = merge_money_images(amount)
    if not result_image:
        await money_matcher.finish(random.choice(config.error_messages))
        return
        
    try:
        base64_str = image_to_base64(result_image)
        success_msg = random.choice(config.success_messages)
        
        # 合并图片和文字消息
        msg = Message([
            MessageSegment.image(base64_str),
            MessageSegment.text(success_msg)
        ])
        
        await money_matcher.send(msg)
        
    except Exception as e:
        logging.error(f"发送消息时出错: {str(e)}")
        await money_matcher.finish(random.choice(config.error_messages)) 