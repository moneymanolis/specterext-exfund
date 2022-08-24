import logging
from flask import redirect, render_template, request, url_for, flash
from flask import current_app as app
from flask_login import login_required

from cryptoadvance.specter.specter import Specter
from cryptoadvance.specter.services.controller import user_secret_decrypted_required
from cryptoadvance.specter.user import User
from cryptoadvance.specter.wallet import Wallet
from cryptoadvance.specter.commands.psbt_creator import PsbtCreator
from embit.liquid.networks import get_network
from .service import ExfundService
from .util import parse_csv

logger = logging.getLogger(__name__)

exfund_endpoint = ExfundService.blueprint


def ext() -> ExfundService:
    """convenience for getting the extension-object"""
    return app.specter.ext["exfund"]


def specter() -> Specter:
    """convenience for getting the specter-object"""
    return app.specter


@exfund_endpoint.route("/", methods=["GET", "POST"])
@login_required
def index():
    user = specter().user_manager.get_user()
    show_menu = ExfundService.id in user.services
    wallet_names = sorted(user.wallet_manager.wallets_names)
    if len(wallet_names) == 0:
        flash("You need a wallet to use the exfund extension.", "error")
        return redirect(url_for("wallets_endpoint.new_wallet_type"))
    wallets = [user.wallet_manager.wallets[name] for name in wallet_names]
    rawcsv = ""
    try:
        if request.method == "POST":
            action = request.form["action"]
            if action == "settings":
                show_menu = request.form.get("show_menu")
                if show_menu:
                    user.add_service(ExfundService.id)
                else:
                    user.remove_service(ExfundService.id)
            elif action == "parse":
                rawcsv = request.form.get("rawcsv", "")
                addresses, chain, invalid_lines = parse_csv(rawcsv)
                expected_net = get_network(specter().chain)
                net = get_network(chain)
                if net != expected_net:
                    raise ValueError(
                        f"Invalid chain: {chain}, expected: {specter().chain}"
                    )
                if invalid_lines:
                    flash(f"{len(invalid_lines)} lines couldn't be parsed")
                assets = set().union(*[wallet.balance.get("assets",{}).keys() for wallet in wallets])
                assets = [specter().default_asset]+list(assets)
                return render_template(
                    "exfund/table.jinja",
                    wallets=wallets,
                    addresses=addresses,
                    is_liquid=specter().is_liquid,
                    assets=assets,
                )
            elif action == "createpsbt":
                wallet_alias = request.form.get("source_wallet")
                wallet = user.wallet_manager.get_by_alias(wallet_alias)
                addresses = request.form.getlist("addresses[]")
                labels = request.form.getlist("labels[]")
                amounts = request.form.getlist("amounts[]")
                if specter().is_liquid:
                    assets = request.form.getlist("assets[]")
                    scales = [1e-8 if a.endswith("-sat") else 1 for a in assets]
                    # remove -sat part
                    assets = [a.split("-")[0] for a in assets]
                else:
                    assets = ["btc" for a in addresses]
                    scales = [1e-8 if u == "sat" else 1 for u in request.form.getlist("units[]")]
                obj = {
                    "recipients": [
                        {
                            "address": address,
                            "amount": round(float(amount)*scale, 8), # convert sat to btc
                            "unit": asset,
                            "label": label
                        }
                        for address, amount, scale, asset, label
                        in zip(addresses, amounts, scales, assets, labels)
                    ],
                    "rbf_tx_id": "",
                    "fee_rate": request.form.get("fee_rate", "1"),
                    "rbf": request.form.get("rbf", True),
                }
                psbt_creator = PsbtCreator(specter(), wallet, "json", request_json=obj)
                psbt = psbt_creator.create_psbt(wallet)
                return render_template(
                    "wallet/send/sign/wallet_send_sign_psbt.jinja",
                    psbt=psbt,
                    labels=labels,
                    wallet_alias=wallet_alias,
                    wallet=wallet,
                    specter=specter(),
                    rand=0,
                )
            else:
                flash(f"Wrong action {action}", "error")
    except Exception as e:
        logger.exception(e)
        flash(f"Server error: {e}", "error")
    return render_template(
        "exfund/index.jinja",
        wallets=wallets,
        show_menu=show_menu,
        rawcsv=rawcsv,
    )
