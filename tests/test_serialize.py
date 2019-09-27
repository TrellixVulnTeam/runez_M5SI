import datetime
import logging

import pytest
from mock import patch

import runez
from runez.serialize import same_type, type_name


@runez.serialize.add_meta(runez.serialize.ClassDescription)
class SlottedExample(object):
    __slots__ = "name"


def test_slotted():
    assert isinstance(SlottedExample._meta, runez.serialize.ClassDescription)
    assert len(SlottedExample._meta.attributes) == 1
    assert not SlottedExample._meta.properties


def test_json(temp_folder):
    assert runez.read_json(None, fatal=False) is None

    assert runez.represented_json(None) == "null\n"
    assert runez.represented_json([]) == "[]\n"
    assert runez.represented_json({}) == "{}\n"
    assert runez.represented_json("foo") == '"foo"\n'

    assert runez.save_json(None, None, fatal=False) == 0

    data = {"a": "b"}

    assert not runez.DRYRUN
    with runez.CaptureOutput(dryrun=True) as logged:
        assert runez.save_json(data, "sample.json") == 1
        assert "Would save" in logged.pop()
    assert not runez.DRYRUN

    with runez.CaptureOutput() as logged:
        assert runez.read_json("sample.json", fatal=False) is None
        assert "No file" in logged.pop()

        assert runez.read_json("sample.json", default={}, fatal=False) == {}
        assert not logged

        with patch("runez.serialize.open", side_effect=Exception):
            assert runez.save_json(data, "sample.json", fatal=False) == -1
            assert "Couldn't save" in logged.pop()

        assert runez.save_json(data, "sample.json", logger=logging.debug) == 1
        assert "Saved " in logged.pop()

        with patch("io.open", side_effect=Exception):
            assert runez.read_json("sample.json", fatal=False) is None
            assert "Couldn't read" in logged.pop()

        assert runez.read_json("sample.json", logger=logging.debug) == data
        assert "Read " in logged.pop()

        assert runez.read_json("sample.json", default=[], fatal=False) == []
        assert "Wrong type" in logged.pop()


class SomeSerializable(runez.Serializable):
    name = "my name"
    some_int = 7
    some_value = list
    another = None

    @property
    def int_prod(self):
        return self.some_int

    def set_some_int(self, value):
        self.some_int = value


def test_meta(logged):
    custom = runez.serialize.ClassDescription(SomeRecord)
    assert len(custom.attributes) == 2
    assert len(custom.properties) == 0

    data = {"name": "some name", "some_int": 15}
    obj = SomeSerializable.from_dict(data)
    obj2 = SomeSerializable()
    assert obj != obj2

    obj2.name = "some name"
    obj2.some_int = 15
    assert obj == obj2

    assert len(SomeSerializable._meta.attributes) == 4
    assert len(SomeSerializable._meta.properties) == 1
    assert obj._meta is SomeSerializable._meta

    assert not logged


class SomeRecord(object):
    name = "my record"
    some_int = 5


def test_to_dict(temp_folder):
    with runez.CaptureOutput() as logged:
        # Try with an object that isn't directly serializable, but has a to_dict() function
        data = {"a": "b"}
        obj = SomeRecord()
        obj.to_dict = lambda *_: data

        assert runez.save_json(obj, "sample2.json", logger=logging.debug) == 1
        assert "Saved " in logged.pop()

        assert runez.read_json("sample2.json", logger=logging.debug) == data
        assert "Read " in logged.pop()


def test_types():
    assert type_name(None) == "None"
    assert type_name("some-string") == "str"
    assert type_name({}) == "dict"
    assert type_name([]) == "list"
    assert type_name(1) == "int"

    assert same_type(None, None)
    assert not same_type(None, "")
    assert same_type("some-string", "some-other-string")
    assert same_type("some-string", u"some-unicode")
    assert same_type(["some-string"], [u"some-unicode"])
    assert same_type(1, 2)


def test_serialization(logged):
    obj = runez.Serializable()
    assert not obj._meta.attributes
    assert not obj._meta.properties

    obj.set_from_dict({}, source="test")  # no-op

    obj = SomeSerializable()

    # Unknown field
    with pytest.raises(runez.system.AbortException):
        obj.set_from_dict({"foo": 1})
    assert "Extra content given for SomeSerializable: foo" in logged.pop()

    obj2 = SomeSerializable.from_dict({"foo": 1, "bar": 2}, ignore=False)
    assert obj == obj2
    assert "Extra content given for SomeSerializable: foo, bar" in logged.pop()

    obj2 = SomeSerializable.from_dict({"foo": 1, "bar": 2}, ignore=["foo", "bar", "baz"])
    assert obj == obj2
    assert not logged

    with pytest.raises(runez.system.AbortException):
        SomeSerializable.from_dict({"foo": 1, "bar": 2}, ignore=["foo"])
    assert "Extra content given for SomeSerializable: bar" in logged.pop()

    with pytest.raises(runez.system.AbortException):
        obj.set_from_dict({"name": 1}, source="test", ignore=False)
    assert "Wrong type 'int' for SomeSerializable.name in test, expecting 'str'" in logged.pop()

    obj.set_from_dict({"some_key": "bar", "name": 1, "some_value": ["foo"]}, source="test", ignore=True)
    assert "Wrong type 'int' for SomeSerializable.name in test, expecting 'str'" in logged.pop()

    assert not hasattr(obj, "some_key")  # We ignore any non-declared keys
    assert obj.name == 1

    # "some_int" was not in data, so it gets a default value
    assert obj.to_dict() == {"name": 1, "some_int": 0, "some_value": ["foo"]}
    assert not logged

    obj2 = SomeSerializable.from_json("", default={})
    assert obj != obj2
    assert not logged

    obj.reset()
    assert obj.name == ""
    assert obj.some_int == 0
    assert obj.some_value == []
    assert obj == obj2

    path = "/dev/null/not-there"
    obj3 = SomeSerializable.from_json(path, fatal=False)
    assert "No file /dev/null/not-there" in logged.pop()

    assert obj == obj3


def test_sanitize():
    assert runez.json_sanitized(None) is None
    assert runez.json_sanitized({1, 2}) == [1, 2]

    now = datetime.datetime.now()
    assert runez.json_sanitized(now) == str(now)
    assert runez.json_sanitized(now, dt=None) is now
    assert runez.json_sanitized([now]) == [str(now)]
    assert runez.json_sanitized([now], dt=None) == [now]

    obj = object()
    assert runez.json_sanitized(obj) == str(obj)
    assert runez.json_sanitized(obj, stringify=None) is obj
