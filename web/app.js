const $ = id => document.getElementById(id);
const form = $('order-form');
const sideName = side => side === 'SELL' ? '卖出' : '买入';
function refreshSide() {
  const sell = form.elements.side.value === 'SELL';
  $('price-label').textContent = sell ? '最低卖出价' : '最高买入价';
  $('size-label').textContent = sell ? '卖出份数' : '买入份数';
  $('estimate-label').textContent = sell ? '预计收入下限' : '预计支出上限';
  $('total-label').textContent = sell ? '收入下限 · 扣费前' : '支出上限 · 不含费用';
  $('estimate-help').textContent = sell ? '扣费前金额。实际卖出价格不会低于你的限价；你需要持有足够份额。' : '不含适用费用。实际买入价格不会高于你的限价。';
  $('preview-help').textContent = sell ? '请确认你持有对应结果的份额。预览有效期 2 分钟；GTC 卖单可能立即或部分成交，剩余部分继续挂单。' : '预览有效期 2 分钟。行情会变化；GTC 订单可能立即或部分成交。';
  $('send').textContent = sell ? '提交真实卖单' : '提交真实买单';
}
const money = value => new Intl.NumberFormat('zh-CN', {style:'currency',currency:'USD',maximumFractionDigits:4}).format(Number(value));
let current = null, busy = false, dirty = false, markets = [], accountConfigured = false;
async function api(path, body) {
  const response = await fetch(path, {method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':document.querySelector('meta[name=csrf-token]').content},body:JSON.stringify(body)});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || '请求失败，请检查后重试。');
  return data;
}
function loading(on, submitting=false) {
  busy=on;
  $('settings-button').disabled=on;
  $('check-account').disabled=on||!accountConfigured;
  $('clear-account').disabled=on||!accountConfigured;
  for (const el of form.elements) el.disabled=on;
  $('load-market').disabled=on;
  $('preview-button').textContent=on&&!submitting?'正在读取市场…':'预览订单 →';
  $('preview-button').classList.toggle('busy',on&&!submitting);
  $('open-confirm').disabled=on;
}
function invalidate() {
  current=null; dirty=true;
  refreshSide();
  $('preview').hidden=true; $('empty').hidden=false;
  $('form-error').hidden=true;
  const p=Number($('price').value),s=Number($('size').value);
  $('estimate').textContent=p>0&&p<1&&s>0?money(p*s):'—';
}
form.addEventListener('input',invalidate);
function showMarket() {
  const selected=markets.find(m=>m.slug===$('market-choice').value);
  if(!selected)return;
  $('market-question').textContent=selected.question;
  $('outcome-0').textContent=selected.outcomes[0];
  $('outcome-1').textContent=selected.outcomes[1];
  form.elements.selection.value='0';
  invalidate();
}
$('market-choice').addEventListener('change',showMarket);
$('market').addEventListener('input',()=>{markets=[];$('market-details').hidden=true;});
async function loadMarkets() {
  if(busy)return false;
  const market=$('market').value.trim();
  if(!market){$('market').reportValidity();return false;}
  $('form-error').hidden=true;loading(true);
  try {
    const result=await api('/api/markets',{market});
    markets=result.markets;
    const select=$('market-choice');select.replaceChildren();
    for(const item of markets){
      const option=document.createElement('option');
      option.value=item.slug;option.textContent=item.question+(item.available?'':'（暂不可下单）');
      option.disabled=!item.available;select.append(option);
    }
    const preferred=markets.find(m=>m.slug===result.selected&&m.available)||markets.find(m=>m.available);
    if(!preferred)throw new Error('这个赛事目前没有接受新订单的子市场。');
    select.value=preferred.slug;$('market-details').hidden=false;showMarket();
    return true;
  } catch(error) {
    markets=[];$('market-details').hidden=true;
    $('form-error').textContent=error.message;$('form-error').hidden=false;$('form-error').focus();
    return false;
  } finally {loading(false);}
}
$('load-market').addEventListener('click',loadMarkets);
form.addEventListener('submit',async e=>{
  e.preventDefault(); if(busy)return;
  if(!markets.length&&!(await loadMarkets()))return;
  const data=Object.fromEntries(new FormData(form));
  current=null; $('preview').hidden=true; $('empty').hidden=false;
  $('form-error').hidden=true; $('status').textContent='';loading(true);
  try {
    current=await api('/api/preview',data);
    $('question').textContent=current.question;
    $('preview-wallet').textContent=current.wallet || '尚未配置账户';
    $('result-side').textContent=current.outcome+' / '+sideName(current.side);
    $('result-order').textContent=money(current.price)+' / '+new Intl.NumberFormat('zh-CN').format(Number(current.size))+' 份';
    $('quotes').textContent=current.bid+' / '+current.ask;
    $('constraints').textContent=current.minimum+' / '+current.tick;
    $('total').textContent=money(current.amount);
    $('preview').hidden=false;$('empty').hidden=true;
  } catch(error) {
    $('form-error').textContent=error.message;$('form-error').hidden=false;$('form-error').focus();
  } finally {loading(false);if(current)$('open-confirm').focus();}
});
$('open-confirm').addEventListener('click',()=>{
  if(!current||busy)return;
  if(!accountConfigured){$('form-error').textContent='请先新建用户配置，再提交订单。';$('form-error').hidden=false;$('form-error').focus();return;}
  $('confirm-summary').textContent='账户 '+(current.wallet||'未配置')+'：'+current.question+' — '+sideName(current.side)+' '+current.size+' 份 '+current.outcome+'，每份'+(current.side==='SELL'?'最低 ':'最高 ')+money(current.price)+'，'+(current.side==='SELL'?'扣费前收入下限 ':'支出上限 ')+money(current.amount)+'（另计费用）。';
  $('confirm-dialog').showModal();$('back').focus();
});
$('back').addEventListener('click',()=>$('confirm-dialog').close());
$('send').addEventListener('click',async()=>{
  if(!current||busy)return;
  const id=current.id;current=null;dirty=false;
  $('confirm-dialog').close();loading(true,true);
  $('preview').hidden=true;$('empty').hidden=true;
  const status=$('status');status.className='';status.textContent='正在提交真实订单…';status.focus();
  try {
    const result=await api('/api/submit',{id});
    if(result.accepted){
      const labels={live:'挂单中',matched:'已撮合，请核对实际成交数量',delayed:'等待撮合'};
      status.className='success';
      status.textContent='订单已接受。'+(labels[result.status]||result.status)+'。订单编号：'+result.order_id+'。请在 Polymarket 核对挂单、成交与持仓。';
    } else {status.textContent=result.message;}
  } catch(error) {status.textContent=error.message||'提交状态未知，请先检查网页挂单和成交记录，勿重复提交。';}
  finally {loading(false,true);status.focus();}
});
refreshSide();
window.addEventListener('beforeunload',event=>{if(dirty||busy){event.preventDefault();event.returnValue='';}});

function showAccount(data) {
  accountConfigured=Boolean(data.configured);
  $('settings-button').textContent=accountConfigured?'新建／更换用户':'新建用户';
  $('account-wallet-display').textContent=accountConfigured?'当前账户：'+data.wallet:'当前没有用户配置';
  $('config-state').textContent=data.configuration||'未配置有效账户';
  $('region-state').textContent=data.region||'未检查';
  $('auth-state').textContent=data.authentication||'未检查';
  $('buying-state').textContent=data.buying||'未检查';
  $('trading-state').textContent=data.trading||'尚不能确认';
  $('check-account').disabled=busy||!accountConfigured;
  $('clear-account').disabled=busy||!accountConfigured;
}
async function checkStatus() {
  if(busy||!accountConfigured)return;
  loading(true);$('account-error').hidden=true;
  $('region-state').textContent='检查中…';
  $('auth-state').textContent='检查中…';
  $('buying-state').textContent='检查中…';
  $('trading-state').textContent='检查中…';
  try {showAccount(await api('/api/settings/check',{}));}
  catch(error){$('account-error').textContent=error.message;$('account-error').hidden=false;$('trading-state').textContent='检查失败，请重试';}
  finally{loading(false);}
}
api('/api/settings/status',{}).then(data=>{showAccount(data);if(data.configured)checkStatus();}).catch(()=>{$('account-wallet-display').textContent='配置状态读取失败，请刷新页面。';});
$('check-account').addEventListener('click',checkStatus);
$('clear-account').addEventListener('click',()=>{if(!busy&&accountConfigured)$('clear-dialog').showModal();});
$('clear-cancel').addEventListener('click',()=>$('clear-dialog').close());
$('clear-confirm').addEventListener('click',async()=>{
  if(busy)return;
  $('clear-confirm').disabled=true;loading(true);$('account-error').hidden=true;
  try{
    const result=await api('/api/settings/clear',{});
    showAccount(result);invalidate();dirty=false;$('status').textContent='';
    $('clear-dialog').close();
  }catch(error){$('account-error').textContent=error.message;$('account-error').hidden=false;$('clear-dialog').close();}
  finally{$('clear-confirm').disabled=false;loading(false);}
});
$('settings-button').addEventListener('click',()=>{
  if(busy)return;
  $('settings-form').reset();$('settings-error').hidden=true;
  $('settings-dialog').showModal();$('account-wallet').focus();
});
$('settings-cancel').addEventListener('click',()=>$('settings-dialog').close());
$('settings-dialog').addEventListener('close',()=>{$('settings-form').reset();});
$('settings-dialog').addEventListener('cancel',event=>{if(busy)event.preventDefault();});
$('settings-form').addEventListener('input',()=>{dirty=true;});
$('settings-form').addEventListener('submit',async event=>{
  event.preventDefault();if(busy)return;
  const data=Object.fromEntries(new FormData($('settings-form')));
  let saved=false;
  loading(true);$('settings-error').hidden=true;
  for(const el of $('settings-form').elements)el.disabled=true;
  $('settings-save').textContent='正在保存…';$('settings-save').classList.add('busy');
  try {
    const result=await api('/api/settings',data);
    invalidate();dirty=false;$('status').textContent='';
    showAccount(result);$('settings-dialog').close();saved=true;
  } catch(error) {
    $('settings-error').textContent=error.message;$('settings-error').hidden=false;$('settings-error').focus();
  } finally {
    data.private_key='';$('account-key').value='';
    for(const el of $('settings-form').elements)el.disabled=false;
    $('settings-save').textContent='保存新用户';$('settings-save').classList.remove('busy');
    loading(false);if(saved)checkStatus();else if(!$('settings-dialog').open)$('settings-button').focus();
  }
});
