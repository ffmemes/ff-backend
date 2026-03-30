from telegram import (
    Bot,
    LabeledPrice,
    Update,
)
from telegram.ext import (
    CallbackContext,
)

from src.tgbot.constants import UserType
from src.tgbot.handlers.treasury.payments import mint_tokens
from src.tgbot.logs import log
from src.tgbot.user_info import get_user_info

PURCHASE_TOKEN_CALLBACK_DATA_PATTERN = "pu_{tokens_to_buy}"
PURCHASE_TOKEN_CALLBACK_DATA_REGEXP = "^pu_"

STARS_TO_TOKEN_EXCHANGE_RATE: int = 1  # >= 1


async def handle_new_token_purchase_request_callback(
    update: Update,
    context: CallbackContext,
):
    data = update.callback_query.data
    raw = data.split("_")[1] if "_" in data else ""
    if not raw.isdigit():
        await update.callback_query.answer()
        return
    tokens_to_buy = int(raw)

    return await send_invoice_buying_coins_for_stars(
        context.bot,
        update.effective_user.id,
        tokens_to_buy,
    )


async def send_invoice_buying_coins_for_stars(
    bot: Bot,
    user_id: int,
    tokens_to_buy: int,
):
    price_in_stars = int(tokens_to_buy * STARS_TO_TOKEN_EXCHANGE_RATE)

    title = f"Buy {tokens_to_buy} 🍔"
    description = "To use in bot or to support the project. No refunds."
    payload = f"buying:{tokens_to_buy}:forStars:{price_in_stars}"
    labelled_price = LabeledPrice(f"{tokens_to_buy} 🍔", price_in_stars)

    await bot.send_invoice(
        chat_id=user_id,
        title=title,
        description=description,
        payload=payload,
        prices=[labelled_price],
        provider_token="",  # stars
        currency="XTR",  # Telegram Stars (XTR),
        # start_parameter=PURCHASE_TOKEN_CALLBACK_DATA_PATTERN.format(
        #     tokens_to_buy=tokens_to_buy
        # ),
    )


async def precheckout_callback(update: Update, context: CallbackContext):
    # user is paying
    # this is for checks before finalizing a payment form our side

    query = update.pre_checkout_query
    await query.answer(ok=True)

    # if query.invoice_payload != "Custom-Payload":
    #     await query.answer(ok=False, error_message="Что-то пошло не так...")
    # else:
    #     await query.answer(ok=True)


async def successful_payment_callback(update: Update, context: CallbackContext):
    # if we have more things to buy, don't forget to handle them separately.

    payment = update.message.successful_payment
    telegram_payment_charge_id = payment.telegram_payment_charge_id
    payload = payment.invoice_payload

    tokens_bought = int(payload.split(":")[1])

    balance = await mint_tokens(
        user_id=update.effective_user.id,
        amount=tokens_bought,
        external_id=telegram_payment_charge_id,
    )

    await update.message.reply_text(
        f"🎁 Payment successful! new /balance: {balance} 🍔",
    )

    await log(f"💰💰💰 user {update.effective_user.name} paid: {payment.to_json()}")

    # await update.message.reply_text(
    #     f"Платеж успешно выполнен! Ваш ID: {telegram_payment_charge_id}",
    #     reply_markup=reply_markup,
    # )


async def refund_command(update: Update, context: CallbackContext):
    _, payment_id = update.message.text.split(" ", 1)

    user = await get_user_info(update.effective_user.id)
    if user["type"] != UserType.ADMIN:
        return

    # TODO:
    # 1. find tx with payment_id
    # 2. get back the number of issued tokens
    # 3. if user doesn't have it anymore - decline

    res: bool = await context.bot.refund_star_payment(
        user_id=update.effective_user.id,
        telegram_payment_charge_id=payment_id,
    )

    await update.message.reply_text(str(res))
