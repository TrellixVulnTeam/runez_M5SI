"""
Convenience methods for (de)serializing objects
"""

import datetime
import inspect
import io
import json
import logging
import os

from runez.base import decode, string_type
from runez.convert import resolved_path, short
from runez.path import ensure_folder
from runez.system import abort, is_dryrun

LOG = logging.getLogger(__name__)


def json_sanitized(value, stringify=decode, dt=str, keep_none=False):
    """
    Args:
        value: Value to sanitize
        stringify (callable | None): Function to use to stringify non-builtin types
        dt (callable | None): Function to use to stringify dates
        keep_none (bool): If False, don't include None values

    Returns:
        An object that should be json serializable
    """
    if value is None or isinstance(value, (int, float, string_type)):
        return value

    if hasattr(value, "to_dict"):
        value = value.to_dict()

    elif isinstance(value, set):
        value = sorted(value)

    if isinstance(value, (tuple, list)):
        return [json_sanitized(v, stringify=stringify, dt=dt, keep_none=keep_none) for v in value if keep_none or v is not None]

    if isinstance(value, dict):
        return dict(
            (
                json_sanitized(k, stringify=stringify, dt=dt, keep_none=keep_none),
                json_sanitized(v, stringify=stringify, dt=dt, keep_none=keep_none),
            )
            for k, v in value.items()
            if keep_none or v is not None
        )

    if isinstance(value, datetime.date):
        if dt is None:
            return value

        return dt(value)

    if stringify is None:
        return value

    return stringify(value)


def same_type(t1, t2):
    """
    :return bool: True if 't1' and 't2' are of equivalent types
    """
    if t1 is None or t2 is None:
        return t1 is t2

    if t1.__class__ is not type:
        t1 = t1.__class__

    if t2.__class__ is not type:
        t2 = t2.__class__

    if issubclass(t1, string_type) and issubclass(t2, string_type):
        return True

    return t1 == t2


def type_name(value):
    """
    :param value: Some object, or None
    :return str: Class name implementing 'value'
    """
    if value is None:
        return "None"

    if isinstance(value, string_type):
        return "str"

    return value.__class__.__name__


class ClassDescription(object):
    """Info on class attributes and properties"""

    def __init__(self, cls):
        self.cls = cls
        self.attributes = {}
        self.properties = []
        for key, value in cls.__dict__.items():
            if not key.startswith("_"):
                if value is None:
                    self.attributes[key] = None

                elif value.__class__ is type:
                    self.attributes[key] = value
                    setattr(cls, key, value())

                elif "property" in value.__class__.__name__:
                    self.properties.append(key)

                elif not inspect.isroutine(value):
                    self.attributes[key] = value.__class__


def add_metaclass(metaclass):
    """Class decorator for creating a class with a metaclass (taken from https://pypi.org/project/six/)."""
    def wrapper(cls):
        orig_vars = cls.__dict__.copy()
        slots = orig_vars.get("__slots__")
        if slots is not None:
            if isinstance(slots, str):
                slots = [slots]
            for slots_var in slots:
                orig_vars.pop(slots_var)
        orig_vars.pop("__dict__", None)
        orig_vars.pop("__weakref__", None)
        if hasattr(cls, "__qualname__"):
            orig_vars["__qualname__"] = cls.__qualname__
        return metaclass(cls.__name__, cls.__bases__, orig_vars)
    return wrapper


def add_meta(meta_type):
    """A simplified metaclass that simply injects a `._meta` field of given type `meta_type`"""
    class meta_injector(type):
        def __init__(cls, name, bases, dct):
            super(meta_injector, cls).__init__(name, bases, dct)
            cls._meta = meta_type(cls)

    return add_metaclass(meta_injector)


@add_meta(ClassDescription)
class Serializable(object):
    """Serializable object"""

    _meta = None  # type: ClassDescription  # This describes fields and properties of descendant classes, populated via metaclass

    def __eq__(self, other):
        if other is not None and other.__class__ is self.__class__:
            for name in self._meta.attributes:
                if not hasattr(other, name) or getattr(self, name) != getattr(other, name):
                    return False

            return True

    @classmethod
    def from_json(cls, path, default=None, fatal=True, logger=None):
        """
        Args:
            path (str): Path to json file
            default (dict | None): Default if file is not present, or if it's not json
            fatal (bool | None): Abort execution on failure if True
            logger (callable | None): Logger to use

        Returns:
            (cls): Deserialized object
        """
        result = cls()
        data = read_json(path, default=default, fatal=fatal, logger=logger)
        result.set_from_dict(data, source=short(path))
        return result

    @classmethod
    def from_dict(cls, data, source=None, ignore=None):
        """
        Args:
            data (dict): Raw data, coming for example from a json file
            source (str | None): Optional, description of source where 'data' came from
            ignore (bool | list | None): True: ignore any and all mismatches (including type mismatch)
                                         False: ignore extra content in `data` (but fail on type mismatch)
                                         None: strict mode, raise exception if `data` does not fully comply to `._meta` schema
                                         list: ignore specified extra given names (but fail on type mismatch)

        Returns:
            (cls): Deserialized object
        """
        result = cls()
        result.set_from_dict(data, source=source, ignore=ignore)
        return result

    def set_from_dict(self, data, source=None, ignore=None):
        """
        Args:
            data (dict): Raw data, coming for example from a json file
            source (str | None): Optional, description of source where 'data' came from
            ignore (bool | list | None): True: ignore any and all mismatches (including type mismatch)
                                         False: ignore extra content in `data` (but fail on type mismatch)
                                         None: strict mode, raise exception if `data` does not fully comply to `._meta` schema
                                         list: ignore specified extra given names (but fail on type mismatch)
        """
        if data is None:
            given = {}

        else:
            given = data.copy()

        for name, vtype in self._meta.attributes.items():
            value = given.pop(name, vtype and vtype())
            if vtype is not None and value is not None and not same_type(vtype, value):
                msg = " in %s" % source if source else ""
                msg = "Wrong type '%s' for %s.%s%s, expecting '%s'" % (type_name(value), type_name(self), name, msg, vtype.__name__)
                if ignore is not True:
                    abort(msg)

                LOG.debug(msg)

            if value is None:
                setattr(self, name, None)

            else:
                setter = getattr(self, "set_%s" % name, None)
                if setter is None:
                    setattr(self, name, value)

                else:
                    setter(value)

        if isinstance(ignore, list):
            for x in ignore:
                given.pop(x, None)

        if given:
            # We have more stuff in `data` than described in `._meta`
            msg = "Extra content given for %s: %s" % (type_name(self), ", ".join(given))
            if not isinstance(ignore, bool):
                abort(msg)

            LOG.debug(msg)

    def reset(self):
        """
        Reset all fields of this object to class defaults
        """
        for name, vtype in self._meta.attributes.items():
            setattr(self, name, vtype and vtype())

    def to_dict(self, keep_none=False):
        """
        :param (bool) keep_none: If False, don't include None values
        :return dict: This object serialized to a dict
        """
        raw = dict((name, getattr(self, name)) for name in self._meta.attributes)
        return json_sanitized(raw, keep_none=keep_none)


def read_json(path, default=None, fatal=True, logger=None):
    """
    Args:
        path (str | None): Path to file to deserialize
        default (dict | list | str | None): Default if file is not present, or if it's not json
        fatal (bool | None): Abort execution on failure if True
        logger (callable | None): Logger to use

    Returns:
        (dict | list | str): Deserialized data from file
    """
    path = resolved_path(path)
    if not path or not os.path.exists(path):
        if default is None:
            return abort("No file %s", short(path), fatal=(fatal, default))
        return default

    try:
        with io.open(path, "rt") as fh:
            data = json.load(fh)
            if default is not None and type(data) != type(default):
                return abort("Wrong type %s for %s, expecting %s", type(data), short(path), type(default), fatal=(fatal, default))

            if logger:
                logger("Read %s", short(path))

            return data

    except Exception as e:
        return abort("Couldn't read %s: %s", short(path), e, fatal=(fatal, default))


def represented_json(data, sort_keys=True, indent=2, keep_none=False, **kwargs):
    """
    Args:
        data (object | None): Data to serialize
        sort_keys (bool): Whether keys should be sorted
        indent (int | None): Indentation to use
        keep_none (bool): If False, don't include None values
        **kwargs: Passed through to `json.dumps()`

    Returns:
        (dict | list | str): Serialized `data`, with defaults that are usually desirable for a nice and clean looking json
    """
    data = json_sanitized(data, keep_none=keep_none)
    return "%s\n" % json.dumps(data, sort_keys=sort_keys, indent=indent, **kwargs)


def save_json(data, path, fatal=True, logger=None, sort_keys=True, indent=2, keep_none=False, **kwargs):
    """
    Args:
        data (object | None): Data to serialize and save
        path (str | None): Path to file where to save
        fatal (bool | None): Abort execution on failure if True
        logger (callable | None): Logger to use
        sort_keys (bool): Save json with sorted keys
        indent (int | None): Indentation to use
        keep_none (bool): If False, don't include None values
        **kwargs: Passed through to `json.dump()`

    Returns:
        (int): 1 if saved, -1 if failed (when `fatal` is False)
    """
    if data is None or not path:
        return abort("No file %s", short(path), fatal=fatal)

    try:
        path = resolved_path(path)
        ensure_folder(path, fatal=fatal, logger=None)
        if is_dryrun():
            LOG.info("Would save %s", short(path))
            return 1

        data = json_sanitized(data, keep_none=keep_none)
        if indent:
            kwargs.setdefault("separators", (",", ": "))

        with open(path, "wt") as fh:
            json.dump(data, fh, sort_keys=sort_keys, indent=indent, **kwargs)
            fh.write("\n")

        if logger:
            logger("Saved %s", short(path))

        return 1

    except Exception as e:
        return abort("Couldn't save %s: %s", short(path), e, fatal=(fatal, -1))
