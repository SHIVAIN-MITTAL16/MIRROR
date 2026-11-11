import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from typing import Literal

from backend.main import APP
from backend.intent_extraction import (
    DEFAULT_GEMINI_TIMEOUT_MS,
    DEFAULT_GEMINI_MODEL,
    _ModelExtraction,
    classify_gemini_failure,
    configured_gemini_timeout_ms,
    create_gemini_client,
    gemini_compatible_schema,
)


@contextmanager
def sqlite_connection(path):
    connection = sqlite3.connect(path)
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def model_result(proposals, clarification_questions=None):
    return json.dumps({
        "proposals": proposals,
        "clarification_questions": clarification_questions or [],
    })


def proposal(kind, operator, value, quote, *, unit=None, hard="hard"):
    return {
        "condition_type": kind,
        "operator": operator,
        "expected_value": value,
        "unit": unit,
        "hard_or_soft": hard,
        "supporting_quote": quote,
    }


class IntentExtractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.old_database_path = os.environ.get("MIRROR_DATABASE_PATH")
        cls.database = str(Path(cls.temp_dir.name) / "intent.sqlite3")
        os.environ["MIRROR_DATABASE_PATH"] = cls.database
        cls.client = TestClient(APP)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        if cls.old_database_path is None:
            os.environ.pop("MIRROR_DATABASE_PATH", None)
        else:
            os.environ["MIRROR_DATABASE_PATH"] = cls.old_database_path
        cls.temp_dir.cleanup()

    def request_with_model(self, text, result, api_key="test-key"):
        fake_client = SimpleNamespace(
            models=SimpleNamespace(generate_content=Mock(return_value=SimpleNamespace(text=result))),
            close=lambda: None,
        )
        with patch.dict(os.environ, {"GEMINI_API_KEY": api_key, "GEMINI_MODEL": "test-model"}), \
             patch("backend.intent_extraction.create_gemini_client", return_value=fake_client) as create:
            response = self.client.post("/api/passport-intents/extract", json={"text": text})
        return response, create

    @staticmethod
    def response_client(response=None, error=None):
        generate = Mock(return_value=response) if error is None else Mock(side_effect=error)
        close = Mock()
        client = SimpleNamespace(
            models=SimpleNamespace(generate_content=generate),
            close=close,
        )
        return client, close

    @staticmethod
    def transient_provider_error(code, status):
        class ProviderError(Exception):
            def __init__(self):
                super().__init__("synthetic provider failure")
                self.code = code
                self.status = status
                self.message = "synthetic provider failure"
        return ProviderError()

    @staticmethod
    def valid_provider_response():
        return SimpleNamespace(text=model_result([
            proposal("item_condition", "eq", "new", "new"),
        ]))

    @staticmethod
    def assert_no_additional_properties(test_case, schema):
        if isinstance(schema, dict):
            test_case.assertNotIn("additionalProperties", schema)
            for value in schema.values():
                IntentExtractionTests.assert_no_additional_properties(test_case, value)
        elif isinstance(schema, list):
            for value in schema:
                IntentExtractionTests.assert_no_additional_properties(test_case, value)

    def test_gemini_schema_adapter_removes_additional_properties_recursively(self):
        schema = gemini_compatible_schema(_ModelExtraction)
        self.assert_no_additional_properties(self, schema)
        self.assertIn("$defs", schema)
        self.assertIn("_ModelProposal", schema["$defs"])
        self.assertIn("proposals", schema["properties"])
        self.assertEqual(schema["properties"]["proposals"]["maxItems"], 20)
        proposal_schema = schema["$defs"]["_ModelProposal"]
        condition_type_schema = proposal_schema["properties"]["condition_type"]["anyOf"][0]
        expected_value_schema = proposal_schema["properties"]["expected_value"]["anyOf"][0]
        self.assertEqual(condition_type_schema["maxLength"], 80)
        self.assertEqual(expected_value_schema["maxLength"], 1000)
        self.assertEqual(condition_type_schema["type"], "string")

    def test_gemini_schema_adapter_preserves_nested_constraints_and_original_schema(self):
        class Nested(BaseModel):
            model_config = ConfigDict(extra="forbid")
            mode: Literal["strict", "soft"] = Field(description="Condition strength")
            value: str = Field(min_length=2, max_length=12)

        class Envelope(BaseModel):
            model_config = ConfigDict(extra="forbid")
            item: Nested

        original = Envelope.model_json_schema()
        expected = json.loads(json.dumps(original))

        def strip_additional_properties(value):
            if isinstance(value, dict):
                return {
                    key: strip_additional_properties(item)
                    for key, item in value.items()
                    if key != "additionalProperties"
                }
            if isinstance(value, list):
                return [strip_additional_properties(item) for item in value]
            return value

        adapted = gemini_compatible_schema(Envelope)
        self.assertEqual(adapted, strip_additional_properties(expected))
        self.assertEqual(original, Envelope.model_json_schema())
        nested = adapted["$defs"]["Nested"]
        self.assertEqual(nested["properties"]["mode"]["enum"], ["strict", "soft"])
        self.assertEqual(nested["properties"]["mode"]["description"], "Condition strength")
        self.assertEqual(nested["properties"]["value"]["minLength"], 2)
        self.assertEqual(nested["properties"]["value"]["maxLength"], 12)
        self.assertEqual(nested["required"], ["mode", "value"])

    def test_actual_provider_schema_argument_is_adapted(self):
        text = "A new laptop."
        raw = model_result([proposal("item_condition", "eq", "new", "new")])
        fake_client = SimpleNamespace(
            models=SimpleNamespace(
                generate_content=Mock(return_value=SimpleNamespace(text=raw)),
            ),
            close=lambda: None,
        )
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key", "GEMINI_MODEL": "test-model"}), \
             patch("backend.intent_extraction.create_gemini_client", return_value=fake_client):
            response = self.client.post("/api/passport-intents/extract", json={"text": text})

        self.assertEqual(response.status_code, 200, response.text)
        config = fake_client.models.generate_content.call_args.kwargs["config"]
        provider_schema = config.response_schema
        self.assertIsInstance(provider_schema, dict)
        self.assert_no_additional_properties(self, provider_schema)
        self.assertIn("proposals", provider_schema["properties"])
        self.assertEqual(provider_schema["properties"]["proposals"]["maxItems"], 20)

    def test_local_pydantic_validation_still_rejects_extra_response_fields(self):
        raw = model_result([proposal("item_condition", "eq", "new", "new")])
        parsed = json.loads(raw)
        parsed["proposals"][0]["buyer_confirmed"] = True
        with self.assertRaises(ValidationError):
            _ModelExtraction.model_validate(parsed)

        response, _ = self.request_with_model("A new laptop.", json.dumps(parsed))
        self.assertEqual(response.status_code, 502)

    def test_successful_extraction_returns_supported_exactly_quoted_proposals(self):
        text = "I need a new laptop under ₹80,000 delivered within five days."
        raw = model_result([
            proposal("price", "lt", "80000", "under ₹80,000", unit="INR"),
            proposal("delivery_days", "lte", "5", "within five days", unit="days"),
            proposal("item_condition", "eq", "new", "I need a new laptop"),
        ])
        response, create = self.request_with_model(text, raw)

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(len(body["proposals"]), 3)
        self.assertEqual(body["proposals"][0]["expected_value"], "80000")
        self.assertEqual(body["proposals"][0]["unit"], "INR")
        self.assertEqual(body["proposals"][1]["expected_value"], "5")
        self.assertEqual(body["proposals"][2]["expected_value"], "new")
        self.assertTrue(body["ready_for_review"])
        self.assertEqual(create.call_args.args, ("test-key", DEFAULT_GEMINI_TIMEOUT_MS))

    def test_default_timeout_is_45000_and_passed_to_google_genai(self):
        with patch.dict(os.environ, {"GEMINI_TIMEOUT_MS": ""}), \
             patch("backend.intent_extraction.genai.Client") as sdk_client:
            self.assertEqual(configured_gemini_timeout_ms(), 45_000)
            create_gemini_client("test-key")

        options = sdk_client.call_args.kwargs["http_options"]
        self.assertEqual(options.timeout, 45_000)

    def test_default_model_is_used_when_environment_override_is_empty(self):
        fake_client = SimpleNamespace(
            models=SimpleNamespace(generate_content=Mock(return_value=SimpleNamespace(
                text=model_result([proposal("item_condition", "eq", "new", "new")]),
            ))),
            close=lambda: None,
        )
        with patch.dict(os.environ, {
            "GEMINI_API_KEY": "test-key",
            "GEMINI_MODEL": "",
        }), patch("backend.intent_extraction.create_gemini_client", return_value=fake_client):
            response = self.client.post("/api/passport-intents/extract", json={"text": "A new laptop."})

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            fake_client.models.generate_content.call_args.kwargs["model"],
            DEFAULT_GEMINI_MODEL,
        )
        self.assertEqual(DEFAULT_GEMINI_MODEL, "gemini-3.5-flash-lite")

    def test_explicit_gemini_model_environment_value_overrides_default(self):
        configured_model = "configured-test-model"
        fake_client = SimpleNamespace(
            models=SimpleNamespace(generate_content=Mock(return_value=SimpleNamespace(
                text=model_result([proposal("item_condition", "eq", "new", "new")]),
            ))),
            close=lambda: None,
        )
        with patch.dict(os.environ, {
            "GEMINI_API_KEY": "test-key",
            "GEMINI_MODEL": configured_model,
        }), patch("backend.intent_extraction.create_gemini_client", return_value=fake_client):
            response = self.client.post("/api/passport-intents/extract", json={"text": "A new laptop."})

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            fake_client.models.generate_content.call_args.kwargs["model"],
            configured_model,
        )

    def test_custom_timeout_is_passed_to_google_genai(self):
        with patch.dict(os.environ, {"GEMINI_TIMEOUT_MS": "60000"}), \
             patch("backend.intent_extraction.genai.Client") as sdk_client:
            self.assertEqual(configured_gemini_timeout_ms(), 60_000)
            create_gemini_client("test-key")

        self.assertEqual(sdk_client.call_args.kwargs["http_options"].timeout, 60_000)

    def test_invalid_timeout_configuration_is_rejected_without_provider_call(self):
        for invalid in ("abc", "0", "-1", "999", "300001", "1.5"):
            with self.subTest(timeout=invalid), \
                 patch.dict(os.environ, {"GEMINI_TIMEOUT_MS": invalid, "GEMINI_API_KEY": "test-key"}), \
                 patch("backend.intent_extraction.create_gemini_client") as create:
                response = self.client.post(
                    "/api/passport-intents/extract",
                    json={"text": "A new laptop."},
                )
                self.assertEqual(response.status_code, 503)
                self.assertEqual(
                    response.json()["detail"],
                    "Gemini extraction timeout configuration is invalid.",
                )
                create.assert_not_called()

    def test_non_exact_supporting_quote_is_rejected(self):
        response, _ = self.request_with_model(
            "I need a laptop under 80000 INR.",
            model_result([proposal("price", "lt", "80000", "under $80,000", unit="USD")]),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["proposals"], [])
        self.assertTrue(response.json()["clarification_questions"])
        self.assertFalse(response.json()["ready_for_review"])

    def test_unsupported_condition_type_is_flagged(self):
        response, _ = self.request_with_model(
            "At least 2000 battery cycles are required.",
            model_result([proposal("battery_cycles", "gte", "2000", "At least 2000 battery cycles are required")]),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["proposals"], [])
        self.assertTrue(response.json()["clarification_questions"])

    def test_catalogue_supported_ram_requires_explicit_unit_and_does_not_convert(self):
        response, _ = self.request_with_model(
            "At least 16 GB RAM is required.",
            model_result([proposal("ram", "gte", "16", "At least 16 GB RAM is required", unit="GB")]),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["proposals"][0]["condition_type"], "ram")
        self.assertEqual(response.json()["proposals"][0]["expected_value"], "16")
        self.assertEqual(response.json()["proposals"][0]["unit"], "GB")

        no_unit, _ = self.request_with_model(
            "At least 16 RAM is required.",
            model_result([proposal("ram", "gte", "16", "At least 16 RAM is required")]),
        )
        self.assertEqual(no_unit.json()["proposals"][0]["unit"], None)
        self.assertTrue(no_unit.json()["clarification_questions"])

    def test_unsupported_operator_is_flagged(self):
        response, _ = self.request_with_model(
            "Price under 80000 INR is required.",
            model_result([proposal("price", "approximately", "80000", "Price under 80000 INR", unit="INR")]),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["proposals"], [])
        self.assertTrue(response.json()["clarification_questions"])

    def test_ambiguous_currency_is_returned_as_incomplete_proposal(self):
        response, _ = self.request_with_model(
            "Price under 80000.",
            model_result([proposal("price", "lt", "80000", "under 80000")]),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["proposals"][0]["unit"], None)
        self.assertTrue(any("currency" in question.lower() for question in response.json()["clarification_questions"]))
        self.assertFalse(response.json()["ready_for_review"])

    def test_missing_hard_or_soft_classification_requires_clarification(self):
        response, _ = self.request_with_model(
            "A new laptop.",
            model_result([proposal("item_condition", "eq", "new", "new", hard=None)]),
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["proposals"][0]["hard_or_soft"])
        self.assertTrue(any("strict requirement or a preference" in question for question in response.json()["clarification_questions"]))
        self.assertFalse(response.json()["ready_for_review"])

    def test_invalid_numeric_value_is_rejected(self):
        response, _ = self.request_with_model(
            "Price under 80000 INR is required.",
            model_result([proposal("price", "lt", "NaN", "under 80000 INR", unit="INR")]),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["proposals"], [])
        self.assertTrue(response.json()["clarification_questions"])

    def test_missing_required_condition_fields_are_flagged(self):
        incomplete = {"supporting_quote": "new"}
        response, _ = self.request_with_model(
            "A new laptop.",
            model_result([incomplete]),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["proposals"], [])
        self.assertTrue(response.json()["clarification_questions"])

    def test_malformed_model_json_returns_generic_provider_response_error(self):
        with self.assertLogs("backend.intent_extraction", level="WARNING") as logs:
            response, _ = self.request_with_model("A new laptop.", "{not json")
        self.assertEqual(response.status_code, 502)
        self.assertNotIn("not json", response.text)
        self.assertEqual(response.json()["detail"], "Gemini returned an invalid structured response.")
        self.assertIn("category=response parsing", " ".join(logs.output))

    def test_missing_api_key_returns_empty_deterministic_fallback_without_calling_client(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}), \
             patch("backend.intent_extraction.create_gemini_client") as create:
            response = self.client.post("/api/passport-intents/extract", json={"text": "A new laptop."})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["extraction_mode"], "deterministic_fallback")
        self.assertIn("GEMINI_API_KEY", " ".join(response.json()["clarification_questions"]))
        self.assertEqual(response.json()["proposals"], [])
        self.assertFalse(response.json()["ready_for_review"])
        create.assert_not_called()

    def test_provider_timeout_returns_generic_error(self):
        close = Mock()
        fake_client = SimpleNamespace(
            models=SimpleNamespace(generate_content=Mock(side_effect=TimeoutError("private detail"))),
            close=close,
        )
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}), \
             patch("backend.intent_extraction.create_gemini_client", return_value=fake_client) as create, \
             patch("backend.intent_extraction.time.sleep") as sleep:
            response = self.client.post("/api/passport-intents/extract", json={"text": "A new laptop."})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["extraction_mode"], "deterministic_fallback")
        self.assertFalse(response.json()["ready_for_review"])
        self.assertEqual(response.json()["proposals"], [])
        self.assertNotIn("private detail", response.text)
        self.assertEqual(create.call_count, 2)
        self.assertEqual(close.call_count, 2)
        sleep.assert_called_once_with(1.0)

    def test_unavailable_retries_once_then_succeeds_and_closes_both_clients(self):
        failed_client, close_first = self.response_client(
            error=self.transient_provider_error(503, "UNAVAILABLE"),
        )
        successful_client, close_second = self.response_client(
            response=self.valid_provider_response(),
        )
        with patch.dict(os.environ, {
            "GEMINI_API_KEY": "test-key",
            "GEMINI_MODEL": "retry-test-model",
        }), patch(
            "backend.intent_extraction.create_gemini_client",
            side_effect=[failed_client, successful_client],
        ) as create, patch("backend.intent_extraction.time.sleep") as sleep:
            response = self.client.post("/api/passport-intents/extract", json={"text": "A new laptop."})

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()["proposals"]), 1)
        self.assertEqual(create.call_count, 2)
        self.assertEqual(create.call_args_list[0].args, ("test-key", 45_000))
        self.assertEqual(create.call_args_list[1].args, ("test-key", 45_000))
        sleep.assert_called_once_with(1.0)
        close_first.assert_called_once_with()
        close_second.assert_called_once_with()

    def test_unavailable_fails_after_one_retry_with_generic_response(self):
        first, close_first = self.response_client(
            error=self.transient_provider_error(503, "UNAVAILABLE"),
        )
        second, close_second = self.response_client(
            error=self.transient_provider_error(503, "UNAVAILABLE"),
        )
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}), \
             patch("backend.intent_extraction.create_gemini_client", side_effect=[first, second]) as create, \
             patch("backend.intent_extraction.time.sleep") as sleep, \
             self.assertLogs("backend.intent_extraction", level="WARNING") as logs:
            response = self.client.post("/api/passport-intents/extract", json={"text": "A new laptop."})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["extraction_mode"], "deterministic_fallback")
        self.assertEqual(response.json()["proposals"], [])
        self.assertFalse(response.json()["ready_for_review"])
        self.assertEqual(create.call_count, 2)
        self.assertEqual(sleep.call_count, 1)
        close_first.assert_called_once_with()
        close_second.assert_called_once_with()
        diagnostic_text = " ".join(logs.output)
        self.assertIn("attempt=1", diagnostic_text)
        self.assertIn("attempt=2", diagnostic_text)
        self.assertIn("model=gemini-3.5-flash-lite", diagnostic_text)
        self.assertIn("provider_status=UNAVAILABLE", diagnostic_text)
        self.assertIn("elapsed_ms=", diagnostic_text)

    def test_deadline_exceeded_retries_once_and_succeeds(self):
        failed_client, close_first = self.response_client(
            error=self.transient_provider_error(504, "DEADLINE_EXCEEDED"),
        )
        successful_client, close_second = self.response_client(
            response=self.valid_provider_response(),
        )
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}), \
             patch("backend.intent_extraction.create_gemini_client", side_effect=[failed_client, successful_client]) as create, \
             patch("backend.intent_extraction.time.sleep") as sleep:
            response = self.client.post("/api/passport-intents/extract", json={"text": "A new laptop."})

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(create.call_count, 2)
        sleep.assert_called_once_with(1.0)
        close_first.assert_called_once_with()
        close_second.assert_called_once_with()

    def test_authentication_error_is_not_retried(self):
        failed_client, close_client = self.response_client(
            error=self.transient_provider_error(401, "UNAUTHENTICATED"),
        )
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}), \
             patch("backend.intent_extraction.create_gemini_client", return_value=failed_client) as create, \
             patch("backend.intent_extraction.time.sleep") as sleep:
            response = self.client.post("/api/passport-intents/extract", json={"text": "A new laptop."})

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["detail"], "Gemini intent extraction failed or timed out.")
        create.assert_called_once()
        sleep.assert_not_called()
        close_client.assert_called_once_with()

    def test_pydantic_response_validation_failure_is_not_retried(self):
        invalid = json.loads(model_result([
            proposal("item_condition", "eq", "new", "new"),
        ]))
        invalid["proposals"][0]["buyer_confirmed"] = True
        fake_client, close_client = self.response_client(
            response=SimpleNamespace(text=json.dumps(invalid)),
        )
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}), \
             patch("backend.intent_extraction.create_gemini_client", return_value=fake_client) as create, \
             patch("backend.intent_extraction.time.sleep") as sleep:
            response = self.client.post("/api/passport-intents/extract", json={"text": "A new laptop."})

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["detail"], "Gemini returned an invalid structured response.")
        create.assert_called_once()
        sleep.assert_not_called()
        close_client.assert_called_once_with()

    def test_provider_failure_diagnostics_classify_without_logging_secrets_or_buyer_text(self):
        cases = [
            (401, "UNAUTHENTICATED", "invalid API key", "authentication"),
            (403, "PERMISSION_DENIED", "permission denied", "permission"),
            (429, "RESOURCE_EXHAUSTED", "quota exceeded", "quota"),
            (404, "NOT_FOUND", "model not found", "model"),
            (504, "DEADLINE_EXCEEDED", "deadline exceeded", "timeout"),
            (400, "INVALID_ARGUMENT", "Unknown name \"additional_properties\" at 'generation_config.response_schema': Cannot find field.", "model"),
            (None, None, "socket connection failed", "network"),
        ]

        class ProviderFailure(Exception):
            def __init__(self, code, status, message):
                self.code = code
                self.status = status
                self.message = message

        for code, provider_status, message, expected in cases:
            with self.subTest(category=expected, code=code):
                diagnostic = classify_gemini_failure(ProviderFailure(code, provider_status, message))
                self.assertEqual(diagnostic["category"], expected)
                self.assertEqual(diagnostic["provider_http_status"], code)
                if code == 400:
                    self.assertIn("additional_properties", diagnostic["provider_message"])
                    self.assertIn("generation_config.response_schema", diagnostic["provider_message"])

        unsafe_message = (
            "Unknown name \"additional_properties\" at 'generation_config.response_schema': "
            "Cannot find field. buyer=17 Example Road API key=AIzaSySecretValue"
        )
        safe_diagnostic = classify_gemini_failure(ProviderFailure(400, "INVALID_ARGUMENT", unsafe_message))
        self.assertNotIn("17 Example Road", safe_diagnostic["provider_message"])
        self.assertNotIn("AIzaSySecretValue", safe_diagnostic["provider_message"])

        self.assertEqual(classify_gemini_failure(TimeoutError("private timeout detail"))["category"], "timeout")

        buyer_text = "My private address is 17 Example Road"
        fake_client = SimpleNamespace(
            models=SimpleNamespace(generate_content=Mock(side_effect=ProviderFailure(
                401, "UNAUTHENTICATED",
                f"API key not valid: {buyer_text}; key=AIzaSyTestSecretValueNotForLogs",
            ))),
            close=lambda: None,
        )
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}), \
             patch("backend.intent_extraction.create_gemini_client", return_value=fake_client), \
             self.assertLogs("backend.intent_extraction", level="WARNING") as logs:
            response = self.client.post("/api/passport-intents/extract", json={"text": buyer_text})

        diagnostic_text = " ".join(logs.output)
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["detail"], "Gemini intent extraction failed or timed out.")
        self.assertIn("category=authentication", diagnostic_text)
        self.assertIn("provider_http_status=401", diagnostic_text)
        self.assertNotIn(buyer_text, diagnostic_text)
        self.assertNotIn("AIzaSyTestSecretValueNotForLogs", diagnostic_text)
        self.assertNotIn("API key not valid", diagnostic_text)

    def test_extraction_has_no_database_writes_confirmation_or_verification_fields(self):
        text = "I need a new laptop under ₹80,000."
        raw = model_result([proposal("price", "lt", "80000", "under ₹80,000", unit="INR")])
        with sqlite_connection(self.database) as db:
            tables = [row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )]
            before = {table: db.execute(f'SELECT * FROM "{table}"').fetchall() for table in tables}
        response, _ = self.request_with_model(text, raw)
        self.assertEqual(response.status_code, 200)
        proposal_body = response.json()["proposals"][0]
        self.assertFalse({"owner", "buyer_confirmed", "merchant_confirmed", "verification_status", "claims"}.intersection(proposal_body))
        with sqlite_connection(self.database) as db:
            after = {table: db.execute(f'SELECT * FROM "{table}"').fetchall() for table in before}
        self.assertEqual(after, before)

    def test_model_cannot_return_confirmation_or_verification_fields(self):
        raw = json.loads(model_result([proposal("item_condition", "eq", "new", "new")]))
        raw["proposals"][0]["buyer_confirmed"] = True
        response, _ = self.request_with_model("A new laptop.", json.dumps(raw))
        self.assertEqual(response.status_code, 502)


if __name__ == "__main__":
    unittest.main()
