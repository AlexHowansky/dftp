"""Tests for the protocol module."""

from dftp.protocol import MessageReader, encode_message


class TestEncodeMessage:
    def test_roundtrip(self):
        msg = {"cmd": "LIST", "args": {"path": "/"}}
        data = encode_message(msg)
        reader = MessageReader()
        messages = reader.feed(data)
        assert len(messages) == 1
        assert messages[0] == msg

    def test_multiple_messages(self):
        reader = MessageReader()
        data = encode_message({"a": 1}) + encode_message({"b": 2})
        messages = reader.feed(data)
        assert len(messages) == 2
        assert messages[0] == {"a": 1}
        assert messages[1] == {"b": 2}

    def test_partial_feed(self):
        msg = {"cmd": "PWD"}
        data = encode_message(msg)
        reader = MessageReader()

        # Feed half the data
        mid = len(data) // 2
        messages = reader.feed(data[:mid])
        assert len(messages) == 0

        # Feed the rest
        messages = reader.feed(data[mid:])
        assert len(messages) == 1
        assert messages[0] == msg

    def test_empty_dict(self):
        reader = MessageReader()
        messages = reader.feed(encode_message({}))
        assert messages == [{}]
