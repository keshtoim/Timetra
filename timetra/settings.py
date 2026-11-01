import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class Settings:
    theme: str = "system"  # light, dark или system
    big_text: bool = False
    tips: bool = True


def load_settings(path: Path) -> Settings:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return Settings(**{k: v for k, v in data.items() if k in Settings.__dataclass_fields__})
    except (OSError, ValueError):
        # испорченный файл настроек не повод не запускаться
        return Settings()


def save_settings(path: Path, settings: Settings) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(settings)), encoding="utf-8")
