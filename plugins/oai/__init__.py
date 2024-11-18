from nonebot import on_message, on_command
from nonebot.adapters.onebot.v11 import Message, MessageEvent, GroupMessageEvent, PrivateMessageEvent
from nonebot.plugin import PluginMetadata
from nonebot import get_driver
from nonebot.rule import to_me, Rule
from typing import Optional, Set, List, Dict
import openai
import tomli
from pathlib import Path
from collections import defaultdict
import json
from datetime import datetime
import os
import asyncio
import re
import random

__plugin_meta__ = PluginMetadata(
    name="OAI Chat",
    description="OpenAI 对话插件",
    usage="""触发方式：
1. @机器人 直接对话
2. 以 'ai' 开头发消息
3. 使用关键词 '问问' 开头
4. 使用 /ask 命令

管理命令：
- /oai on：开启当前群的对话功能
- /oai off：关闭当前群的对话功能
- /oai private on：开启私聊功能
- /oai private off：关闭私聊功能
- /oai prefix add 前缀：添加触发前缀
- /oai prefix remove 前缀：删除触发前缀
- /oai prefix list：查看所有触发前缀""",
    config=None,
)

# 读取 TOML 配置文件
config_file = Path("config.toml")
if not config_file.exists():
    raise ValueError("配置文件 config.toml 不存在")

with open(config_file, "rb") as f:
    config = tomli.load(f)
    oai_config = config["oai"]
    trigger_config = oai_config["trigger"]
    messages_config = config["messages"]

# 配置 OpenAI
openai.api_key = oai_config["api_key"]
openai.base_url = oai_config.get("api_base", "https://api.openai.com/v1")
model = oai_config.get("model", "gpt-3.5-turbo")
temperature = float(oai_config.get("temperature", 0.7))
max_tokens = int(oai_config.get("max_tokens", 2000))
max_history = int(oai_config.get("max_history", 5))

# 存储配置
enabled_groups: Set[int] = set()
private_chat_enabled: bool = trigger_config.get("enable_private", True)
trigger_prefixes: Set[str] = set(trigger_config.get("prefixes", ["ai", "问问"]))
enable_prefix: bool = trigger_config.get("enable_prefix", True)
enable_at: bool = trigger_config.get("enable_at", True)
enable_command: bool = trigger_config.get("enable_command", True)

# 获取系统提示语
system_prompt = oai_config.get("system_prompt", "")

# 添加对话历史存储
chat_history = defaultdict(list)

# 在配置部分添加
separate_users = oai_config.get("separate_users", True)

# 修改用户标识获取函
def get_user_id(event: MessageEvent) -> str:
    if isinstance(event, GroupMessageEvent):
        group_id = event.group_id
        # 根据群设置决定是否隔离用户
        if group_isolation.get(group_id, default_isolation):
            return f"group_{group_id}_{event.user_id}"
        else:
            return f"group_{group_id}"
    return f"private_{event.user_id}"

# 自定义规则：检查消息前缀，并排除命令
def check_prefix() -> Rule:
    async def _check_prefix(event: MessageEvent) -> bool:
        msg = event.get_plaintext().strip().lower()
        # 如果消息以命令前缀开头，则不处理
        if msg.startswith('/'):
            return False
        return any(msg.startswith(prefix.lower()) for prefix in trigger_prefixes)
    return Rule(_check_prefix)

# 自定义规则：检查是否为命令
def check_not_command() -> Rule:
    async def _check_not_command(event: MessageEvent) -> bool:
        msg = event.get_plaintext().strip()
        return not msg.startswith('/')
    return Rule(_check_not_command)

# 创建命令处理器
from nonebot.permission import SUPERUSER

command = on_command("oai", permission=SUPERUSER, priority=5, block=True)

@command.handle()
async def handle_command(event: MessageEvent):
    args = str(event.get_message()).strip().split()
    cmd = args[0] if args else ""
    
    if isinstance(event, GroupMessageEvent):
        group_id = event.group_id
        if cmd == "on":
            enabled_groups.add(group_id)
            await command.finish("已在本群启用 AI 对话")
        elif cmd == "off":
            enabled_groups.discard(group_id)
            await command.finish("已在本群禁用 AI 对话")
    
    if cmd == "private":
        subcmd = args[1] if len(args) > 1 else ""
        global private_chat_enabled
        if subcmd == "on":
            private_chat_enabled = True
            await command.finish("已启用私聊功能")
        elif subcmd == "off":
            private_chat_enabled = False
            await command.finish("已禁用私聊功能")
    
    elif cmd == "prefix":
        subcmd = args[1] if len(args) > 1 else ""
        if subcmd == "add" and len(args) > 2:
            trigger_prefixes.add(args[2])
            await command.finish(f"已添加触发前缀：{args[2]}")
        elif subcmd == "remove" and len(args) > 2:
            if len(trigger_prefixes) <= 1:
                await command.finish("至少需要保留一个触发前缀")
            trigger_prefixes.discard(args[2])
            await command.finish(f"已删除触发前缀：{args[2]}")
        elif subcmd == "list":
            prefix_list = "、".join(trigger_prefixes)
            await command.finish(f"当前触发前缀：{prefix_list}")
    
    elif cmd == "toggle":
        subcmd = args[1] if len(args) > 1 else ""
        if subcmd == "prefix":
            global enable_prefix
            enable_prefix = not enable_prefix
            await command.finish(f"前缀触发已{'启用' if enable_prefix else '禁用'}")
        elif subcmd == "at":
            global enable_at
            enable_at = not enable_at
            await command.finish(f"@触发已{'启用' if enable_at else '禁用'}")
        elif subcmd == "command":
            global enable_command
            enable_command = not enable_command
            await command.finish(f"命令触发已{'启用' if enable_command else '禁用'}")
    
    elif cmd == "separate":
        if not isinstance(event, GroupMessageEvent):
            await command.finish("此命令只能在群聊中使用")
            return
            
        subcmd = args[1] if len(args) > 1 else ""
        global separate_users
        if subcmd == "on":
            separate_users = True
            # 清理当前群的历史记录
            group_prefix = f"group_{event.group_id}"
            for key in list(chat_history.keys()):
                if key.startswith(group_prefix):
                    chat_history.pop(key)
            await command.finish("已启用群聊用户分离，历史记录已清理")
        elif subcmd == "off":
            separate_users = False
            # 清理当前群的历史记录
            group_prefix = f"group_{event.group_id}"
            for key in list(chat_history.keys()):
                if key.startswith(group_prefix):
                    chat_history.pop(key)
            # 创建新的群组共享历史记录
            chat_history[f"group_{event.group_id}"] = []
            await command.finish("已禁用群聊用户分离，历史记录已清理")

# 创建消息响应器，调整优先级并添加命令检查
if enable_at:
    chat_at = on_message(
        rule=to_me() & check_not_command(), 
        priority=10, 
        block=True
    )
if enable_prefix:
    chat_prefix = on_message(
        rule=check_prefix(), 
        priority=10, 
        block=True
    )
if enable_command:
    chat_command = on_command("ask", priority=10, block=True)

# 读取日志配置
log_config = config.get("log", {})
enable_log = log_config.get("enable", True)
log_path = Path(log_config.get("path", "logs/chat"))
log_format = log_config.get("format", "markdown")

# 确保日志目录存在
if enable_log:
    log_path.mkdir(parents=True, exist_ok=True)

# 添加日志文件处理函数
async def ensure_log_file(log_file: Path) -> bool:
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        
        if not log_file.exists():
            initial_content = ""
            if log_format == "markdown":
                initial_content = f"""# AI 对话日志

> 创建时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
> 文件说明：此文件记录 AI 助手的对话记录，包含用户信息、对话内容和相关元数据。

## 目录
- [对话记录](#对话记录)
- [错误记录](#错误记录)

---

# 对话记录

"""
            else:
                initial_content = f"""=============== AI 对话日志 ===============
创建时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
说明：此文件记录 AI 助手的对话记录

"""
            log_file.write_text(initial_content, encoding='utf-8')
        
        return os.access(log_file, os.W_OK)
    except Exception as e:
        print(f"日志文件初始化失败：{e}")
        return False

# 修改日志记录函数
async def save_chat_log(
    user_id: str,
    user_name: str,
    group_id: Optional[int],
    group_name: Optional[str],
    question: str,
    answer: str,
    error: Optional[str] = None,
    metadata: Optional[dict] = None
) -> None:
    if not enable_log:
        return

    try:
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H:%M:%S")
        
        # 创建日期目录
        date_dir = log_path / date_str
        
        # 确定文件名
        if group_id:
            filename = f"group_{group_id}_{date_str}.{log_format}"
        else:
            filename = f"private_{user_id}_{date_str}.{log_format}"
        
        log_file = date_dir / filename
        
        if not await ensure_log_file(log_file):
            print(f"无法写入日志文件：{log_file}")
            return
        
        # 获取额外元数据
        meta = {
            "timestamp": now.timestamp(),
            "date": date_str,
            "time": time_str,
            "user_id": user_id,
            "user_name": user_name,
            "platform": "qq",
            **(metadata or {})
        }
        
        if group_id:
            meta.update({
                "chat_type": "group",
                "group_id": group_id,
                "group_name": group_name
            })
        else:
            meta.update({"chat_type": "private"})

        if log_format == "markdown":
            # 生成更清晰的时间戳标题
            content = f"""
## {time_str} - {'群聊' if group_id else '私聊'}对话

### 📝 基本信息
- **时间**：{date_str} {time_str}
- **用户**：{user_name} (`{user_id}`)
{"- **群组**：" + group_name + f" (`{group_id}`)" if group_id else "- **对话类型**：私聊"}

### 💭 对话内容
<details open>
<summary>展开/折叠</summary>

#### 🗣️ 提问
```
{question.strip() if question.strip() else '(空消息)'}
```

#### 🤖 回复
```
{answer.strip() if answer.strip() else '(空回复)'}
```
</details>

"""
            if error:
                content += f"""
### ❌ 错误信息
```
{error}
```
"""
            
            content += f"""
### 🔍 元数据
```json
{json.dumps(meta, ensure_ascii=False, indent=2)}
```

---

"""
        else:
            content = f"""
========== {time_str} - {'群聊' if group_id else '私聊'}对话 ==========
时间：{date_str} {time_str}
用户：{user_name} ({user_id})
{"群组：" + group_name + f" ({group_id})" if group_id else "对话类型：私聊"}

[提问]
{question.strip() if question.strip() else '(空消息)'}

[回复]
{answer.strip() if answer.strip() else '(空回复)'}

"""
            if error:
                content += f"""
[错误信息]
{error}

"""
            
            content += f"""
[元数据]
{json.dumps(meta, ensure_ascii=False, indent=2)}

{"=" * 50}

"""
        
        # 写入日志
        max_retries = 3
        for attempt in range(max_retries):
            try:
                async with asyncio.Lock():
                    # 检查文件大小并处理
                    if log_file.exists() and log_file.stat().st_size > 10 * 1024 * 1024:  # 10MB
                        # 创建新的日志文件，使用时间戳区分
                        timestamp = now.strftime("%H%M%S")
                        new_file = log_file.with_name(f"{log_file.stem}_{timestamp}{log_file.suffix}")
                        log_file.rename(new_file)
                        await ensure_log_file(log_file)
                    
                    with open(log_file, 'a', encoding='utf-8') as f:
                        f.write(content)
                break
            except Exception as e:
                if attempt == max_retries - 1:
                    print(f"写入日志失败（尝试 {attempt + 1}/{max_retries}）：{e}")
                else:
                    await asyncio.sleep(0.1)
                    
    except Exception as e:
        print(f"日志记录失败：{e}")

# 添加消清理函数
def clean_message(text: str) -> str:
    if not text:
        return text
    
    # 移除开头的空白字符和换行
    text = text.lstrip()
    
    # 移除结尾的空白字符和换行
    text = text.rstrip()
    
    # 处理多余的换行（连续的换行改为最多两个）
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    # 处理行中间的多余空格
    text = re.sub(r'[ \t]+', ' ', text)
    
    # 确保段落之间只有一个换行
    text = re.sub(r'\n[ \t]*\n[ \t]*', '\n\n', text)
    
    return text

# 读取自定义消息配置
message_config = config.get("messages", {})
empty_input_msg = message_config.get("empty_input", "请输入有效的消息内容")
empty_at_msg = message_config.get("empty_at", "Hi，我在呢！有什么可以帮你的吗？")

async def handle_chat_common(event: MessageEvent, msg_text: str):
    # 检查群聊功能是否开启
    if isinstance(event, GroupMessageEvent):
        group_id = event.group_id
        if not chat_enabled.get(group_id, default_chat_enabled):
            return "小冰已读，不回！。"
    
    # 检查私聊权限
    if isinstance(event, PrivateMessageEvent) and not private_chat_enabled:
        return "私聊功能已禁用"
    
    # 使用新的用户标识获取函数
    user_id = get_user_id(event)
    
    # 获取用户信息
    user_name = event.sender.nickname or str(event.user_id)
    group_id = None
    group_name = None
    if isinstance(event, GroupMessageEvent):
        group_id = event.group_id
        group_name = "未知群名"  # 如果需要真实群名，需要通过 API 获取
    
    try:
        # 创建 HTTP 头部
        headers = {
            "Authorization": f"Bearer {openai.api_key}",
            "Content-Type": "application/json"
        }
        
        # 准备消息历史
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        
        # 添加历史消息（不包 system prompt）
        user_messages = [msg for msg in chat_history[user_id] if msg["role"] != "system"]
        messages.extend(user_messages)
        # 添加当前消息
        messages.append({"role": "user", "content": msg_text})
        
        data = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        
        # 检查输入消息是否为空
        if not msg_text.strip():
            # 从配置中获取空消息列表，如果不是列表则转换为列表
            empty_messages = messages_config.get("empty_input", ["请输入有效的消息内容"])
            if not isinstance(empty_messages, list):
                empty_messages = [empty_messages]
            
            # 随机选择一条消息
            error_msg = random.choice(empty_messages)
            
            await save_chat_log(
                str(event.user_id), user_name, group_id, group_name,
                msg_text, "", error_msg
            )
            return error_msg
        
        # 发送请求
        import httpx
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    f"{openai.base_url}/v1/chat/completions",
                    headers=headers,
                    json=data,
                    timeout=30.0
                )
            except httpx.TimeoutException:
                error_msg = "请求超时，请稍后重试"
                await save_chat_log(
                    str(event.user_id), user_name, group_id, group_name,
                    msg_text, "", error_msg
                )
                return error_msg
            except httpx.NetworkError:
                error_msg = "网络错误，请检查网络连接"
                await save_chat_log(
                    str(event.user_id), user_name, group_id, group_name,
                    msg_text, "", error_msg
                )
                return error_msg
            
            if response.status_code != 200:
                error_msg = f"API 请求失败：{response.status_code} - {response.text}"
                await save_chat_log(
                    str(event.user_id), user_name, group_id, group_name,
                    msg_text, "", error_msg
                )
                return error_msg
            
            try:
                result = response.json()
            except json.JSONDecodeError:
                error_msg = "API 返回的数据格式错误"
                await save_chat_log(
                    str(event.user_id), user_name, group_id, group_name,
                    msg_text, "", error_msg
                )
                return error_msg
            
            # 检查返回数据的完整性
            if not result:
                error_msg = "API 返回空数据"
                await save_chat_log(
                    str(event.user_id), user_name, group_id, group_name,
                    msg_text, "", error_msg
                )
                return error_msg
                
            if "choices" not in result or not result["choices"]:
                error_msg = "API 返回数据不完整"
                await save_chat_log(
                    str(event.user_id), user_name, group_id, group_name,
                    msg_text, "", error_msg
                )
                return error_msg
            
            # 获取回复内容并清理
            try:
                reply = result["choices"][0]["message"]["content"]
                reply = clean_message(reply)  # 清理回复内容
            except (KeyError, IndexError):
                error_msg = "API 返回数据结构异常"
                await save_chat_log(
                    str(event.user_id), user_name, group_id, group_name,
                    msg_text, "", error_msg
                )
                return error_msg
            
            # 检查回复内容
            if not reply or not reply.strip():
                error_msg = "API 返回空回复"
                await save_chat_log(
                    str(event.user_id), user_name, group_id, group_name,
                    msg_text, "", error_msg
                )
                return error_msg
            
            # 记录成功的对话（使用清理后的回复）
            await save_chat_log(
                str(event.user_id), user_name, group_id, group_name,
                msg_text, reply
            )
            
            # 更新对话历史（使用清理后的回复）
            try:
                # 确保历史记录中包含 system prompt
                if system_prompt and (not chat_history[user_id] or chat_history[user_id][0]["role"] != "system"):
                    chat_history[user_id].insert(0, {"role": "system", "content": system_prompt})
                
                chat_history[user_id].append({"role": "user", "content": msg_text})
                chat_history[user_id].append({"role": "assistant", "content": reply})
                
                # 保持历史记录在限定条数内，但保留 system prompt
                if system_prompt:
                    while len(chat_history[user_id]) > (max_history * 2) + 1:
                        chat_history[user_id].pop(1)
                        chat_history[user_id].pop(1)
                else:
                    while len(chat_history[user_id]) > max_history * 2:
                        chat_history[user_id].pop(0)
            except Exception as e:
                print(f"更新对话历史时发生错误：{e}")
                # 继续处理，不影响回复
            
            return Message(reply)  # 返回清理后的回复
        
    except Exception as e:
        error_msg = f"发生未知错误：{str(e)}"
        await save_chat_log(
            str(event.user_id), user_name, group_id, group_name,
            msg_text, "", error_msg
        )
        return error_msg

# 添加清除历史记录的命令
clear_history = on_command("clear", priority=10, block=True)

@clear_history.handle()
async def handle_clear_history(event: MessageEvent):
    user_id = get_user_id(event)
    # 保留 system prompt
    if system_prompt and chat_history[user_id] and chat_history[user_id][0]["role"] == "system":
        system_message = chat_history[user_id][0]
        chat_history[user_id].clear()
        chat_history[user_id].append(system_message)
    else:
        chat_history[user_id].clear()
        if system_prompt:
            chat_history[user_id].append({"role": "system", "content": system_prompt})
    await clear_history.finish("已清除对话历史记录！（系统提示已保留）")

if enable_at:
    @chat_at.handle()
    async def handle_chat_at(event: MessageEvent):
        # 检查群聊功能
        if isinstance(event, GroupMessageEvent):
            group_id = event.group_id
            if not chat_enabled.get(group_id, default_chat_enabled):
                await chat_at.finish("冰冰收到，已读不回！。")
                return
        
        msg_text = event.get_plaintext().strip()
        # 处理空@的情况
        if not msg_text:
            empty_at_messages = config.get("messages", {}).get("empty_at", [
                "Hi，我在呢！有什么可以帮你的吗？😊"
            ])
            random_msg = random.choice(empty_at_messages) if isinstance(empty_at_messages, list) else empty_at_messages
            await chat_at.finish(Message(random_msg))
            return
            
        reply = await handle_chat_common(event, msg_text)
        if reply:
            await chat_at.finish(reply)

if enable_prefix:
    @chat_prefix.handle()
    async def handle_chat_prefix(event: MessageEvent):
        # 检查群聊功能
        if isinstance(event, GroupMessageEvent):
            group_id = event.group_id
            if not chat_enabled.get(group_id, default_chat_enabled):
                await chat_prefix.finish("冰冰收到，已读不回！。")
                return
        
        # 检查私聊权限
        if isinstance(event, PrivateMessageEvent):
            if not await check_private_chat(event):
                await chat_prefix.finish("私聊功能已禁用")
                return
            
        msg_text = event.get_plaintext().strip()
        # 移除触发前缀
        for prefix in trigger_prefixes:
            if msg_text.lower().startswith(prefix.lower()):
                msg_text = msg_text[len(prefix):].strip()
                break
        
        reply = await handle_chat_common(event, msg_text)
        if reply:
            await chat_prefix.finish(reply)

if enable_command:
    @chat_command.handle()
    async def handle_chat_command(event: MessageEvent):
        # 检查群聊功能
        if isinstance(event, GroupMessageEvent):
            group_id = event.group_id
            if not chat_enabled.get(group_id, default_chat_enabled):
                await chat_command.finish("冰冰收到，已读不回！")
                return
        
        if not await check_command_permission(event):
            await chat_command.finish("冰冰不认识你！才不听你话！")
            return
            
        if isinstance(event, PrivateMessageEvent) and not await check_private_chat(event):
            await chat_command.finish("私聊功能已禁用")
            return
            
        msg_text = str(event.get_message()).strip()
        reply = await handle_chat_common(event, msg_text)
        if reply:
            await chat_command.finish(reply)

# 读取配置文件后添加
admin_config = config.get("admin", {})
superusers = set(admin_config.get("superusers", []))
admin_private_chat = admin_config.get("enable_private_chat", True)
admin_command = admin_config.get("enable_command", True)

# 修改用户权限检查函数
def is_superuser(event: MessageEvent) -> bool:
    return event.user_id in superusers

# 修改私聊权限检查
async def check_private_chat(event: PrivateMessageEvent) -> bool:
    is_super = is_superuser(event)
    print(f"用户 {event.user_id} 的权限检查：是否超级用户={is_super}, admin_private_chat={admin_private_chat}, private_chat_enabled={private_chat_enabled}")
    if is_super:
        return admin_private_chat
    return private_chat_enabled

# 修改命令权限检查
async def check_command_permission(event: MessageEvent) -> bool:
    if is_superuser(event):
        return admin_command
    return enable_command

# 在文件开头的导入部分添加
from typing import Dict

# 在全局变量部分添加
group_isolation: Dict[int, bool] = {}  # 存储每个群的隔离状态
default_isolation = oai_config.get("group_isolation", True)  # 从配置文件获取默认值
chat_enabled: Dict[int, bool] = {}  # 存储每个群的聊天功能状态
default_chat_enabled = True  # 默认开启聊天功能

# 添加新的命令处理器
chat_settings = on_command(
    "chat",
    permission=lambda event: event.user_id in superusers,
    priority=5,
    block=True
)

@chat_settings.handle()
async def handle_chat_settings(event: MessageEvent):
    global group_isolation, chat_enabled
    
    # 获取原始消息文本
    msg_text = str(event.get_message()).strip()
    
    # 如果只有命令名称（"/chat"），显示当前状态
    if msg_text == "/chat":
        if isinstance(event, GroupMessageEvent):
            group_id = event.group_id
            isolation_status = "开启" if group_isolation.get(group_id, default_isolation) else "关闭"
            chat_status = "开启" if chat_enabled.get(group_id, default_chat_enabled) else "关闭"
            
            await chat_settings.finish(f"""群聊设置状态：
- 聊天功能：{chat_status}
- 对话隔离：{isolation_status}

使用方法：
/chat true      - 开启群聊功能
/chat false     - 关闭群聊功能
/chat group true  - 开启群聊隔离（每个人独立对话）
/chat group false - 关闭群聊隔离（群内共享对话）""")
        else:
            await chat_settings.finish("此命令只能在群聊中使用。")
        return
    
    # 获取命令参数
    args = msg_text.split()[1:]  # 去掉命令名称，获取参数部分
    if not args:
        # 如果没有参数，显示帮助信息
        await chat_settings.finish("""使用方法：
/chat true      - 开启群聊功能
/chat false     - 关闭群聊功能
/chat group true  - 开启群聊隔离
/chat group false - 关闭群聊隔离""")
        return
    
    # 处理群聊开关命令
    if args[0].lower() in ['true', 'false']:
        if not isinstance(event, GroupMessageEvent):
            await chat_settings.finish("此命令只能在群聊中使用。")
            return
        
        group_id = event.group_id
        new_state = args[0].lower() == 'true'
        old_state = chat_enabled.get(group_id, default_chat_enabled)
        
        # 更新设置
        chat_enabled[group_id] = new_state
        
        await chat_settings.finish(f"群聊功能已{'开启' if new_state else '关闭'}。")
        return
    
    # 处理群聊隔离命令
    if len(args) >= 2 and args[0] == "group":
        if not isinstance(event, GroupMessageEvent):
            await chat_settings.finish("此命令只能在群聊中使用。")
            return
        
        group_id = event.group_id
        
        # 解析 true/false 参数
        if args[1].lower() not in ['true', 'false']:
            await chat_settings.finish("参数错误。请使用 'true' 或 'false'。")
            return
        
        new_state = args[1].lower() == 'true'
        old_state = group_isolation.get(group_id, default_isolation)
        
        # 更新设置
        group_isolation[group_id] = new_state
        
        # 如果状态发生改变，清理该群的历史记录
        if new_state != old_state:
            group_prefix = f"group_{group_id}"
            # 清理相关的历史记录
            for key in list(chat_history.keys()):
                if key.startswith(group_prefix):
                    chat_history.pop(key)
            
            # 如果关闭隔离，创建新的群组共享历史记录
            if not new_state:
                chat_history[f"group_{group_id}"] = []
                if system_prompt:
                    chat_history[f"group_{group_id}"].append({"role": "system", "content": system_prompt})
        
        await chat_settings.finish(f"群聊隔离已{'开启' if new_state else '关闭'}。\n{'每个人的对话都是独立的' if new_state else '群内成员共享对话上下文'}。")
        return
    
    # 如果命令格式不正确
    await chat_settings.finish("""无效的命令。使用方法：
/chat true      - 开启群聊功能
/chat false     - 关闭群聊功能
/chat group true  - 开启群聊隔离
/chat group false - 关闭群聊隔离""")