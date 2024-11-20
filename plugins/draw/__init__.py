from nonebot import on_message, on_command
from nonebot.adapters.onebot.v11 import Message, MessageEvent, MessageSegment, GroupMessageEvent, PrivateMessageEvent, Bot
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule, to_me
from nonebot.permission import SUPERUSER
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
from nonebot.matcher import Matcher
from nonebot.params import CommandArg

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
    draw_config = config["draw"]
    messages_config = config["messages"]

# 声明全局变量并从配置读取默认值
drawing_enabled = draw_config.get("enable", False)  # 从配置文件读取默认值

logger.info(f"绘图功能状态: {'启用' if drawing_enabled else '禁用'}")

# 获取配置
API_KEY = draw_config["api_key"]
API_URL = draw_config["api_url"]
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
    "": "square"
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

# 在文件开头的配置读取部分添加新的消息列表
DRAWING_START_MESSAGES = draw_messages.get("drawing_start", [
    "让冰冰想想怎么画...",
    "冰冰正在认真画画中...",
    "冰冰拿起画笔开始画了..."
])

# 自定义规则：检查消息是否为绘图关命令
def check_draw_commands() -> Rule:
    async def _check_draw_commands(event: MessageEvent) -> bool:
        msg = event.get_plaintext().strip()
        # 检查是否为管理命令或绘图命令
        return msg.startswith("/draw") or msg.startswith(DRAW_COMMAND)
    return Rule(_check_draw_commands)

# 创建统一的消息响应器
draw = on_message(
    rule=check_draw_commands(),
    priority=10,
    block=True
)

@draw.handle()
async def handle_draw(bot: Bot, event: MessageEvent):
    global drawing_enabled  # 确保使用全局变量
    msg = event.get_plaintext().strip()
    
    # 记录日志
    logger.info(f"收到消息 - 用户ID: {event.user_id}, 群ID: {event.group_id if isinstance(event, GroupMessageEvent) else 'private'}")
    logger.info(f"原始消息: {msg}")
    logger.info(f"当前绘图功能状态: {'启用' if drawing_enabled else '禁用'}")
    
    # 处理 /draw 管理命令
    if msg.startswith("/draw"):
        # 检查权限
        if event.user_id not in config.get("admin", {}).get("superusers", []):
            logger.warning(f"用户 {event.user_id} 尝试使用管理命令但权限不足")
            await draw.finish("您没有使用该命令的权限")
            return
            
        # 获取参数
        cmd_text = msg.replace("/draw", "").strip()
        logger.info(f"管理命令参数: '{cmd_text}'")
        
        try:
            # 没有参数时示帮助信息
            if not cmd_text:
                status = "开启" if drawing_enabled else "关闭"
                help_text = f"""当前绘图功能状态：{status}

可用命令：
/draw true - 开启绘图功能
/draw false - 关闭绘图功能
/draw model - 显示可用模型列表
/draw model <模型名称> - 切换到指定模型"""
                logger.info("发送帮助信息")
                await bot.send(event=event, message=help_text)
                return

            # 处理命令
            args = cmd_text.split()
            cmd = args[0].lower()
            
            if cmd in ["true", "false"]:
                drawing_enabled = (cmd == "true")
                logger.info(f"绘图功能已{'开启' if drawing_enabled else '关闭'}")
                await bot.send(event=event, message=f"绘图功能已{'开启' if drawing_enabled else '关闭'}")
                
            elif cmd == "model":
                if len(args) == 1:  # 显示可用模型列表
                    models = {
                        "flux1": "Silicon Flow的FLUX.1模型",
                        "flux1.1": "FAL的FLUX 1.1-ultra模型"
                    }
                    model_list = "\n".join(f"- {k}: {v}" for k, v in models.items())
                    current_model = draw_config.get("default_service", "siliconflow")
                    response = (
                        f"当前使用的模型：{current_model}\n\n"
                        f"可用模型列表：\n{model_list}\n\n"
                        f"使用 /draw model <模型名称> 切换模型"
                    )
                    logger.info("发送模型列表")
                    await bot.send(event=event, message=response)
                else:  # 切换模型
                    new_model = args[1].lower()
                    if new_model not in SERVICE_TYPE_MAP:
                        response = (
                            f"未知的模型名称：{new_model}\n"
                            f"可用模型：{', '.join(SERVICE_TYPE_MAP.keys())}"
                        )
                        logger.info(f"无效的模型名称: {new_model}")
                        await bot.send(event=event, message=response)
                        return
                        
                    old_model = draw_config.get("default_service", "siliconflow")
                    draw_config["default_service"] = SERVICE_TYPE_MAP[new_model]
                    logger.info(f"切换模型: {old_model} -> {SERVICE_TYPE_MAP[new_model]}")
                    await bot.send(event=event, message=f"已切换到模型：{new_model}")
            else:
                logger.warning(f"无效的命令参数: {cmd}")
                await bot.send(event=event, message="无效的命令参数，请使用 /draw 查看帮助信息")
                
        except Exception as e:
            logger.error(f"处理管理命令时发生错误: {e}", exc_info=True)
            await bot.send(event=event, message="命令处理过程中发生错误，请查看日志")
            
    # 处理绘图命令
    elif msg.startswith(DRAW_COMMAND):
        # 检查功能是否启用
        if not drawing_enabled:
            logger.info("绘图功能已禁用，拒绝请求")
            await draw.finish("听不见···听不见···")
            return
            
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
                    # 发送开始绘制的提示
                    await draw.send(random.choice(DRAWING_START_MESSAGES))
                    
                    # 优化提示词
                    optimized_prompt = await optimize_prompt(prompt)
                    
                    # 如果优化后的提示词为空，直接返回（因为optimize_prompt已经发送了提示消息）
                    if not optimized_prompt:
                        return
                    
                    # 内容检查
                    if not check_content(optimized_prompt):
                        await draw.finish(random.choice(FILTER_MESSAGES))
                        return
                    
                    # 使用绘画管理器生成图片
                    image_data, inference_time = await drawing_manager.generate_image(
                        args["service"],
                        optimized_prompt,
                        args["size"],
                        args["steps"]
                    )
                    
                    # 更新用户最后使用时间
                    last_use_time[user_id] = datetime.now()
                    
                    # 计算总用时
                    total_time = (datetime.now() - start_time).total_seconds()
                    
                    # 修改消息构建部分
                    msg_text = (
                        f"\n这是你要的：{prompt}\n"  # 使用 f-string
                        f"优化后的提示词：{optimized_prompt}\n"
                        f"参数：尺寸={args['size']}, 步数={args['steps']}\n"
                        f"总用时：{total_time:.1f}秒"
                    )
                    
                    # 构建消息
                    msg = Message([
                        MessageSegment.image(image_data),
                        MessageSegment.text(msg_text)  # 使用预先构建的文本
                    ])
                    
                    await draw.finish(msg)
                    
                except Exception as e:
                    # 忽略 FinishedException
                    if not isinstance(e, FinishedException):
                        logger.error(f"生成图片过程中发生错误: {e}", exc_info=True)
                        await draw.finish(random.choice(ERROR_MESSAGES))
                
        except Exception as e:
            # 忽略 FinishedException
            if not isinstance(e, FinishedException):
                logger.error(f"处理绘图请求时发生错误: {e}", exc_info=True)
                await draw.finish(random.choice(ERROR_MESSAGES))

# 添加提示词优化函数
async def optimize_prompt(prompt: str, max_retries: int = 3) -> str:
    """优化提示词，失败时重试"""
    for retry_count in range(max_retries):
        try:
            headers = {
                "Authorization": f"Bearer {config['oai']['api_key']}",
                "Content-Type": "application/json"
            }
            
            template_content = PROMPT_TEMPLATE.replace("{prompt}", prompt)
            messages = [
                {
                    "role": "system",
                    "content": template_content
                }
            ]
            
            logger.info(f"开始优化提示词 (第{retry_count + 1}次尝试): {prompt}")
            
            try:
                async with httpx.AsyncClient() as client:
                    async def request():
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
                        return response

                    # 添加30秒超时
                    response = await asyncio.wait_for(request(), timeout=30.0)
                    
                    if response.status_code != 200:
                        logger.error(f"提示词优化失败，状态码：{response.status_code}")
                        if retry_count == max_retries - 1:
                            await draw.finish(random.choice([
                                "你是不是画了上面不该画的？",
                                "中间层崩了~~",
                                "这个内容不太合适呢",
                                "换个别的画吧~"
                            ]))
                            return ""
                        continue
                        
                    result = response.json()
                    optimized_prompt = result["choices"][0]["message"]["content"].strip()
                    
                    # 如果优化后的提示词为空，尝试重试
                    if not optimized_prompt:
                        if retry_count < max_retries - 1:
                            logger.warning(f"提示词优化返回空，进行第{retry_count + 2}次尝试")
                            await asyncio.sleep(1)  # 等待1秒后重试
                            continue
                        else:
                            await draw.finish(random.choice([
                                "你是不是画了上面不该画的？",
                                "中间层崩了~~",
                                "这个内容不太合适呢",
                                "换个别的画吧~"
                            ]))
                            return ""
                    
                    # 清理优化后的提示词
                    optimized_prompt = optimized_prompt.replace("\n", " ").strip()
                    optimized_prompt = re.sub(r'^(?:Input:|Output:)\s*', '', optimized_prompt)
                    optimized_prompt = re.sub(r'\s*(?:Input:|Output:)\s*', '', optimized_prompt)
                    
                    logger.info(f"原始提示词: {prompt}")
                    logger.info(f"优化后提示词: {optimized_prompt}")
                    
                    # 如果清理后的提示词为空，尝试重试
                    if not optimized_prompt:
                        if retry_count < max_retries - 1:
                            logger.warning(f"清理后提示词为空，进行第{retry_count + 2}次尝试")
                            await asyncio.sleep(1)
                            continue
                        else:
                            await draw.finish(random.choice([
                                "你是不是画了上面不该画的？",
                                "中间层崩了~~",
                                "这个内容不太合适呢",
                                "换个别的画吧~"
                            ]))
                            return ""
                    
                    return optimized_prompt
                    
            except asyncio.TimeoutError:
                logger.error(f"提示词优化超时 (第{retry_count + 1}次尝试)")
                if retry_count == max_retries - 1:
                    await draw.finish(random.choice([
                        "中间层超时了...",
                        "优化提示词超时了，请稍后再试",
                        "处理时间太长了，换个时间再试吧",
                        "服器太忙了，稍后再来哦~"
                    ]))
                    return ""
                await asyncio.sleep(1)
                continue
                
        except Exception as e:
            logger.error(f"提示词优化过程中发生错误 (第{retry_count + 1}次尝试): {str(e)}")
            if retry_count == max_retries - 1:
                await draw.finish(random.choice([
                    "你是不画了上面不该画的？",
                    "中间层崩了~~",
                    "这个内容不太合适呢",
                    "换别的画吧~"
                ]))
                return ""
            await asyncio.sleep(1)
            continue
            
    return ""  # 所有重试都失败后返回空字符串

def parse_args(text: str) -> Tuple[str, dict]:
    """解析命令参数"""
    # 初始化默认值
    args = {
        "size": IMAGE_SIZE,
        "steps": NUM_INFERENCE_STEPS,
        "service": draw_config.get("default_service", "siliconflow")  # 从配置读取默认服务
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
    model=draw_config.get("model", "black-forest-labs/FLUX.1-dev"),
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