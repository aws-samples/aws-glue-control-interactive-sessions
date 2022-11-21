# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import os

from aws_lambda_powertools import Logger, Metrics, Tracer
from aws_lambda_powertools.utilities.data_classes import EventBridgeEvent, event_source
from aws_lambda_powertools.utilities.typing import LambdaContext
from control import InteractiveSessionControl


ENFORCE_VPC_CONNECTION = os.environ.get("ENFORCE_VPC_CONNECTION")
MAX_WORKERS = os.environ.get("MAX_WORKERS")
MAX_IDLE_TIMEOUT_MINUTES = os.environ.get("MAX_IDLE_TIMEOUT_MINUTES")

logger = Logger()
tracer = Tracer()
metrics = Metrics()


@event_source(data_class=EventBridgeEvent)
@metrics.log_metrics
@logger.inject_lambda_context
@tracer.capture_lambda_handler(capture_response=False)
def lambda_handler(event: EventBridgeEvent, _: LambdaContext):
    """Inspects Glue Interactive Sessions and terminates if it does not meet boundary conditions.

    The conditions are configured through environment variables, see above. Where we can define:
    * Whether interactive sessions need a vpc connection attached
    * The maximum workers one can use with an interactive session
    * The maximum idle timeout (in minutes) for a session (when to close it due to inactivity)
    """
    vpc_connection = False if not ENFORCE_VPC_CONNECTION or ENFORCE_VPC_CONNECTION.lower() == "false" else True
    InteractiveSessionControl(vpc_connection, MAX_WORKERS, MAX_IDLE_TIMEOUT_MINUTES).inspect(event)
