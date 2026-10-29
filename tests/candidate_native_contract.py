"""Our callback → native serialized OTLP seam. Run inside the pinned LiteLLM image.

python -m unittest discover -s tests -p candidate_native_contract.py
No provider, real credentials, live Langfuse, or upstream test suite required.
"""

import asyncio
import base64
import copy
import gzip
import json
import os
import sys
import threading
import unittest
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
os.environ["LITELLM_LOG"] = "ERROR"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/candidate"))

import litellm  # noqa: E402
from google.protobuf.json_format import MessageToDict  # noqa: E402
from litellm.litellm_core_utils.litellm_logging import Logging  # noqa: E402
from litellm.proxy._types import UserAPIKeyAuth  # noqa: E402
from litellm.proxy.litellm_pre_call_utils import add_litellm_data_to_request  # noqa: E402
from litellm.proxy.proxy_server import ProxyConfig  # noqa: E402
from litellm.types.llms.openai import ResponsesAPIResponse  # noqa: E402
from native_langfuse import NativeLangfuse  # noqa: E402
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (  # noqa: E402
    ExportTraceServiceRequest,
)
from starlette.requests import Request  # noqa: E402


class NativeContract(unittest.TestCase):
    def setUp(self):
        self.payloads = []
        payloads = self.payloads

        class Sink(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"data":[{"id":"synthetic","name":"synthetic"}]}')

            def do_POST(self):
                raw = self.rfile.read(int(self.headers["Content-Length"]))
                if self.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                request = ExportTraceServiceRequest()
                request.ParseFromString(raw)
                payloads.append(MessageToDict(request))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"{}")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Sink)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        os.environ.update(
            LANGFUSE_HOST=f"http://127.0.0.1:{self.server.server_port}",
            LANGFUSE_PUBLIC_KEY="pk-lf-synthetic",
            LANGFUSE_SECRET_KEY="sk-lf-synthetic",
            PROXYLENS_TRACE_DEPLOYMENT="candidate",
        )
        self.callback = NativeLangfuse()
        self.now = datetime.now(UTC)

    def tearDown(self):
        self.callback.flush()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def spans(self):
        self.callback.flush()
        return [
            span
            for payload in self.payloads
            for resource in payload["resourceSpans"]
            for scope in resource["scopeSpans"]
            for span in scope["spans"]
            if any(
                item["key"] == "langfuse.observation.type"
                and item["value"].get("stringValue") == "generation"
                for item in span.get("attributes", [])
            )
        ]

    @staticmethod
    def attributes(span):
        return {
            item["key"]: item["value"].get("stringValue", item["value"])
            for item in span["attributes"]
        }

    @staticmethod
    def request(owner, key):
        metadata = {
            "user_api_key_user_id": owner,
            "user_api_key_alias": key,
            "user_api_key_end_user_id": "forged-customer",
            "trace_user_id": "forged-owner",
            "session_id": "forged-session",
            "existing_trace_id": "a" * 32,
            "trace_public": True,
        }
        return {
            "model": "synthetic-model",
            "call_type": "acompletion",
            "litellm_call_id": "caller-call-id",
            "messages": [{"role": "user", "content": "def add(a, b): return a + b"}],
            "optional_params": {},
            "response_cost": 0.001,
            "user": "forged-user",
            "standard_callback_dynamic_params": {
                "langfuse_host": "http://caller.invalid",
                "langfuse_public_key": "pk-caller",
                "langfuse_secret_key": "sk-caller",
            },
            "litellm_params": {
                "metadata": metadata,
                "litellm_metadata": {"trace_user_id": "forged-alternate"},
                "proxy_server_request": {
                    "headers": {
                        "langfuse_trace_user_id": "forged-header-owner",
                        "langfuse_session_id": "forged-header-session",
                        "langfuse_trace_public": "true",
                    }
                },
            },
            "standard_logging_object": {
                "metadata": copy.deepcopy(metadata),
                "request_tags": [],
                "hidden_params": {},
            },
        }

    @staticmethod
    def response():
        return litellm.ModelResponse(
            id="synthetic-response",
            model="synthetic-model",
            choices=[{"message": {"role": "assistant", "content": "synthetic output"}}],
            usage={"prompt_tokens": 100, "completion_tokens": 40, "total_tokens": 140},
        )

    def test_key_owner_wins_and_sessions_are_scoped_without_mutating_request(self):
        for owner, key in (("user-a", "A"), ("user-a", "A2"), ("user-b", "B")):
            request = self.request(owner, key)
            original = copy.deepcopy(request)
            response = self.response()
            response_before = response.model_dump()
            asyncio.run(
                self.callback.async_log_success_event(
                    request, response, self.now, self.now + timedelta(seconds=1)
                )
            )
            self.assertEqual(request, original)
            self.assertEqual(response.model_dump(), response_before)
        spans = self.spans()
        self.assertEqual(len(spans), 3)
        attrs = [self.attributes(span) for span in spans]
        self.assertEqual(
            [a["user.id"] for a in attrs],
            ["candidate/user-a", "candidate/user-a", "candidate/user-b"],
        )
        for a, owner in zip(attrs, ("user-a", "user-a", "user-b"), strict=True):
            self.assertTrue(a["session.id"].startswith(f"candidate/{owner}/request/"))
            self.assertIn("def add", a["langfuse.observation.input"])
            self.assertIn("synthetic output", a["langfuse.observation.output"])
            self.assertEqual(a["langfuse.observation.metadata.attribution_basis"], "key_owner")
            self.assertEqual(a["langfuse.observation.metadata.session_basis"], "request_fallback")
        self.assertEqual(len({a["session.id"] for a in attrs}), 3)
        self.assertTrue(all(base64.b64decode(span["traceId"]).hex() != "a" * 32 for span in spans))
        self.assertNotIn("forged", json.dumps(spans))
        self.assertNotIn("caller.invalid", json.dumps(spans))

    def test_credentials_are_masked_in_content_tools_parameters_and_failures(self):
        request = self.request("user-a", "A")
        request["messages"][0]["content"] += " Authorization: Bearer AUTH_CANARY"
        request["messages"].append(
            {"role": "tool", "content": '{"api_key":"API_CANARY","result":"useful tool result"}'}
        )
        request["optional_params"] = {
            "tools": [
                {
                    "name": "synthetic_tool",
                    "description": "oauth_token=OAUTH_CANARY; useful description",
                }
            ],
            "extra_headers": {"X-Management-Key": "MANAGEMENT_CANARY"},
            "stop": ["provider_api_key=PROVIDER_CANARY"],
        }
        response = self.response()
        response.choices[0].message.content = "useful output sk-lf-synthetic"
        original = copy.deepcopy(request)
        asyncio.run(self.callback.async_log_success_event(request, response, self.now, self.now))
        request["exception"] = RuntimeError(
            "useful upstream error Authorization: Bearer ERROR_CANARY"
        )
        asyncio.run(self.callback.async_log_failure_event(request, None, self.now, self.now))
        spans = self.spans()
        self.assertEqual(len(spans), 2)
        encoded = json.dumps(spans)
        for marker in (
            "AUTH_CANARY",
            "API_CANARY",
            "OAUTH_CANARY",
            "MANAGEMENT_CANARY",
            "PROVIDER_CANARY",
            "ERROR_CANARY",
            "sk-lf-synthetic",
        ):
            self.assertNotIn(marker, encoded)
        for text in (
            "def add",
            "useful tool result",
            "synthetic_tool",
            "useful description",
            "useful output",
            "useful upstream error",
        ):
            self.assertIn(text, encoded)
        self.assertEqual(request["messages"], original["messages"])
        self.assertEqual(request["optional_params"], original["optional_params"])
        self.assertIn("sk-lf-synthetic", response.choices[0].message.content)
        failed = self.attributes(spans[1])
        self.assertEqual(failed["langfuse.observation.level"], "ERROR")
        self.assertIn("useful upstream error", failed["langfuse.observation.status_message"])

    def test_json_tool_result_remains_parseable_after_targeted_masking(self):
        request = self.request("user-a", "A")
        request["messages"] = [
            {"role": "tool", "content": '{"access_token":"OAUTH_CANARY","result":42}'}
        ]
        asyncio.run(
            self.callback.async_log_success_event(request, self.response(), self.now, self.now)
        )
        observed = json.loads(self.attributes(self.spans()[0])["langfuse.observation.input"])
        self.assertEqual(
            json.loads(observed["messages"][0]["content"]),
            {"access_token": "[REDACTED]", "result": 42},
        )

    def test_installed_proxy_stamping_and_responses_dispatch_reach_safe_native_trace(self):
        async def run():
            request = Request(
                {
                    "type": "http",
                    "path": "/v1/responses",
                    "method": "POST",
                    "query_string": b"",
                    "headers": [(b"langfuse_trace_user_id", b"forged-header-owner")],
                    "scheme": "http",
                    "server": ("localhost", 4000),
                }
            )
            prepared = await add_litellm_data_to_request(
                {
                    "model": "synthetic-model",
                    "input": "def native_source(): return 42",
                    "metadata": {
                        "user_api_key_user_id": "forged-owner",
                        "trace_user_id": "forged-owner",
                        "session_id": "forged-session",
                    },
                    "litellm_metadata": {"user_api_key_user_id": "forged-owner"},
                },
                request,
                UserAPIKeyAuth(user_id="user-a", api_key="synthetic-key-hash"),
                ProxyConfig(),
                {},
                "1.106.6",
            )
            logging = Logging(
                model="synthetic-model",
                messages=prepared["input"],
                stream=False,
                call_type="aresponses",
                start_time=self.now,
                litellm_call_id="synthetic-dispatch",
                function_id="synthetic-function",
                dynamic_async_success_callbacks=[self.callback],
            )
            logging.update_environment_variables(
                model="synthetic-model",
                user="forged-customer",
                optional_params={},
                litellm_params={
                    "metadata": prepared["litellm_metadata"],
                    "proxy_server_request": prepared["proxy_server_request"],
                },
            )
            result = ResponsesAPIResponse(
                id="resp_synthetic_dispatch",
                created_at=int(self.now.timestamp()),
                object="response",
                model="synthetic-model",
                status="completed",
                output=[
                    {
                        "type": "message",
                        "id": "msg_synthetic",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "native responses output",
                                "annotations": [],
                            }
                        ],
                    }
                ],
                usage={
                    "input_tokens": 100,
                    "input_tokens_details": {"cached_tokens": 20},
                    "output_tokens": 40,
                    "output_tokens_details": {"reasoning_tokens": 10},
                    "total_tokens": 140,
                },
                parallel_tool_calls=False,
                tool_choice="auto",
                tools=[],
            )
            await logging.async_success_handler(
                result=result, start_time=self.now, end_time=self.now + timedelta(seconds=1)
            )

        asyncio.run(run())
        spans = self.spans()
        self.assertEqual(len(spans), 1)
        attrs = self.attributes(spans[0])
        self.assertEqual(attrs["user.id"], "candidate/user-a")
        self.assertIn("def native_source", attrs["langfuse.observation.input"])
        self.assertIn("native responses output", attrs["langfuse.observation.output"])
        usage = json.loads(attrs["langfuse.observation.usage_details"])
        self.assertEqual(
            (usage["input"], usage["cache_read_input_tokens"], usage["output"], usage["total"]),
            (80, 20, 40, 140),
        )
        self.assertNotIn("forged", json.dumps(spans))

    def test_early_failure_without_authenticated_owner_is_explicitly_unattributed(self):
        request = self.request("user-b", "B")
        request["standard_logging_object"] = {"metadata": {}, "request_tags": []}
        request["exception"] = RuntimeError("denied invalid authorization")
        asyncio.run(self.callback.async_log_failure_event(request, None, self.now, self.now))
        attrs = self.attributes(self.spans()[0])
        self.assertNotIn("user.id", attrs)
        self.assertEqual(attrs["langfuse.observation.metadata.attribution_basis"], "unattributed")
        self.assertTrue(attrs["session.id"].startswith("candidate/unattributed/request/"))

    def test_completed_stream_keeps_visible_tools_and_image_reference(self):
        async def run():
            request = self.request("user-a", "A")
            request["messages"] = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "synthetic image request"},
                        {
                            "type": "image_url",
                            "image_url": {"url": "data:image/png;base64,c3ludGhldGlj"},
                        },
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": "call_synthetic",
                    "content": "visible tool result",
                },
            ]
            response = self.response()
            response.choices[0].message.tool_calls = [
                litellm.ChatCompletionMessageToolCall(
                    id="call_synthetic",
                    type="function",
                    function={"name": "inspect_file", "arguments": '{"path":"synthetic.py"}'},
                )
            ]
            logging = Logging(
                model="synthetic-model",
                messages=request["messages"],
                stream=True,
                call_type="acompletion",
                start_time=self.now,
                litellm_call_id="synthetic-stream",
                function_id="synthetic-function",
                dynamic_async_success_callbacks=[self.callback],
            )
            logging.update_environment_variables(
                model="synthetic-model",
                user="forged",
                optional_params={"stream": True},
                litellm_params=request["litellm_params"],
            )
            await logging.async_success_handler(
                result=response, start_time=self.now, end_time=self.now + timedelta(seconds=1)
            )

        asyncio.run(run())
        spans = self.spans()
        self.assertEqual(len(spans), 1)
        encoded = json.dumps(spans)
        for text in (
            "visible tool result",
            "data:image/png;base64,c3ludGhldGlj",
            "inspect_file",
            "synthetic.py",
        ):
            self.assertIn(text, encoded)


if __name__ == "__main__":
    unittest.main()
