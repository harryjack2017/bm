import asyncio
import aioredis
import ujson
import lz4.frame
from conf import conf
from thrift.protocol.TCompactProtocol import TCompactProtocol
from thrift.transport.TTransport import TMemoryBuffer
from utils import logger, log, print_excp
from random import random

DI_TTL = 5 * 60 if conf.IS_PROD else 60
RECO_TTL = 7 * 24 * 3600 if conf.IS_PROD else 60
RELATED_CARD_TTL = 0


# noinspection PyMethodMayBeStatic
class RedisClient:
    def __init__(self):
        self.redis_pool = []
        self.current = -1
        self.max = len(conf.REDIS['addresses'])
        self.di_versions = {}
        self.reco_versions = {}

    async def prepare_conn(self):
        addresses = conf.REDIS['addresses']
        password = conf.REDIS.get('password')
        self.redis_pool = await asyncio.gather(*[
            aioredis.create_redis_pool(addresses[i], minsize=1, maxsize=1) for i in range(self.max)
        ])
        logger.info('RedisClient init done')

    async def close(self):
        for i in self.redis_pool:
            try:
                i.close()
                await i.wait_closed()
            except Exception as e:
                print_excp(e)

    async def connect(self, write=False):
        if write:
            return self.redis_pool[0]
        else:
            self.current = (self.current + 1) % self.max
            return self.redis_pool[self.current]

    def lucky(self):
        return random() < conf.REDIS['probability']

    def get_di_version(self, typ):
        return self.di_versions.get(self.di_cls_name(typ), {}).get('version', 0)

    def get_reco_version(self, creator):
        return self.reco_versions.get(creator.__name__, {}).get('version', 0)

    def cache_list(self, creator, interfaceName, id_index=None):
        version = self.get_reco_version(creator)

        def wrapper(f):
            async def g(*args, **kwargs):
                service = args[0]
                key = f'{interfaceName}:{version}'
                if id_index is not None:
                    key = f'{key}:{args[id_index]}'
                objs = []

                if service is None:
                    # recommend service is down, resort to redis
                    try:
                        redis = await self.connect()
                        robjs = await redis.lrange(key, 0, -1)
                        robjs = robjs or []
                        for robj in robjs:
                            if robj is None:
                                continue

                            obj = creator()
                            mobj = TMemoryBuffer(lz4.frame.decompress(robj))
                            cobj = TCompactProtocol(mobj)
                            obj.read(cobj)
                            objs.append(obj)

                        logger.debug(f'[REDIS] Get list of {key} from cache')
                    except Exception as e:
                        log.print_excp(e)
                else:
                    objs = await f(*args, **kwargs)
                    # save obj to redis randomly
                    if self.lucky() and objs is not None and len(objs) > 0:
                        try:
                            redis = await self.connect(True)
                            vals = []
                            for obj in objs:
                                mobj = TMemoryBuffer()
                                cobj = TCompactProtocol(mobj)
                                obj.write(cobj)
                                vals.append(lz4.frame.compress(mobj.getvalue()))

                            if len(vals) > 0:
                                tr = redis.multi_exec()
                                tr.ltrim(key, 1, 0)
                                tr.rpush(key, *vals)
                                tr.expire(key, RECO_TTL)

                                await tr.execute()
                                logger.debug(f'[REDIS] Set list of {key} to cache')
                        except Exception as e:
                            log.print_excp(e)

                return objs

            return g

        return wrapper

    async def cache_set(self, f, creator, prefix, id_index, *args, **kwargs):
        capacity = 10
        service = args[0]
        version = self.get_reco_version(creator)
        key = f'{prefix}:{version}'
        if id_index is not None:
            key = f'{key}:{args[id_index]}'
        obj = None

        if service is None:
            # recommend service is down, fetch one from redis randomly
            try:
                redis = await self.connect()
                robj = await redis.srandmember(key)
                if robj is not None:
                    obj = creator()
                    mobj = TMemoryBuffer(lz4.frame.decompress(robj))
                    cobj = TCompactProtocol(mobj)
                    obj.read(cobj)

                    logger.debug(f'[REDIS] Get Response obj of {key} from cache')
            except Exception as e:
                log.print_excp(e)
        else:
            obj = await f(*args, **kwargs)

            # save obj to redis randomly
            if self.lucky() and obj is not None:
                try:
                    redis = await self.connect(True)
                    # del some randomly when total number is more than {capacity}
                    total = await redis.scard(key)
                    if total > capacity * 1.25:
                        await redis.execute('spop', key, int(total - capacity * 0.75))
                    else:
                        tr = redis.multi_exec()
                        mobj = TMemoryBuffer()
                        cobj = TCompactProtocol(mobj)
                        obj.write(cobj)
                        tr.sadd(key, lz4.frame.compress(mobj.getvalue()))
                        tr.expire(key, RECO_TTL)
                        await tr.execute()
                        logger.debug(f'[REDIS] Set Response obj of {key} to cache')
                except Exception as e:
                    log.print_excp(e)

        return obj

    def cache_tabs(self, interfaceName, id_index):
        def wrapper(f):
            async def fn(*args, **kwargs):
                objs = await f(*args, **kwargs)
                return objs[0] if len(objs) > 0 else None

            async def g(*args, **kwargs):
                obj = await self.cache_set(fn, recttypes.Tabs, f'tab:{interfaceName}', id_index, *args, **kwargs)
                return [obj] if obj is not None else []

            return g

        return wrapper

    def cache_card(self, interfaceName, id_index=None):
        def wrapper(f):
            async def g(*args, **kwargs):
                return await self.cache_set(f, recttypes.Response, interfaceName, id_index, *args, **kwargs)

            return g

        return wrapper

    async def get_details_from_cache(self, idts, prefix):
        obj = dittypes.DIResponse(typeList=[idt.type for idt in idts])
        idts_left = None
        try:
            # 先从Redis拿数据
            redis = await self.connect()
            idts_left = []

            for idt in idts:
                typ = idt.type
                ids = idt.ids

                version = self.get_di_version(typ)
                key_prefix = f'{prefix}:{typ}:{version}'
                keys = [f'{key_prefix}:{i}' for i in ids]
                # 一次从多个key读取数据
                items = await redis.mget(*keys)
                logger.debug(f'[REDIS] Get {len(items)} DIResponse objs of {typ} from redis')

                ids = [ids[i] for i, v in enumerate(items) if v is None]
                items = [it for it in items if it is not None]

                if len(ids) > 0:
                    idts_left.append(dittypes.IdsWithType(ids=ids, type=typ))

                vals = []
                for item in items:
                    if item is None:
                        continue

                    # 从Redis中的二进制数据恢复成所需结构
                    creator = self.di_creator(typ)
                    if creator is None:
                        continue

                    val = creator()
                    mval = TMemoryBuffer(lz4.frame.decompress(item))
                    cval = TCompactProtocol(mval)
                    val.read(cval)
                    vals.append(val)

                self.di_setlist(obj, typ, vals)
        except Exception as e:
            log.print_excp(e)

        return obj, idts_left

    async def set_details_to_cache(self, obj_left, prefix):
        try:
            redis = await self.connect(write=True)

            pairs = []
            keys = []
            types = obj_left.typeList

            for typ in types:
                version = self.get_di_version(typ)
                key_prefix = f'{prefix}:{typ}:{version}'
                items = self.di_getlist(obj_left, typ)

                for it in items:
                    key = f'{key_prefix}:{self.di_id(typ, it)}'
                    mval = TMemoryBuffer()
                    cval = TCompactProtocol(mval)
                    it.write(cval)
                    pairs.extend((key, lz4.frame.compress(mval.getvalue())))
                    keys.append(key)

            # 一次性向Redis中存储多个数据
            if len(pairs) > 0:
                tr = redis.multi_exec()
                tr.mset(*pairs)

                for key in keys:
                    tr.expire(key, DI_TTL)

                await tr.execute()
                logger.debug(f'[REDIS] Set {len(items)} DIResponse objs of type:{typ} to redis')

        except Exception as e:
            log.print_excp(e)

    def cache_details(self, idts_index=None, id_index=None, type_index=None):  # idt means ids_with_type
        prefix = 'di'

        def wrapper(f):
            async def g(*args, **kwargs):
                is_group = idts_index is not None
                idts = args[idts_index] if is_group else [
                    dittypes.IdsWithType(ids=[args[id_index]], type=args[type_index])]
                (obj, idts_left) = await self.get_details_from_cache(idts, prefix)

                if idts_left is None:
                    idts_left = idts

                if len(idts_left) <= 0:
                    return obj

                if is_group:
                    args = [arg for arg in args]
                    args[idts_index] = idts_left

                # 从底层服务拿数据
                obj_left = await f(*args, **kwargs)

                if obj_left is not None:
                    await self.set_details_to_cache(obj_left, prefix)
                else:
                    return obj

                # 合并obj和obj_left
                idts_left_map = {idt.type: idt.ids for idt in idts_left}
                for idt in idts:
                    typ = idt.type
                    if idts_left_map.get(typ) is None:
                        continue

                    ids = idt.ids
                    items = self.di_getlist(obj, typ) or []
                    left_items = self.di_getlist(obj_left, typ) or []

                    items_map = {self.di_id(typ, it): it for it in items}
                    left_items_map = {self.di_id(typ, it): it for it in left_items}

                    merged_items = [items_map.get(id) or left_items_map.get(id) for id in ids]
                    self.di_setlist(obj, typ, [it for it in merged_items if it is not None])

                return obj

            return g

        return wrapper

    def di_id(self, typ, item):
        from models.v1.resource.base_video import BaseVideo
        api_cls = self.api_cls(typ)
        if issubclass(api_cls, BaseVideo):
            res = item.BaseVideo.id
        else:
            res = item.id

        return res

    def api_cls(self, typ):
        from models.v1.request_handler import REC_TYPE_TO_CLS_BASE
        return REC_TYPE_TO_CLS_BASE.get(typ)

    def di_list_name(self, typ):
        api_cls = self.api_cls(typ)
        return api_cls and api_cls.DI_LIST_NAME

    def di_cls_name(self, typ):
        api_cls = self.api_cls(typ)
        return api_cls and api_cls.DI_CLS_NAME

    def di_getlist(self, di, typ):
        list_name = self.di_list_name(typ)
        return list_name and getattr(di, list_name) or []

    def di_setlist(self, di, typ, items):
        list_name = self.di_list_name(typ)
        if list_name:
            setattr(di, list_name, items)

    def di_creator(self, typ):
        cls_name = self.di_cls_name(typ)
        return cls_name and getattr(dittypes, cls_name)

    # def cache_related_card(self, interfaceName, id_index=-1):
    #     capacity = 5
    #     prefix = interfaceName
    #     def wrapper(f):
    #         async def g(*args, **kwargs):
    #             service = args[0]
    #             rid = args[id_index]
    #             skey = f'{prefix}:{rid}'
    #             obj = None

    #             if service is None:
    #                 # service is down, fetch from redis
    #                 try:
    #                     redis = await self.connect()
    #                     robj = await redis.srandmember(skey)
    #                     obj = recttypes.Response()
    #                     mobj = TMemoryBuffer(robj)
    #                     cobj = TCompactProtocol(mobj)
    #                     obj.read(cobj)
    #                     logger.debug(f'[REDIS] Get Response obj of {interfaceName}:{rid} from cache')
    #                 except Exception as e:
    #                     log.print_excp(e)
    #             else:
    #                 obj = await f(*args, **kwargs)
    #                 if self.lucky() and obj is not None:
    #                     try:
    #                         redis = await self.connect(write=True)
    #                         # del some randomly when too many
    #                         total = await redis.scard(skey)
    #                         if total > capacity:
    #                             await redis.execute('spop', skey, int(total - capacity * 0.75))
    #                         else:
    #                             # save id to the redis set corresponding to interfaceName
    #                             mobj = TMemoryBuffer()
    #                             cobj = TCompactProtocol(mobj)
    #                             obj.write(cobj)
    #                             await redis.sadd(skey, mobj.getvalue())
    #                             logger.debug(f'[REDIS] Set Response obj of {interfaceName}:{rid} to cache')

    #                             # set ttl of skey
    #                             await redis.expire(skey, RELATED_CARD_TTL)
    #                     except Exception as e:
    #                         log.print_excp(e)

    #             return obj

    #         return g
    #     return wrapper


redis = RedisClient()
