from __future__ import annotations

import hashlib
import hmac
import json

from cms.db import MyceliaDBError, Node
from cms.modules.ecosystem.repository import EcosystemRepository
from cms.modules.webshop.repository import WebshopRepository
from cms.richtext import plain_text as richtext_plain


class FakeCrypto:
    def __init__(self) -> None:
        self.key = b"test-key"
    def encrypt_json(self, record_id: str, value: dict) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    def decrypt_json(self, record_id: str, token: str) -> dict:
        return json.loads(token)
    def blind_index(self, namespace: str, value: str) -> str:
        normalized = " ".join(value.casefold().split()).encode()
        return hmac.new(self.key, namespace.encode() + b"\0" + normalized, hashlib.sha256).hexdigest()


class FakeDB:
    def __init__(self) -> None:
        self.nodes: dict[str, dict[str, str]] = {}
    def list_node_ids(self, prefix: str = "") -> list[str]:
        return [node_id for node_id in self.nodes if node_id.startswith(prefix)]
    def get_node(self, node_id: str) -> Node:
        if node_id not in self.nodes:
            raise MyceliaDBError("ERR missing node")
        return Node(node_id, dict(self.nodes[node_id]))
    def set_property(self, node_id: str, key: str, value: str) -> None:
        self.nodes.setdefault(node_id, {})[key] = value
    def delete_node(self, node_id: str) -> str:
        if node_id not in self.nodes:
            raise MyceliaDBError("ERR missing node")
        del self.nodes[node_id]
        return f"OK ERASED {node_id}"


class FakeBackups:
    def __init__(self) -> None:
        self.checkpoints = 0
    def save_checkpoint(self) -> str:
        self.checkpoints += 1
        return "OK"
    def purge_historical_backups(self) -> int:
        return 0


def repos():
    db=FakeDB(); crypto=FakeCrypto(); backups=FakeBackups()
    shop=WebshopRepository(db,crypto,backups)
    eco=EcosystemRepository(db,crypto,backups,shop)
    return shop,eco,db


def user_shop(shop_repo, username="ralf", email="ralf@example.test"):
    user=shop_repo.register_user(username=username,email=email,display_name=username.title(),password="eine-sehr-lange-passphrase",privacy_ack=True, email_verified_proof=True)
    shop=shop_repo.save_shop(owner_id=user.id,name=f"{username} Shop",slug=f"{username}-shop",description="Shop",contact_email=email,payment_instructions="Test")
    return user,shop


def test_creator_forum_kb_community_roundtrip():
    ws,eco,_=repos(); user,shop=user_shop(ws)
    profile=eco.save_creator(user.id,"Ralf Creator","Bio","https://example.test")
    post=eco.save_creator_post(user.id,None,"Creator Post","creator-post","Inhalt","public","published")
    kb=eco.save_kb(user.id,None,"Wissen","wissen","Artikel","published",None)
    topic=eco.create_forum_topic(user.id,"Thema","Erster Beitrag")
    eco.add_forum_reply(topic.id,user.id,"Antwort")
    community=eco.create_community_post(user.id,"Hallo Community")
    eco.add_community_comment(community.id,user.id,"Kommentar")
    assert profile.user_id==user.id
    assert richtext_plain(eco.get_creator_post(post.id).body)=="Inhalt"
    assert eco.get_kb(kb.id).status=="published"
    assert len(eco.list_forum_replies(topic.id))==2
    assert len(eco.list_community_comments(community.id))==1


def test_forum_and_knowledge_overviews_include_visible_shop_content():
    ws,eco,_=repos(); first,first_shop=user_shop(ws,"overview1","overview1@example.test")
    second,second_shop=user_shop(ws,"overview2","overview2@example.test")
    global_topic=eco.create_forum_topic(first.id,"Globales Thema","Start")
    shop_topic=eco.create_forum_topic(second.id,"Shop-Thema","Start",second_shop.id)
    global_article=eco.save_kb(first.id,None,"Globales Wissen","globales-wissen","Text","published",None)
    shop_article=eco.save_kb(second.id,None,"Shop-Wissen","shop-wissen","Text","published",second_shop.id)

    topics=eco.list_forum_overview({first_shop.id,second_shop.id})
    articles=eco.list_kb_overview({first_shop.id,second_shop.id})

    assert {item.id for item in topics} == {global_topic.id,shop_topic.id}
    assert {item.id for item in articles} == {global_article.id,shop_article.id}


def test_membership_download_documents_and_ticket():
    ws,eco,_=repos(); owner,shop=user_shop(ws,"owner","owner@example.test")
    member=ws.register_user(username="member",email="member@example.test",display_name="Member",password="eine-sehr-lange-passphrase",privacy_ack=True, email_verified_proof=True)
    eco.join_shop(shop.id,member.id)
    assert eco.is_member(shop.id,member.id)
    asset=eco.save_download(owner.id,None,"Datei","datei","Beschreibung","test.txt","text/plain",b"secret","members",True)
    assert eco.get_download(asset.id).content_b64
    doc=eco.save_document(owner.id,None,"Dokument","dokument","Inhalt","members","published")
    assert eco.get_document(doc.id).visibility=="members"
    ticket=eco.create_ticket(shop.id,member.id,"Hilfe","Bitte helfen")
    eco.add_ticket_message(ticket.id,owner.id,"Antwort")
    assert len(eco.list_ticket_messages(ticket.id))==2


def test_marketplace_and_privacy_export_delete():
    ws,eco,db=repos(); owner,shop=user_shop(ws,"owner2","owner2@example.test")
    ws.save_product(owner_id=owner.id,product_id=None,name="Produkt",slug="produkt",description="Test",price_cents=100,currency="EUR",stock=2,product_type="digital",active=True)
    eco.save_creator(owner.id,"Owner Creator","Bio","")
    eco.save_document(owner.id,None,"Doc","doc","Content","public","published")
    assert len(eco.marketplace_products())==1
    export=eco.export_user_data(owner.id)
    assert export["creator_profile"]["user_id"]==owner.id
    assert len(export["documents"])==1
    deleted=eco.delete_user_data(owner.id)
    assert deleted>=2
    assert eco.get_creator(owner.id) is None


def test_download_visibility_is_fail_closed_and_ticket_closed_rejects_messages():
    ws,eco,_=repos(); owner,shop=user_shop(ws,"hardowner","hardowner@example.test")
    member=ws.register_user(username="hardmember",email="hardmember@example.test",display_name="Hard Member",password="eine-sehr-lange-passphrase",privacy_ack=True, email_verified_proof=True)
    try:
        eco.save_download(owner.id,None,"Privat","privat","Beschreibung","x.bin","text/html",b"<script>x</script>","private",True)
    except ValueError as exc:
        assert "Sichtbarkeit" in str(exc)
    else:
        raise AssertionError("Private/unknown Download visibility was accepted")
    ticket=eco.create_ticket(shop.id,member.id,"Hilfe","Start")
    eco.update_ticket_status(ticket.id, owner.id, "closed")
    try:
        eco.add_ticket_message(ticket.id, member.id, "soll nicht gehen")
    except ValueError as exc:
        assert "geschlossen" in str(exc)
    else:
        raise AssertionError("Closed ticket accepted a new message")


def test_locked_forum_topic_rejects_reply_in_repository():
    ws,eco,_=repos(); user,_=user_shop(ws,"lockuser","lockuser@example.test")
    topic=eco.create_forum_topic(user.id,"Lock Test","Start")
    topic.locked=True
    # Rewrite topic with the same encrypted repository path to simulate an owner/admin lock.
    eco._write(eco.FORUM_TOPIC_PREFIX, topic.id, "forum_topic", topic, {
        "author_idx": eco.crypto.blind_index("forum-topic-author", topic.author_id),
        "scope": "global",
    })
    try:
        eco.add_forum_reply(topic.id,user.id,"Antwort")
    except ValueError as exc:
        assert "geschlossen" in str(exc)
    else:
        raise AssertionError("Locked forum topic accepted a reply")
