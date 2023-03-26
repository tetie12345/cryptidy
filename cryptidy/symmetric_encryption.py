#! /usr/bin/env python
#  -*- coding: utf-8 -*-
#
# This file is part of cryptidy module

"""
AES-256 symmetric encryption routines based on pycryptodomex / pycryptodome
This library may encrypt / decrypt strings, bytes or python objects that support pickling


Versioning semantics:
    Major version: backward compatibility breaking changes
    Minor version: New functionality
    Patch version: Backwards compatible bug fixes

"""

__intname__ = "cryptidy.symmetric_encryption"
__author__ = "Orsiris de Jong"
__copyright__ = "Copyright (C) 2018-2021 Orsiris de Jong"
__licence__ = "BSD 3 Clause"
__version__ = "1.1.1"
__build__ = "2023013101"


import pickle
import sys
from base64 import b64encode, b64decode
from binascii import Error as binascii_Error
from datetime import datetime
from logging import getLogger

if sys.version_info[0] < 3 or (sys.version_info[0] == 3 and sys.version_info[1] < 4):
    import time

    def timestamp_get():
        """
        Get UTC timestamp
        """
        return time.mktime(datetime.utcnow().timetuple())

else:

    def timestamp_get():
        """
        Get UTC timestamp
        """
        return datetime.utcnow().timestamp()


# Try to import as absolute when used as module, import as relative for autotests
try:
    from cryptidy.padding import pad, unpad
except ImportError:
    from .padding import pad, unpad
# noqaF401: generate_key is not used here, but should be available from the pacakge, disabling flake8 check
try:
    # pylint: disable=W0611,unused-import
    from cryptidy.aes_encryption import (
        aes_encrypt,
        aes_decrypt,
        generate_key,
        generate_random_string,
    )  # noqa: F401
except ImportError:
    from .aes_encryption import (
        aes_encrypt,
        aes_decrypt,
        generate_key,
        generate_random_string,
    )  # noqa: F401
# Python 2.7 compat fixes (missing typing and FileNotFoundError)
try:
    from typing import Any, Union, Tuple
except ImportError:
    pass

logger = getLogger(__name__)


def verify_key(aes_key):
    # type: (bytes) -> None
    """
    Simple key length and type verification to make decryption debugging easier
    """

    if not len(aes_key) in [16, 24, 32]:
        raise TypeError(
            "Wrong encryption key provided. Allowed key sizes are 16, 24 or 32 bytes."
        )
    try:
        if "BEGIN" in aes_key.decode("utf-8", errors="backslashreplace"):
            raise TypeError(
                "Wrong encryption key provided. This looks like an RSA key."
            )
    except (UnicodeDecodeError, TypeError):
        # On earlier Python versions, keys cannot be decoded
        pass
    if not isinstance(aes_key, bytes):
        raise TypeError("Wrong encryption key provided. Key type should be binary.")


def encrypt_message_hf(
    msg, key, header=b"", footer=b"", random_header_len=0, random_footer_len=0
):
    # type: (Any, bytes, Union[str, bytes], Union[str, bytes], int, int) -> bytes
    """
    Simple wrapper for encrypt_message that adds  a given (or random) header and footer
    This function solely exists for compat reasons
    When a header/footer is added, it serves for message identification (eg like rsa key header/footers)
    When random bytes are requested, it serves to additional scramble data
    """
    if header and isinstance(header, str):
        header = header.encode("utf-8")
    if random_header_len > 0:
        header += generate_random_string(random_header_len).encode("utf-8")
    if footer and isinstance(footer, str):
        footer = footer.encode("utf-8")
    if random_footer_len > 0:
        footer += generate_random_string(random_footer_len).encode("utf-8")
    enc_msg = encrypt_message(msg, key)
    return header + enc_msg + footer


def encrypt_message(msg, aes_key):
    # type: (Any, bytes) -> bytes
    """
    Simple base64 wrapper for aes_encrypt_message
    """
    verify_key(aes_key)
    return b64encode(aes_encrypt_message(msg, aes_key))


def aes_encrypt_message(msg, aes_key):
    # type: (Any, bytes) -> bytes
    """
    AES encrypt a python object / bytes / string and add an encryption timestamp

    :param msg: original data, can be a python object, bytes, str or else
    :param aes_key: aes encryption key
    :return: (bytes): encrypted data
    """

    try:
        try:
            # Always try to pickle whatever we receive
            nonce, tag, ciphertext = aes_encrypt(pickle.dumps(msg), aes_key)
        except (TypeError, pickle.PicklingError, OverflowError):
            # Allow a fallback solution when object is not pickable
            # msg accepts bytes or text
            if isinstance(msg, bytes):
                nonce, tag, ciphertext = aes_encrypt(msg, aes_key)
            elif isinstance(msg, str):
                nonce, tag, ciphertext = aes_encrypt(msg.encode("utf-8"), aes_key)
            else:
                raise ValueError("Invalid type of data given for AES encryption.")

        timestamp = pad(str(timestamp_get())).encode("utf-8")
        return nonce + tag + timestamp + ciphertext
    except Exception as exc:  # pylint: disable=W0703,broad-except
        raise ValueError("Cannot AES encrypt data: %s." % exc)


def decrypt_message_hf(
    msg, key, header=None, footer=None, random_header_len=0, random_footer_len=0
):
    # type: (Union[bytes, str], bytes, Union[str, bytes], Union[str, bytes], int, int) -> Tuple[datetime, Any]
    """
    Simple wrapper for decrypt_message that adds random header and footer chars
    This function solely exists for compat reasons
    """
    # Remove header and footer if set
    if header:
        msg = msg[len(header) :]
    if footer:
        msg = msg[: -len(footer)]

    if random_footer_len > 0:
        return decrypt_message(msg[random_header_len:][:-random_footer_len], key)
    else:
        return decrypt_message(msg[random_header_len:], key)


def decrypt_message(msg, aes_key):
    # type: (Union[bytes, str], bytes) -> Tuple[datetime, Any]
    """
    Simple base64 wrapper for aes_decrypt_message that adds optional headers and footers for message identification
    """
    verify_key(aes_key)
    try:
        decoded_msg = b64decode(msg)
    except (TypeError, binascii_Error):
        raise TypeError("decrypt_message accepts b64 encoded byte objects")
    return aes_decrypt_message(decoded_msg, aes_key)


def aes_decrypt_message(msg, aes_key):
    # type: (bytes, bytes) -> Tuple[datetime, Any]
    """
    AES decrypt a python object / bytes / string and check the encryption timestamp

    :param msg: original aes encrypted data
    :param aes_key: aes encryption key
    :return: original data
    """
    nonce, tag, timestamp, ciphertext = (msg[0:16], msg[16:32], msg[32:64], msg[64:])

    try:
        source_timestamp = float(unpad(timestamp.decode("utf-8")))
        timestamp_now = timestamp_get()
        if source_timestamp > timestamp_now:
            print("*** WARNING *** Encrypted data timestamp is in future\n")
        if source_timestamp < timestamp_now - 86400 * 365:
            print(
                "*** WARNING *** Encrypted data timestamp is older than one year. If the source"
                "computer clock is not set, it may encounter various certificate error issues.\n"
            )
        source_timestamp = datetime.fromtimestamp(source_timestamp)
    except (
        TypeError,
        AttributeError,
        UnicodeDecodeError,
        ValueError,
        IndexError,
    ):
        raise ValueError("Encryption timestamp is bogus")

    try:
        data = aes_decrypt(aes_key, nonce, tag, ciphertext)
        aes_key = None  # Wipe from memory as soon as possible
        try:
            data = pickle.loads(data)
        # May happen on unpickled encrypted data when pickling failed on encryption and fallback was used
        # ModuleNotFoundError may happen if we unpickle a class which was not loaded
        except (pickle.UnpicklingError, TypeError, OverflowError, KeyError):
            pass
        except ModuleNotFoundError as exc:
            logger.error(
                "Cannot unpickle an object. If you're decrypting a class, it needs to be loaded: {}".format(
                    exc
                )
            )
        # Try to catch any other pickle exception not listed above
        except Exception as exc:  # pylint: disable=W0703,broad-except
            logger.error("cryptidy unpickle error: {0}. Is data pickled ?".format(exc))
            logger.info("Trace:", exc_info=True)
        return source_timestamp, data
    except Exception as exc:  # pylint: disable=W0703,broad-except
        raise ValueError("Cannot decrypt AES data: %s" % exc) from None
