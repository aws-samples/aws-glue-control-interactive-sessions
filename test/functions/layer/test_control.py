# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

from typing import Any
from unittest.mock import patch

import pytest
from aws_lambda_powertools.utilities.data_classes import EventBridgeEvent

from src.functions.handlers.control import InteractiveSessionControl


@patch("src.functions.handlers.control.boto3")
class TestInteractiveSessionControl:
    """Tests the interactive session control mechanism."""

    PRINCIPAL = "some@principal"
    SUBTENANT = "some-subtenant"
    VPC = True
    WORKERS = InteractiveSessionControl.DEFAULT_WORKERS
    IDLE_TIMEOUT = InteractiveSessionControl.DEFAULT_IDLE_TIMEOUT

    @pytest.fixture(autouse=True)
    def environ(self, monkeypatch: Any) -> None:
        """Patches environment variables required for tests."""
        monkeypatch.setenv("EMAIL_SNS_ARN", "some-arn")

    @pytest.fixture()
    def event(self) -> EventBridgeEvent:
        """Stub event mimicing the cloud trail event for glue CreateSession

        Returns:
            EventBridgeEvent: event with all relevant details for test case.
        """
        return EventBridgeEvent(
            {
                "detail": {
                    "userIdentity": {"principalId": self.PRINCIPAL},
                    "requestParameters": {
                        "id": "debd3e86-1432-484b-b231-7e5e22d468b8",
                        "numberOfWorkers": 2,
                        "idleTimeout": 60,
                    },
                    "responseElements": {
                        "session": {
                            "id": f"{self.SUBTENANT}-d4868e04-4a21-43c0-8fd3",
                            "connections": {"connections": ["internal"]},
                        },
                    },
                },
            },
        )

    def test_connection_attached_should_not_terminate(
        self,
        boto3_mock,
        event: EventBridgeEvent,
    ):
        """Tests the session is not killed when vpc configuration attached."""
        controller = InteractiveSessionControl(self.VPC, self.WORKERS, self.IDLE_TIMEOUT)
        controller.inspect(event)
        assert not boto3_mock.client("glue").delete_session.called

    def test_connection_missing_should_terminate(
        self,
        boto3_mock,
        event: EventBridgeEvent,
    ):
        """Tests the session is killed when no vpc connection attached."""
        detail = event.detail
        del detail["responseElements"]["session"]["connections"]
        event = EventBridgeEvent({"detail": detail})
        boto3_mock.client("glue").get_session.return_value = {
            "Session": {"Status": "ACTIVE"},
        }

        controller = InteractiveSessionControl(self.VPC, self.WORKERS, self.IDLE_TIMEOUT)
        controller.inspect(event)
        assert boto3_mock.client("glue").delete_session.called
        assert boto3_mock.client("sns").publish.called

    def test_workers_exceeding_should_terminate(
        self,
        boto3_mock,
        event: EventBridgeEvent,
    ):
        """Tests the session is killed when number of workers exceeds limit."""
        event.detail["requestParameters"]["numberOfWorkers"] = self.WORKERS + 1
        boto3_mock.client("glue").get_session.return_value = {
            "Session": {"Status": "ACTIVE"},
        }

        controller = InteractiveSessionControl(self.VPC, self.WORKERS, self.IDLE_TIMEOUT)
        controller.inspect(event)
        assert boto3_mock.client("glue").delete_session.called
        assert boto3_mock.client("sns").publish.called

    def test_idle_timeout_exceeding_should_terminate(
        self,
        boto3_mock,
        event: EventBridgeEvent,
    ):
        """Tests the session is killed when the idle timeout exceeds the limit."""
        event.detail["requestParameters"]["idleTimeout"] = self.IDLE_TIMEOUT + 1
        boto3_mock.client("glue").get_session.return_value = {
            "Session": {"Status": "ACTIVE"},
        }

        controller = InteractiveSessionControl(self.VPC, self.WORKERS, self.IDLE_TIMEOUT)
        controller.inspect(event)
        assert boto3_mock.client("glue").delete_session.called
        assert boto3_mock.client("sns").publish.called

    def test_connection_missing_should_terminate_no_notification(
        self,
        boto3_mock,
        event: EventBridgeEvent,
        monkeypatch: Any,
    ):
        """Tests session is killed even if no sns topic is configured."""
        detail = event.detail
        del detail["responseElements"]["session"]["connections"]
        event = EventBridgeEvent({"detail": detail})
        boto3_mock.client("glue").get_session.return_value = {
            "Session": {"Status": "ACTIVE"},
        }
        monkeypatch.setenv("EMAIL_SNS_ARN", "")

        controller = InteractiveSessionControl(self.VPC, self.WORKERS, self.IDLE_TIMEOUT)
        controller.inspect(event)
        assert boto3_mock.client("glue").delete_session.called
        assert not boto3_mock.client("sns").publish.called

    def test_invalid_principal_id_should_terminate(
        self,
        boto3_mock,
        event: EventBridgeEvent,
    ):
        """Tests that the session is terminated if the principal is invalid."""
        detail = event.detail
        del detail["responseElements"]["session"]["connections"]
        detail["userIdentity"]["principalId"] = "ABC"
        detail["requestParameters"]["tags"] = {}
        detail["requestParameters"]["tags"]["owner"] = "abc.a@a"
        event = EventBridgeEvent({"detail": detail})
        boto3_mock.client("glue").get_session.return_value = {
            "Session": {"Status": "ACTIVE"},
        }

        controller = InteractiveSessionControl(self.VPC, self.WORKERS, self.IDLE_TIMEOUT)
        controller.inspect(event)
        assert boto3_mock.client().delete_session.called

    def test_failed_session_should_be_ignored(
        self,
        boto3_mock,
        event: EventBridgeEvent,
    ):
        """Tests if the function can handle sessions that never started."""
        detail = event.detail
        detail["responseElements"] = None
        event = EventBridgeEvent({"detail": detail})
        controller = InteractiveSessionControl(self.VPC, self.WORKERS, self.IDLE_TIMEOUT)
        controller.inspect(event)
        assert not boto3_mock.client("glue").delete_session.called
