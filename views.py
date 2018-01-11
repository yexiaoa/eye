#!/usr/bin/env python
# -*- coding:utf-8 -*-

import logging

from django.utils.translation import ugettext as _, ugettext_lazy as _l
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.urls import reverse_lazy
from django.views.generic import TemplateView, FormView, ListView, DetailView
from rest_framework import views
from rest_framework import viewsets, mixins
from rest_framework.permissions import AllowAny

from betting.common_data import TradeStatus, GameType
from betting.betting_business import get_all_coinflip_history, create_promotion, get_promotion_count
from betting.betting_business import get_my_coinflip_history, get_my_jackpot_history
from betting.business.deposit_business import join_coinflip_game, join_jackpot_game, ws_send_cf_news, create_random_hash, getWins, get_ranks
from betting.business.steam_business import get_user_inventories
from betting.business.cache_manager import update_coinflip_game_in_cache, get_current_jackpot_id, get_steam_bot_status
from betting.forms import TradeUrlForm
from betting.models import Deposit, CoinFlipGame, Announcement, UserProfile, SendRecord, GiveAway
from betting.serializers import DepositSerializer, AnnouncementSerializer, SteamerSerializer, GiveawaySerializer
from betting.utils import current_user, reformat_ret, get_maintenance, get_string_config_from_site_config
from betting.business.check_lack import check_lack

from social_auth.models import SteamUser
from django.conf import settings


_logger = logging.getLogger(__name__)


def get_announcement(anno_type):
    ret = None
    announ = Announcement.objects.filter(anno_type=anno_type, enable=True).order_by('num').first()
    if announ:
        ret = AnnouncementSerializer(announ).data
    return ret


def get_giveaway():
    ret = None
    give = GiveAway.objects.filter(enable=True).order_by('num').first()
    if give:
        ret = GiveawaySerializer(give).data
    return ret


def format_ranking_list(type='win', days=0):
    users = SteamUser.objects.filter(is_active=True)
    ranking_list = []
    for user in users:
        times, wpct, cost, income = getWins(steamer=user, days=days)
        info = {
            'user': SteamerSerializer(user).data,
            'income': income,
            'wpct': wpct
        }
        ranking_list.append(info)

    if type == 'win':
        ranking_list = [elem for elem in ranking_list if elem['income'] > 0]
        ranking_list.sort(key=lambda k: (k['income'], k['wpct']), reverse=True)

    if type == 'lose':
        ranking_list = [elem for elem in ranking_list if elem['income'] < 0]
        ranking_list.sort(key=lambda k: (k['income'], k['wpct']))

    length = len(ranking_list)
    if length > 10:
        ranking_list = ranking_list[0:10]
    elif length < 10:
        info_blank = {
            'user': {
                'name': u'未上榜'
            },
            'income': '',
            'wpct': ''
        }
        for i in range(10-length):
            ranking_list.append(info_blank)

    return ranking_list


class HomePageView(TemplateView):
    template_name = 'pages/home.html'

    def get_context_data(self, **kwargs):
        if self.request.user.is_anonymous():
            ref_code = self.request.GET.get('ref', None)
            if ref_code:
                self.request.session['ref_code'] = ref_code
        else:
            ref_code = self.request.session.get('ref_code', None)
            if ref_code:
                create_promotion(ref_code, self.request.user)
        return super(HomePageView, self).get_context_data(**kwargs)


home_page_view = HomePageView.as_view()


class SupportView(TemplateView):
    template_name = 'common/site/support.html'


support_view = SupportView.as_view()


class MaintenanceView(TemplateView):
    template_name = 'pages/maintenance.html'

maintenance_view = MaintenanceView.as_view()


class CoinFlipView(TemplateView):
    template_name = 'pages/coinflip.html'

    def get_context_data(self, **kwargs):
        context = super(CoinFlipView, self).get_context_data(**kwargs)
        user = current_user(self.request)
        context['banner'] = get_announcement(0)
        context['promotion'] = get_announcement(1)
        context['nbar'] = 'coinflip'
        context['ranks'] = get_ranks(GameType.Coinflip.value)
        return context

coinflip_view = CoinFlipView.as_view()


class JackpotView(TemplateView):
    template_name = 'pages/jackpot.html'

    def get_context_data(self, **kwargs):
        context = super(JackpotView, self).get_context_data(**kwargs)
        user = current_user(self.request)
        context['banner'] = get_announcement(0)
        context['promotion'] = get_announcement(1)
        context['nbar'] = 'jackpot'
        context['ranks'] = get_ranks(GameType.Jackpot.value)
        return context

jackpot_view = JackpotView.as_view()


class PlayFairView(TemplateView):
    template_name = 'pages/play_fair.html'

    def get_context_data(self, **kwargs):
        context = super(PlayFairView, self).get_context_data(**kwargs)
        param_str = kwargs.get('fairs', '')
        if param_str:
            params = param_str.split('-')
            if len(params) > 0:
                context['hash'] = params[0]
            if len(params) > 1:
                context['secret'] = params[1]
            if len(params) > 2:
                context['percent'] = params[2]
            if len(params) > 3:
                context['tickets'] = params[3]
        return context

provably_fair = PlayFairView.as_view()


class GetStartedView(TemplateView):
    template_name = 'common/site/get_started.html'

get_started_view = GetStartedView.as_view()


class TermsOfServiceView(TemplateView):
    template_name = 'common/site/terms_of_service.html'

terms_of_service = TermsOfServiceView.as_view()


class ProfileView(LoginRequiredMixin, SuccessMessageMixin, FormView):
    login_url = reverse_lazy('social:begin', args=('steam',))
    redirect_field_name = 'redirect_to'
    form_class = TradeUrlForm

    success_message = "Successfully modified your trade url."

    def get_success_url(self):
        return self.request.path

    def get_initial(self):
        resp = {}
        user = current_user(self.request)
        if user:
            resp['tradeUrl'] = user.tradeurl
        return resp

    def form_valid(self, form):
        user = current_user(self.request)
        if user:
            user.tradeurl = form.data['tradeUrl']
            user.save()
        return super(ProfileView, self).form_valid(form)


class TradeUrlView(ProfileView):
    template_name = 'pages/profile_detail/tradeUrl.html'

tradeUrl_view = TradeUrlView.as_view()


class PackageView(ProfileView):
    template_name = 'pages/profile_detail/package.html'

    def get_context_data(self, **kwargs):
        context = super(PackageView, self).get_context_data(**kwargs)
        last_order = ''
        security_code = ''
        user = current_user(self.request)
        if user and user.is_authenticated():
            record = SendRecord.objects.filter(
                steamer__steamid=user.steamid,
                status=TradeStatus.Initialed.value
            ).first()
            if record:
                last_order = record.trade_no or ''
                security_code = record.security_code
        context['last_order'] = last_order
        context['security_code'] = security_code
        return context
    
package_view = PackageView.as_view()


class TradeRecordView(ProfileView):
    template_name = 'pages/profile_detail/trade_record.html'

trade_record_view = TradeRecordView.as_view()


class DepositRecordView(ProfileView):
    template_name = 'pages/profile_detail/deposit_record.html'

deposit_record_view = DepositRecordView.as_view()


class ShopView(TemplateView):
    template_name = 'pages/profile_detail/shop.html'

    def get_context_data(self, **kwargs):
        context = super(ShopView, self).get_context_data(**kwargs)
        return context

shop_view = ShopView.as_view()


class JoinJackpotView(views.APIView):

    def create(self, request):
        # _logger.debug('create deposit')
        try:
            m = get_maintenance()
            if m:
                return reformat_ret(201, [], _('The site in on maintenance, please wait for a while.'))

            steamer = current_user(request)
            if steamer:
                code, result = join_jackpot_game(request.data, steamer)
                if code == 0:
                    return reformat_ret(0, {'uid': result.uid}, _l('join jackpot successfully'))
                else:
                    return reformat_ret(101, {}, result)
            return reformat_ret(0, {}, 'jackpot')
        except Exception as e:
            _logger.exception(e)
            return reformat_ret(500, {}, 'jackpot exception')

    def post(self, request, format=None):
        return self.create(request)

join_jackpot_view = JoinJackpotView.as_view()


class JoinCoinflipView(views.APIView):

    def create(self, request):
        try:
            m = get_maintenance()
            if m:
                return reformat_ret(201, [], _('The site in on maintenance, please wait for a while.'))

            steamer = current_user(request)
            if steamer:
                code, result = join_coinflip_game(request.data, steamer)
                if code == 0:
                    return reformat_ret(0, result, 'create coinflip successfully')
                elif code == 201:
                    return reformat_ret(201, {}, _l("Someone has joined the game."))
                else:
                    return reformat_ret(101, {}, result)
            return reformat_ret(0, {}, 'coinflip')
        except CoinFlipGame.DoesNotExist as e:
            _logger.error(e)
            return reformat_ret(301, {}, 'Invalid game')
        except Exception as e:
            _logger.exception(e)
            return reformat_ret(500, {}, 'coinflip exception')

    def post(self, request, format=None):
        return self.create(request)

join_coinflip_view = JoinCoinflipView.as_view()


class InventoryQueryView(views.APIView):

    def get_inventories(self, request):
        try:
            steamer = current_user(request)
            s_assetid = request.query_params.get('s_assetid', None)
            items = get_user_inventories(steamer.steamid, s_assetid, lang=request.LANGUAGE_CODE)
            if items is None:
                return reformat_ret(311, {}, _l("We get issues when query inventory from steam, try again later."))
            resp_data = {
                'inventory': items
            }
            return reformat_ret(0, resp_data, 'success')
        except Exception as e:
            _logger.exception(e)
            return reformat_ret(500, {}, 'exception')

    def get(self, request, format=None):
        return self.get_inventories(request)

    def post(self, request, format=None):
        return self.get_inventories(request)

inventory_query_view = InventoryQueryView.as_view()


class CoinflipHistoryQueryView(views.APIView):
    permission_classes = (AllowAny,)

    def query_history(self, request):
        try:
            ret = []
            user = current_user(request)
            game = request.data.get('game', 'coinflip')
            q_type = request.data.get('type', 'all')
            page = request.data.get('page', 1)
            page = 1 if page < 1 else page
            if q_type == 'all':
                if game == 'coinflip':
                    ret = get_all_coinflip_history(page=page)
            elif q_type == 'myself' and user:
                if game == 'coinflip':
                    ret = get_my_coinflip_history(user, page=page)
                elif game == 'jackpot':
                    ret = get_my_jackpot_history(user, page=page)
            return reformat_ret(0, ret, 'query history successfully')
        except Exception as e:
            _logger.exception(e)
            return reformat_ret(500, {}, 'exception')

    def get(self, request, format=None):
        return self.query_history(request)

    def post(self, request, format=None):
        return self.query_history(request)

cf_history_view = CoinflipHistoryQueryView.as_view()


class DepositStatusQueryView(views.APIView):

    def query_status(self, request):
        try:
            uid = request.query_params.get('uid', None)
            if uid:
                deposit = Deposit.objects.get(uid=uid)
                resp_data = {
                    'uid': deposit.uid,
                    'tradeNo': deposit.trade_no,
                    'securityCode': deposit.security_code,
                    'status': deposit.status
                }
                return reformat_ret(0, resp_data, 'success')
        except Exception as e:
            _logger.exception(e)
            return reformat_ret(500, {}, 'query deposit status exception')
        return reformat_ret(403, {}, "invalid params")

    def get(self, request, format=None):
        return self.query_status(request)

deposit_status_query_view = DepositStatusQueryView.as_view()


class WithdrawStatusView(views.APIView):

    def query_status(self, request):
        try:
            uid = request.query_params.get('uid', None)
            if uid:
                record = SendRecord.objects.get(uid=uid)
                resp_data = {
                    'uid': record.uid,
                    'trade_no': record.trade_no,
                    'security_code': record.security_code,
                    'status': record.status
                }
                return reformat_ret(0, resp_data, 'Successfully')
        except Exception as e:
            _logger.exception(e)
            return reformat_ret(500, {}, u'查询取回报价异常')
        return reformat_ret(103, {}, u"无效参数")

    def get(self, request, format=None):
        return self.query_status(request)

withdraw_status_view = WithdrawStatusView.as_view()


class CreateRandomHashView(views.APIView):

    def get(self, request, format=None):
        try:
            count = request.query_params.get('count', 10000)
            create_random_hash(count)
            return reformat_ret(0, {'count': count}, 'new hash success')
        except Exception as e:
            _logger.exception(e)
            return reformat_ret(500, {}, 'query deposit status exception')

create_random_hash_view = CreateRandomHashView.as_view()


class UpdateThemeView(views.APIView):

    def post(self, request, format=None):
        try:
            user = current_user(request)
            theme = request.data.get('theme', 'light')
            if user.is_authenticated():
                if hasattr(user, 'profile'):
                    profile = user.profile
                    profile.theme = theme
                    profile.save()
                else:
                    UserProfile.objects.create(steamer=user, theme=theme)
            return reformat_ret(0, {}, 'update theme success')
        except Exception as e:
            _logger.exception(e)
            return reformat_ret(500, {}, 'query deposit status exception')


update_theme_view = UpdateThemeView.as_view()


class QueryUserLack(views.APIView):

    def get(self, request, format=None):
        try:
            params = request.query_params
            botid = params.get('botid')
            appid = params.get('appid')
            contextid = params.get('contextid')
            exclude = params.get('exclude', None)
            steamid = params.get('steamid', None)
            details = params.get('details', False)
            remove = params.get('remove', False)
            body = check_lack(botid=botid, appid=appid, contextid=contextid, steamid=steamid, exclude=exclude, details=details, remove=remove)
            return reformat_ret(0, body, 'ok')
        except Exception as e:
            _logger.exception(e)
            return reformat_ret(500, {}, 'query deposit status exception')


query_user_lack_view = QueryUserLack.as_view()


class AffiliatePageView(TemplateView):
    template_name = 'pages/affiliate.html'

    def get_context_data(self, **kwargs):
        context = super(AffiliatePageView, self).get_context_data(**kwargs)
        user = current_user(self.request)
        ref_point = 0
        ref_count = 0
        if not user.is_anonymous():
            ref_point = user.ref_point
            ref_count = get_promotion_count(user)
        context['ref_point'] = ref_point
        context['ref_count'] = ref_count
        return context


affiliate_page_view = AffiliatePageView.as_view()
