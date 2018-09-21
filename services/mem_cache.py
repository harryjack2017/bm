from time import time
from cachetools import TTLCache
from cachetools.keys import hashkey
from conf import conf

TTL = 300 if conf.IS_PROD else 60

class MemCache:
    def __init__(self, capacity, *indices):
        self._cache = TTLCache(capacity, TTL, timer=time)
        self._indices = indices

    def __call__(self, f):
        async def g(*args, **kwargs):
            key = hashkey(*[';'.join(args[idx]) if isinstance(args[idx], list) else args[idx] for idx in self._indices])
            res = self._cache.get(key)
            if res is None:
                res = await f(*args, **kwargs)
                nocache = False
                try:
                    nocache = res.disableCache
                except:
                    pass

                if not nocache:
                    self._cache[key] = res

            return res

        return g
