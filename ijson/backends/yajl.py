from ctypes import Structure, c_uint, c_ubyte, c_int, c_long, c_double, \
                   c_void_p, c_char_p, CFUNCTYPE, POINTER, byref, string_at, cast , \
                   cdll, util, c_char
from decimal import Decimal

from ijson import common


so_name = util.find_library('yajl')

# Temporary hack for Hardy 64. find_library doesn't find this file for some
# reason.
if so_name is None:
    import os
    hardy64_name = '/usr/lib/libyajl.so.1'
    if os.path.exists(hardy64_name):
        so_name = hardy64_name

if so_name is None:
    raise Exception('YAJL shared object not found.')
yajl = cdll.LoadLibrary(so_name)

yajl.yajl_alloc.restype = POINTER(c_char)
yajl.yajl_get_error.restype = POINTER(c_char)

C_EMPTY = CFUNCTYPE(c_int, c_void_p)
C_INT = CFUNCTYPE(c_int, c_void_p, c_int)
C_LONG = CFUNCTYPE(c_int, c_void_p, c_long)
C_DOUBLE = CFUNCTYPE(c_int, c_void_p, c_double)
C_STR = CFUNCTYPE(c_int, c_void_p, POINTER(c_ubyte), c_uint)


def number(value):
    '''
    Helper function casting a string that represents any Javascript number
    into appropriate Python value: either int or Decimal.
    '''
    try:
        return int(value)
    except ValueError:
        return Decimal(value)

_callback_data = [
    # Mapping of JSON parser events to callback C types and value converters.
    # Used to define the Callbacks structure and actual callback functions
    # inside the parse function.
    ('null', C_EMPTY, lambda: None),
    ('boolean', C_INT, lambda v: bool(v)),
    # "integer" and "double" aren't actually yielded by yajl since "number"
    # takes precedence if defined
    ('integer', C_LONG, lambda v, l: int(string_at(v, l))),
    ('double', C_DOUBLE, lambda v, l: float(string_at(v, l))),
    ('number', C_STR, lambda v, l: number(string_at(v, l))),
    ('string', C_STR, lambda v, l: string_at(v, l).decode('utf-8')),
    ('start_map', C_EMPTY, lambda: None),
    ('map_key', C_STR, lambda v, l: string_at(v, l)),
    ('end_map', C_EMPTY, lambda: None),
    ('start_array', C_EMPTY, lambda: None),
    ('end_array', C_EMPTY, lambda: None),
]

class Callbacks(Structure):
    _fields_ = [(name, type) for name, type, func in _callback_data]

class Config(Structure):
    _fields_ = [
        ("allowComments", c_uint),
        ("checkUTF8", c_uint)
    ]

YAJL_OK = 0
YAJL_CANCELLED = 1
YAJL_INSUFFICIENT_DATA = 2
YAJL_ERROR = 3


def basic_parse(f, allow_comments=False, check_utf8=False, buf_size=64 * 1024):
    '''
    An iterator returning events from a JSON being parsed. This basic parser
    doesn't maintain any context and just returns parser events from an
    underlying library, converting them into Python native data types.

    Parameters:

    - f: a readable file-like object with JSON input
    - allow_comments: tells parser to allow comments in JSON input
    - check_utf8: if True, parser will cause an error if input is invalid utf-8
    - buf_size: a size of an input buffer

    Events returned from parser are pairs of (event type, value) and can be as
    follows:

        ('null', None)
        ('boolean', <True or False>)
        ('number', <int or Decimal>)
        ('string', <unicode>)
        ('map_key', <str>)
        ('start_map', None)
        ('end_map', None)
        ('start_array', None)
        ('end_array', None)
    '''
    events = []

    def callback(event, func_type, func):
        def c_callback(context, *args):
            events.append((event, func(*args)))
            return 1
        return func_type(c_callback)

    callbacks = Callbacks(*[callback(*data) for data in _callback_data])
    config = Config(allow_comments, check_utf8)
    handle = yajl.yajl_alloc(byref(callbacks), byref(config), None, None)
    try:
        while True:
            buffer = f.read(buf_size)
            if buffer:
                result = yajl.yajl_parse(handle, buffer, len(buffer))
            else:
                result = yajl.yajl_parse_complete(handle)
            if result == YAJL_ERROR:
                perror = yajl.yajl_get_error(handle, 1, buffer, len(buffer))
                error = cast(perror, c_char_p).value
                yajl.yajl_free_error(handle, perror)
                raise common.JSONError(error)
            if not buffer and not events:
                if result == YAJL_INSUFFICIENT_DATA:
                    raise common.IncompleteJSONError()
                break

            for event in events:
                yield event
            events = []
    finally:
        yajl.yajl_free(handle)

def parse(file, **kwargs):
    return common.parse(basic_parse(file, **kwargs))

def items(file, prefix):
    return common.items(parse(file), prefix)
