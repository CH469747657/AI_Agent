"""企业微信消息加解密

参考: wechatpy (4.3k⭐) 的加解密实现
企微回调消息使用 AES-CBC-256 加密，需实现 WXBizMsgCrypt
"""

import base64
import hashlib
import socket
import struct
import time
import xml.etree.ElementTree as ET
from typing import Optional

from Crypto.Cipher import AES


class WeComCrypto:
    """企业微信消息加解密工具

    参考: wechatpy.enterprise.crypto.WeChatCrypto
    """

    def __init__(self, token: str, encoding_aes_key: str, corp_id: str):
        self.token = token
        self.corp_id = corp_id
        self.aes_key = base64.b64decode(encoding_aes_key + "=")

    def verify_signature(self, msg_signature: str, timestamp: str, nonce: str, encrypt: str = None) -> bool:
        """验证消息签名"""
        sort_list = sorted([self.token, timestamp, nonce, encrypt or ""])
        sha1 = hashlib.sha1("".join(sort_list).encode()).hexdigest()
        return sha1 == msg_signature

    def decrypt(self, encrypted: str) -> str:
        """解密消息"""
        cipher = AES.new(self.aes_key, AES.MODE_CBC, self.aes_key[:16])
        decrypted = cipher.decrypt(base64.b64decode(encrypted))

        # 去除 PKCS7 填充
        pad_len = decrypted[-1]
        content = decrypted[:-pad_len]

        # 解析: 16字节随机串 + 4字节消息长度 + 消息内容 + CorpID
        xml_len = socket.ntohl(struct.unpack("I", content[16:20])[0])
        xml_content = content[20:20 + xml_len].decode("utf-8")
        from_corp_id = content[20 + xml_len:].decode("utf-8")

        if from_corp_id != self.corp_id:
            raise ValueError(f"CorpID mismatch: expected {self.corp_id}, got {from_corp_id}")

        return xml_content

    def encrypt(self, reply_msg: str) -> str:
        """加密回复消息"""
        msg = reply_msg.encode("utf-8")
        # 16字节随机串 + 4字节消息长度 + 消息内容 + CorpID
        random_bytes = "0123456789abcdef".encode()
        msg_len = struct.pack("I", socket.htonl(len(msg)))
        content = random_bytes + msg_len + msg + self.corp_id.encode()

        # PKCS7 填充
        pad_len = 32 - (len(content) % 32)
        content += bytes([pad_len]) * pad_len

        cipher = AES.new(self.aes_key, AES.MODE_CBC, self.aes_key[:16])
        encrypted = cipher.encrypt(content)
        return base64.b64encode(encrypted).decode()

    def generate_signature(self, timestamp: str, nonce: str, encrypted: str) -> str:
        """生成签名"""
        sort_list = sorted([self.token, timestamp, nonce, encrypted])
        return hashlib.sha1("".join(sort_list).encode()).hexdigest()

    def wrap_reply(self, reply_msg: str, timestamp: str = None, nonce: str = None) -> str:
        """包装加密回复消息为 XML 格式"""
        timestamp = timestamp or str(int(time.time()))
        nonce = nonce or "1234567890123456"
        encrypted = self.encrypt(reply_msg)
        signature = self.generate_signature(timestamp, nonce, encrypted)

        return f"""<xml>
<Encrypt><![CDATA[{encrypted}]]></Encrypt>
<MsgSignature><![CDATA[{signature}]]></MsgSignature>
<TimeStamp>{timestamp}</TimeStamp>
<Nonce><![CDATA[{nonce}]]></Nonce>
</xml>"""

    def decrypt_message(self, post_data: bytes, msg_signature: str, timestamp: str, nonce: str) -> dict:
        """解密企微回调消息，返回解析后的 dict"""
        xml_tree = ET.fromstring(post_data)
        encrypt = xml_tree.find("Encrypt").text

        if not self.verify_signature(msg_signature, timestamp, nonce, encrypt):
            raise ValueError("Signature verification failed")

        decrypted_xml = self.decrypt(encrypt)
        msg_tree = ET.fromstring(decrypted_xml)

        msg_dict = {}
        for child in msg_tree:
            msg_dict[child.tag] = child.text
        return msg_dict
