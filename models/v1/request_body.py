from conf import enum


class RecResult:
    def __init__(self, rid=None, typ=None, result=None, ua=None, **extra):
        self.id = rid or result.id
        self.type = typ or result.resultType
        if self.type == enum.ARTIST_RE_TYPE:
            self.type = enum.ARTIST_SINGER_RE_TYPE
        self.result = result
        self.ua = ua or {}
        self.extra = extra

    def __getattr__(self, attr):
        return self.extra.get(attr)