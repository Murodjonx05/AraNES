"""
PERMISSIONS — динамический менеджер Pydantic-схем.

Имена полей:
    [relative_path:plugin_name]:class_name:field_name (lowercase)

Приоритеты:
    P2 (с prefix) > P1 (без prefix)
    Коллизия одного уровня → останется только одно поле
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field as dc_field
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple, Type, Union

from pydantic import BaseModel, create_model
from pydantic_core import PydanticUndefined
from pydantic.fields import FieldInfo


logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────
# Внутренние структуры данных
# ─────────────────────────────────────────────────────────

@dataclass
class _FieldEntry:
    """Запись об одном поле во внутреннем реестре."""
    annotation: Any
    field_info: FieldInfo
    priority: int                  # 1 = без prefix, 2 = с prefix
    source_plugin: str             # имя плагина (модели), откуда поле


@dataclass
class _PluginRecord:
    """Запись о зарегистрированном плагине (модели)."""
    model_class: Type[BaseModel]
    prefix: Optional[str]          # None если без prefix
    # original_name -> transformed_name
    name_map: Dict[str, str] = dc_field(default_factory=dict)


# ─────────────────────────────────────────────────────────
# Утилиты
# ─────────────────────────────────────────────────────────

def _is_pydantic_model(obj: Any) -> bool:
    try:
        return isinstance(obj, type) and issubclass(obj, BaseModel)
    except TypeError:
        return False


def _normalize_prefix(prefix: str) -> str:
    """
    Приводит префикс к формату с разделителями ':'.
    Пример: 'plugins/quiz' -> 'plugins:quiz'
    """
    return prefix.replace("\\", "/").replace("/", ":").strip(":").lower()


def _build_transformed_name(prefix: Optional[str], class_name: str, field_name: str) -> str:
    """
    Строит имя по шаблону:
        [relative_path:plugin_name]:class_name:field_name
    где разделитель — ':'. Всё приводится к нижнему регистру.
    """
    parts = []
    if prefix:
        parts.append(prefix)
    parts.append(class_name)
    parts.append(field_name)
    return ":".join(parts).lower()


# ─────────────────────────────────────────────────────────
# PermissionsRegistry
# ─────────────────────────────────────────────────────────

class PermissionsRegistry:
    """
    Динамический менеджер Pydantic-схем с поддержкой namespace и приоритетов.

    Использование:
        registry = PermissionsRegistry()
        registry.register(AuthPlugin)                    # без prefix, приоритет 1
        registry.register(SecurityPlugin, prefix="sec")  # с prefix, приоритет 2

        Model = registry.schema()
        obj   = registry.instance(**{"sec:securityplugin:timeout": 30})
        data  = registry.unmap(obj, AuthPlugin)
    """

    def __init__(self):
        # Реестр плагинов: имя_плагина -> _PluginRecord
        self._plugins: Dict[str, _PluginRecord] = {}

        # Плоский реестр полей итоговой схемы: transformed_name -> _FieldEntry
        self._fields: Dict[str, _FieldEntry] = {}

        # Для имени поля: кто последний "выиграл" коллизию (plugin_name)
        self._collisions: Dict[str, str] = {}

        # Текущая модель
        self._model: Optional[Type[BaseModel]] = None

        # Флаг изменений
        self._dirty: bool = False
        self._lock = threading.RLock()
        self._change_listeners: List[Callable[["PermissionsRegistry"], None]] = []

    # ─────────────────────────────────────────────
    # РЕГИСТРАЦИЯ плагина
    # ─────────────────────────────────────────────
    def register(self, model: Type[BaseModel], prefix: Optional[str] = None) -> None:
        """
        Регистрирует Pydantic-модель как плагин.

        Args:
            model:  класс Pydantic-модели
            prefix: опциональный префикс. Если задан — приоритет 2, иначе — 1.

        Пример:
            registry.register(AuthPlugin)
            registry.register(SecurityPlugin, prefix="sec")
        """
        with self._lock:
            self._register_model(model, prefix, rebuild=True)
        self._notify_change()

    def register_many(self, entries: Iterable[Tuple[Type[BaseModel], Optional[str]]]) -> None:
        """
        Регистрирует несколько Pydantic-моделей за один проход с одним rebuild.

        Args:
            entries: последовательность (model, prefix)
        """
        with self._lock:
            for model, prefix in entries:
                self._register_model(model, prefix, rebuild=False)
            self._dirty = True
            self._rebuild()
        self._notify_change()

    def unregister(self, model_or_name: Union[Type[BaseModel], str]) -> None:
        """
        Удаляет плагин из реестра и пересобирает схему.

        Args:
            model_or_name: класс модели или имя плагина
        """
        with self._lock:
            if _is_pydantic_model(model_or_name):
                plugin_name = model_or_name.__name__.lower()
            elif isinstance(model_or_name, str):
                plugin_name = model_or_name.lower()
            else:
                raise TypeError("Ожидался класс Pydantic BaseModel или имя плагина.")

            if plugin_name not in self._plugins:
                raise KeyError(f"Плагин '{plugin_name}' не зарегистрирован.")

            del self._plugins[plugin_name]
            self._rebuild_from_plugins()
        self._notify_change()

    def add_change_listener(self, listener: Callable[["PermissionsRegistry"], None]) -> None:
        with self._lock:
            self._change_listeners.append(listener)

    def remove_change_listener(self, listener: Callable[["PermissionsRegistry"], None]) -> None:
        with self._lock:
            self._change_listeners = [item for item in self._change_listeners if item != listener]

    def _register_model(
        self,
        model: Type[BaseModel],
        prefix: Optional[str],
        rebuild: bool,
    ) -> None:
        if not _is_pydantic_model(model):
            raise TypeError(f"Ожидался класс Pydantic BaseModel, получено: {type(model)}")

        plugin_name = model.__name__.lower()

        if plugin_name in self._plugins:
            raise ValueError(f"Плагин '{plugin_name}' уже зарегистрирован.")

        normalized_prefix = _normalize_prefix(prefix) if prefix else None
        priority = 2 if normalized_prefix else 1
        record = _PluginRecord(model_class=model, prefix=normalized_prefix)

        self._add_fields(model, normalized_prefix, plugin_name, priority, record)

        self._plugins[plugin_name] = record
        self._dirty = True
        if rebuild:
            self._rebuild()

    # ─────────────────────────────────────────────
    # ПОЛУЧЕНИЕ модели и экземпляра
    # ─────────────────────────────────────────────
    def schema(self) -> Type[BaseModel]:
        """Возвращает текущий класс динамической модели."""
        with self._lock:
            if self._model is None:
                raise RuntimeError("Ничего не зарегистрировано. Вызови .register() сначала.")
            return self._model

    def instance(self, **kwargs) -> BaseModel:
        """
        Создаёт экземпляр текущей модели.

        Пример:
            obj = registry.instance(**{"authplugin:name": "admin"})
        """
        with self._lock:
            return self.schema()(**kwargs)

    # ─────────────────────────────────────────────
    # UNMAP — обратная трансформация
    # ─────────────────────────────────────────────
    def unmap(self, instance: BaseModel, target_model: Type[BaseModel]) -> Dict[str, Any]:
        """
        Извлекает данные из общего экземпляра обратно в формат целевой модели.
        Отрезает все namespace-префиксы, возвращает словарь с оригинальными именами.

        Args:
            instance:     экземпляр динамической модели (из .instance())
            target_model: класс плагина, в формат которого хотим вернуть данные

        Returns:
            Dict с оригинальными именами полей и их значениями.

        Пример:
            data = registry.unmap(obj, AuthPlugin)
            # data = {"name": "admin", "level": 5}

            # Можно сразу создать экземпляр оригинальной модели:
            auth = AuthPlugin(**data)
        """
        with self._lock:
            if not _is_pydantic_model(target_model):
                raise TypeError(f"Ожидался класс Pydantic BaseModel, получено: {type(target_model)}")

            plugin_name = target_model.__name__.lower()

            if plugin_name not in self._plugins:
                raise KeyError(f"Плагин '{plugin_name}' не зарегистрирован.")

            record = self._plugins[plugin_name]
            instance_data = instance.model_dump()

            result: Dict[str, Any] = {}

            for original_name, transformed_name in record.name_map.items():
                if transformed_name in instance_data:
                    result[original_name] = instance_data[transformed_name]
                else:
                    logger.warning(
                        f"[UNMAP] Поле '{transformed_name}' не найдено в экземпляре "
                        f"(возможно, оно было перезаписано другим плагином/коллизией). Пропускаем."
                    )

            return result

    # ─────────────────────────────────────────────
    # ИНФОРМАЦИЯ
    # ─────────────────────────────────────────────
    def fields(self) -> Dict[str, tuple]:
        """
        Возвращает текущие поля: { transformed_name: (type, default, priority, source) }
        """
        with self._lock:
            return {
                name: (entry.annotation, entry.field_info.default, entry.priority, entry.source_plugin)
                for name, entry in self._fields.items()
            }

    def default_permissions(self) -> Dict[str, Any]:
        """
        Возвращает словарь дефолтных значений для всех зарегистрированных прав.
        Если поле обязательное и без default/default_factory, ставится None.
        """
        defaults: Dict[str, Any] = {}
        with self._lock:
            for name, entry in self._fields.items():
                field_info = entry.field_info
                if hasattr(field_info, "is_required") and field_info.is_required():
                    logger.warning(
                        "[PERMISSIONS] Field '%s' is required but has no default. Using None.",
                        name,
                    )
                    defaults[name] = None
                    continue
                if getattr(field_info, "default_factory", None):
                    defaults[name] = field_info.default_factory()
                else:
                    defaults[name] = (
                        None if field_info.default is PydanticUndefined else field_info.default
                    )
        return defaults

    def collisions(self) -> List[str]:
        """Возвращает список полей, в которых была перезапись (коллизия)."""
        with self._lock:
            return list(self._collisions.keys())

    def plugins(self) -> List[str]:
        """Возвращает список зарегистрированных плагинов."""
        with self._lock:
            return list(self._plugins.keys())

    # ─────────────────────────────────────────────
    # ВНУТРЕННИЕ методы
    # ─────────────────────────────────────────────
    def _rebuild(self) -> None:
        """Пересоздаёт модель. Пропускает если нет изменений."""
        if not self._dirty:
            return

        if not self._fields:
            self._model = None
            self._dirty = False
            return

        field_definitions = {
            name: (entry.annotation, entry.field_info)
            for name, entry in self._fields.items()
        }

        self._model = create_model("PermissionModel", **field_definitions)
        self._dirty = False

    def _notify_change(self) -> None:
        for listener in list(self._change_listeners):
            try:
                listener(self)
            except Exception as exc:
                logger.warning("[PERMISSIONS] Change listener failed: %s", exc)

    def _rebuild_from_plugins(self) -> None:
        self._fields = {}
        self._collisions = {}
        for plugin_name, record in self._plugins.items():
            record.name_map = {}
            normalized_prefix = record.prefix
            priority = 2 if normalized_prefix else 1
            self._add_fields(record.model_class, normalized_prefix, plugin_name, priority, record)
        self._dirty = True
        self._rebuild()

    def _add_fields(
        self,
        model: Type[BaseModel],
        normalized_prefix: Optional[str],
        plugin_name: str,
        priority: int,
        record: _PluginRecord,
    ) -> None:
        for field_name, field_info in model.model_fields.items():
            transformed = _build_transformed_name(normalized_prefix, model.__name__, field_name)
            record.name_map[field_name] = transformed

            entry = _FieldEntry(
                annotation=field_info.annotation,
                field_info=field_info,
                priority=priority,
                source_plugin=plugin_name,
            )

            existing = self._fields.get(transformed)
            if existing is None:
                self._fields[transformed] = entry
                continue

            if entry.priority > existing.priority:
                logger.info(
                    f"[COLLISION/OVERRIDE] '{transformed}': "
                    f"Поле из плагина '{plugin_name}' (P{priority}) перезаписывает "
                    f"'{existing.source_plugin}' (P{existing.priority})"
                )
                self._fields[transformed] = entry
                self._collisions[transformed] = plugin_name
            elif entry.priority == existing.priority:
                logger.info(
                    f"[COLLISION/OVERRIDE] '{transformed}': "
                    f"Поле из плагина '{plugin_name}' (P{priority}) перезаписывает "
                    f"'{existing.source_plugin}' (P{existing.priority})"
                )
                self._fields[transformed] = entry
                self._collisions[transformed] = plugin_name
            else:
                logger.info(
                    f"[COLLISION/IGNORED] '{transformed}': "
                    f"Поле из плагина '{plugin_name}' (P{priority}) "
                    f"уступает '{existing.source_plugin}' (P{existing.priority})"
                )
                self._collisions[transformed] = existing.source_plugin


PERMISSIONS = PermissionsRegistry()
