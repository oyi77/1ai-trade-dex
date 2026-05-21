"""Shared EIP-712 typed data signing utility for EVM-based venues."""
from eth_account import Account
from eth_account.messages import encode_typed_data
from loguru import logger


def _strip_domain_type(types: dict) -> dict:
    """Remove EIP712Domain from types dict for encode_typed_data (3-arg form).

    eth_account >= 0.13 encode_typed_data() with the 3-argument form
    does NOT expect EIP712Domain in the types dict.
    """
    return {k: v for k, v in types.items() if k != "EIP712Domain"}


def sign_typed_data(private_key: str, domain: dict, types: dict, primary_type: str, message: dict) -> str:
    """Sign EIP-712 typed data and return hex signature.

    Args:
        private_key: Hex private key (with or without 0x prefix)
        domain: EIP-712 domain dict (name, version, chainId, verifyingContract)
        types: EIP-712 type definitions dict (may include EIP712Domain — it is stripped)
        primary_type: The primary type name (e.g., "Order", "Bet")
        message: The message data to sign

    Returns:
        Hex string signature (0x prefixed)
    """
    account = Account.from_key(private_key)

    message_types = _strip_domain_type(types)

    encoded = encode_typed_data(
        domain_data=domain,
        message_types=message_types,
        message_data=message,
    )
    signed = account.sign_message(encoded)

    logger.debug("EIP-712 signed: primary_type={}, signer={}", primary_type, account.address)
    return signed.signature.hex()


def recover_typed_data_signer(domain: dict, types: dict, primary_type: str, message: dict, signature: str) -> str:
    """Recover the signer address from an EIP-712 signature."""
    message_types = _strip_domain_type(types)

    encoded = encode_typed_data(
        domain_data=domain,
        message_types=message_types,
        message_data=message,
    )
    recovered = Account.recover_message(encoded, signature=signature)
    return recovered
