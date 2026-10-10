"""Manifest 格式校验与纯数据投影，不依赖应用或桌面层。"""

import json
import math
import re
import unicodedata
from dataclasses import dataclass

from ohmymeme.core.assets import is_safe_filename


class ManifestValidationError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class ManifestMeme:
    filename: str
    name: str
    sha256: str
    file_size: int
    mtime: str
    sort_order: int

    def to_data(self):
        return {
            "filename": self.filename,
            "name": self.name,
            "sha256": self.sha256,
            "file_size": self.file_size,
            "mtime": self.mtime,
            "sort_order": self.sort_order,
        }


@dataclass(frozen=True, slots=True)
class ManifestCollection:
    name: str
    filenames: tuple[str, ...]
    children: tuple["ManifestCollection", ...] = ()

    def to_data(self):
        data = {"name": self.name, "filenames": list(self.filenames)}
        if self.children:
            data["children"] = [child.to_data() for child in self.children]
        return data


@dataclass(frozen=True, slots=True)
class ManifestProjection:
    memes: tuple[ManifestMeme, ...]
    collections: tuple[ManifestCollection, ...]

    def to_data(self):
        return {
            "version": 3,
            "memes": [meme.to_data() for meme in self.memes],
            "collections": [collection.to_data() for collection in self.collections],
        }


class ManifestService:
    """Parse manifest input into an immutable v3 projection."""

    def parse_json(self, raw, strict_hash=False):
        if isinstance(raw, bytes):
            try:
                raw = raw.decode("utf-8")
            except UnicodeDecodeError as error:
                raise ManifestValidationError("invalid_utf8") from error
        if not isinstance(raw, str):
            raise ManifestValidationError("invalid_json")
        try:
            data = json.loads(
                raw,
                object_pairs_hook=_reject_duplicate_keys,
                parse_constant=_reject_constant,
            )
        except json.JSONDecodeError as error:
            raise ManifestValidationError("invalid_json") from error
        return self.parse_data(data, strict_hash=strict_hash)

    def parse_data(self, data, strict_hash=False):
        _validate_json_value(data)
        if not isinstance(data, dict):
            raise ManifestValidationError("manifest_not_object")
        version = data.get("version", 2)
        if type(version) is not int or version not in (2, 3):
            raise ManifestValidationError("unsupported_version")
        memes = _optional_list(data, "memes")
        collections = _optional_list(data, "collections")
        filenames = set()
        filename_identities = set()
        sort_orders = set()
        parsed_memes = []
        for index, entry in enumerate(memes):
            if not isinstance(entry, dict):
                raise ManifestValidationError("entry_not_object")
            if "sort_order" not in entry:
                if version == 2:
                    sort_order = index
                else:
                    raise ManifestValidationError("missing_sort_order")
            else:
                sort_order = entry["sort_order"]
            if type(sort_order) is not int:
                raise ManifestValidationError("invalid_sort_order")
            if sort_order in sort_orders:
                raise ManifestValidationError("duplicate_sort_order")
            sort_orders.add(sort_order)
            parsed = _parse_meme(entry, sort_order, strict_hash)
            if parsed.filename in filenames:
                raise ManifestValidationError("duplicate_filename")
            identity = unicodedata.normalize("NFC", parsed.filename).casefold()
            if identity in filename_identities:
                raise ManifestValidationError("filename_case_conflict")
            filenames.add(parsed.filename)
            filename_identities.add(identity)
            parsed_memes.append(parsed)
        parsed_collections = _parse_collections(collections, ())
        return ManifestProjection(tuple(parsed_memes), parsed_collections)

    def canonical_bytes(self, value):
        _validate_canonical_value(value)
        return _canonical(value).encode("utf-8")


def _reject_duplicate_keys(pairs):
    data = {}
    for key, value in pairs:
        if key in data:
            raise ManifestValidationError("duplicate_key")
        data[key] = value
    return data


def _reject_constant(_value):
    raise ManifestValidationError("non_finite_number")


def _required_list(data, field):
    value = data.get(field)
    if not isinstance(value, list):
        raise ManifestValidationError(f"{field}_not_list")
    return value


def _optional_list(data, field):
    value = data.get(field, [])
    if not isinstance(value, list):
        raise ManifestValidationError(f"{field}_not_list")
    return value


def _parse_meme(entry, sort_order, strict_hash):
    if not isinstance(entry, dict):
        raise ManifestValidationError("entry_not_object")
    filename = entry.get("filename")
    if not isinstance(filename, str) or not is_safe_filename(filename):
        raise ManifestValidationError("unsafe_filename")
    name = _text(entry.get("name") or filename.rsplit(".", 1)[0])
    sha256 = entry.get("sha256", "")
    if not isinstance(sha256, str) or (
        strict_hash and re.fullmatch(r"[0-9a-f]{64}", sha256) is None
    ):
        raise ManifestValidationError("invalid_sha256")
    file_size = entry.get("file_size", 0)
    if type(file_size) is not int or file_size < 0:
        raise ManifestValidationError("invalid_file_size")
    mtime = entry.get("mtime", "")
    if not isinstance(mtime, str):
        raise ManifestValidationError("invalid_mtime")
    return ManifestMeme(filename, name, sha256, file_size, mtime, sort_order)


def _parse_collections(entries, parent_path):
    parsed = []
    names = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ManifestValidationError("entry_not_object")
        name = _text(entry.get("name"))
        identity = unicodedata.normalize("NFC", name).casefold()
        if identity in names:
            raise ManifestValidationError("collection_case_conflict")
        names.add(identity)
        filenames = _required_list(entry, "filenames")
        parsed_filenames = []
        for filename in filenames:
            if not isinstance(filename, str) or not is_safe_filename(filename):
                raise ManifestValidationError("unsafe_filename")
            if filename in parsed_filenames:
                raise ManifestValidationError("duplicate_collection_filename")
            parsed_filenames.append(filename)
        children = entry.get("children", [])
        if not isinstance(children, list):
            raise ManifestValidationError("children_not_list")
        parsed.append(
            ManifestCollection(
                unicodedata.normalize("NFC", name),
                tuple(parsed_filenames),
                _parse_collections(children, parent_path + (identity,)),
            )
        )
    return tuple(parsed)


def _text(value):
    if not isinstance(value, str):
        raise ManifestValidationError("invalid_text")
    _validate_text(value)
    normalized = unicodedata.normalize("NFC", value)
    if not normalized:
        raise ManifestValidationError("invalid_text")
    return normalized


def _validate_json_value(value):
    if isinstance(value, str):
        _validate_text(value)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ManifestValidationError("invalid_object_key")
            _validate_text(key)
            _validate_json_value(item)
        return
    if isinstance(value, list):
        for item in value:
            _validate_json_value(item)
        return
    if isinstance(value, float) and not math.isfinite(value):
        raise ManifestValidationError("non_finite_number")
    if value is None or type(value) in (bool, int, float):
        return
    raise ManifestValidationError("invalid_json_value")


def _validate_canonical_value(value):
    if isinstance(value, str):
        _validate_surrogates(value)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ManifestValidationError("invalid_object_key")
            _validate_surrogates(key)
            _validate_canonical_value(item)
        return
    if isinstance(value, list):
        for item in value:
            _validate_canonical_value(item)
        return
    if isinstance(value, float) and not math.isfinite(value):
        raise ManifestValidationError("non_finite_number")
    if value is None or type(value) in (bool, int, float):
        return
    raise ManifestValidationError("invalid_json_value")


def _validate_text(value):
    for character in value:
        point = ord(character)
        if point <= 0x1F:
            raise ManifestValidationError("control_character")
    _validate_surrogates(value)


def _validate_surrogates(value):
    for character in value:
        point = ord(character)
        if 0xD800 <= point <= 0xDFFF:
            raise ManifestValidationError("unpaired_surrogate")


def _canonical(value):
    if value is None:
        return "null"
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is int:
        if abs(value) > 9007199254740991:
            raise ManifestValidationError("number_out_of_range")
        return str(value)
    if type(value) is float:
        return _canonical_float(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False, allow_nan=False)
    if isinstance(value, list):
        return "[" + ",".join(_canonical(item) for item in value) + "]"
    if isinstance(value, dict):
        return (
            "{"
            + ",".join(
                json.dumps(key, ensure_ascii=False, allow_nan=False)
                + ":"
                + _canonical(value[key])
                for key in sorted(value, key=lambda item: item.encode("utf-16-be"))
            )
            + "}"
        )
    raise ManifestValidationError("invalid_json_value")


def _canonical_float(value):
    if not math.isfinite(value):
        raise ManifestValidationError("non_finite_number")
    if value == 0:
        return "0"
    text = repr(value).lower()
    absolute = abs(value)
    if "e" not in text:
        return text[:-2] if text.endswith(".0") else text
    mantissa, exponent = text.split("e")
    exponent_value = int(exponent)
    if 1e-6 <= absolute < 1e21:
        return _expand_exponent(mantissa, exponent_value)
    if mantissa.endswith(".0"):
        mantissa = mantissa[:-2]
    return mantissa + "e" + ("+" if exponent_value >= 0 else "") + str(exponent_value)


def _expand_exponent(mantissa, exponent):
    sign = ""
    if mantissa.startswith("-"):
        sign, mantissa = "-", mantissa[1:]
    point = mantissa.find(".")
    digits = mantissa.replace(".", "")
    position = (point if point >= 0 else len(mantissa)) + exponent
    if position <= 0:
        return sign + "0." + "0" * -position + digits
    if position >= len(digits):
        return sign + digits + "0" * (position - len(digits))
    return sign + digits[:position] + "." + digits[position:]
