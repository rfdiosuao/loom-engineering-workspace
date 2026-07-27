from __future__ import annotations

import os
import sys
import unittest
from dataclasses import FrozenInstanceError, fields


PYTHON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)


from core.model_catalog import (
    ModelDescriptor,
    build_model_descriptors,
    classify_model_catalog_error,
    model_descriptor_to_dict,
    resolve_model_descriptor,
    selectable_model_ids,
)


class ModelCatalogTests(unittest.TestCase):
    def test_model_descriptor_is_frozen_and_has_only_the_frozen_contract_fields(self) -> None:
        descriptor = ModelDescriptor(
            model_id="gpt-test",
            display_name="GPT Test",
            provider_id="member_gateway",
            capabilities=("chat",),
            protocols=("responses",),
            available=True,
            unavailable_reason="",
        )

        self.assertEqual(
            [field.name for field in fields(ModelDescriptor)],
            [
                "model_id",
                "display_name",
                "provider_id",
                "capabilities",
                "protocols",
                "available",
                "unavailable_reason",
            ],
        )
        with self.assertRaises(FrozenInstanceError):
            descriptor.available = False

    def test_visible_model_is_not_selectable_until_a_protocol_is_verified(self) -> None:
        descriptors = build_model_descriptors(
            ["gpt-5.6-luna"],
            provider_id="member_gateway",
        )

        self.assertIsInstance(descriptors[0], ModelDescriptor)
        self.assertEqual(descriptors[0].model_id, "gpt-5.6-luna")
        self.assertEqual(descriptors[0].capabilities, ("chat",))
        self.assertEqual(descriptors[0].protocols, ())
        self.assertFalse(descriptors[0].available)
        self.assertEqual(descriptors[0].unavailable_reason, "protocol_not_verified")
        self.assertEqual(selectable_model_ids(descriptors), [])

    def test_protocol_evidence_and_aliases_produce_one_selectable_descriptor(self) -> None:
        descriptors = build_model_descriptors(
            [
                {
                    "id": "gpt-5.6-luna",
                    "displayName": "GPT 5.6 Luna",
                    "capabilities": ["chat", "tools", "coding", "text"],
                },
                "GPT-5.6-LUNA",
                "gpt-luna",
            ],
            provider_id="member_gateway",
            aliases={"gpt-5.6-luna": ["gpt-luna", "GPT-5.6-LUNA", "gpt-luna"]},
            protocol_evidence={"gpt-luna": ["responses", "chat_completions", "responses"]},
        )

        self.assertEqual(len(descriptors), 1)
        self.assertEqual(descriptors[0].model_id, "gpt-5.6-luna")
        self.assertEqual(descriptors[0].display_name, "GPT 5.6 Luna")
        self.assertEqual(descriptors[0].capabilities, ("chat", "tools", "coding"))
        self.assertEqual(descriptors[0].protocols, ("chat_completions", "responses"))
        self.assertTrue(descriptors[0].available)
        self.assertEqual(selectable_model_ids(descriptors), ["gpt-5.6-luna"])
        self.assertEqual(
            resolve_model_descriptor(
                descriptors,
                "GPT-LUNA",
                aliases={"gpt-5.6-luna": ["gpt-luna"]},
            ).model_id,
            "gpt-5.6-luna",
        )
        self.assertEqual(
            model_descriptor_to_dict(descriptors[0]),
            {
                "modelId": "gpt-5.6-luna",
                "displayName": "GPT 5.6 Luna",
                "providerId": "member_gateway",
                "capabilities": ["chat", "tools", "coding"],
                "protocols": ["chat_completions", "responses"],
                "available": True,
                "unavailableReason": "",
            },
        )

    def test_empty_catalog_and_explicitly_unavailable_models_are_not_selectable(self) -> None:
        self.assertEqual(build_model_descriptors([], provider_id="custom"), [])
        descriptors = build_model_descriptors(
            [{"id": "gpt-disabled", "available": False, "unavailableReason": "group_denied"}],
            provider_id="custom",
            protocol_evidence={"gpt-disabled": ["responses"]},
        )

        self.assertFalse(descriptors[0].available)
        self.assertEqual(descriptors[0].unavailable_reason, "group_denied")
        self.assertEqual(selectable_model_ids(descriptors), [])

    def test_model_catalog_errors_are_structured_localized_and_retryable_when_safe(self) -> None:
        expected = {
            "selected_model_not_listed": ("selected_model_not_listed", False, None),
            "http_404": ("protocol_endpoint_not_found", False, 404),
            "http_503": ("upstream_temporarily_unavailable", True, 503),
            "http_524": ("upstream_response_timeout", True, 524),
        }

        for raw, (code, retryable, status_code) in expected.items():
            with self.subTest(raw=raw):
                error = classify_model_catalog_error(raw)
                self.assertEqual(error["code"], code)
                self.assertEqual(error["retryable"], retryable)
                self.assertEqual(error["statusCode"], status_code)
                self.assertTrue(error["messageZh"])
                self.assertNotIn("http_", error["messageZh"].lower())


if __name__ == "__main__":
    unittest.main()
