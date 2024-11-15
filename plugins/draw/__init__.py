from nonebot import on_message
from nonebot.adapters.onebot.v11 import Message, MessageEvent, MessageSegment
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule
import tomli
from pathlib import Path
import httpx
import asyncio
from typing import Optional, Dict, Tuple
from nonebot.log import logger
from datetime import datetime, timedelta
import re
import random
from nonebot.exception import FinishedException
import json

from .drawing_manager import DrawingManager
from .services.siliconflow import SiliconFlowService
from .services.fal import FALService

__plugin_meta__ = PluginMetadata(
    name="AI绘图",
    description="使用FLUX进行AI绘图",
    usage="""使用方法：
    {bot_name}画 <描述文字>""",
    config=None,
)

# 读取配置文件
config_file = Path("config.toml")
if not config_file.exists():
    raise ValueError("配置文件 config.toml 不存在")

with open(config_file, "rb") as f:
    config = tomli.load(f)
    draw_config = config["draw"]  # 改用 draw 配置
    messages_config = config["messages"]  # 读取通用消息配置

# 获取配置
API_KEY = draw_config["api_key"]
API_URL = draw_config["api_url"]
MODEL = draw_config["model"]
IMAGE_SIZE = draw_config["image_size"]
NUM_INFERENCE_STEPS = draw_config["num_inference_steps"]
DRAW_COMMAND = draw_config["draw_command"]
MAX_RETRIES = draw_config.get("max_retries", 3)
RETRY_DELAY = draw_config.get("retry_delay", 5)
COOLDOWN = draw_config.get("cooldown", 60)
TIMEOUT = draw_config.get("timeout", 60)

# 获取提示词优化配置
PROMPT_OPTIMIZER_MODEL = draw_config["prompt_optimizer"]["model"]
PROMPT_TEMPLATE = draw_config["prompt_optimizer"]["template"]

# 获取图片尺寸配置
IMAGE_SIZES = draw_config["image_sizes"]

# 内容过滤配置
CONTENT_FILTER = draw_config["content_filter"]
FORBIDDEN_KEYWORDS = draw_config["forbidden_keywords"]

logger.info(f"画图命令已加载，触发命令为：{DRAW_COMMAND}")
logger.info(f"可用图片尺寸：{IMAGE_SIZES}")

# 用于存储用户最后一次使用时间
last_use_time: Dict[int, datetime] = {}
# 用于控制并发
drawing_lock = asyncio.Lock()

# 修改尺寸类型映射
SIZE_TYPE_MAP = {
    "横": "landscape",
    "竖": "portrait",
    "正": "square"
}

# 修改服务类型映射
SERVICE_TYPE_MAP = {
    "flux1": "siliconflow",  # Silicon Flow 的 FLUX.1
    "flux1.1": "fal"         # FAL 的 FLUX 1.1-ultra
}

# 在配置部分后添加固定的消息定义
draw_messages = draw_config.get("messages", {})
FILTER_MESSAGES = draw_messages.get("filter_messages", [
    "你冰哥不画这玩意",
    "这个不能画哦~",
    "这种东西可不行",
    "换个别的画吧"
])

ERROR_MESSAGES = draw_messages.get("error_messages", [
    "冰冰出错了",
    "冰冰遇到一些问题",
    "冰冰系统开小差了",
    "冰冰出错了呢"
])

EMPTY_INPUT_MESSAGES = draw_messages.get("empty_input", [
    "告诉冰冰你想画什么",
    "告诉冰冰你想画的内容",
    "告诉冰冰你想画什么吧~",
    "告诉冰冰你想画什么吧~"
])

# 自定义规则：检查消息是否以画图命令开头
def check_draw_command() -> Rule:
    async def _check_draw_command(event: MessageEvent) -> bool:
        msg = event.get_plaintext().strip()
        is_match = msg.startswith(DRAW_COMMAND)
        logger.debug(f"收到消息：{msg}，是否匹配命令：{is_match}")
        return is_match
    return Rule(_check_draw_command)

# 创建消息响应器
draw = on_message(rule=check_draw_command(), priority=10, block=True)

# 添加提示词优化函数
async def optimize_prompt(prompt: str) -> str:
    """优化提示词"""
    try:
        headers = {
            "Authorization": f"Bearer {config['oai']['api_key']}",
            "Content-Type": "application/json"
        }
        
        # 正确处理模板中的 prompt 变量
        template_content = PROMPT_TEMPLATE.replace("{prompt}", prompt)
        
        messages = [
            {
                "role": "system",
                "content": template_content
            }
        ]
        
        logger.info(f"开始优化提示词: {prompt}")
        logger.debug(f"使用模型: {PROMPT_OPTIMIZER_MODEL}")
        
        async with httpx.AsyncClient() as client:
            try:
                logger.debug("发送优化请求...")
                response = await client.post(
                    f"{config['oai']['api_base']}/v1/chat/completions",
                    headers=headers,
                    json={
                        "model": PROMPT_OPTIMIZER_MODEL,
                        "messages": messages,
                        "temperature": 0.7,
                        "max_tokens": 200
                    },
                    timeout=30.0
                )
            except httpx.TimeoutException as e:
                logger.error(f"提示词优化请求超时: {str(e)}")
                return prompt
            except httpx.RequestError as e:
                logger.error(f"提示词优化请求错误: {str(e)}")
                return prompt
            except Exception as e:
                logger.error(f"提示词优化请求异常: {str(e)}", exc_info=True)
                return prompt
                
            try:
                logger.debug(f"API响应状态码: {response.status_code}")
                logger.debug(f"API响应内容: {response.text[:200]}...")
                
                if response.status_code != 200:
                    logger.error(f"提示词优化失败，状态码：{response.status_code}")
                    logger.error(f"错误响应：{response.text}")
                    return prompt
                    
                result = response.json()
                logger.debug("成功解析API响应")
                
                optimized_prompt = result["choices"][0]["message"]["content"].strip()
                logger.info(f"提示词优化成功: {optimized_prompt}")
                
                # 清理优化后的提示词
                optimized_prompt = optimized_prompt.replace("\n", " ").strip()
                optimized_prompt = re.sub(r'^(?:Input:|Output:)\s*', '', optimized_prompt)
                optimized_prompt = re.sub(r'\s*(?:Input:|Output:)\s*', '', optimized_prompt)
                
                logger.info(f"原始提示词: {prompt}")
                logger.info(f"优化后提示词: {optimized_prompt}")
                
                return optimized_prompt
                
            except KeyError as e:
                logger.error(f"API响应格式错误: {str(e)}")
                logger.error(f"响应内容: {response.text}")
                return prompt
            except json.JSONDecodeError as e:
                logger.error(f"API响应解析失败: {str(e)}")
                logger.error(f"响应内容: {response.text}")
                return prompt
            except Exception as e:
                logger.error(f"处理API响应时发生错误: {str(e)}", exc_info=True)
                return prompt
            
    except Exception as e:
        logger.error(f"提示词优化过程中发生未知错误: {str(e)}", exc_info=True)
        return prompt

def parse_args(text: str) -> Tuple[str, dict]:
    """解析命令参数"""
    # 初始化默认值
    args = {
        "size": IMAGE_SIZE,
        "steps": NUM_INFERENCE_STEPS,
        "service": "siliconflow"  # 默认使用 siliconflow
    }
    
    pattern = r'^(.*?)(?:\s+-[snm]\s+\S+)*$'
    match = re.match(pattern, text.strip())
    
    if not match:
        return text.strip(), args
    
    prompt = match.group(1).strip()
    
    # 分别匹配参数
    size_match = re.search(r'-s\s+(\S+)', text)
    steps_match = re.search(r'-n\s+(\d+)', text)
    model_match = re.search(r'-m\s+(\S+)', text)  # 新增模型参数
    
    # 处理尺寸参数
    if size_match:
        size_type = size_match.group(1)
        size_key = SIZE_TYPE_MAP.get(size_type)
        if size_key and size_key in IMAGE_SIZES:
            args["size"] = IMAGE_SIZES[size_key]
            
    # 处理步数参数
    if steps_match:
        try:
            steps_num = int(steps_match.group(1))
            if 1 <= steps_num <= 100:
                args["steps"] = steps_num
                logger.info(f"设置生成步数为：{steps_num}")
        except ValueError:
            pass
            
    # 处理模型参数
    if model_match:
        model_type = model_match.group(1).lower()
        if model_type in SERVICE_TYPE_MAP:
            args["service"] = SERVICE_TYPE_MAP[model_type]
            logger.info(f"使用模型：{args['service']}")
            
    return prompt, args

def retry_on_error(max_retries: int = None, retry_delay: int = None):
    """重试装饰器"""
    max_retries = max_retries or MAX_RETRIES
    retry_delay = retry_delay or RETRY_DELAY
    
    def decorator(func):
        async def wrapper(*args, **kwargs):
            for i in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:  # 改为捕获所有异常
                    if i < max_retries - 1:
                        logger.warning(f"第{i+1}次重试失败: {str(e)}")
                        await asyncio.sleep(retry_delay)
                    else:
                        raise
            return await func(*args, **kwargs)
        return wrapper
    return decorator

def check_content(prompt: str) -> bool:
    """检查提示词是否包含违禁内容"""
    if not CONTENT_FILTER:
        return True
        
    for keyword in FORBIDDEN_KEYWORDS:
        if keyword.lower() in prompt.lower():
            logger.warning(f"检测到违禁词: {keyword}")
            return False
    return True

# 初始化绘画管理器
drawing_manager = DrawingManager()

# 注册 Silicon Flow 服务
silicon_flow = SiliconFlowService(
    api_key=API_KEY,
    api_url=API_URL,
    model=MODEL,
    timeout=TIMEOUT,
    max_retries=MAX_RETRIES,
    retry_delay=RETRY_DELAY
)
drawing_manager.register_service("siliconflow", silicon_flow)

fal_service = FALService(
    api_key=draw_config["fal"]["api_key"],
    model=draw_config["fal"]["model"],
    enable_safety_checker=draw_config["fal"]["enable_safety_checker"],
    safety_tolerance=draw_config["fal"]["safety_tolerance"],
    output_format=draw_config["fal"]["output_format"],
    sync_mode=draw_config["fal"]["sync_mode"],
    aspect_ratios=draw_config["fal"]["aspect_ratios"],
    timeout=TIMEOUT,
    max_retries=MAX_RETRIES,
    retry_delay=RETRY_DELAY
)
drawing_manager.register_service("fal", fal_service)

@draw.handle()
async def handle_draw(event: MessageEvent):
    user_id = event.user_id
    start_time = datetime.now()
    
    try:
        # 检查冷却时间
        if user_id in last_use_time:
            elapsed = datetime.now() - last_use_time[user_id]
            if elapsed.total_seconds() < COOLDOWN:
                await draw.finish(f"绘图功能冷却中，请在{int(COOLDOWN - elapsed.total_seconds())}秒后再试")
                return

        # 检查并发
        if drawing_lock.locked():
            await draw.finish("别人在画，你急也没用")
            return

        # 获取原始消息和解析参数
        msg = event.get_plaintext().strip()
        command_text = msg[len(DRAW_COMMAND):].strip()
        prompt, args = parse_args(command_text)
        
        logger.info(f"处理画图请求，原始消息：{msg}")
        logger.info(f"解析结果 - 提示词：{prompt}，参数：{args}")
        
        if not prompt:
            random_msg = random.choice(EMPTY_INPUT_MESSAGES)
            await draw.finish(
                f"{random_msg}\n"
                "参数说明：\n"
                "-s [横/竖/正] 指定图片方向\n"
                "-n [步数] 指定生成步数(1-100)\n"
                "-m [flux1/flux1.1] 指定模型版本"
            )
            return

        # 内容过滤检查
        if not check_content(prompt):
            await draw.finish(random.choice(FILTER_MESSAGES))
            return

        async with drawing_lock:
            try:
                # 优化提示词
                optimized_prompt = await optimize_prompt(prompt)
                
                # 内容检查
                if not check_content(optimized_prompt):
                    await draw.finish(random.choice(FILTER_MESSAGES))
                    return
                
                # 使用绘画管理器生成图片
                image_data, inference_time = await drawing_manager.generate_image(
                    args["service"],  # 使用选择的服务
                    optimized_prompt,
                    args["size"],
                    args["steps"]
                )
                
                # 更新用户最后使用时间
                last_use_time[user_id] = datetime.now()
                
                # 计算总用时
                total_time = (datetime.now() - start_time).total_seconds()
                
                # 构建消息
                msg = Message([
                    MessageSegment.image(image_data),
                    MessageSegment.text(
                        f"\n这是你要的{prompt}\n"
                        f"优化后的提示词：{optimized_prompt}\n"
                        f"参数：{args['size']}, {args['steps']} step\n"
                        f"总用时：{total_time:.1f}秒"
                    )
                ])
                
                await draw.finish(msg)
                
            except Exception as e:
                if not isinstance(e, FinishedException):
                    logger.error(f"生成图片过程中发生错误: {str(e)}", exc_info=True)
                    await draw.finish(random.choice(ERROR_MESSAGES))
                
    except Exception as e:
        if not isinstance(e, FinishedException):
            logger.error(f"处理请求过程中发生未知错误: {str(e)}", exc_info=True)
            await draw.finish(random.choice(ERROR_MESSAGES))