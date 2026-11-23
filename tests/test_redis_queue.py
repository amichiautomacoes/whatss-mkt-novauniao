from datetime import datetime, timedelta, timezone
from uuid import UUID

import fakeredis
import pytest

from app.queue import redis_queue


@pytest.fixture
def queue(monkeypatch):
    client = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(redis_queue.Redis, "from_url", lambda *args, **kwargs: client)
    return redis_queue.RedisMessageQueue()


def pending_row(history_id=100):
    return {
        "history_id": history_id, "source_id": 10, "campaign_id": 1,
        "lead_key": UUID("b9000000-0000-0000-0000-000000000001"),
        "phone": "5531999999999", "message": "Olá Ana", "attempts": 0,
        "scheduled_at": datetime.now(timezone.utc) - timedelta(seconds=1),
    }


def test_queue_round_trip_supports_uuid_and_durable_history(queue):
    row = pending_row()
    assert queue.enqueue_many([row]) == 1
    messages = queue.list_pending(limit=1)
    assert len(messages) == 1
    assert messages[0]["history_id"] == 100
    assert messages[0]["lead_key"] == str(row["lead_key"])
    assert messages[0]["source_id"] == 10


def test_duplicate_enqueue_does_not_reset_an_inflight_message(queue):
    row = pending_row()
    queue.enqueue_many([row])
    message = queue.list_pending(limit=1)[0]
    queue.record_provider_response(message["id"], {"key": {"id": "provider-1"}}, datetime.now(timezone.utc))
    assert queue.enqueue_many([row]) == 0
    payload = queue.client.hgetall(queue._message_key(message["id"]))
    assert payload["status"] == "processing"
    assert "provider-1" in payload["provider_response"]
    assert queue.list_pending(limit=1) == []


def test_expired_processing_preserves_provider_proof_for_reconciliation(queue):
    queue.enqueue_many([pending_row()])
    message = queue.list_pending(limit=1)[0]
    queue.record_provider_response(message["id"], {"key": {"id": "provider-1"}}, datetime.now(timezone.utc))
    queue.client.zadd(queue.processing_key, {message["id"]: 0})
    recovered = queue.list_pending(limit=1)[0]
    assert recovered["provider_response"] == {"key": {"id": "provider-1"}}
    assert recovered["accepted_at"] is not None


def test_messages_are_claimed_once_and_respect_scheduled_time(queue):
    future = pending_row(101)
    future["scheduled_at"] = datetime.now(timezone.utc) + timedelta(hours=1)
    queue.enqueue_many([pending_row(), future])
    assert [row["history_id"] for row in queue.list_pending(limit=10)] == [100]
    assert queue.list_pending(limit=10) == []


def test_retries_keep_attempts_and_eventually_stop(queue):
    queue.enqueue_many([pending_row()])
    message_id = queue.list_pending(limit=1)[0]["id"]
    assert queue.mark_failed(message_id, "Rejected") is True
    assert queue.list_pending(limit=1) == []
    for expected_attempt in (1, 2):
        queue.client.zadd(queue.scheduled_key, {message_id: 0})
        message = queue.list_pending(limit=1)[0]
        assert message["attempts"] == expected_attempt
        assert queue.mark_failed(message_id, "Rejected") is (expected_attempt < 2)
    assert queue.client.zscore(queue.failed_key, message_id) is not None
    assert queue.list_pending(limit=1) == []


def test_legacy_queue_entries_are_isolated(queue):
    queue.client.zadd("whatsapp_test:scheduled", {"1:old-lead": 0})
    assert queue.prefix == "whatsapp_test:v2"
    assert queue.list_pending(limit=10) == []


def test_other_campaign_backlog_does_not_block_automatic_campaign(queue):
    earlier = [pending_row(history_id=index) for index in range(10)]
    for row in earlier:
        row["scheduled_at"] -= timedelta(minutes=5)
    automatic = pending_row(100)
    automatic["campaign_id"] = 42
    queue.enqueue_many([*earlier, automatic])
    messages = queue.list_pending(limit=1, campaign_id=42)
    assert [row["history_id"] for row in messages] == [100]
