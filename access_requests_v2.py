"""Хранилище запросов на доступ и информации о выдаче прав.

Самодостаточный модуль: использует свой JSON-файл access_data.json
и не требует изменений в user_settings.py.
"""
import json
import os
import time
from typing import Dict, Any, Optional

DATA_FILE = os.environ.get("ACCESS_DATA_FILE", "access_data.json")


def _load() -> Dict[str, Any]:
    if not os.path.exists(DATA_FILE):
        return {"requests": {}, "grants": {}}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("requests", {})
        data.setdefault("grants", {})
        return data
    except Exception:
        return {"requests": {}, "grants": {}}


def _save(data: Dict[str, Any]) -> None:
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DATA_FILE)


# ---------- Запросы на доступ ----------

def add_request(user_id: int, first_name: str = "", username: str = "") -> bool:
    """Возвращает True, если запрос добавлен; False — если уже существовал."""
    data = _load()
    key = str(user_id)
    if key in data["requests"]:
        # Обновим имя/username на свежие
        data["requests"][key]["first_name"] = first_name
        data["requests"][key]["username"] = username
        _save(data)
        return False
    data["requests"][key] = {
        "first_name": first_name,
        "username": username,
        "ts": int(time.time()),
    }
    _save(data)
    return True


def remove_request(user_id: int) -> None:
    data = _load()
    data["requests"].pop(str(user_id), None)
    _save(data)


def has_request(user_id: int) -> bool:
    data = _load()
    return str(user_id) in data["requests"]


def get_requests() -> Dict[str, Dict[str, Any]]:
    return _load()["requests"]


# ---------- Кто выдал права ----------

def set_granted_by(user_id: int, admin_id: int) -> None:
    data = _load()
    data["grants"][str(user_id)] = {
        "admin_id": admin_id,
        "ts": int(time.time()),
    }
    _save(data)


def get_granted_by(user_id: int) -> Optional[int]:
    data = _load()
    g = data["grants"].get(str(user_id))
    return g["admin_id"] if g else None


def clear_grant(user_id: int) -> None:
    data = _load()
    data["grants"].pop(str(user_id), None)
    _save(data)
