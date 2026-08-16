"""AWS Lambda handler for the fail-closed Pine SQS processor boundary."""

from __future__ import annotations

from daily_alpha.pine_processor import DynamoPineEventStore, process_sqs_batch


def lambda_handler(event, context):
    del context
    store = DynamoPineEventStore()
    return process_sqs_batch(event, store)
