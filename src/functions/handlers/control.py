# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import os
import time

import boto3
from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities.data_classes import EventBridgeEvent


REGION = os.getenv("AWS_REGION", "eu-west-1")

logger = Logger()


class InteractiveSessionControl:
    """Inspects newly created sessions and applies control mechanisms."""

    EMAIL_SUBJECT = "Glue Interactive Session Closed"
    EMAIL_CONTENT = (
        "The glue interactive session was closed, as it did not meet our guidelines.\n"
        "Workers: {workers}/{max_workers} \n"
        "Idle_timeout: {idle_timeout}/{max_idle_timeout} \n"
        "Enforce VPC Connection: {enforce_vpc} \n"
        "Session: {session} \n"
        "User: {principal_id} \n"
    )
    DEFAULT_IDLE_TIMEOUT = 2880
    DEFAULT_WORKERS = 5
    PENDING_STATES = {"PENDING", "PROVISIONING"}

    def __init__(self, enforce_vpc: bool, max_workers: int, max_idle_timeout: int) -> None:
        """Init.

        Args:
            enforce_vpc (bool): whether to enforce vpc connection
            max_workers (int): maximum numbers of workers attached to a session
            max_idle_timeout (int): maximum time in minutes a session can idle.
        """
        self.enforce_vpc = enforce_vpc
        self.max_workers = max_workers
        self.max_idle_timeout = max_idle_timeout

        self.sns = boto3.client("sns", region_name=REGION)
        self.glue = boto3.client(
            "glue",
            region_name=REGION,
        )
        self.EMAIL_SNS_ARN = os.getenv("EMAIL_SNS_ARN")

    def has_connection_attached(self, event: EventBridgeEvent) -> bool:
        """Checks whether the session has a connection attached.

        Args:
            event (EventBridgeEvent): event from cloudtrail audit

        Returns:
            bool: True if connection attached, False otherwise
        """
        session = event.detail["responseElements"]["session"]
        if (
            "connections" in session
            and "connections" in session["connections"]
            and session["connections"]["connections"]
        ):
            return True

        return False

    def terminate_session(self, session_id: str) -> None:
        """Terminate glue interactive session.

        In case the session is still pending, it will wait for completion
        before deleting.

        Args:
            session_id (str): id of the interactive session
        """
        status = next(iter(self.PENDING_STATES))
        timeout = time.time() + 60 * 2
        logger.info(f"waiting for session `{session_id}` to be created")
        while status in self.PENDING_STATES and time.time() < timeout:
            session = self.glue.get_session(Id=session_id)
            status = session["Session"]["Status"]
            if status in self.PENDING_STATES:
                time.sleep(3)
        self.glue.delete_session(Id=session_id)

    def send_user_notification(self, principal_id: str, session: str, workers: int, idle_timeout: int) -> None:
        """Send notification through sns topic.

        Args:
            principal_id (str): user that created the session
            session (str): id of the session
            workers: number of workers
            idle_timeout: timeout defined on the session
        """
        self.sns.publish(
            TopicArn=self.EMAIL_SNS_ARN,
            Message=self.EMAIL_CONTENT.format(
                workers=workers,
                max_workers=self.max_workers,
                idle_timeout=idle_timeout,
                max_idle_timeout=self.max_idle_timeout,
                enforce_vpc=str(self.enforce_vpc),
                session=session,
                principal_id=principal_id,
            ),
            Subject=self.EMAIL_SUBJECT,
        )

    def inspect(self, event: EventBridgeEvent) -> None:
        """Inspect the glue interactive session and check for boundary constraints.

        This will check, the following:
        * whether vpc is enforced and applied to the session
        * whether the workers do not exceed the max workers defined
        * whether the idle timeout does not exceed the maximum defined

        Args:
            event (EventBridgeEvent): cloud trail event
        """
        if not event.detail["responseElements"]:
            request_id = event.detail["requestParameters"]["id"]
            logger.info(f"create session failed for id `{request_id}`.")
            return

        session_id = event.detail["responseElements"]["session"]["id"]
        principal_id = event.detail["userIdentity"]["principalId"]
        workers = event.detail["requestParameters"].get("numberOfWorkers", self.DEFAULT_WORKERS)
        idle_timeout = event.detail["requestParameters"].get("idleTimeout", self.DEFAULT_IDLE_TIMEOUT)
        if "@" not in principal_id:
            principal_id = event.get("detail").get("requestParameters", {}).get("tags", {}).get("owner")
        if principal_id:
            principal_id = principal_id.split(":")[-1].split("@")[0]
        else:
            logger.info(
                f"Invalid principal id {principal_id} for interactive session {session_id}",
            )
            self.terminate_session(session_id)
            return

        logger.info(
            f"auditing glue interactive session `{session_id}` started by user `{principal_id}`",
        )

        controls_failed = False
        if self.enforce_vpc and not self.has_connection_attached(event):
            logger.warning(f"session `{session_id}` has no connection attached.")
            controls_failed = True

        if self.max_workers and int(workers) > int(self.max_workers):
            logger.warning(f"session `{session_id}` has too many workers attached: {workers}/{self.max_workers}")
            controls_failed = True

        if self.max_idle_timeout and int(idle_timeout) > int(self.max_idle_timeout):
            logger.warning(
                f"session `{session_id}` has idle timeout set above threshold: {idle_timeout}/{self.max_idle_timeout}",
            )
            controls_failed = True

        if controls_failed:
            self.terminate_session(session_id)
            logger.info(f"session terminated `{session_id}`")

            if self.EMAIL_SNS_ARN:
                logger.info("sending email")
                self.send_user_notification(principal_id, session_id, workers, idle_timeout)
