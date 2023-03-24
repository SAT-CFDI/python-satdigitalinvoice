import inspect
import os
from collections import defaultdict
from pprint import PrettyPrinter

from satcfdi.xelement import XElement

current_dir = os.path.dirname(__file__)




class XElementPrettyPrinter(PrettyPrinter):
    _dispatch = PrettyPrinter._dispatch.copy()
    _dispatch[XElement.__repr__] = PrettyPrinter._pprint_dict
    _dispatch[defaultdict.__repr__] = PrettyPrinter._pprint_dict


def verify_result(data, filename):
    calle_frame = inspect.stack()[1]
    caller_file = inspect.getmodule(calle_frame[0]).__file__
    caller_file = os.path.splitext(os.path.basename(caller_file))[0]

    if isinstance(data, bytes):
        ap = 'b'
    else:
        ap = ''
    filename_base, filename_ext = os.path.splitext(filename)

    full_path = os.path.join(current_dir, caller_file, filename_base)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)

    try:
        with open(full_path + filename_ext, 'r' + ap, encoding=None if ap else 'utf-8') as f:
            if f.read() == data:
                os.remove(full_path + ".diff" + filename_ext)
                return True
        with open(full_path + ".diff" + filename_ext, 'w' + ap, encoding=None if ap else 'utf-8', newline=None if ap else '\n') as f:
            f.write(data)
        return False
    except FileNotFoundError:
        with open(full_path + filename_ext, 'w' + ap, encoding=None if ap else 'utf-8', newline=None if ap else '\n') as f:
            f.write(data)
        return True
