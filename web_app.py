"""Local-only order form. No orders are sent until the user confirms a preview."""
import asyncio
import os
import tempfile
import json
import re
import secrets
import threading
import time
from decimal import Decimal, InvalidOperation
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import httpx
from dotenv import dotenv_values
from polymarket import AsyncPublicClient, AsyncSecureClient
from polymarket.errors import RequestRejectedError

ROOT = Path(__file__).resolve().parent
PORT = 8765
ORIGIN = f'http://127.0.0.1:{PORT}'
CSRF = secrets.token_urlsafe(32)
PREVIEWS = {}
LOCK = threading.Lock()
REVISION = 0
ACTIVE_SUBMISSIONS = 0


class InputError(Exception):
    pass


def account_status():
    config = dotenv_values(ROOT / '.env')
    key = (config.get('POLYMARKET_PRIVATE_KEY') or '').strip()
    wallet = (config.get('POLYMARKET_WALLET_ADDRESS') or '').strip()
    configured = bool(re.fullmatch(r'0x[0-9a-fA-F]{64}', key) and
                      re.fullmatch(r'0x[0-9a-fA-F]{40}', wallet))
    if configured:
        from eth_account import Account
        try:
            Account.from_key(key)
        except Exception:
            configured = False
    return {'configured': configured, 'wallet': wallet if configured else '',
            'configuration': '已保存，格式正确' if configured else '未配置有效账户'}


def save_account(data):
    global REVISION
    key = str(data.get('private_key', '')).strip()
    wallet = str(data.get('wallet', '')).strip()
    if not re.fullmatch(r'0x[0-9a-fA-F]{64}', key):
        raise InputError('私钥需要 0x 加 64 位十六进制字符。请完整复制，不要补零。')
    if not re.fullmatch(r'0x[0-9a-fA-F]{40}', wallet):
        raise InputError('账户钱包地址需要 0x 加 40 位十六进制字符。')
    from eth_account import Account
    try:
        Account.from_key(key)
    except Exception:
        raise InputError('私钥数值无效，请重新复制。') from None
    with LOCK:
        if ACTIVE_SUBMISSIONS:
            raise InputError('有订单正在提交，请等待结果后再切换账户。')
        path = ROOT / '.env'
        fd, name = tempfile.mkstemp(prefix='.account-', dir=ROOT)
        try:
            with os.fdopen(fd, 'w') as file:
                file.write(f'POLYMARKET_PRIVATE_KEY={key}\nPOLYMARKET_WALLET_ADDRESS={wallet}\n')
            os.chmod(name, 0o600)
            os.replace(name, path)
        finally:
            if os.path.exists(name):
                os.unlink(name)
        REVISION += 1
        PREVIEWS.clear()
    return account_status()


def clear_account():
    global REVISION
    with LOCK:
        if ACTIVE_SUBMISSIONS:
            raise InputError('有订单正在提交，请等待结果后再清除账户。')
        (ROOT / '.env').unlink(missing_ok=True)
        REVISION += 1
        PREVIEWS.clear()
    return account_status()


def api_region_status(geo):
    """Interpret the frontend geoblock response using Polymarket's API rules."""
    blocked = geo.get('blocked')
    country = str(geo.get('country') or '').upper()
    if blocked is False:
        return 'allowed', 'API 地区检查通过'
    # These jurisdictions are frontend close-only; the API is not restricted.
    if blocked is True and country in {'IE', 'JP', 'MT', 'NL', 'KR'}:
        return 'allowed', f'{country}：网页端受限，API 允许'
    if blocked is True:
        return 'restricted', f'{country or "当前地区"}：API 下单受限'
    return 'unknown', '无法确认 API 地区状态'


async def check_account():
    with LOCK:
        revision = REVISION
        config = dotenv_values(ROOT / '.env')
    key = (config.get('POLYMARKET_PRIVATE_KEY') or '').strip()
    wallet = (config.get('POLYMARKET_WALLET_ADDRESS') or '').strip()
    if not account_status()['configured']:
        raise InputError('请先新建用户配置。')
    result = {'configured': True, 'wallet': wallet, 'configuration': '已保存，格式正确',
              'region': '未知', 'authentication': '未检查', 'buying': '未检查',
              'trading': '尚不能确认能否交易'}
    region_state = 'unknown'
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            response = await http.get('https://polymarket.com/api/geoblock')
            response.raise_for_status()
            region_state, result['region'] = api_region_status(response.json())
    except Exception:
        pass
    if region_state == 'restricted':
        result['trading'] = '当前地区不允许 API 下单'
    else:
        try:
            async with await AsyncSecureClient.create(private_key=key, wallet=wallet) as client:
                result['authentication'] = '通过'
                try:
                    funds = await client.get_balance_allowance(asset_type='COLLATERAL')
                    if funds.balance <= 0:
                        result['buying'] = '买入余额不足'
                    elif not any(value > 0 for value in funds.allowances.values()):
                        result['buying'] = '买入授权不足'
                    else:
                        result['buying'] = '余额和授权已读取'
                except Exception:
                    result['buying'] = '余额或授权暂时无法读取'
        except Exception:
            result['authentication'] = '未通过或连接失败'
        if region_state == 'allowed' and result['authentication'] == '通过':
            result['trading'] = 'API 具备基础条件；具体订单仍需核对余额、持仓和市场'
        elif result['authentication'] != '通过':
            result['trading'] = '目前不能确认账户可下单'
    with LOCK:
        if revision != REVISION:
            raise InputError('账户已更换，请重新检查状态。')
    return result


def numbers(data):
    try:
        p, s = Decimal(str(data['price'])), Decimal(str(data['size']))
        if not p.is_finite() or not s.is_finite() or not 0 < p < 1 or not 0 < s <= 1000000:
            raise ValueError()
        if s != s.quantize(Decimal('0.01')):
            raise ValueError()
        return p, s
    except (KeyError, InvalidOperation, ValueError):
        raise InputError('请输入 0 到 1 之间的价格，以及大于 0、最多两位小数的份数。') from None


def market_slug(value):
    target = str(value or '').strip()
    if not target or len(target) > 500:
        raise InputError('请填写 Polymarket 市场链接或标识。')
    if '://' in target:
        u = urlparse(target)
        if u.scheme != 'https' or u.hostname not in ('polymarket.com', 'www.polymarket.com'):
            raise InputError('请粘贴 https://polymarket.com 的市场链接。')
        parts = [part for part in u.path.split('/') if part]
        if not parts:
            raise InputError('请粘贴包含具体赛事或市场的链接。')
        target = parts[-1]
    if not re.fullmatch(r'[a-zA-Z0-9-]+', target):
        raise InputError('市场标识只能包含字母、数字和短横线。')
    return target


def market_info(market):
    return {'slug': market.slug, 'question': market.question,
            'outcomes': [market.outcomes.yes.label, market.outcomes.no.label],
            'available': market.state.closed is False and market.state.accepting_orders is True}


async def discover_markets(data):
    slug = market_slug(data.get('market'))
    async with AsyncPublicClient() as client:
        try:
            event = await client.get_event(slug=slug)
            markets = [market_info(m) for m in event.markets]
        except RequestRejectedError as exc:
            if exc.status != 404:
                raise
            try:
                markets = [market_info(await client.get_market(slug=slug))]
            except RequestRejectedError as market_exc:
                if market_exc.status == 404:
                    raise InputError('没有找到这个赛事或市场，请检查链接。') from None
                raise
    if not markets:
        raise InputError('这个赛事没有可选择的子市场。')
    markets.sort(key=lambda m: (m['slug'] != slug, not m['available'], m['question']))
    return {'markets': markets, 'selected': next((m['slug'] for m in markets if m['slug'] == slug),
                                                  next((m['slug'] for m in markets if m['available']), markets[0]['slug']))}


async def preview(data):
    with LOCK:
        revision = REVISION
    p, s = numbers(data)
    slug = market_slug(data.get('market_slug'))
    selection = str(data.get('selection', ''))
    side = data.get('side')
    if side not in ('BUY', 'SELL'):
        raise InputError('请选择买入或卖出。')
    if selection not in ('0', '1'):
        raise InputError('请选择市场结果。')
    async with AsyncPublicClient() as client:
        market = await client.get_market(slug=slug)
        if market.state.closed or market.state.accepting_orders is not True:
            raise InputError('这个市场目前不接受新订单，请选择其他市场。')
        selected = market.outcomes.yes if selection == '0' else market.outcomes.no
        outcome = selected.label
        token = selected.token_id
        if not token:
            raise InputError('未找到该结果的交易代币，请检查具体子市场。')
        book = await client.get_order_book(token_id=token)
    if book.tick_size is None or book.min_order_size is None:
        raise InputError('未取得市场交易限制，请稍后重新预览。')
    tick, minimum = Decimal(str(book.tick_size)), Decimal(str(book.min_order_size))
    if tick <= 0 or p % tick:
        raise InputError(f'此市场的价格步长是 {tick}，请调整价格。')
    if s < minimum:
        raise InputError(f'此市场至少交易 {minimum} 份，请调整数量。')
    result = dict(id=secrets.token_urlsafe(24), question=market.question, outcome=outcome, side=side,
                  token_id=str(token), price=str(p), size=str(s), amount=str(p*s),
                  bid=str(max((x.price for x in book.bids), default='暂无')),
                  ask=str(min((x.price for x in book.asks), default='暂无')),
                  minimum=str(minimum), tick=str(tick), created=time.time())
    with LOCK:
        if revision != REVISION:
            raise InputError("账户已切换，请重新预览订单。")
        result["wallet"] = account_status()["wallet"]
        for k in list(PREVIEWS):
            if time.time()-PREVIEWS[k]['created'] > 300:
                del PREVIEWS[k]
        PREVIEWS[result['id']] = result
    return result


def consume_preview(identifier):
    global ACTIVE_SUBMISSIONS
    with LOCK:
        item = PREVIEWS.pop(identifier, None)
        if not item or time.time()-item['created'] > 120:
            raise InputError('预览已过期或已提交。先核对现有订单，再重新预览。')
        ACTIVE_SUBMISSIONS += 1
        return item


async def submit(item):
    # Network restrictions are checked, never bypassed.
    async with httpx.AsyncClient(timeout=15) as http:
        geo_response = await http.get('https://polymarket.com/api/geoblock')
        geo_response.raise_for_status()
        geo = geo_response.json()
    if api_region_status(geo)[0] != 'allowed':
        raise InputError('当前地区未通过平台 API 下单检查，未提交订单。')
    config = dotenv_values(ROOT / '.env')
    key = (config.get('POLYMARKET_PRIVATE_KEY') or '').strip()
    wallet = (config.get('POLYMARKET_WALLET_ADDRESS') or '').strip()
    if not re.fullmatch(r'0x[0-9a-fA-F]{64}', key) or not re.fullmatch(r'0x[0-9a-fA-F]{40}', wallet):
        raise InputError('本机 .env 的私钥或钱包地址格式不正确，请在本机修正。')
    async with await AsyncSecureClient.create(private_key=key, wallet=wallet) as client:
        response = await client.place_limit_order(token_id=item['token_id'], side=item['side'],
                                                 price=item['price'], size=item['size'])
        if not response.ok:
            # Never expose upstream request details or secrets to the browser.
            return {'accepted': False, 'message': '平台拒绝了订单。请检查账户余额、交易授权和市场当前状态，然后重新预览。'}
        return {'accepted': True, 'order_id': str(response.order_id), 'status': str(response.status)}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, status, data, content_type='application/json; charset=utf-8'):
        body = data.encode() if isinstance(data, str) else json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.headers.get('Host') != f'127.0.0.1:{PORT}':
            return self.reply(403, {'error': '请使用本机地址打开页面。'})
        files = {'/': ('index.html', 'text/html; charset=utf-8'),
                 '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                 '/style.css': ('style.css', 'text/css; charset=utf-8')}
        if self.path not in files:
            return self.reply(404, {'error': '未找到页面。'})
        name, kind = files[self.path]
        self.reply(200, (ROOT/'web'/name).read_text().replace('__CSRF__', CSRF), kind)

    def do_POST(self):
        global ACTIVE_SUBMISSIONS
        if (self.headers.get('Host') != f'127.0.0.1:{PORT}' or
            self.headers.get('Origin') != ORIGIN or
            self.headers.get('X-CSRF-Token') != CSRF):
            return self.reply(403, {'error': '会话验证失败，请刷新页面。'})
        if self.path not in ('/api/markets', '/api/preview', '/api/submit', '/api/settings', '/api/settings/status', '/api/settings/clear', '/api/settings/check'):
            return self.reply(404, {'error': '未找到操作。'})
        submitting = self.path == '/api/submit'
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length < 4096:
                raise InputError('请求格式不正确。')
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise InputError('请求格式不正确。')
            if submitting:
                item = consume_preview(str(data.get('id', '')))
                try:
                    value = asyncio.run(asyncio.wait_for(submit(item), 50))
                finally:
                    with LOCK:
                        ACTIVE_SUBMISSIONS -= 1
            elif self.path == '/api/settings':
                value = save_account(data)
            elif self.path == '/api/settings/status':
                value = account_status()
            elif self.path == '/api/settings/clear':
                value = clear_account()
            elif self.path == '/api/settings/check':
                value = asyncio.run(asyncio.wait_for(check_account(), 35))
            elif self.path == '/api/markets':
                value = asyncio.run(asyncio.wait_for(discover_markets(data), 35))
            else:
                value = asyncio.run(asyncio.wait_for(preview(data), 35))
            self.reply(200, value)
        except InputError as exc:
            self.reply(400, {'error': str(exc)})
        except Exception:
            message = ('提交未能确认，订单可能已被接受。请先在 Polymarket 核对挂单与成交，勿直接重试。'
                       if submitting else ('配置操作失败，请检查文件权限或刷新页面后重试。' if self.path.startswith('/api/settings') else '暂时无法读取市场。请检查网络和具体子市场链接，再重试。'))
            self.reply(502, {'error': message})


if __name__ == '__main__':
    import sys
    import webbrowser
    try:
        server = ThreadingHTTPServer(('127.0.0.1', PORT), Handler)
    except OSError as exc:
        import errno
        if exc.errno != errno.EADDRINUSE:
            raise
        try:
            with httpx.Client(trust_env=False, timeout=3) as local:
                page = local.get(ORIGIN + '/')
            is_our_app = (page.status_code == 200 and
                          '<title>Polymarket · 下单台</title>' in page.text and
                          'id="order-form"' in page.text)
        except Exception:
            is_our_app = False
        if is_our_app:
            print('下单页面已在运行，直接打开已有页面。', flush=True)
            if '--open' in sys.argv:
                webbrowser.open(ORIGIN)
            sys.exit(0)
        print(f'端口 {PORT} 被其他程序占用，未停止任何程序。请检查后再启动。', flush=True)
        sys.exit(1)
    if '--open' in sys.argv:
        threading.Timer(0.5, lambda: webbrowser.open(ORIGIN)).start()
    print(f'本地下单页面：{ORIGIN}  （Ctrl+C 停止）', flush=True)
    server.serve_forever()
