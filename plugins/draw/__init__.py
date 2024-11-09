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
    flux_config = config["flux"]

# 获取配置
API_KEY = flux_config["api_key"]
API_URL = flux_config["api_url"]
MODEL = flux_config["model"]
IMAGE_SIZE = flux_config["image_size"]
NUM_INFERENCE_STEPS = flux_config["num_inference_steps"]
DRAW_COMMAND = flux_config["draw_command"]
MAX_RETRIES = flux_config.get("max_retries", 3)
RETRY_DELAY = flux_config.get("retry_delay", 5)
COOLDOWN = flux_config.get("cooldown", 60)
PROMPT_OPTIMIZER_MODEL = flux_config.get("prompt_optimizer_model", "gemini-1.5-pro-latest")
PROMPT_TEMPLATE = flux_config.get("prompt_optimization_template", "")
IMAGE_SIZES = flux_config.get("image_sizes", {})

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
    try:
        # 使用 OpenAI API 优化提示词
        headers = {
            "Authorization": f"Bearer {config['openai']['api_key']}",
            "Content-Type": "application/json"
        }
        
        messages = [
            {
                "role": "system",
                "content": PROMPT_TEMPLATE.format(prompt=prompt)
            }
        ]
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{config['openai']['api_base']}/v1/chat/completions",
                headers=headers,
                json={
                    "model": PROMPT_OPTIMIZER_MODEL,
                    "messages": messages,
                    "temperature": 0.7,
                    "max_tokens": 200
                },
                timeout=30.0
            )
            
            if response.status_code != 200:
                logger.error(f"提示词优化失败：{response.status_code}")
                return prompt
                
            result = response.json()
            optimized_prompt = result["choices"][0]["message"]["content"].strip()
            
            # 清理优化后的提示词
            optimized_prompt = optimized_prompt.replace("\n", " ").strip()
            # 移除可能的 Input: 和 Output: 标记
            optimized_prompt = re.sub(r'^(?:Input:|Output:)\s*', '', optimized_prompt)
            optimized_prompt = re.sub(r'\s*(?:Input:|Output:)\s*', '', optimized_prompt)
            
            logger.info(f"原始提示词：{prompt}")
            logger.info(f"优化后提示词：{optimized_prompt}")
            
            return optimized_prompt
            
    except Exception as e:
        logger.error(f"提示词优化过程中发生错误：{str(e)}")
        return prompt  # 如果优化失败，返回原始提示词

def parse_args(text: str) -> Tuple[str, dict]:
    """解析命令参数"""
    # 初始化默认值
    args = {
        "size": IMAGE_SIZE,
        "steps": NUM_INFERENCE_STEPS
    }
    
    # 修改正则表达式，使其更精确地匹配参数
    pattern = r'^(.*?)(?:\s+-[sn]\s+\S+)*$'  # 先匹配整个字符串
    match = re.match(pattern, text.strip())
    
    if not match:
        return text.strip(), args
    
    prompt = match.group(1).strip()
    
    # 分别匹配参数
    size_match = re.search(r'-s\s+(\S+)', text)
    steps_match = re.search(r'-n\s+(\d+)', text)
    
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
            
    return prompt, args

@draw.handle()
async def handle_draw(event: MessageEvent):
    user_id = event.user_id
    
    # 检查冷却时间
    if user_id in last_use_time:
        elapsed = datetime.now() - last_use_time[user_id]
        if elapsed.total_seconds() < COOLDOWN:
            remaining = int(COOLDOWN - elapsed.total_seconds())
            await draw.finish(f"绘图功能冷却中，请在{remaining}秒后再试")
            return

    # 检查并发
    if drawing_lock.locked():
        await draw.finish("有其他用户正在生成图片，请稍后再试")
        return

    # 获取原始消息
    msg = event.get_plaintext().strip()
    command_text = msg[len(DRAW_COMMAND):].strip()
    
    # 解析参数
    prompt, args = parse_args(command_text)
    
    logger.info(f"处理画图请求，原始消息：{msg}")
    logger.info(f"解析结果 - 提示词：{prompt}，参数：{args}")
    
    if not prompt:
        await draw.finish(
            "请输入想要画的内容~\n"
            "参数说明：\n"
            "-s [横/竖/正] 指定图片方向\n"
            "-n [步数] 指定生成步数(1-100)"
        )
        return

    async with drawing_lock:  # 加锁防止并发
        try:
            # 优化提示词
            optimized_prompt = await optimize_prompt(prompt)
            
            # 准备请求数据
            payload = {
                "model": MODEL,
                "prompt": optimized_prompt,
                "image_size": args["size"],
                "num_inference_steps": args["steps"]
            }
            
            headers = {
                "Authorization": f"Bearer {API_KEY}",
                "Content-Type": "application/json"
            }

            # 重试逻辑
            for retry in range(MAX_RETRIES):
                try:
                    logger.info(f"开始发送API请求，提示词：{optimized_prompt}，第{retry + 1}次尝试")
                    
                    async with httpx.AsyncClient() as client:
                        response = await client.post(
                            API_URL,
                            json=payload,
                            headers=headers,
                            timeout=60.0
                        )

                        if response.status_code == 200:
                            break  # 成功则跳出重试循环
                        
                        if retry < MAX_RETRIES - 1:  # 如果不是最后一次重试
                            logger.warning(f"请求失败，{RETRY_DELAY}秒后重试")
                            await asyncio.sleep(RETRY_DELAY)
                        else:
                            error_msg = f"绘图失败：API返回错误 {response.status_code}"
                            logger.error(error_msg)
                            await draw.finish(error_msg)
                            return
                            
                except httpx.TimeoutException:
                    if retry < MAX_RETRIES - 1:
                        logger.warning(f"请求超时，{RETRY_DELAY}秒后重试")
                        await asyncio.sleep(RETRY_DELAY)
                    else:
                        logger.error("请求超时，已达到最大重试次数")
                        await draw.finish("绘图超时，请稍后重试")
                        return

            result = response.json()
            logger.info("API请求成功，开始处理返回结果")
            
            # 提取图片URL和用时
            image_url = result["images"][0]["url"]
            inference_time = result["timings"]["inference"]

            # 下载图片（也添加重试逻辑）
            for retry in range(MAX_RETRIES):
                try:
                    async with httpx.AsyncClient() as client:
                        img_response = await client.get(image_url)
                        if img_response.status_code == 200:
                            break
                        if retry < MAX_RETRIES - 1:
                            logger.warning(f"图片下载失败，{RETRY_DELAY}秒后重试")
                            await asyncio.sleep(RETRY_DELAY)
                        else:
                            logger.error("图片下载失败，已达到最大重试次数")
                            await draw.finish("图片下载失败")
                            return
                except Exception as e:
                    if retry < MAX_RETRIES - 1:
                        logger.warning(f"图片下载出错：{e}，{RETRY_DELAY}秒后重试")
                        await asyncio.sleep(RETRY_DELAY)
                    else:
                        logger.error(f"图片下载失败：{e}")
                        await draw.finish("图片下载失败")
                        return

            # 更新用户最后使用时间
            last_use_time[user_id] = datetime.now()

            # 构建消息并发送（添加参数信息）
            logger.info("图片下载成功，准备发送消息")
            msg = Message([
                MessageSegment.image(img_response.content),
                MessageSegment.text(
                    f"\n这是你要的{prompt}"
                    f"\n优化后的提示词：{optimized_prompt}"
                    f"\n参数：{args['size']}, {args['steps']}步"
                    f"\n用时{inference_time}秒"
                )
            ])
            return await draw.finish(msg)

        except Exception as e:
            if 'FinishedException' in str(e):
                return
            logger.error(f"发生错误：{str(e)}")
            return await draw.finish(f"绘图过程中发生错误：{str(e)}")