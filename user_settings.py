from __future__ import annotations

import json
from pathlib import Path

import ccxt.async_support as ccxt

from config import DEFAULT_EXCHANGES, DEFAULT_MIN_ARB_PCT, SETTINGS_FILE

# Динамически получаем список всех бирж, которые поддерживает библиотека ccxt
AVAILABLE_EXCHANGES = set(ccxt.exchanges)

def _load_raw() -> dict:
    if not SETTINGS_FILE.exists():
        return {}
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_raw(data: dict) -> None:
    SETTINGS_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _default_profile() -> dict:
    return {
        "exchanges": list(DEFAULT_EXCHANGES),
        "min_arb_pct": DEFAULT_MIN_ARB_PCT,
        "signals_enabled": False,
    }


def _get_profile(user_id: int) -> dict:
    key = str(user_id)
    entry = _load_raw().get(key)
    if isinstance(entry, list):
        return {
            "exchanges": entry,
            "min_arb_pct": DEFAULT_MIN_ARB_PCT,
            "signals_enabled": False,
        }
    if isinstance(entry, dict):
        profile = _default_profile()
        profile.update(entry)
        return profile
    return _default_profile()


def _set_profile(user_id: int, profile: dict) -> None:
    data = _load_raw()
    data[str(user_id)] = profile
    _save_raw(data)


def is_valid_exchange(exchange_id: str) -> bool:
    name = exchange_id.strip().lower()
    if name not in AVAILABLE_EXCHANGES:
        return False
    return getattr(ccxt, name, None) is not None


def get_user_exchanges(user_id: int) -> list[str]:
    exchanges = _get_profile(user_id).get("exchanges", [])
    valid = [e for e in exchanges if is_valid_exchange(e)]
    return valid or list(DEFAULT_EXCHANGES)


def set_user_exchanges(user_id: int, exchanges: list[str]) -> None:
    profile = _get_profile(user_id)
    profile["exchanges"] = exchanges
    _set_profile(user_id, profile)


def get_min_arb_pct(user_id: int) -> float:
    try:
        return float(_get_profile(user_id).get("min_arb_pct", DEFAULT_MIN_ARB_PCT))
    except (TypeError, ValueError):
        return DEFAULT_MIN_ARB_PCT


def set_min_arb_pct(user_id: int, pct: float) -> None:
    profile = _get_profile(user_id)
    profile["min_arb_pct"] = max(0.0, pct)
    _set_profile(user_id, profile)


def get_signals_enabled(user_id: int) -> bool:
    return bool(_get_profile(user_id).get("signals_enabled", False))


def set_signals_enabled(user_id: int, enabled: bool) -> None:
    profile = _get_profile(user_id)
    profile["signals_enabled"] = enabled
    _set_profile(user_id, profile)


def get_all_users_with_signals() -> list[int]:
    data = _load_raw()
    users = []
    for uid_str, profile in data.items():
        if isinstance(profile, dict) and profile.get("signals_enabled"):
            try:
                users.append(int(uid_str))
            except ValueError:
                continue
    return users


def add_user_exchange(user_id: int, exchange_id: str) -> tuple[bool, str]:
    name = exchange_id.strip().lower()
    if not is_valid_exchange(name):
        return False, (
            f"Биржа «{exchange_id}» не поддерживается библиотекой ccxt.\n"
            "Проверьте правильность написания ID (например: binance, upbit, bitget)."
        )
    current = get_user_exchanges(user_id)
    if name in current:
        return False, f"{name.upper()} уже в списке."
    if len(current) >= 20:
        return False, "Максимум 20 бирж. Уберите лишние через /remove."
    current.append(name)
    set_user_exchanges(user_id, current)
    return True, f"Добавлено: {name.upper()}. Сейчас: {_fmt_list(current)}"


def remove_user_exchange(user_id: int, exchange_id: str) -> tuple[bool, str]:
    name = exchange_id.strip().lower()
    current = get_user_exchanges(user_id)
    if name not in current:
        return False, f"{name.upper()} не было в вашем списке."
    if len(current) <= 1:
        return False, "Нельзя убрать последнюю биржу. Сначала добавьте другую."
    current = [e for e in current if e != name]
    set_user_exchanges(user_id, current)
    return True, f"Убрано: {name.upper()}. Сейчас: {_fmt_list(current)}"


def reset_user_exchanges(user_id: int) -> str:
    profile = _get_profile(user_id)
    profile["exchanges"] = list(DEFAULT_EXCHANGES)
    _set_profile(user_id, profile)
    return f"Сброшено к стандарту: {_fmt_list(DEFAULT_EXCHANGES)}"


def format_user_settings(user_id: int) -> str:
    ex = get_user_exchanges(user_id)
    min_pct = get_min_arb_pct(user_id)
    signals = get_signals_enabled(user_id)
    
    min_line = (
        f"Мин. арбитраж: {min_pct}% (показывать всё)"
        if min_pct <= 0
        else f"Мин. арбитраж: {min_pct}% (топ и подсветка)"
    )
    sig_line = "Сигналы (авто-скан): " + ("✅ ВКЛ" if signals else "❌ ВЫКЛ")
    
    return (
        f"⚙️ Ваши настройки\n\n"
        f"• Биржи ({len(ex)}): {_fmt_list(ex)}\n"
        f"• {min_line}\n"
        f"• {sig_line}\n\n"
        f"Изменить мин: /min 0.05\n"
        f"Сигналы: /signals on/off\n"
        f"Биржи: /exchanges"
    )


def _fmt_list(exchanges: list[str]) -> str:
    return ", ".join(e.upper() for e in exchanges)
