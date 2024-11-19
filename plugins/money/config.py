from pathlib import Path
import tomli
from pydantic import BaseModel

class Config(BaseModel):
    # 插件配置
    keywords: list = ["冰冰v我", "冰冰vwo", "冰冰V我", "冰冰Vwo"]
    image_dir: str = str(Path(__file__).parent / "images")
    max_amount: int = 10000
    exceed_messages: list = [
        "这么多钱，你怎么不去抢银行？",
        "这么多钱，你咋不上天呢？",
        "一次最多v你100哦，再多我就破产了",
        "你这么有钱，要不v我试试？",
        "这么多钱，你是不是想让我去贷款？"
    ]
    success_messages: list = [
        "给你钱，快去买快乐水吧！",
        "最后一点咯~",
        "钱都给你了，记得请我吃饭！",
        "给你给你，记得还我",
        "冰爷不差钱，收好！"
    ]
    error_messages: list = [
        "今天钱包掉了~下次再说吧",
        "我的钱包好像被偷了...",
        "糟糕，今天忘记带钱包了",
        "不好意思，今天银行卡被冻结了",
        "哎呀，今天的零花钱用完了"
    ]
    negative_messages: list = [
        "你想给我钱？谢谢啊！",
        "想给我钱就直说嘛，干嘛这么客气~",
        "谢谢请给我吧~",
        "好人一生平安~",
        "有钱能使鬼推磨~有钱也能使冰冰推磨~"
    ]

# 读取 TOML 配置文件
config_file = Path("config.toml")
if not config_file.exists():
    raise ValueError("配置文件 config.toml 不存在")

try:
    # 读取配置文件
    with open(config_file, "rb") as f:
        toml_config = tomli.load(f)
        money_config = toml_config.get("money", {})
    
    # 合并默认配置和配置文件中的配置
    config = Config(**{
        **Config().dict(),  # 默认配置
        **money_config      # 配置文件中的配置
    })
    
except Exception as e:
    # 如果获取失败，使用默认配置
    config = Config()
    print(f"使用默认配置，原因：{str(e)}")