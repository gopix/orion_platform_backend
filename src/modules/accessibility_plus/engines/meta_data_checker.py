from typing import Any

from src.modules.accessibility_plus.engines.metadata_agent import MetadataAgent


class MetaDataChecker(MetadataAgent):
	def __init__(self, metadata: dict[str, Any] | None = None):
		super().__init__()
		self.metadata = metadata or {}

	def run(self, tests: list[str] | None = None) -> dict[str, Any]:
		requested_tests = tests or list(self.supported_checks)
		unknown_tests = [t for t in requested_tests if t not in self.supported_checks]
		selected_tests = [t for t in requested_tests if t in self.supported_checks]

		results = [self.run_check(test_code, self.metadata) for test_code in selected_tests]

		return {
			"agent_code": self.agent_code,
			"requested_tests": requested_tests,
			"unknown_tests": unknown_tests,
			"results": results,
		}
