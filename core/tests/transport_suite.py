"""The behaviour every transport must have. A test class per implementation
inherits ``TransportSuite`` and supplies a ``transport`` fixture."""

from __future__ import annotations

import math

import pytest
from support import HEADER, Measurement, Number, NumberResult, at, measurement, take

from pswamp_core.messages import PmuFrame, ResultEnvelope, sent_at
from pswamp_core.subscription import Overflow


class TransportSuite:
    async def test_a_subscriber_gets_an_equal_copy(self, transport, app):
        sent = measurement(1)
        with transport.subscribe(Measurement, app=app) as feed:
            await feed.ready(10)
            await transport.publish(sent, app=app, key="k")
            ((key, got),) = await take(feed, 1)
        assert key == "k"
        assert got.model_dump() == sent.model_dump() and got is not sent
        assert sent_at(got) is not None  # stamped on receipt, for the keep-up monitor

    async def test_nan_arrives_as_null(self, transport, app):
        frame = PmuFrame(timestamp=at(0), mRID="s", header=HEADER, values=[50.0, math.nan, 1.0, 2.0])
        with transport.subscribe(PmuFrame, app=app) as feed:
            await feed.ready(10)
            await transport.publish(frame, app=app, key="k")
            ((_, got),) = await take(feed, 1)
        assert got.values == [50.0, None, 1.0, 2.0]

    async def test_a_topic_carries_one_class(self, transport, app):
        result = NumberResult(timestamp=at(0), app={"name": "n", "uuid": "u"}, result=Number(value=1))
        with transport.subscribe(ResultEnvelope, app=app) as base, transport.subscribe(NumberResult, app=app) as exact:
            await base.ready(10)
            await exact.ready(10)
            await transport.publish(result, app=app, key="k")
            await take(exact, 1)
        assert base.get_nowait() is None

    async def test_two_classes_of_one_name_cannot_share_a_topic(self, transport, app):
        other = type("Measurement", (Measurement,), {})
        assert other.topic == Measurement.topic and other is not Measurement
        with transport.subscribe(Measurement, app=app):
            with pytest.raises(ValueError, match="cannot share"):
                transport.subscribe(other, app=app)
            with transport.subscribe(other, app=app + "x"):  # another app: another topic
                pass

    async def test_apps_are_apart_and_the_key_filters(self, transport, app):
        other = app + "x"
        with (
            transport.subscribe(Measurement, app=app, key="k1") as mine,
            transport.subscribe(Measurement, app=other) as other_app,
            transport.subscribe(Measurement, app=app) as every_key,
        ):
            for feed in (mine, other_app, every_key):
                await feed.ready(10)
            await transport.publish(measurement(1), app=app, key="k1")
            await transport.publish(measurement(2), app=app, key="k2")
            got = await take(every_key, 2)
            ((_, only),) = await take(mine, 1)
        assert [key for key, _ in got] == ["k1", "k2"]
        assert only.mRID == "m1" and mine.get_nowait() is None
        assert other_app.get_nowait() is None

    async def test_one_subscription_over_several_classes_keeps_publish_order(self, transport, app):
        with transport.subscribe(Measurement, app=app, overflow=Overflow.GROW) as feed:
            await feed.ready(10)
            for i in (3, 1, 2):  # timestamps going backwards are carried as published
                await transport.publish(measurement(i), app=app, key="k")
            got = await take(feed, 3)
        assert [m.mRID for _, m in got] == ["m3", "m1", "m2"]
