import asyncio
from time import time
from datetime import datetime
from thrift import TTornado
from thrift.protocol.TCompactProtocol import TCompactProtocolFactory
from .thrift.recommend import RecommendService, ttypes as recttypes
from .thrift.di import DIService, ttypes as dittypes
from conf import conf, enum
from .redis_client import redis
from .mem_cache import MemCache
from utils import logger

RECO_SERVICE_NAME = 'RECO'
DI_SERVICE_NAME = 'DI'
NETWORK_STATUS = '3G'
ANDROID_PLATEFORM_ID = '1'
TIMEOUT = 2 if conf.IS_PROD else None


def get_UTC_time():
    return f'{int(datetime.now().timestamp() * 1000)}'

async def timeout(cor, timeout):
    done, _ = await asyncio.wait([cor], timeout=timeout)
    if len(done) > 0:
        return done.pop().result()
    else:
        raise(Exception('Operation Timeout'))

def timing(serviceName, interfaceName):
    def wrapper(f):
        async def g(*args, **kwargs):
            start = time()
            res = await f(*args, **kwargs)
            stop = time()
            logger.debug(f'{int(1000 * (stop-start))}ms for {serviceName}:{interfaceName}')
            return res

        return g
    return wrapper

def expand_request(f):
    async def g(*args, **kwargs):
        req = args[0]
        xheaders = req['xheaders']
        app_version = xheaders['app-version']
        country = xheaders['country']
        lang = xheaders['lang']
        prefre_lang = xheaders['prefer-lang']
        uid = req['user'].id

        kwargs['app_code'] = xheaders['app-code']
        kwargs['log_id'] = req['logid']
        return await f(app_version, country, lang, prefre_lang, uid, *args[1:], **kwargs)
    return g

# 因为app_version这个参数会影响到MemCache，
# 在向底层服务发送请求的时候将客户端传来的app-version转换成一个最近一次发版的版本号，
# 这样可以缓解因为app_version参数值过多引起MemCache所需内存的膨胀
def normalize_app_version(versions):
    def wrapper(f):
        async def g(*args, **kwargs):
            app_version = None
            version = args[0]
            for v in versions:
                if version >= v:
                    app_version = v
                else:
                    break

            if not app_version:
                app_version = versions[0]
            return await f(app_version, *args[1:], **kwargs)
        return g
    return wrapper


# downgrade表示是否需要向redis中取降级数据
def tclient(downgrade):
    def wrapper(f):
        async def g(*args, **kwargs):
            if conf.IS_FAILOVER:
                if downgrade:
                    return await f(None, *args, **kwargs)
                else:
                    return None

            res = None
            opened = False
            re_conn = TTornado.TTornadoStreamTransport(conf.CONTENT_SVC['HOST'], conf.CONTENT_SVC['PORT'])

            try:
                re_conn.open()
                opened = True
                tclient = RecommendService.Client(re_conn, TCompactProtocolFactory())
                res = await timeout(f(tclient, *args, **kwargs), TIMEOUT)
            except Exception as e:
                logger.error(f"{kwargs['log_id']} {e}")

                # 降级到Redis中取数据
                if downgrade:
                    res = await timeout(f(None, *args, **kwargs), 1)
            finally:
                if opened:
                    re_conn.close()

            return res

        return g
    return wrapper


def diclient(f):
    async def g(*args, **kwargs):
        if conf.IS_FAILOVER:
            return None

        res = None
        opened = False
        di_conn = TTornado.TTornadoStreamTransport(conf.DI_CONTENT_SVC['HOST'], conf.DI_CONTENT_SVC['PORT'])

        try:
            di_conn.open()
            opened = True
            diclient = DIService.Client(di_conn, TCompactProtocolFactory())
            res = await timeout(f(diclient, *args, **kwargs), TIMEOUT)
        except Exception as e:
            logger.error(f"{kwargs['log_id']} {e}")
        finally:
            if opened:
                di_conn.close()

        return res
    return g


@tclient(False)
async def test(tclient):
    return await tclient.test('')

# get all the names of the tabs which contains the data
@timing(RECO_SERVICE_NAME, enum.TABS_LIST_INTERFACE)
@expand_request
@MemCache(32, -3) # lang
@tclient(True)
@redis.cache_list(recttypes.Tabs, enum.TABS_LIST_INTERFACE)
async def fetch_tab_names(tclient, app_version, country, lang, langList, user_id, log_id=None, app_code=None):
    req = recttypes.Request(userId=user_id, country=country, language=lang, languageList=[], platformId=ANDROID_PLATEFORM_ID,
                            interfaceName=enum.TABS_LIST_INTERFACE, networkStatus=NETWORK_STATUS,
                            timeSign=get_UTC_time(), clientVersion=app_code, logId=log_id)
    res = await tclient.fetchTabs(req)
    return res


# get banner data
@timing(RECO_SERVICE_NAME, enum.BANNER_INTERFACE_NAME)
@expand_request
@MemCache(2048, -3, -1) # lang tab_id
@tclient(True)
@redis.cache_list(recttypes.Banner, enum.BANNER_INTERFACE_NAME, id_index=-1)
async def fetch_banner_data(tclient, app_version, country, lang, langList, user_id, tab_id, log_id=None, app_code=None):
    req = recttypes.Request(userId=user_id, country=country, cardId='', language=lang, languageList=langList, type=0,
                            interfaceName=enum.BANNER_INTERFACE_NAME, networkStatus=NETWORK_STATUS, platformId=ANDROID_PLATEFORM_ID,
                            tabId=tab_id, timeSign=get_UTC_time(), clientVersion=app_code, logId=log_id)
    res = await tclient.fetchBannerData(req)
    return res


# get related banners for special publisher detail page
@timing(RECO_SERVICE_NAME, enum.RELATED_BANNER_INTERFACE_NAME)
@expand_request
@tclient(False)
async def fetch_related_banner_data(tclient, app_version, country, lang, langList, user_id, resourceType, resourceId, log_id=None, app_code=None):
    req = recttypes.Request(userId=user_id, country=country, cardId='', language=lang, languageList=langList, type=0,
                            interfaceName=enum.RELATED_BANNER_INTERFACE_NAME, networkStatus=NETWORK_STATUS, platformId=ANDROID_PLATEFORM_ID,
                            timeSign=get_UTC_time(), resourceType=resourceType, resourceId=resourceId, clientVersion=app_code, logId=log_id)
    res = await tclient.fetchBannerData(req)
    return res

@timing(RECO_SERVICE_NAME, enum.TABS_INTERFACE_NAME)
@expand_request
@normalize_app_version([enum.VERSION_BASE, enum.VERSION_1065, enum.VERSION_NEWEST])
@MemCache(16384, -8, -5, -3, -2, -1) # lang tabId num nextToken
@tclient(True)
async def fetch_tabs_data(tclient, app_version, country, lang, langList, user_id, tabId, num, nextToken, log_id=None, app_code=None):
    # if app_version >= enum.VERSION_1065:
    #     return await fetch_tabs_data_2(tclient, app_version, country, lang, langList, user_id, tabId, num, nextToken, log_id=log_id, app_code=app_code) # pylint: disable=no-value-for-parameter
    # else:
    #     return await fetch_tabs_data_1(tclient, app_version, country, lang, langList, user_id, tabId, num, nextToken, log_id=log_id, app_code=app_code) # pylint: disable=no-value-for-parameter
    res = await fetch_tabs_data_1(tclient, app_version, country, lang, langList, user_id, tabId, num, nextToken, log_id=log_id, app_code=app_code) # pylint: disable=no-value-for-parameter
    return res

# get tabs info
@redis.cache_tabs(enum.TABS_INTERFACE_NAME_1, id_index=-3)
async def fetch_tabs_data_1(tclient, app_version, country, lang, langList, user_id, tabId, num, nextToken, log_id=None, app_code=None):
    req = recttypes.Request(userId=user_id, tabId=tabId, country=country, language=lang, languageList=langList,
                            platformId=ANDROID_PLATEFORM_ID, interfaceName=enum.TABS_INTERFACE_NAME_1,
                            networkStatus=NETWORK_STATUS, num=num, nextToken=nextToken,
                            timeSign=get_UTC_time(), clientVersion=app_code, logId=log_id)
    res = await tclient.fetchTabs(req)
    return res

@redis.cache_tabs(enum.TABS_INTERFACE_NAME_2, id_index=-3)
async def fetch_tabs_data_2(tclient, app_version, country, lang, langList, user_id, tabId, num, nextToken, log_id=None, app_code=None):
    req = recttypes.Request(userId=user_id, tabId=tabId, country=country, language=lang, languageList=langList,
                            platformId=ANDROID_PLATEFORM_ID, interfaceName=enum.TABS_INTERFACE_NAME_2,
                            networkStatus=NETWORK_STATUS, num=num, nextToken=nextToken,
                            timeSign=get_UTC_time(), clientVersion=app_code, logId=log_id)
    res = await tclient.fetchTabs(req)
    return res


@expand_request
async def fetch_list_data(app_version, country, lang, langList, user_id, card_id, tab_id, num, next, type,
    log_id=None, app_code=None, red_dot=False):
    if card_id == enum.BUZZ_TAB_ID:
        return await fetch_nullcard_list_data(app_version, country, lang, langList, user_id, enum.NULL_CARD_ID, tab_id, num, next, type, log_id=log_id, app_code=app_code) # pylint: disable=no-value-for-parameter
    else:
        return await fetch_normal_list_data(app_version, country, lang, langList, user_id, card_id, tab_id, num, next, type, log_id=log_id, app_code=app_code, red_dot=red_dot) # pylint: disable=no-value-for-parameter

# get the list of recommend data
@timing(RECO_SERVICE_NAME, enum.CARDLIST_INTERFACE_NAME)
@MemCache(16384, -5, -3, -2, -1) # lang card_id num next type
@tclient(True)
@redis.cache_card(enum.CARDLIST_INTERFACE_NAME, id_index=-5)
async def fetch_normal_list_data(tclient, app_version, country, lang, langList, user_id, card_id, tab_id, num, next, type,
    log_id=None, app_code=None, red_dot=False):  # first paging type = 0, else type = 1
    req = recttypes.Request(
        userId=user_id, country=country, cardId=card_id, language=lang, languageList=langList, num=num, finalId=next, type=type,
        interfaceName=enum.CARDLIST_INTERFACE_NAME, networkStatus=NETWORK_STATUS, platformId=ANDROID_PLATEFORM_ID, tabId=tab_id,
        timeSign=get_UTC_time(), clientVersion=app_code, logId=log_id)
    res = await tclient.recommend(req)
    return res

# get the list of null card data
@timing(RECO_SERVICE_NAME, enum.CARDLIST_NULL_INTERFACE_NAME)
@tclient(True)
@redis.cache_card(enum.CARDLIST_NULL_INTERFACE_NAME, id_index=-5)
async def fetch_nullcard_list_data(tclient, app_version, country, lang, langList, user_id, card_id, tab_id, num, next, type,
    log_id=None, app_code=None):  # first paging type = 0, else type = 1
    req = recttypes.Request(
        userId=user_id, country=country, cardId=card_id, language=lang, languageList=langList, num=num, finalId=next, type=type,
        interfaceName=enum.CARDLIST_NULL_INTERFACE_NAME, tabId=tab_id, networkStatus=NETWORK_STATUS, platformId=ANDROID_PLATEFORM_ID,
        timeSign=get_UTC_time(), clientVersion=app_code, logId=log_id)
    res = await tclient.recommend(req)
    return res

# get the programs of the live tv channel
@timing(RECO_SERVICE_NAME, enum.CARDLIST_LIVE_CARD_NAME)
@expand_request
@MemCache(1024, -6, -5, -4, -3, -1)
@tclient(True)
@redis.cache_card(enum.CARDLIST_LIVE_CARD_NAME, id_index=-3)
async def fetch_live_tv_programs(tclient, app_version, country, lang, langList, user_id, num, next, type, resourceId, resourceType, nextToken,
    log_id=None, app_code=None):
    req = recttypes.Request(
        userId=user_id, country=country, language=lang, languageList=langList, num=num, finalId=next, type=type,
        interfaceName=enum.CARDLIST_LIVE_CARD_NAME, networkStatus=NETWORK_STATUS, platformId=ANDROID_PLATEFORM_ID,
        nextToken=nextToken, resourceId=resourceId, resourceType=resourceType, timeSign=get_UTC_time(), clientVersion=app_code, logId=log_id)
    res = await tclient.recommend(req)
    return res

# get all live tv channels
@timing(RECO_SERVICE_NAME, enum.ALL_LIVE_CAHNNELS_INTERFACE_NAME)
@expand_request
@MemCache(8, -1)
@tclient(True)
@redis.cache_card(enum.ALL_LIVE_CAHNNELS_INTERFACE_NAME)
async def fetch_all_live_channels(tclient, app_version, country, lang, langList, user_id, num, log_id=None, app_code=None):
    req = recttypes.Request(
        userId=user_id, country=country, language=lang, languageList=langList, num=num, type=0, timeSign=get_UTC_time(),
        interfaceName=enum.ALL_LIVE_CAHNNELS_INTERFACE_NAME, networkStatus=NETWORK_STATUS,
        platformId=ANDROID_PLATEFORM_ID, clientVersion=app_code, logId=log_id)
    return await tclient.recommend(req)

# get detail page by a group of ids and their type
@timing(DI_SERVICE_NAME, 'group')
@expand_request
@redis.cache_details(idts_index=-1)
@diclient
@timing(DI_SERVICE_NAME, 'service:group')
async def fetch_di_detail_page_info(diclient, app_version, country, lang, langList, user_id, ids_with_types, log_id=None, app_code=None):
    req = dittypes.DIRequest(idsWithTypes=ids_with_types, serviceName=None, timeSign=get_UTC_time(), logId=log_id)
    res = await diclient.getDetail(req)
    return res


# get one detail info by type and id
@timing(DI_SERVICE_NAME, 'one')
@expand_request
@redis.cache_details(type_index=-2, id_index=-1)
@diclient
@timing(DI_SERVICE_NAME, 'service:one')
async def fetch_di_one_detail(diclient, app_version, country, lang, langList, user_id, type, id, log_id=None, app_code=None):
    req = dittypes.DIOneRequest(type=type, id=id, languageId=lang, serviceName=None, timeSign=get_UTC_time(), logId=log_id)
    res = await diclient.getOneDetailByObj(req)
    return res

##### for detail related cards part #####

# get related short videos
@timing(RECO_SERVICE_NAME, enum.GENERAL_VIDEO_RELATED_INTERFACE_NAME)
@expand_request
@tclient(False)
# @redis.cache_related_card(enum.GENERAL_VIDEO_RELATED_INTERFACE_NAME, id_index=-1)
async def fetch_related_video(tclient, app_version, country, lang, langList, user_id, num, next, type, filterId, resourceType, resourceId,
    log_id=None, app_code=None):
    req = recttypes.Request(
        userId=user_id, country=country, language=lang, languageList=langList, num=num, finalId=next, type=type,
        interfaceName=enum.GENERAL_VIDEO_RELATED_INTERFACE_NAME, networkStatus=NETWORK_STATUS, resourceType=resourceType,
        platformId=ANDROID_PLATEFORM_ID, resourceId=resourceId, filterId=filterId,
        timeSign=get_UTC_time(), clientVersion=app_code, logId=log_id)
    return await tclient.recommend(req)


# get other short videos of this publisher
@timing(RECO_SERVICE_NAME, enum.OTHER_SHORTVIDEO_OF_THE_PUBLISHER)
@expand_request
@tclient(False)
# @redis.cache_related_card(enum.OTHER_SHORTVIDEO_OF_THE_PUBLISHER, id_index=-1)
async def fetch_other_short_video_of_the_publisher(tclient, app_version, country, lang, langList, user_id, num, next, type, filterId, resourceType,
    resourceId, log_id=None, app_code=None):
    req = recttypes.Request(
        userId=user_id, country=country, language=lang, languageList=langList, num=num, finalId=next, type=type,
        interfaceName=enum.OTHER_SHORTVIDEO_OF_THE_PUBLISHER, networkStatus=NETWORK_STATUS, resourceType=resourceType,
        platformId=ANDROID_PLATEFORM_ID, resourceId=resourceId, filterId=filterId,
        timeSign=get_UTC_time(), clientVersion=app_code, logId=log_id)
    return await tclient.recommend(req)


# get similar publishers
@timing(RECO_SERVICE_NAME, enum.SIMIALR_PUBLISHER_INTERFACE_NAME)
@expand_request
@tclient(False)
# @redis.cache_related_card(enum.SIMIALR_PUBLISHER_INTERFACE_NAME, id_index=-1)
async def fetch_similar_publishers(tclient, app_version, country, lang, langList, user_id, num, next, type, resourceType, resourceId,
    log_id=None, app_code=None):
    req = recttypes.Request(
        userId=user_id, country=country, language=lang, languageList=langList, num=num, finalId=next, type=type,
        interfaceName=enum.SIMIALR_PUBLISHER_INTERFACE_NAME, networkStatus=NETWORK_STATUS, timeSign=get_UTC_time(),
        resourceType=resourceType, platformId=ANDROID_PLATEFORM_ID, resourceId=resourceId, filterId=resourceId, clientVersion=app_code, logId=log_id)
    return await tclient.recommend(req)


# get popular videos of publisher
@timing(RECO_SERVICE_NAME, enum.POPULAR_VIDEOS_OF_PUBLISHER_INTERFACE_NAME)
@expand_request
@tclient(False)
# @redis.cache_related_card(enum.POPULAR_VIDEOS_OF_PUBLISHER_INTERFACE_NAME, id_index=-1)
async def fetch_popular_vidoes_of_publisher(tclient, app_version, country, lang, langList, user_id, num, next, type, resourceType,
    resourceId, log_id=None, app_code=None):
    req = recttypes.Request(
        userId=user_id, country=country, language=lang, languageList=langList, num=num, finalId=next, type=type,
        interfaceName=enum.POPULAR_VIDEOS_OF_PUBLISHER_INTERFACE_NAME, networkStatus=NETWORK_STATUS,
        resourceType=resourceType, platformId=ANDROID_PLATEFORM_ID, resourceId=resourceId,
        timeSign=get_UTC_time(), clientVersion=app_code, logId=log_id)
    return await tclient.recommend(req)


# get recent videos of publisher
@timing(RECO_SERVICE_NAME, enum.RECENT_VIDEOS_OF_PUBLISHER_INTERFACE_NAME)
@expand_request
@tclient(False)
# @redis.cache_related_card(enum.RECENT_VIDEOS_OF_PUBLISHER_INTERFACE_NAME, id_index=-1)
async def fetch_recent_vidoes_of_publisher(tclient, app_version, country, lang, langList, user_id, num, next, type, resourceType,
    resourceId, log_id=None, app_code=None):
    req = recttypes.Request(
        userId=user_id, country=country, language=lang, languageList=langList, num=num, finalId=next, type=type,
        interfaceName=enum.RECENT_VIDEOS_OF_PUBLISHER_INTERFACE_NAME, networkStatus=NETWORK_STATUS,
        resourceType=resourceType, platformId=ANDROID_PLATEFORM_ID, resourceId=resourceId,
        timeSign=get_UTC_time(), clientVersion=app_code, logId=log_id)
    return await tclient.recommend(req)


# sort by popular of all short videos of this publisher
@timing(RECO_SERVICE_NAME, enum.SHORTVIDEO_POPULAR_INTERFACE_NAME)
@expand_request
@tclient(False)
# @redis.cache_related_card(enum.SHORTVIDEO_POPULAR_INTERFACE_NAME, id_index=-1)
async def fetch_popular_short_videos_of_publisher(tclient, app_version, country, lang, langList, user_id, num, next, type, filterId,
    resourceType, resourceId, log_id=None, app_code=None):
    req = recttypes.Request(
        userId=user_id, country=country, language=lang, languageList=langList, num=num, finalId=next, type=type,
        interfaceName=enum.SHORTVIDEO_POPULAR_INTERFACE_NAME, networkStatus=NETWORK_STATUS, timeSign=get_UTC_time(),
        resourceType=resourceType, platformId=ANDROID_PLATEFORM_ID, resourceId=resourceId,
        filterId=filterId, clientVersion=app_code, logId=log_id)
    res = await tclient.recommend(req)
    return res


# sort by lastest released of all short videos of this publisher
@timing(RECO_SERVICE_NAME, enum.SHORTVIDEO_LATEST_INTERFACE_NAME)
@expand_request
@tclient(False)
# @redis.cache_related_card(enum.SHORTVIDEO_LATEST_INTERFACE_NAME, id_index=-1)
async def fetch_lastest_short_videos_of_publisher(tclient, app_version, country, lang, langList, user_id, num, next, type,
    resourceType, resourceId, log_id=None, app_code=None):
    req = recttypes.Request(
        userId=user_id, country=country, language=lang, languageList=langList, num=num, finalId=next, type=type,
        interfaceName=enum.SHORTVIDEO_LATEST_INTERFACE_NAME, networkStatus=NETWORK_STATUS, timeSign=get_UTC_time(),
        resourceType=resourceType, platformId=ANDROID_PLATEFORM_ID, resourceId=resourceId, clientVersion=app_code, logId=log_id)
    return await tclient.recommend(req)


# get the tv shows of the publisher
@timing(RECO_SERVICE_NAME, enum.TVSHOW_OF_PUBLISHER_INTERFACE_NAME)
@expand_request
@tclient(False)
# @redis.cache_related_card(enum.TVSHOW_OF_PUBLISHER_INTERFACE_NAME, id_index=-1)
async def fetch_tv_shows_of_publisher(tclient, app_version, country, lang, langList, user_id, num, next, type, resourceType,
    resourceId, log_id=None, app_code=None):
    req = recttypes.Request(
        userId=user_id, country=country, language=lang, languageList=langList, num=num, finalId=next, type=type,
        interfaceName=enum.TVSHOW_OF_PUBLISHER_INTERFACE_NAME, networkStatus=NETWORK_STATUS, timeSign=get_UTC_time(),
        resourceType=resourceType, platformId=ANDROID_PLATEFORM_ID, resourceId=resourceId, clientVersion=app_code, logId=log_id)
    return await tclient.recommend(req)


# get the albums of the publisher
@timing(RECO_SERVICE_NAME, enum.ALBUMS_OF_PUBLISHER_INTERFACE_NAME)
@expand_request
@tclient(False)
# @redis.cache_related_card(enum.ALBUMS_OF_PUBLISHER_INTERFACE_NAME, id_index=-1)
async def fetch_albums_of_publisher(tclient, app_version, country, lang, langList, user_id, num, next, type, resourceType,
    resourceId, log_id=None, app_code=None):
    req = recttypes.Request(
        userId=user_id, country=country, language=lang, languageList=langList, num=num, finalId=next, type=type,
        interfaceName=enum.ALBUMS_OF_PUBLISHER_INTERFACE_NAME, networkStatus=NETWORK_STATUS, timeSign=get_UTC_time(),
        resourceType=resourceType, platformId=ANDROID_PLATEFORM_ID, resourceId=resourceId, clientVersion=app_code, logId=log_id)
    return await tclient.recommend(req)


# get the artists of the publisher
@timing(RECO_SERVICE_NAME, enum.ARTISTS_OF_PUBLISHER_INTERFACE_NAME)
@expand_request
@tclient(False)
# @redis.cache_related_card(enum.ARTISTS_OF_PUBLISHER_INTERFACE_NAME, id_index=-1)
async def fetch_artists_of_publisher(tclient, app_version, country, lang, langList, user_id, num, next, type, resourceType,
    resourceId, log_id=None, app_code=None):
    req = recttypes.Request(
        userId=user_id, country=country, language=lang, languageList=langList, num=num, finalId=next, type=type,
        interfaceName=enum.ARTISTS_OF_PUBLISHER_INTERFACE_NAME, networkStatus=NETWORK_STATUS, timeSign=get_UTC_time(),
        resourceType=resourceType, platformId=ANDROID_PLATEFORM_ID, resourceId=resourceId, clientVersion=app_code, logId=log_id)
    return await tclient.recommend(req)


# get the movies of the publisher
@timing(RECO_SERVICE_NAME, enum.MOVIES_OF_PUBLISHER_INTERFACE_NAME)
@expand_request
@tclient(False)
# @redis.cache_related_card(enum.MOVIES_OF_PUBLISHER_INTERFACE_NAME, id_index=-1)
async def fetch_movies_of_publisher(tclient, app_version, country, lang, langList, user_id, num, next, type, resourceType,
    resourceId, log_id=None, app_code=None):
    req = recttypes.Request(
        userId=user_id, country=country, language=lang, languageList=langList, num=num, finalId=next, type=type,
        interfaceName=enum.MOVIES_OF_PUBLISHER_INTERFACE_NAME, networkStatus=NETWORK_STATUS, timeSign=get_UTC_time(),
        resourceType=resourceType, platformId=ANDROID_PLATEFORM_ID, resourceId=resourceId, clientVersion=app_code, logId=log_id)
    return await tclient.recommend(req)


''' some other interfaces which will be used in future below '''
# get the episodes of the season
@timing(RECO_SERVICE_NAME, enum.EPISODES_OF_SEASON_INTERFACE_NAME)
@expand_request
@tclient(False)
# @redis.cache_related_card(enum.EPISODES_OF_SEASON_INTERFACE_NAME, id_index=-1)
async def fetch_episodes_of_season(tclient, app_version, country, lang, langList, user_id, num, next, type, resourceType,
    resourceId, log_id=None, app_code=None):
    req = recttypes.Request(
        userId=user_id, country=country, language=lang, languageList=langList, num=num, finalId=next, type=type,
        interfaceName=enum.EPISODES_OF_SEASON_INTERFACE_NAME, networkStatus=NETWORK_STATUS, resourceType=resourceType,
        platformId=ANDROID_PLATEFORM_ID, resourceId=resourceId, timeSign=get_UTC_time(), clientVersion=app_code, logId=log_id)
    return await tclient.recommend(req)


# get espisodes of the season by a video id
@timing(RECO_SERVICE_NAME, enum.AROUND_PLAYING_EPISODES_OF_SEASON_INTERFACE_NAME)
@expand_request
@tclient(False)
# @redis.cache_related_card(enum.AROUND_PLAYING_EPISODES_OF_SEASON_INTERFACE_NAME, id_index=-2)
async def fetch_around_playing_episodes_of_season(tclient, app_version, country, lang, langList, user_id, num, next, type,
    resourceType, resourceId, filterId, log_id=None, app_code=None):
    req = recttypes.Request(
        userId=user_id, country=country, language=lang, languageList=langList, num=num, finalId=next, type=type,
        interfaceName=enum.AROUND_PLAYING_EPISODES_OF_SEASON_INTERFACE_NAME, networkStatus=NETWORK_STATUS, resourceType=resourceType,
        platformId=ANDROID_PLATEFORM_ID, resourceId=resourceId, filterId=filterId, timeSign=get_UTC_time(), clientVersion=app_code, logId=log_id)
    return await tclient.recommend(req)


# get the similar tv shows
@timing(RECO_SERVICE_NAME, enum.TVSHOWS_SIMILAR_INTERFACE_NAME)
@expand_request
@tclient(False)
# @redis.cache_related_card(enum.TVSHOWS_SIMILAR_INTERFACE_NAME, id_index=-1)
async def fetch_related_tv_shows(tclient, app_version, country, lang, langList, user_id, num, next, type, resourceType,
    resourceId, log_id=None, app_code=None):
    req = recttypes.Request(
        userId=user_id, country=country, language=lang, languageList=langList, num=num, finalId=next, type=type,
        interfaceName=enum.TVSHOWS_SIMILAR_INTERFACE_NAME, networkStatus=NETWORK_STATUS, platformId=ANDROID_PLATEFORM_ID,
        resourceType=resourceType, resourceId=resourceId, timeSign=get_UTC_time(), filterId=resourceId, clientVersion=app_code, logId=log_id)
    return await tclient.recommend(req)


# get recommended movies
@timing(RECO_SERVICE_NAME, enum.MOVIE_SIMILAR_INTERFACE_NAME)
@expand_request
@tclient(False)
# @redis.cache_related_card(enum.MOVIE_SIMILAR_INTERFACE_NAME, id_index=-1)
async def fecth_similar_movies(tclient, app_version, country, lang, langList, user_id, num, next, type, resourceType,
    resourceId, log_id=None, app_code=None):
    req = recttypes.Request(
        userId=user_id, country=country, language=lang, languageList=langList, num=num, finalId=next, type=type,
        interfaceName=enum.MOVIE_SIMILAR_INTERFACE_NAME, networkStatus=NETWORK_STATUS, platformId=ANDROID_PLATEFORM_ID,
        resourceType=resourceType, resourceId=resourceId, timeSign=get_UTC_time(), filterId=resourceId, clientVersion=app_code, logId=log_id)
    return await tclient.recommend(req)


# get all the songs of this artist
@timing(RECO_SERVICE_NAME, enum.LASTEST_SONGS_OF_ARTIST_INTERFACE_NAME)
@expand_request
@tclient(False)
# @redis.cache_related_card(enum.LASTEST_SONGS_OF_ARTIST_INTERFACE_NAME, id_index=-1)
async def fetch_lastest_songs_of_artist(tclient, app_version, country, lang, langList, user_id, num, next, type,
    resourceType, resourceId, log_id=None, app_code=None):
    req = recttypes.Request(
        userId=user_id, country=country, language=lang, languageList=langList, num=num, finalId=next, type=type,
        interfaceName=enum.LASTEST_SONGS_OF_ARTIST_INTERFACE_NAME, networkStatus=NETWORK_STATUS, resourceType=resourceType,
        platformId=ANDROID_PLATEFORM_ID, resourceId=resourceId, timeSign=get_UTC_time(), clientVersion=app_code, logId=log_id)
    res = await tclient.recommend(req)
    return res


# get other songs of this album
@timing(RECO_SERVICE_NAME, enum.SONGS_OF_OTHER_ALBUM_INTERFACE_NAME)
@expand_request
@tclient(False)
# @redis.cache_related_card(enum.SONGS_OF_OTHER_ALBUM_INTERFACE_NAME, id_index=-1)
async def fetch_other_songs_of_album(tclient, app_version, country, lang, langList, user_id, num, next, type, filterId,
    resourceType, resourceId, log_id=None, app_code=None):
    req = recttypes.Request(
        userId=user_id, country=country, language=lang, languageList=langList, num=num, finalId=next, type=type,
        interfaceName=enum.SONGS_OF_OTHER_ALBUM_INTERFACE_NAME, networkStatus=NETWORK_STATUS, resourceType=resourceType,
        platformId=ANDROID_PLATEFORM_ID, resourceId=resourceId, filterId=filterId, timeSign=get_UTC_time(), clientVersion=app_code, logId=log_id)
    return await tclient.recommend(req)


# get similar songs
@timing(RECO_SERVICE_NAME, enum.SIMILAR_SONGS_INTERFACE_NAME)
@expand_request
@tclient(False)
# @redis.cache_related_card(enum.SIMILAR_SONGS_INTERFACE_NAME, id_index=-1)
async def fetch_similar_songs(tclient, app_version, country, lang, langList, user_id, num, next, type, resourceType,
    resourceId, log_id=None, app_code=None):
    req = recttypes.Request(
        userId=user_id, country=country, language=lang, languageList=langList, num=num, finalId=next, type=type,
        interfaceName=enum.SIMILAR_SONGS_INTERFACE_NAME, networkStatus=NETWORK_STATUS, resourceType=resourceType,
        platformId=ANDROID_PLATEFORM_ID, resourceId=resourceId, timeSign=get_UTC_time(), filterId=resourceId, clientVersion=app_code, logId=log_id)
    return await tclient.recommend(req)


# get all the songs of this album
@timing(RECO_SERVICE_NAME, enum.SONGS_OF_ALBUM_INTERFACE_NAME)
@expand_request
@tclient(False)
# @redis.cache_related_card(enum.SONGS_OF_ALBUM_INTERFACE_NAME, id_index=-1)
async def fetch_songs_of_album(tclient, app_version, country, lang, langList, user_id, num, next, type, resourceType,
    resourceId, log_id=None, app_code=None):
    req = recttypes.Request(
        userId=user_id, country=country, language=lang, languageList=langList, num=num, finalId=next, type=type,
        interfaceName=enum.SONGS_OF_ALBUM_INTERFACE_NAME, networkStatus=NETWORK_STATUS, resourceType=resourceType,
        platformId=ANDROID_PLATEFORM_ID, resourceId=resourceId, timeSign=get_UTC_time(), clientVersion=app_code, logId=log_id)
    return await tclient.recommend(req)


# get all the songs of this album without paging
@timing(RECO_SERVICE_NAME, enum.SONGS_OF_THE_ALBUM_NO_PAGING_INTERFACE_NAME)
@expand_request
@tclient(False)
# @redis.cache_related_card(enum.SONGS_OF_THE_ALBUM_NO_PAGING_INTERFACE_NAME, id_index=-1)
async def fetch_songs_of_album_without_paging(tclient, app_version, country, lang, langList, user_id, type, resourceType,
    resourceId, log_id=None, app_code=None):
    req = recttypes.Request(
        userId=user_id, country=country, language=lang, languageList=langList, type=type, resourceType=resourceType,
        interfaceName=enum.SONGS_OF_THE_ALBUM_NO_PAGING_INTERFACE_NAME, networkStatus=NETWORK_STATUS,
        platformId=ANDROID_PLATEFORM_ID, resourceId=resourceId, timeSign=get_UTC_time(), clientVersion=app_code, logId=log_id)
    res = await tclient.recommend(req)
    return res


# get related albums
@timing(RECO_SERVICE_NAME, enum.ALBUMS_SIMILAR_INTERFACE_NAME)
@expand_request
@tclient(False)
# @redis.cache_related_card(enum.ALBUMS_SIMILAR_INTERFACE_NAME, id_index=-1)
async def fetch_related_albums(tclient, app_version, country, lang, langList, user_id, num, next, type, resourceType,
    resourceId, log_id=None, app_code=None):
    req = recttypes.Request(
        userId=user_id, country=country, language=lang, languageList=langList, num=num, finalId=next, type=type,
        interfaceName=enum.ALBUMS_SIMILAR_INTERFACE_NAME, networkStatus=NETWORK_STATUS, timeSign=get_UTC_time(),
        platformId=ANDROID_PLATEFORM_ID, resourceType=resourceType, resourceId=resourceId, filterId=resourceId, clientVersion=app_code, logId=log_id)
    return await tclient.recommend(req)


# get popular songs of the artist
@timing(RECO_SERVICE_NAME, enum.SONGS_POPULAR_OF_ARTIST_INTERFACE_NAME)
@expand_request
@tclient(False)
# @redis.cache_related_card(enum.SONGS_POPULAR_OF_ARTIST_INTERFACE_NAME, id_index=-1)
async def fetch_popular_songs_of_artist(tclient, app_version, country, lang, langList, user_id, num, next, type,
    resourceType, resourceId, log_id=None, app_code=None):
    req = recttypes.Request(
        userId=user_id, country=country, language=lang, languageList=langList, num=num, finalId=next, type=type,
        interfaceName=enum.SONGS_POPULAR_OF_ARTIST_INTERFACE_NAME, networkStatus=NETWORK_STATUS, resourceType=resourceType,
        platformId=ANDROID_PLATEFORM_ID, resourceId=resourceId, timeSign=get_UTC_time(), clientVersion=app_code, logId=log_id)
    res = await tclient.recommend(req)
    return res


# get all albums of the artist
@timing(RECO_SERVICE_NAME, enum.ALBUMS_OF_ARTIST_INTERFACE_NAME)
@expand_request
@tclient(False)
# @redis.cache_related_card(enum.ALBUMS_OF_ARTIST_INTERFACE_NAME, id_index=-1)
async def fetch_all_albums_of_artist(tclient, app_version, country, lang, langList, user_id, num, next, type,
    resourceType, resourceId, log_id=None, app_code=None):
    req = recttypes.Request(
        userId=user_id, country=country, language=lang, languageList=langList, num=num, finalId=next, type=type,
        interfaceName=enum.ALBUMS_OF_ARTIST_INTERFACE_NAME, networkStatus=NETWORK_STATUS, resourceType=resourceType,
        platformId=ANDROID_PLATEFORM_ID, resourceId=resourceId, timeSign=get_UTC_time(), clientVersion=app_code, logId=log_id)
    res = await tclient.recommend(req)
    return res


# get popular albums of the artist
@timing(RECO_SERVICE_NAME, enum.POPULAR_ALBUMS_OF_ARTIST_INTERFACE_NAME)
@expand_request
@tclient(False)
# @redis.cache_related_card(enum.POPULAR_ALBUMS_OF_ARTIST_INTERFACE_NAME, id_index=-1)
async def fetch_popular_albums_of_artist(tclient, app_version, country, lang, langList, user_id, num, next, type,
    resourceType, resourceId, log_id=None, app_code=None):
    req = recttypes.Request(
        userId=user_id, country=country, language=lang, languageList=langList, num=num, finalId=next, type=type,
        interfaceName=enum.POPULAR_ALBUMS_OF_ARTIST_INTERFACE_NAME, networkStatus=NETWORK_STATUS, resourceType=resourceType,
        platformId=ANDROID_PLATEFORM_ID, resourceId=resourceId, timeSign=get_UTC_time(), clientVersion=app_code, logId=log_id)
    res = await tclient.recommend(req)
    return res


# get similar artists
@timing(RECO_SERVICE_NAME, enum.ARTISTS_SIMILAR_INTERFACE_NAME)
@expand_request
@tclient(False)
# @redis.cache_related_card(enum.ARTISTS_SIMILAR_INTERFACE_NAME, id_index=-1)
async def fetch_similar_artists(tclient, app_version, country, lang, langList, user_id, num, next, type,
    resourceType, resourceId, log_id=None, app_code=None):
    req = recttypes.Request(
        userId=user_id, country=country, language=lang, languageList=langList, num=num, finalId=next, type=type,
        interfaceName=enum.ARTISTS_SIMILAR_INTERFACE_NAME, networkStatus=NETWORK_STATUS, platformId=ANDROID_PLATEFORM_ID,
        resourceType=resourceType, resourceId=resourceId, timeSign=get_UTC_time(), filterId=resourceId, clientVersion=app_code, logId=log_id)
    res = await tclient.recommend(req)
    return res


# get the seasons of the tv show and sorted by publishe time
@timing(RECO_SERVICE_NAME, enum.SEASONS_LATEST_OF_TVSHOW_INTERFACE_NAME)
@expand_request
@tclient(False)
# @redis.cache_related_card(enum.SEASONS_LATEST_OF_TVSHOW_INTERFACE_NAME, id_index=-1)
async def fetch_lastest_seasons_of_tvshow(tclient, app_version, country, lang, langList, user_id, num, next, type,
    resourceType, resourceId, log_id=None, app_code=None):
    req = recttypes.Request(
        userId=user_id, country=country, language=lang, languageList=langList, num=num, finalId=next, type=type,
        interfaceName=enum.SEASONS_LATEST_OF_TVSHOW_INTERFACE_NAME, networkStatus=NETWORK_STATUS, platformId=ANDROID_PLATEFORM_ID,
        resourceId=resourceId, resourceType=resourceType, timeSign=get_UTC_time(), clientVersion=app_code, logId=log_id)
    return await tclient.recommend(req)


# get the first season of the tv show
@timing(RECO_SERVICE_NAME, enum.FIRST_SEASON_OF_TVSHOW_INTERFACE_NAME)
@expand_request
@tclient(False)
# @redis.cache_related_card(enum.FIRST_SEASON_OF_TVSHOW_INTERFACE_NAME, id_index=-1)
async def fetch_first_season_of_tvshow(tclient, app_version, country, lang, langList, user_id, num, next, type,
    resourceType, resourceId, log_id=None, app_code=None):
    req = recttypes.Request(
        userId=user_id, country=country, language=lang, languageList=langList, num=num, finalId=next, type=type,
        interfaceName=enum.FIRST_SEASON_OF_TVSHOW_INTERFACE_NAME, networkStatus=NETWORK_STATUS, platformId=ANDROID_PLATEFORM_ID,
        resourceId=resourceId, resourceType=resourceType, timeSign=get_UTC_time(), clientVersion=app_code, logId=log_id)
    return await tclient.recommend(req)


# get similar playlists
@timing(RECO_SERVICE_NAME, enum.SIMILAR_PLAYLISTS_INTERFACE_NAME)
@expand_request
@tclient(False)
# @redis.cache_related_card(enum.SIMILAR_PLAYLISTS_INTERFACE_NAME, id_index=-1)
async def fetch_similar_playlist(tclient, app_version, country, lang, langList, user_id, num, next, type,
    resourceType, resourceId, log_id=None, app_code=None):
    req = recttypes.Request(
        userId=user_id, country=country, language=lang, languageList=langList, num=num, finalId=next, type=type,
        interfaceName=enum.SIMILAR_PLAYLISTS_INTERFACE_NAME, networkStatus=NETWORK_STATUS, resourceType=resourceType,
        platformId=ANDROID_PLATEFORM_ID, resourceId=resourceId, timeSign=get_UTC_time(), filterId=resourceId, clientVersion=app_code, logId=log_id)
    return await tclient.recommend(req)


# get all songs of playlist
@timing(RECO_SERVICE_NAME, enum.SONGS_OF_PLAYLIST_INTERFACE_NAME)
@expand_request
@tclient(False)
# @redis.cache_related_card(enum.SONGS_OF_PLAYLIST_INTERFACE_NAME, id_index=-1)
async def fetch_songs_of_playlist(tclient, app_version, country, lang, langList, user_id, num, next, type, filterId,
    resourceType, resourceId, log_id=None, app_code=None):
    req = recttypes.Request(
        userId=user_id, country=country, language=lang, languageList=langList, num=num, finalId=next, type=type,
        interfaceName=enum.SONGS_OF_PLAYLIST_INTERFACE_NAME, networkStatus=NETWORK_STATUS, resourceType=resourceType,
        platformId=ANDROID_PLATEFORM_ID, resourceId=resourceId, timeSign=get_UTC_time(), filterId=filterId, clientVersion=app_code, logId=log_id)
    return await tclient.recommend(req)


# get all songs of playlist without paging
@timing(RECO_SERVICE_NAME, enum.SONGS_OF_THE_PLAYLIST_NO_PAGING_INTERFACE_NAME)
@expand_request
@tclient(False)
# @redis.cache_related_card(enum.SONGS_OF_THE_PLAYLIST_NO_PAGING_INTERFACE_NAME, id_index=-1)
async def fetch_songs_of_playlist_without_paging(tclient, app_version, country, lang, langList, user_id, type,
    resourceType, resourceId, log_id=None, app_code=None):
    req = recttypes.Request(
        userId=user_id, country=country, language=lang, languageList=langList, type=type, resourceType=resourceType,
        interfaceName=enum.SONGS_OF_THE_PLAYLIST_NO_PAGING_INTERFACE_NAME, networkStatus=NETWORK_STATUS,
        platformId=ANDROID_PLATEFORM_ID, resourceId=resourceId, timeSign=get_UTC_time(), clientVersion=app_code, logId=log_id)
    return await tclient.recommend(req)


# get recommand search result
@timing(RECO_SERVICE_NAME, enum.SEARCH_CONTENT_RECOMMAND_INTERFACE_NAME)
@expand_request
@tclient(False)
async def fetch_nosearch_recommend(tclient, app_version,  country, lang, langList, user_id, num, log_id=None, app_code=None):
    req = recttypes.Request(
        userId=user_id, country=country, language=lang, languageList=langList, num=num, resourceType=None,
        interfaceName=enum.SEARCH_CONTENT_RECOMMAND_INTERFACE_NAME, networkStatus=NETWORK_STATUS,
        platformId=ANDROID_PLATEFORM_ID, resourceId=None, timeSign=get_UTC_time(), clientVersion=app_code,
        logId=log_id)
    return await tclient.recommend(req)


@timing(RECO_SERVICE_NAME, enum.LOCAL_RELEVANT_RECOMMAND_INTERFACE_NAME)
@expand_request
@tclient(False)
async def fetch_local_relevant(tclient, app_version, country, lang, langList, user_id, num, file_name, log_id=None, app_code=None):
    req = recttypes.Request(
        userId=user_id, country=country, language=lang, languageList=langList, num=num, resourceType=None,
        interfaceName=enum.LOCAL_RELEVANT_RECOMMAND_INTERFACE_NAME, networkStatus=NETWORK_STATUS,
        localFileInfo=recttypes.LocalFileInfo(fileName=file_name),
        platformId=ANDROID_PLATEFORM_ID, resourceId=None, timeSign=get_UTC_time(), clientVersion=app_code,
        logId=log_id)
    return await tclient.recommend(req)

@timing(RECO_SERVICE_NAME, enum.BROWSE_ITEMS_INTERFACE)
@expand_request
@tclient(True)
@redis.cache_card(enum.BROWSE_ITEMS_INTERFACE, id_index=-1)
async def fetch_browse_list(tclient, app_version, country, lang, langList, user_id, tab_id, num, type, next,
    genres, langs, singers, actors, directors, release_years, sort_opt, browse_type, log_id=None, app_code=None):
    req = recttypes.Request(
        userId=user_id, country=country, language=lang, languageList=langList, clientVersion=app_code, tabId=tab_id,
        interfaceName=enum.BROWSE_ITEMS_INTERFACE, resourceType=browse_type, num=num, type=type, finalId=next,
        logId=log_id, genresList=genres, singerList=singers, actorList=actors, directorList=directors, releaseYears=release_years,
        browseLangs=langs, sortOpt=sort_opt, platformId=ANDROID_PLATEFORM_ID)
    res = await tclient.recommend(req)
    return res
