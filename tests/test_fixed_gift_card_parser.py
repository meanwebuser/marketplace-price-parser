"""Fixed denominations need page evidence, never a catalog/default price."""
import pytest
import subprocess
from pathlib import Path

from analyzer.output import gift_card_offers_from_raw


def _fixed(**changes):
    listing = {
        "marketplace": "ggsel", "pid": "fixed-50",
        "url": "https://ggsel.net/catalog/product/fixed-50",
        "title": "Apple Gift Card USA $50",
        "descText": "Apple redemption code. Region USA. Denomination 50 USD.",
        "pageText": "Apple Gift Card USA $50\n4 200 ₽\nКупить",
        "initialPrices": [{"text": "4 200 ₽", "cls": "ProductBuyBlock_amount"}],
        "options": [], "skippedControls": [], "variantControlCount": 0,
        "buyButtonDisabled": False, "buyButtonText": "Купить",
    }
    listing.update(changes)
    return {"listings": [listing]}


def test_fixed_denomination_uses_browser_price_and_stock_without_subscription_fields():
    offer, = gift_card_offers_from_raw(_fixed())
    assert (offer["denomination"], offer["denomination_currency"], offer["region"]) == (50, "USD", "US")
    assert offer["price_rub"] == 4200
    assert offer["price_per_unit"] == 84
    assert offer["price_verified"] is True
    assert offer["available"] is True
    assert offer["control_kind"] == "fixed-denomination"
    assert "tier" not in offer and "duration" not in offer


@pytest.mark.parametrize("changes", [
    {"title": "Apple Gift Card USA $2-$100"},
    {"title": "Apple Gift Card USA 2–100 USD"},
    {"title": "Apple Gift Card USA $2 to 100"},
    {"title": "Apple Gift Card USA 2/3/4/50 USD"},
    {"title": "Apple Gift Card USA $50.125"},
    {"descText": "USA code $25 or $50"},
    {"descText": "USA code 50 EUR"},
    {"descText": "USA code $50 (USDT)"},
    {"descText": "USA or Turkey Apple code $50"},
    {"descText": "USA or Canada Apple code $50"},
    {"title": "Apple Gift Card", "descText": "Code 50 USD", "pageText": "50 USD"},
    {"title": "Apple Gift Card $50", "descText": "Contact us for a code", "pageText": "50 USD"},
    {"initialPrices": [{"text": "4 200 ₽", "cls": "catalog-card-price"}]},
    {"initialPrices": []},
    {"initialPrices": [{"text": "50 USD", "cls": "ProductBuyBlock_amount"}]},
    {"initialPrices": [{"text": "4200 ₽", "cls": "ProductBuyBlock_amount"},
                       {"text": "4300 ₽", "cls": "id_product_price"}]},
    {"options": [{"text": "$50", "clicked": False}]},
    {"skippedControls": [{"kind": "button", "text": "$50"}]},
    {"variantControlCount": 1},
    {"error": "capture failed"},
])
def test_fixed_denomination_rejects_unconfirmed_or_ambiguous_listing(changes):
    assert list(gift_card_offers_from_raw(_fixed(**changes))) == []


@pytest.mark.parametrize("disabled,text,expected", [
    (True, "Нет в наличии", False),
    (False, "Нет в наличии", False),
    (None, "Нет в наличии", False),
    (None, "Купить", None),
])
def test_fixed_denomination_stock_is_separate_from_verified_price(disabled, text, expected):
    offer, = gift_card_offers_from_raw(_fixed(buyButtonDisabled=disabled, buyButtonText=text))
    assert offer["available"] is expected
    assert offer["price_verified"] is True


def test_explicit_unavailable_buy_text_overrides_enabled_purchase_flag():
    listing = _fixed()["listings"][0]
    listing["options"] = [{
        "text": "$50", "clicked": True, "selectedAfter": True,
        "purchaseAvailable": True, "buyButtonText": "Нет в наличии",
        "prices": [{"text": "4 200 ₽", "cls": "ProductBuyBlock_amount"}],
    }]
    offer, = gift_card_offers_from_raw({"listings": [listing]})
    assert offer["available"] is False
    assert offer["availability_status"] == "out_of_stock"


def test_fixed_turkish_denomination_uses_try_only():
    offer, = gift_card_offers_from_raw(_fixed(
        title="Apple Gift Card Turkey 500 TRY", descText="Region Turkey; code 500 TL",
        pageText="Apple Turkey 500 ₺",), "TR")
    assert (offer["denomination"], offer["denomination_currency"], offer["region"]) == (500, "TRY", "TR")


def test_fixed_and_selected_suffix_dollar_denomination():
    raw = _fixed(title="Apple Gift Card USA 50$", descText="Region USA; Apple code", pageText="Купить")
    offer, = gift_card_offers_from_raw(raw)
    assert offer["denomination"] == 50
    raw["listings"][0]["options"] = [{
        "text": "50$ Долларов", "clicked": True, "selectedAfter": True,
        "prices": [{"text": "4200 ₽", "cls": "id_product_price"}],
    }]
    offer, = gift_card_offers_from_raw(raw)
    assert offer["denomination"] == 50


def test_capture_reads_product_buy_state_and_fails_closed_on_multiple_buy_buttons():
    """Execute the embedded DOM reader without loading Playwright or a browser."""
    script = r"""
const fs = require('fs'), vm = require('vm');
const src = fs.readFileSync(process.argv[1], 'utf8');
const start = src.indexOf('const PAGE_FN = `'), end = src.indexOf('\n`;\n', start);
const sandbox = {};
vm.runInNewContext(src.slice(start, end + 3) + '\nthis.source = PAGE_FN;', sandbox);
const read = new Function('document', sandbox.source + '\nreturn snapshotPurchaseState();');
function button(text, disabled) {
  return {innerText: text, disabled, getClientRects: () => [1],
    getAttribute: () => null, matches: () => false, closest: () => null};
}
let buttons = [button('Купить', true)];
const block = {querySelectorAll: () => buttons};
const doc = {querySelectorAll: s => s.includes('ProductBuyBlock') ? [block] : []};
let state = read(doc);
if (state.buyButtonDisabled !== true || state.buyButtonText !== 'Купить') throw Error(JSON.stringify(state));
buttons = [button('Нет в наличии', false)];
state = read(doc);
if (state.buyButtonText !== 'Нет в наличии') throw Error(JSON.stringify(state));
buttons = [button('Купить', false), button('Buy', false)];
state = read(doc);
if (state.buyButtonDisabled !== null || state.buyButtonText !== '') throw Error('ambiguous buy accepted');
buttons = [button('50 USD', false)];
state = read(doc);
if (state.buyButtonDisabled !== null) throw Error('variant interpreted as Buy');
state = read({querySelectorAll: () => []});
if (state.buyButtonDisabled !== null) throw Error('missing Buy interpreted as available');
const collect = new Function('document', sandbox.source + '\nreturn collectVariantControls();');
const texts = ['2$ (USD)', '3 USD', '50$ Долларов'];
const chips = texts.map(innerText => ({innerText, className: '', getAttribute: () => null,
  querySelector: () => null, matches: () => false}));
const giftDoc = {title: 'Apple iTunes Gift Card USA',
  querySelectorAll: s => s === 'button' ? chips : []};
state = collect(giftDoc);
if (JSON.stringify(state.controls.map(x => x.text)) !== JSON.stringify(texts)) throw Error('amount controls skipped');
giftDoc.title = 'MiniMax subscription';
if (collect(giftDoc).controls.length !== 0) throw Error('amount gate leaked to subscriptions');
"""
    subprocess.run(["node", "-e", script, str(Path(__file__).resolve().parents[1] / "click.py")],
                   check=True, capture_output=True, text=True, timeout=10)


def test_final_verifier_fixed_product_evidence_requires_exact_region_amount_and_no_controls():
    script = r"""
const fs = require('fs'), vm = require('vm');
const src = fs.readFileSync(process.argv[1], 'utf8');
const start = src.indexOf('function fixedProductEvidence(');
const end = src.indexOf('\nasync function verifyOne', start);
if (start < 0 || end < 0) throw Error('fixed verifier evidence function not found');
const sandbox = {};
vm.runInNewContext(src.slice(start, end) + '\nthis.check = fixedProductEvidence;', sandbox);
const offer = {region: 'US', denomination: 50, denominationCurrency: 'USD'};
const evidence = {title: 'Apple Gift Card USA $50', description: 'Digital code for USA account',
  variantControlCount: 0, amountControls: []};
if (!sandbox.check(offer, evidence).ok) throw Error('exact fixed product rejected');
if (sandbox.check(offer, {...evidence, title: 'Apple Gift Card Turkey $50'}).ok) throw Error('wrong region accepted');
if (sandbox.check(offer, {...evidence, description: 'USA or Canada; $50'}).ok) throw Error('mixed region accepted');
if (sandbox.check(offer, {...evidence, description: 'USA code, also available in EUR'}).ok) throw Error('foreign currency accepted');
if (sandbox.check(offer, {...evidence, title: 'Apple Gift Card USA $2-$100'}).ok) throw Error('range accepted as fixed amount');
if (sandbox.check(offer, {...evidence, title: 'Apple Gift Card USA $50 or $100'}).ok) throw Error('multiple amounts accepted');
if (sandbox.check(offer, {...evidence, amountControls: ['$50']}).ok) throw Error('selectable amount accepted as fixed');
if (sandbox.check(offer, {...evidence, amountControls: ['50$']}).ok) throw Error('suffix denomination control accepted as fixed');
if (sandbox.check(offer, {...evidence, variantControlCount: 1}).ok) throw Error('variant control accepted as fixed');
"""
    subprocess.run(["node", "-e", script, str(Path(__file__).resolve().parents[1] / "verify_winners.js")],
                   check=True, capture_output=True, text=True, timeout=10)
