from services.thrift.di import ttypes as dittypes
from services import fetch_di_detail_page_info, fetch_di_one_detail, \
                     get_history_multiple, get_watchlist_multiple, get_subscribe_multiple, get_thumb_multiple, \
                     get_history_single, get_watchlist_single, get_subscribe_single, get_thumb_single
from models.v1 import enum
from .resource import ShortVideo, Publisher, MovieFilm, MusicVideo, MusicPlaylistQueue, \
                      MusicPlaylist, MusicAlbum, MusicAlbumQueue, MusicArtist, TvEpisode, TvSeason, TvShow
from .resource.live_tv import LiveChannel, LiveProgramme, LiveChannelPagingPrograms
from .request_body import RecResult
from .container.ua_card_paging import UaCardPaging
from .container.tab.card_paging import TabCardPaging
from .resource.browse_card import BrowseItemPaging
from .resource.browse_card import BrowseCardItem
from .resource.game import Game


RESOURCES_CLASSES_BASE = [
    ShortVideo, Publisher, MovieFilm,
    MusicArtist, MusicAlbum, MusicPlaylist, MusicVideo,
    TvShow, TvEpisode, TvSeason,
    LiveChannel, LiveProgramme,
    BrowseCardItem, Game
]

REC_TYPE_TO_CLS_BASE = {enum.API_TO_REC[cls.API_TYPE]: cls for cls in RESOURCES_CLASSES_BASE}
API_TYPE_TO_CLS_BASE = {cls.API_TYPE: cls for cls in RESOURCES_CLASSES_BASE}

UA_SINGLE = {
    enum.CARD_HISTORY: get_history_single,
    enum.CARD_WATCHLIST: get_watchlist_single,
    enum.CARD_SUBSCRIBE: get_subscribe_single,
    enum.CARD_THUMB: get_thumb_single
}

UA_MULTIPLE = {
    enum.CARD_HISTORY: get_history_multiple,
    enum.CARD_WATCHLIST: get_watchlist_multiple,
    enum.CARD_SUBSCRIBE: get_subscribe_multiple,
    enum.CARD_THUMB: get_thumb_multiple
}

def rec_type_to_cls(req):
    res = {
        **REC_TYPE_TO_CLS_BASE
    }
    if req['xheaders']['app-version'] >= enum.VERSION_1065:
        res[enum.API_TO_REC[MusicPlaylist.API_TYPE]] = MusicPlaylistQueue
        res[enum.API_TO_REC[MusicAlbum.API_TYPE]] = MusicAlbumQueue

    if req['xheaders']['app-version'] >= enum.VERSION_NEWEST:
        res[enum.API_TO_REC[LiveChannel.API_TYPE]] = LiveChannelPagingPrograms

    return res

def api_type_to_cls(req):
    res = {
        **API_TYPE_TO_CLS_BASE
    }
    if req['xheaders']['app-version'] >= enum.VERSION_1065:
        res[MusicPlaylist.API_TYPE] = MusicPlaylistQueue
        res[MusicAlbum.API_TYPE] = MusicAlbumQueue

    if req['xheaders']['app-version'] >= enum.VERSION_NEWEST:
        res[LiveChannel.API_TYPE] = LiveChannelPagingPrograms

    return res


# idt_list: [{id, type, history, watchlist, subscribe, thumb}]
class ResourceGroupBuilder:
    @staticmethod
    async def build(req, rec_list):
        if len(rec_list) <= 0:
            return {}

        REC_TYPE_TO_CLS = rec_type_to_cls(req)

        # 处理di请求
        id_rec = {}
        type_ids = {}
        for it in rec_list:
            type_ids.setdefault(it.type, []).append(it.id)
            id_rec[it.id] = it

        idwts = []
        for typ, ids in type_ids.items():
            idwts.append(dittypes.IdsWithType(ids=ids, type=typ))

        di = await fetch_di_detail_page_info(req, idwts) # pylint: disable=no-value-for-parameter
        # 处理ua请求
        uid = req['user'].id
        ua_res = {}
        for t, m in UA_MULTIPLE.items():
            rids = []
            for it in rec_list:
                rid = it.id
                ua = it.ua.get(t)
                if ua is True: # 需要向ua-server发请求
                    rids.append(rid)
                elif isinstance(ua, dict): # 已经拿到ua数据了
                    ua_res.setdefault(rid, {})[t] = ua

            if len(rids) > 0:
                items = await m(uid, rids)
                for j, item in enumerate(items or []):
                    ua_res.setdefault(rids[j], {})[t] = item

        objs = {}

        for typ in (di and di.typeList or []):
            Ctor = REC_TYPE_TO_CLS.get(typ)

            if Ctor is None:
                continue

            for val in getattr(di, Ctor.DI_LIST_NAME):
                obj = Ctor(req, Ctor.API_TYPE)
                obj.fill(di=val)
                rec = id_rec.get(obj.id)
                obj.fill(rec=rec.result, ua=ua_res.get(obj.id), extra=rec.extra)
                objs[obj.id] = obj

        return objs


class ResourceProfileBuilder:
    @staticmethod
    async def build(req, api_type, rid):
        API_TYPE_TO_CLS = api_type_to_cls(req)

        Ctor = API_TYPE_TO_CLS.get(api_type)
        if Ctor is None:
            return None

        rec = RecResult(rid=rid, typ=enum.API_TO_REC[Ctor.API_TYPE], ua={t: True for t in Ctor.DETAIL_UA_TYPES})

        uid = req['user'].id
        rid = rec.id
        typ = rec.type
        di = await fetch_di_one_detail(req, typ, rid) # pylint: disable=no-value-for-parameter

        ua_res = {}
        for t, m in UA_SINGLE.items():
            ua = rec.ua.get(t)
            if ua is True:
                ua_res[t] = await m(uid, rid, redirect_type=enum.REC_TO_UA[typ])
            elif isinstance(ua, dict):
                ua_res[t] = ua

        res = None
        for tp in (di and di.typeList or []):
            if tp != typ:
                continue

            for val in getattr(di, Ctor.DI_LIST_NAME):
                obj = Ctor(req, Ctor.API_TYPE)
                obj.fill(di=val)
                if obj.id != rid:
                    continue

                obj.fill(rec=rec.result, ua=ua_res, extra=rec.extra)
                res = obj
                break

        return res


class CardPagingBuilder:
    @staticmethod
    async def build(req):
        API_TYPE_TO_CLS = api_type_to_cls(req)
        paging = None

        tab_id = req.args.get('tab_id', enum.HOME_TAB_ID)
        card_id = req['context'].path_params['cardId']
        related_type = req.args.get('relatedType')

        if card_id in enum.ALL_UA_CARDS: # ua card
            paging = UaCardPaging(req, card_id, typ=card_id)
        elif related_type: # related card
            Ctor = API_TYPE_TO_CLS.get(related_type)
            if Ctor is not None:
                Pagings = getattr(Ctor, 'PAGING_CARDS', Ctor.RELATED_CARDS)
                interface_Paging = {Paging.INTERFACE: Paging for Paging in Pagings}
                Paging = interface_Paging.get(req.args.get('interface'))
                if Paging is not None:
                    paging = Paging(req, card_id)
        elif tab_id: # tab card
            paging = TabCardPaging(req, tab_id, card_id)

        if paging is not None:
            await paging.render()

        return paging
