import datetime
import logging
from copy import copy

import pytest
from mock import patch

import runez
from runez.schema import determined_schema_type, Dict, Integer, List, String, UniqueIdentifier, ValidationException
from runez.serialize import add_meta, ClassMetaDescription, same_type, SerializableDescendants, type_name, with_behavior


@add_meta(ClassMetaDescription)
class MetaSlotted(object):
    __slots__ = "name"


@add_meta(ClassMetaDescription)
class MetaSlotted2(object):
    __slots__ = ["name", "surname"]

    @property
    def full_name(self):
        return "%s %s" % (self.name, self.surname)


class SlottedExample(runez.Serializable, with_behavior(strict=True, extras=Exception)):
    __slots__ = ["name"]


def test_slotted(logged):
    assert isinstance(MetaSlotted._meta, ClassMetaDescription)
    assert len(MetaSlotted._meta.attributes) == 1
    assert not MetaSlotted._meta.properties

    assert isinstance(MetaSlotted2._meta, ClassMetaDescription)
    assert len(MetaSlotted2._meta.attributes) == 2
    assert MetaSlotted2._meta.properties == ["full_name"]

    assert isinstance(SlottedExample._meta, ClassMetaDescription)
    assert len(SlottedExample._meta.attributes) == 1
    assert not SlottedExample._meta.properties

    se = SlottedExample.from_dict({"name": "foo"})
    assert se.name == "foo"
    assert se.to_dict() == {"name": "foo"}

    with pytest.raises(Exception) as e:
        SlottedExample.from_dict({"foo": "bar"})
    assert str(e.value) == "Extra content given for SlottedExample: foo"


def test_bogus_class():
    with pytest.raises(ValidationException):

        class Bogus(runez.Serializable):
            """This class shouldn't have to unique identifiers"""

            id1 = UniqueIdentifier
            id2 = UniqueIdentifier


def test_determined_schema_type():
    assert str(determined_schema_type("a")) == "string (default: a)"
    assert str(determined_schema_type(u"a")) == "string (default: a)"
    assert str(determined_schema_type(5)) == "integer (default: 5)"

    assert str(determined_schema_type(str)) == "string"
    assert str(determined_schema_type(int)) == "integer"
    assert str(determined_schema_type(dict)) == "dict[any, any]"
    assert str(determined_schema_type(list)) == "list[any]"
    assert str(determined_schema_type(set)) == "list[any]"
    assert str(determined_schema_type(tuple)) == "list[any]"

    assert str(determined_schema_type(List)) == "list[any]"
    assert str(determined_schema_type(List(Integer))) == "list[integer]"
    assert str(determined_schema_type(Dict(String, List(Integer)))) == "dict[string, list[integer]]"

    with pytest.raises(ValidationException) as e:
        determined_schema_type(object())
    assert "Invalid schema definition" in str(e.value)


def test_json(temp_folder):
    assert runez.read_json(None, default=None) is None

    assert runez.represented_json(None) == "null\n"
    assert runez.represented_json([]) == "[]\n"
    assert runez.represented_json({}) == "{}\n"
    assert runez.represented_json("foo") == '"foo"\n'

    assert runez.represented_json({None: 2}) == '{\n  "null": 2\n}\n'
    assert runez.represented_json({None: 2}, none_key="None") == '{\n  "None": 2\n}\n'
    assert runez.represented_json({None: None}, keep_none=True) == '{\n  "null": null\n}\n'
    assert runez.represented_json({None: 1, "foo": None}, keep_none=True, none_key="_null") == '{\n  "_null": 1,\n  "foo": null\n}\n'

    if runez.PY2:
        assert runez.represented_json({None: 2, "foo": "bar"}) == '{\n  "null": 2,\n  "foo": "bar"\n}\n'
        assert runez.represented_json({None: 1, "foo": None}, keep_none=True) == '{\n  "null": 1,\n  "foo": null\n}\n'

    else:
        with pytest.raises(TypeError):
            # py3 stdlib can't sort with None key...
            runez.represented_json({None: 2, "foo": "bar"})

    data = {"a": "x", "b": "y"}
    assert runez.represented_json(data) == '{\n  "a": "x",\n  "b": "y"\n}\n'
    assert runez.represented_json(data, indent=None) == '{"a": "x", "b": "y"}'

    assert runez.save_json(None, None, fatal=False) == 0

    assert not runez.DRYRUN
    with runez.CaptureOutput(dryrun=True) as logged:
        assert runez.save_json(data, "sample.json") == 1
        assert "Would save" in logged.pop()
    assert not runez.DRYRUN

    with runez.CaptureOutput() as logged:
        with pytest.raises(runez.system.AbortException):
            runez.read_json(None)
        assert "No file None" in logged.pop()

        assert runez.read_json("sample.json", default=None) is None
        assert not logged

        assert runez.read_json("sample.json", default={}) == {}
        assert not logged

        with patch("runez.serialize.open", side_effect=Exception):
            assert runez.save_json(data, "sample.json", fatal=False) == -1
            assert "Couldn't save" in logged.pop()

        assert runez.save_json(data, "sample.json", logger=logging.debug) == 1
        assert "Saved " in logged.pop()

        with patch("io.open", side_effect=Exception):
            with pytest.raises(runez.system.AbortException):
                runez.read_json("sample.json")
            assert "Couldn't read sample.json" in logged.pop()

            assert runez.read_json("sample.json", default=None) is None
            assert not logged


class SomeSerializable(runez.Serializable, with_behavior(strict=True)):
    name = "my name"
    some_int = 7
    some_value = List(Integer)
    another = None

    _called = None

    @classmethod
    def do_something_on_class(cls, value):
        cls._called = value

    def do_something_on_instance(cls, value):
        cls._called = value

    @property
    def int_prod(self):
        return self.some_int

    def set_some_int(self, value):
        self.some_int = value


class SomeRecord(object):
    name = "my record"
    some_int = 5


def test_meta(logged):
    custom = ClassMetaDescription(SomeRecord, None)
    assert len(custom.attributes) == 2
    assert len(custom.properties) == 0
    assert custom.by_type == {"string": ["name"], "integer": ["some_int"]}
    assert custom.attributes["name"].default == "my record"
    assert custom.attributes["some_int"].default == 5
    assert str(custom.behavior) == "extras: function 'debug'"

    assert SerializableDescendants.descendant_with_name("NoSuchDescendant") is None
    assert SerializableDescendants.descendant_with_name("SomeSerializable") is SomeSerializable._meta
    assert SerializableDescendants.descendant_with_name("tests.test_serialize.SomeSerializable") is SomeSerializable._meta

    assert SomeSerializable._called is None
    SerializableDescendants.call("do_something_on_class", "testing")
    assert SomeSerializable._called == "testing"

    with pytest.raises(TypeError):
        SerializableDescendants.call("do_something_on_instance", "testing")

    with pytest.raises(ValidationException) as e:
        SomeSerializable.from_dict({"some_int": "foo"})
    assert str(e.value) == "Can't deserialize SomeSerializable.some_int: expecting int, got 'foo'"

    data = {"name": "some name", "some_int": 15}
    obj = SomeSerializable.from_dict(data)
    assert isinstance(obj, SomeSerializable)
    assert obj.name == "some name"
    assert obj.some_int == 15

    obj2 = SomeSerializable()
    assert isinstance(obj2, SomeSerializable)
    assert obj2.another is None
    assert obj2.name == "my name"  # Default values
    assert obj2.some_int == 7
    assert obj2.some_value is None

    obj2 = copy(obj)
    assert isinstance(obj2, SomeSerializable)
    assert obj2 is not obj
    assert obj2 == obj

    obj2 = SomeSerializable()
    assert obj != obj2
    assert SomeSerializable._meta.changed_attributes(obj, obj2) == [("name", "some name", "my name"), ("some_int", 15, 7)]

    obj2.name = "some name"
    obj2.some_int = 15
    assert obj == obj2

    assert len(SomeSerializable._meta.attributes) == 4
    assert len(SomeSerializable._meta.properties) == 1
    assert obj._meta is SomeSerializable._meta

    assert not logged

    obj = SomeSerializable.from_dict({"name": "foo", "some_int": 1})
    obj.set_from_dict({"name": "foo"})
    assert obj.name == "foo"
    assert obj.some_int == 7  # Value reset to object's default

    obj = SomeSerializable.from_dict({"name": "foo", "some_int": 1})
    obj.set_from_dict({"name": "foo"}, merge=True)
    assert obj.name == "foo"
    assert obj.some_int == 1  # Value NOT reset to default


def test_sanitize():
    assert runez.serialize.json_sanitized(None) is None
    assert runez.serialize.json_sanitized({1, 2}) == [1, 2]
    assert runez.serialize.json_sanitized({None: 2}) == {None: 2}
    assert runez.serialize.json_sanitized({None: 2}, none_key="None") == {"None": 2}

    now = datetime.datetime.now()
    assert runez.serialize.json_sanitized(now) == str(now)
    assert runez.serialize.json_sanitized(now, dt=None) is now
    assert runez.serialize.json_sanitized([now]) == [str(now)]
    assert runez.serialize.json_sanitized([now], dt=None) == [now]

    obj = object()
    assert runez.serialize.json_sanitized(obj) == str(obj)
    assert runez.serialize.json_sanitized(obj, stringify=None) is obj


def test_serialization(logged):
    obj = runez.Serializable()
    assert not obj._meta.attributes
    assert not obj._meta.properties

    obj.set_from_dict({}, source="testing")  # no-op
    assert not logged

    obj.set_from_dict({"foo": 0}, source="testing")  # no-op
    assert not logged

    obj = SomeSerializable.from_dict({}, source="testing")
    assert obj.to_dict() == {"name": "my name", "some_int": 7}

    # Unknown fields
    obj2 = SomeSerializable.from_dict({"foo": 1, "bar": 2})
    assert not hasattr(obj2, "foo")  # non-declared keys are ignored
    assert obj2.some_int == 7  # Fields not in data still get their default value
    assert obj == obj2
    assert "Extra content given for SomeSerializable: bar, foo" in logged.pop()

    obj2 = SomeSerializable.from_json("", default={})
    assert obj == obj2
    assert not logged

    obj.some_int = 5
    obj.reset()
    assert obj.name == "my name"
    assert obj.some_int == 7
    assert obj.some_value is None
    assert obj == obj2

    if not runez.WINDOWS:
        obj3 = SomeSerializable.from_json("/dev/null/not-there", default=None)
        assert not logged
        assert obj == obj3


def test_to_dict(temp_folder):
    with runez.CaptureOutput() as logged:
        # Try with an object that isn't directly serializable, but has a to_dict() function
        data = {"a": "b"}
        obj = SomeRecord()
        obj.to_dict = lambda *_: data

        assert runez.save_json(obj, "sample2.json", logger=logging.debug) == 1
        assert "Saved " in logged.pop()
        assert runez.read_json("sample2.json") == data
        assert not logged


def test_types():
    assert type_name(None) == "None"
    assert type_name("some-string") == "str"
    assert type_name(u"some-string") == "str"
    assert type_name({}) == "dict"
    assert type_name(dict) == "dict"
    assert type_name([]) == "list"
    assert type_name(1) == "int"

    assert same_type(None, None)
    assert not same_type(None, "")
    assert not same_type("", None)
    assert same_type("some-string", "some-other-string")
    assert same_type("some-string", u"some-unicode")
    assert same_type(["some-string"], [u"some-unicode"])
    assert same_type(1, 2)
