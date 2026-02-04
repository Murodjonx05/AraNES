from pydantic import BaseModel

from core.permission import PermissionsRegistry


def test_register_and_instance_without_prefix():
    class AuthPlugin(BaseModel):
        name: str = "guest"
        level: int = 1

    registry = PermissionsRegistry()
    registry.register(AuthPlugin)

    Model = registry.schema()
    obj = Model()

    assert obj.model_dump() == {
        "authplugin:name": "guest",
        "authplugin:level": 1,
    }


def test_prefix_normalization_and_unmap():
    class QuizPlugin(BaseModel):
        enabled: bool = True
        attempts: int = 3

    registry = PermissionsRegistry()
    registry.register(QuizPlugin, prefix="plugins/quiz")

    obj = registry.instance(**{"plugins:quiz:quizplugin:attempts": 5})
    data = registry.unmap(obj, QuizPlugin)

    assert data == {"enabled": True, "attempts": 5}


def test_prefix_priority_overwrites_lower_priority():
    class BasePlugin(BaseModel):
        value: str = "base"

    class OverridePlugin(BaseModel):
        value: str = "override"

    registry = PermissionsRegistry()
    registry.register(BasePlugin)
    registry.register(OverridePlugin, prefix="plugins/override")

    fields = registry.fields()
    assert "baseplugin:value" in fields
    assert "plugins:override:overrideplugin:value" in fields
