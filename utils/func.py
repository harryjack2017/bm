from operator import attrgetter

def get_attr(obj, path, default):
    try:
        return attrgetter(path)(obj)
    except AttributeError:
        return default
